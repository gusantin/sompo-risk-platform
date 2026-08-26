import json
import logging
import math
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import datetime, timezone
from time import monotonic

from flask import Flask, g, has_request_context, jsonify, request
from flask.json.provider import DefaultJSONProvider

from config import Config
from integracoes.inmet import consultar_avisos_inmet, consultar_inmet
from integracoes.inpe_queimadas import consultar_queimadas
from integracoes.open_meteo import consultar_clima, consultar_hidrologia, consultar_terreno
from integracoes.sgb import consultar_suscetibilidade
from services.firebase_client import FirebaseClient
from services.alert_service import AlertService, AlertValidationError
from services.audit_service import AuditService
from services.auth_service import ApplicationAuthService
from services.sompo_agro_agent import (
    AgentProviderError, AgentProviderNotConfiguredError, AgentValidationError,
    AgroRiskAgent, AgroRiskTools,
)
from services.device_service import DeviceService, DeviceUnauthorizedError, DeviceValidationError
from services.event_service import EventService
from services.firestore_service import montar_analise, salvar_documento
from services.historico_risco_service import HistoricoRiscoService
from services.live_case_service import LiveCaseService
from services.machine_risk_service import calcular_risco_maquina
from services.maquina_service import MaquinaService, ValidacaoMaquinaError
from services.operational_risk_service import calcular_risco_operacional, machine_is_operating
from services.propriedade_service import ESTADOS, PropriedadeService, ValidacaoPropriedadeError, validar_id
from services.rate_limit_service import InMemoryRateLimiter
from services.regional_risk_service import RegionalRiskService
from services.regional_snapshot_service import RegionalSnapshotService
from services.risco_service import calcular_riscos
from services.risk_context_service import MOTOR_VERSION, RiskContextService
from services.risk_explanation_service import explain_risks
from services.snapshot_service import SnapshotService
from services.telemetria_service import TelemetriaService
from services.telemetria_service import parse_timestamp
from services.unit_service import UnitValidationError, validate_measurements


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)


class ISOJSONProvider(DefaultJSONProvider):
    def default(self, valor):
        if isinstance(valor, datetime): return valor.astimezone(timezone.utc).isoformat()
        return super().default(valor)


app = Flask(__name__)
app.json = ISOJSONProvider(app)
app.config.from_object(Config)
app.config["MAX_CONTENT_LENGTH"] = app.config["JSON_MAX_BYTES"]
firebase = FirebaseClient(app.config["FIREBASE_KEY_PATH"])
propriedades = PropriedadeService(firebase)
maquinas = MaquinaService(firebase, propriedades)
telemetria = TelemetriaService(firebase, app.config["TELEMETRY_DEFAULT_LIMIT"], app.config["TELEMETRY_MAX_LIMIT"])
risk_context_service = RiskContextService(firebase, app.config["IOT_MAX_AGE_MINUTES"], telemetria, maquinas,
                                           app.config["MACHINE_LOCATION_MAX_AGE_SECONDS"],
                                           app.config["IOT_MAX_AGE_SECONDS"],
                                           app.config["PROPERTY_TELEMETRY_QUERY_LIMIT"])
historico_risco = HistoricoRiscoService(firebase, app.config["RISK_HISTORY_DEFAULT_LIMIT"], app.config["RISK_HISTORY_MAX_LIMIT"])
regional_snapshots = RegionalSnapshotService(firebase, app.config["REGIONAL_READ_MAX_LIMIT"])
application_auth = ApplicationAuthService()
devices = DeviceService(firebase, maquinas, app.config["DEVICE_TOKEN_HASH_ITERATIONS"])
events = EventService(firebase, app.config["EVENT_SIGNIFICANT_SCORE_DELTA"])
alerts = AlertService(firebase, app.config["ALERT_COOLDOWN_SECONDS"], app.config["ALERT_HOTSPOT_DISTANCE_KM"],
                      app.config["ALERT_HOTSPOT_CRITICAL_DISTANCE_KM"], app.config["HOTSPOT_MAX_AGE_HOURS"])
snapshots = SnapshotService(firebase)
audit = AuditService(firebase)
rate_limiter = InMemoryRateLimiter()
agro_risk_tools = AgroRiskTools(
    propriedades, snapshots, maquinas, telemetria, devices, events, alerts,
    lambda: LiveCaseService.load_snapshot(app.config["LIVE_CASE_SNAPSHOT_PATH"]),
    consultar_avisos_inmet,
)
agro_risk_agent = AgroRiskAgent(
    agro_risk_tools,
    provider=app.config["LLM_PROVIDER"],
    ollama_url=app.config["OLLAMA_URL"],
    model=app.config["OLLAMA_MODEL"],
    timeout_seconds=app.config["SOMPO_AGENT_TIMEOUT_SECONDS"],
)
COLECAO_SENSORES = "leituras_sensores"
COLECAO_ANALISES = "analises_risco"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
PUBLIC_ENDPOINTS = {"home", "health", "ready", "static"}


class _SkipPostAnalysis(Exception):
    pass


def _development_bypass(config_name):
    return (app.config.get("TESTING") is True or (
        app.config.get("ENVIRONMENT") in {"development", "test"} and app.config.get(config_name) is True
    ))


@app.before_request
def preparar_request_e_autorizar():
    candidate = request.headers.get("X-Request-ID", "")
    g.request_id = candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else str(uuid.uuid4())
    g.request_started = monotonic()
    g.auth_context = None
    if request.content_length and request.content_length > app.config["JSON_MAX_BYTES"]:
        if request.endpoint == "receber_dados":
            _log_iot_ingestion("rejected", reason="payload_too_large")
        return _erro("Corpo JSON excede o tamanho máximo permitido.", 413, "payload_muito_grande")
    if request.method == "OPTIONS" or request.endpoint in PUBLIC_ENDPOINTS or request.endpoint == "receber_dados":
        return None
    if _development_bypass("ALLOW_DEV_AUTH_BYPASS"):
        g.auth_context = {"kind": "development", "actorId": "development_bypass"}
        return None
    g.auth_context = application_auth.authenticate(request.headers.get("Authorization"), app.config["APP_API_KEYS"])
    if g.auth_context is None:
        return _erro("Autenticação da aplicação é obrigatória.", 401, "api_unauthorized")
    return None


@app.after_request
def aplicar_contrato_e_cors(resposta):
    resposta.headers["X-API-Contract-Version"] = app.config["API_CONTRACT_VERSION"]
    resposta.headers["X-Request-ID"] = getattr(g, "request_id", str(uuid.uuid4()))
    origem = request.headers.get("Origin")
    if origem and origem in app.config["CORS_ALLOWED_ORIGINS"]:
        resposta.headers["Access-Control-Allow-Origin"] = origem
        resposta.headers["Vary"] = "Origin"
        resposta.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Device-Token, X-Request-ID"
        resposta.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
    elapsed = round((monotonic() - getattr(g, "request_started", monotonic())) * 1000, 1)
    LOGGER.info(json.dumps({
        "event": "http_request", "requestId": getattr(g, "request_id", None),
        "endpoint": request.endpoint, "method": request.method, "path": request.path,
        "status": resposta.status_code, "elapsedMs": elapsed,
        "fazendaId": (request.view_args or {}).get("fazenda_id") or getattr(g, "fazenda_id", None),
        "maquinaId": (request.view_args or {}).get("maquina_id") or getattr(g, "maquina_id", None),
    }, ensure_ascii=False, separators=(",", ":")))
    return resposta


def obter_token():
    return firebase.obter_token()


def _firebase_args():
    firebase.initialize()
    return firebase.firestore_url, obter_token


def _erro(mensagem, status=400, codigo="requisicao_invalida"):
    return jsonify({"status": "erro", "codigo": codigo, "mensagem": mensagem,
                    "requestId": getattr(g, "request_id", None),
                    "error": {"code": codigo.upper(), "message": mensagem}}), status


def _log_iot_ingestion(outcome, data=None, identity=None, reason=None, observed_at=None,
                       document_id=None, deduplicated=None):
    """Log estruturado da ingestão sem headers, token ou payload completo."""
    payload = data if isinstance(data, dict) else {}
    resolved = identity if isinstance(identity, dict) else {}

    def safe_id(value):
        return value if isinstance(value, str) and REQUEST_ID_PATTERN.fullmatch(value) else None

    def safe_number(key):
        value = payload.get(key)
        return value if (isinstance(value, (int, float)) and not isinstance(value, bool)
                         and math.isfinite(value)) else None

    entry = {
        "event": "iot_ingestion", "requestId": getattr(g, "request_id", None),
        "outcome": outcome, "reason": reason,
        "receivedAt": datetime.now(timezone.utc).isoformat(),
        "observedAt": observed_at.isoformat() if isinstance(observed_at, datetime) else None,
        "deviceId": safe_id(resolved.get("deviceId") or payload.get("deviceId")),
        "fazendaId": safe_id(resolved.get("fazendaId") or payload.get("fazendaId")),
        "maquinaId": safe_id(resolved.get("maquinaId") or payload.get("maquinaId")),
        "temperatura": safe_number("temperatura"), "umidade": safe_number("umidade"),
        "documentoId": safe_id(document_id), "deduplicated": deduplicated,
    }
    message = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    (LOGGER.info if outcome == "accepted" else LOGGER.warning)(message)


def _audit(action, resource_type, resource_id, changes=None):
    if app.config.get("TESTING") and not app.config.get("TEST_AUDIT_WRITES"):
        return
    try:
        audit.record(action, resource_type, resource_id, getattr(g, "auth_context", None),
                     getattr(g, "request_id", None), changes)
    except Exception as error:
        LOGGER.warning("audit_unavailable action=%s error_type=%s", action, type(error).__name__)


def _machine_requires_attention(machine_risk=None, operational_risk=None, device_health=None):
    return ((machine_risk or {}).get("level") in {"high", "critical"}
            or (operational_risk or {}).get("level") in {"high", "critical"}
            or (device_health or {}).get("status") in {"stale", "offline"})


def _best_effort(label, operation, default=None):
    try:
        return operation()
    except Exception as error:
        LOGGER.warning("%s_failed error_type=%s", label, type(error).__name__)
        return default


@app.errorhandler(404)
def not_found(_error):
    return _erro("Endpoint não encontrado.", 404, "nao_encontrado")


@app.errorhandler(405)
def method_not_allowed(_error):
    return _erro("Método não permitido.", 405, "metodo_nao_permitido")


@app.errorhandler(413)
def payload_too_large(_error):
    return _erro("Corpo JSON excede o tamanho máximo permitido.", 413, "payload_muito_grande")


@app.errorhandler(Exception)
def unexpected_error(error):
    LOGGER.error("unhandled_request_error error_type=%s request_id=%s",
                 type(error).__name__, getattr(g, "request_id", None))
    return _erro("Erro interno.", 500, "internal_error")


def salvar_no_firebase(temperatura, umidade, fazenda_id, maquina_id, measurements=None):
    medicoes = measurements or {"temperature": temperatura, "humidity": umidade}
    return salvar_documento(
        *_firebase_args(), COLECAO_SENSORES,
        {"fazendaId": fazenda_id, "maquinaId": maquina_id, "temperatura": temperatura,
         "umidade": umidade, "measurements": medicoes,
         "measurementScope": "unknown", "dataHora": datetime.now(timezone.utc), "origem": "ESP32"},
    )


def _coordenada(nome, minimo, maximo):
    valor = request.args.get(nome)
    if valor is None or not valor.strip():
        raise ValueError(f"Parâmetro '{nome}' é obrigatório.")
    try:
        numero = float(valor)
    except ValueError as erro:
        raise ValueError(f"Parâmetro '{nome}' deve ser numérico.") from erro
    if not math.isfinite(numero) or not minimo <= numero <= maximo:
        raise ValueError(f"Parâmetro '{nome}' deve estar entre {minimo} e {maximo}.")
    return numero


def _fontes(latitude, longitude):
    inicio = monotonic()
    consultas = {
        "clima": consultar_clima, "hidrologia": consultar_hidrologia,
        "terreno": consultar_terreno, "sgb": consultar_suscetibilidade,
        "queimadas": consultar_queimadas, "inmet": consultar_inmet,
    }
    executor = ThreadPoolExecutor(max_workers=len(consultas), thread_name_prefix="fonte-risco")
    futuros = {executor.submit(funcao, latitude, longitude): nome for nome, funcao in consultas.items()}
    resultados = {}
    try:
        for futuro in as_completed(futuros, timeout=app.config["EXTERNAL_API_BUDGET_SECONDS"]):
            nome = futuros[futuro]
            try:
                resultados[nome] = futuro.result()
            except Exception as erro:
                LOGGER.warning("source_unavailable source=%s error_type=%s", nome, type(erro).__name__)
                resultados[nome] = {"status": "erro_api", "dados": {}, "mensagem": "Fonte indisponível."}
    except TimeoutError:
        LOGGER.warning("Orçamento global das integrações excedido")
    finally:
        for futuro, nome in futuros.items():
            if nome not in resultados:
                futuro.cancel()
                resultados[nome] = {"status": "timeout", "dados": {}, "mensagem": "Tempo global excedido."}
        executor.shutdown(wait=False, cancel_futures=True)
    elapsed_ms = round((monotonic() - inicio) * 1000)
    request_id = getattr(g, "request_id", None) if has_request_context() else None
    for source, result in resultados.items():
        LOGGER.info(json.dumps({"event": "external_source", "requestId": request_id, "source": source,
            "status": result.get("status"), "cache": result.get("cache", False), "elapsedTotalMs": elapsed_ms},
            ensure_ascii=False, separators=(",", ":")))
    return resultados


def _analise_coordenada(latitude, longitude):
    fontes = _fontes(latitude, longitude); riscos = calcular_riscos(fontes)
    return {"riscos": riscos, "dataCoverage": {
        "weatherAvailable": fontes.get("clima", {}).get("status") in ("ok", "parcial"),
        "satelliteAvailable": fontes.get("queimadas", {}).get("status") in ("ok", "parcial"),
        "geospatialAvailable": any(fontes.get(n, {}).get("status") in ("ok", "parcial") for n in ("sgb", "terreno", "hidrologia"))},
        "hotspotInfo": fontes.get("queimadas", {}).get("dados", {}),
        "weatherSummary": fontes.get("clima", {}).get("dados", {}),
        "sourceHealth": {nome: {"status": fonte.get("status"), "cacheHit": fonte.get("cache", False),
            "observedAt": fonte.get("dados", {}).get("dataHoraObservacaoUtc"),
            "consultedAt": fonte.get("consultadoEm")} for nome, fonte in fontes.items()}}


regional_risk = RegionalRiskService(_analise_coordenada, app.config["REGIONAL_MAX_CONCURRENCY"],
                                    app.config["REGIONAL_CACHE_TTL_SECONDS"])


def _id_sensor(dados, campo, padrao):
    valor = dados.get(campo, padrao)
    try:
        validar_id(valor, campo)
    except ValidacaoPropriedadeError as erro:
        raise ValueError(str(erro)) from erro
    if len(valor) > app.config["IDENTIFICADOR_MAX_LENGTH"]:
        raise ValueError(f"{campo} excede o tamanho máximo permitido.")
    return valor


@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "online", "projeto": "Sompo", "firebase": firebase.status,
                    "apiContractVersion": app.config["API_CONTRACT_VERSION"]})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "apiContractVersion": app.config["API_CONTRACT_VERSION"]})


@app.route("/ready", methods=["GET"])
def ready():
    firebase_configured = os.path.isfile(app.config["FIREBASE_KEY_PATH"])
    auth_configured = app.config["ENVIRONMENT"] != "production" or bool(app.config["APP_API_KEYS"])
    configurado = firebase_configured and auth_configured
    corpo = {"status": "ready" if configurado else "not_ready", "firebaseConfigured": firebase_configured,
             "applicationAuthConfigured": auth_configured,
             "apiContractVersion": app.config["API_CONTRACT_VERSION"]}
    return jsonify(corpo), 200 if configurado else 503


@app.route("/devices", methods=["POST", "GET"])
def devices_collection():
    if request.method == "GET":
        try:
            return jsonify({"status": "ok", "items": devices.list(request.args.get("fazendaId")),
                            "apiContractVersion": app.config["API_CONTRACT_VERSION"]})
        except (ValueError, ValidacaoPropriedadeError) as error:
            return _erro(str(error), 400, "dados_invalidos")
        except Exception:
            return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")
    if not request.is_json:
        return _erro("Content-Type deve ser application/json.", 415, "tipo_conteudo_invalido")
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) - {"deviceId", "fazendaId", "maquinaId", "token", "metadata"}:
        return _erro("Payload de dispositivo inválido.", 400, "dados_invalidos")
    try:
        device = devices.create(data.get("deviceId"), data.get("fazendaId"), data.get("maquinaId"),
                                data.get("token"), data.get("metadata"))
        _audit("device.created", "device", device["deviceId"], {
            "fazendaId": device["fazendaId"], "maquinaId": device["maquinaId"],
        })
        return jsonify({"status": "ok", "device": device}), 201
    except (DeviceValidationError, ValidacaoPropriedadeError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception as error:
        if "409" in str(error):
            return _erro("deviceId já existe.", 409, "conflito")
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/devices/<device_id>", methods=["GET", "PATCH"])
def device_detail(device_id):
    try:
        if request.method == "GET":
            device = devices.get(device_id)
        else:
            if not request.is_json:
                return _erro("Content-Type deve ser application/json.", 415, "tipo_conteudo_invalido")
            data = request.get_json(silent=True)
            if (not isinstance(data, dict) or set(data) != {"status"}
                    or data.get("status") not in {"active", "revoked"}):
                return _erro("PATCH aceita status active ou revoked.", 400, "dados_invalidos")
            device = devices.set_status(device_id, data["status"])
            if device:
                _audit("device.status_changed", "device", device_id, {"status": data["status"]})
        if device is None:
            return _erro("Dispositivo não encontrado.", 404, "nao_encontrado")
        return jsonify({"status": "ok", "device": device})
    except (DeviceValidationError, ValidacaoPropriedadeError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception:
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/devices/<device_id>/rotate", methods=["POST"])
def rotate_device_token(device_id):
    if not request.is_json:
        return _erro("Content-Type deve ser application/json.", 415, "tipo_conteudo_invalido")
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"token"}:
        return _erro("Payload deve conter somente token.", 400, "dados_invalidos")
    try:
        device = devices.rotate(device_id, data["token"])
        if device is None:
            return _erro("Dispositivo não encontrado.", 404, "nao_encontrado")
        _audit("device.credential_rotated", "device", device_id, {"tokenVersion": device["tokenVersion"]})
        return jsonify({"status": "ok", "device": device})
    except (DeviceValidationError, ValidacaoPropriedadeError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception:
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/dados", methods=["POST"])
def receber_dados():
    if not request.is_json:
        _log_iot_ingestion("rejected", reason="content_type_not_json")
        return _erro("Content-Type deve ser application/json.", 415, "tipo_conteudo_invalido")
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        _log_iot_ingestion("rejected", reason="invalid_json")
        return _erro("Corpo JSON deve ser um objeto.")
    identity = None
    observed_at = None
    try:
        allowed = {"deviceId", "readingId", "observedAt", "temperatura", "umidade",
                   "fazendaId", "maquinaId", "measurements"}
        if set(dados) - allowed:
            raise ValueError("Payload contém campos inesperados.")
        device_id = dados.get("deviceId")
        g.device_id = device_id if isinstance(device_id, str) else None
        device_token = request.headers.get("X-Device-Token")
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Device "):
            device_token = authorization[7:]
        if _development_bypass("ALLOW_DEV_DEVICE_BYPASS") and not device_id and not device_token:
            fazenda_id = _id_sensor(dados, "fazendaId", "fazenda_01")
            maquina_id = _id_sensor(dados, "maquinaId", "trator_01")
            identity = {"deviceId": "development_device", "fazendaId": fazenda_id,
                        "maquinaId": maquina_id, "status": "active"}
        else:
            validar_id(device_id, "deviceId")
            identity = devices.authenticate(device_id, device_token)
            fazenda_id, maquina_id = identity["fazendaId"], identity["maquinaId"]
            if dados.get("fazendaId") not in (None, fazenda_id):
                raise DeviceUnauthorizedError("Dispositivo não pertence à fazenda informada.")
            if dados.get("maquinaId") not in (None, maquina_id):
                raise DeviceUnauthorizedError("Dispositivo não pertence à máquina informada.")
        g.fazenda_id, g.maquina_id = fazenda_id, maquina_id
        allowed_request, retry_after = rate_limiter.allow(
            f"iot:{identity['deviceId']}", app.config["IOT_RATE_LIMIT_REQUESTS"],
            app.config["IOT_RATE_LIMIT_WINDOW_SECONDS"],
        )
        if not allowed_request:
            _log_iot_ingestion("rejected", dados, identity, "rate_limit_exceeded")
            response, status = _erro("Limite de ingestão excedido.", 429, "rate_limit_exceeded")
            response.headers["Retry-After"] = str(retry_after)
            return response, status
        temperatura = umidade = None
        legacy = dados.get("measurements") is None
        if legacy:
            if dados.get("temperatura") is None or dados.get("umidade") is None:
                raise ValueError("measurements ou temperatura e umidade são obrigatórios.")
            if any(not isinstance(dados.get(field), (int, float)) or isinstance(dados.get(field), bool)
                   for field in ("temperatura", "umidade")):
                raise ValueError("Temperatura e umidade devem ser números JSON, não texto.")
            temperatura, umidade = float(dados["temperatura"]), float(dados["umidade"])
            if not math.isfinite(temperatura) or not math.isfinite(umidade):
                raise ValueError("Temperatura e umidade devem ser números finitos.")
            if not app.config["TEMPERATURA_MIN_C"] <= temperatura <= app.config["TEMPERATURA_MAX_C"]:
                raise ValueError(f"Temperatura deve estar entre {app.config['TEMPERATURA_MIN_C']} e {app.config['TEMPERATURA_MAX_C']} °C.")
            if not 0 <= umidade <= 100:
                raise ValueError("Umidade deve estar entre 0 e 100%.")
            measurements = {"temperature": temperatura, "humidity": umidade}
            descriptors = {
                "temperature": {"type": "temperature", "scope": "unknown", "target": None, "unit": "celsius"},
                "humidity": {"type": "relative_humidity", "scope": "unknown", "target": None, "unit": "percent"},
            }
        else:
            machine = maquinas.obter(fazenda_id, maquina_id)
            if not machine or machine.get("fazendaId") != fazenda_id:
                raise DeviceUnauthorizedError("Associação do dispositivo com a máquina não é válida.")
            measurements, descriptors = validate_measurements(
                dados["measurements"], machine, app.config["MAX_MEASUREMENTS"], strict=True,
            )
        observed_at = parse_timestamp(dados.get("observedAt")) or datetime.now(timezone.utc)
        if (observed_at - datetime.now(timezone.utc)).total_seconds() > 60:
            raise ValueError("observedAt não pode estar no futuro.")
        reading_id = dados.get("readingId")
        if reading_id is not None:
            validar_id(reading_id, "readingId")
    except DeviceUnauthorizedError:
        _log_iot_ingestion("rejected", dados, identity, "device_unauthorized", observed_at)
        return _erro("Dispositivo não autorizado.", 401, "device_unauthorized")
    except (DeviceValidationError, UnitValidationError, ValidacaoPropriedadeError, TypeError, ValueError) as erro:
        _log_iot_ingestion("rejected", dados, identity, str(erro), observed_at)
        return _erro(str(erro), 400, "dados_invalidos")
    try:
        if _development_bypass("ALLOW_DEV_DEVICE_BYPASS") and identity["deviceId"] == "development_device" and legacy:
            resultado = salvar_no_firebase(temperatura, umidade, fazenda_id, maquina_id)
            document_id, duplicate = resultado.get("name", "").split("/")[-1], False
        else:
            document_id, duplicate, saved_reading = telemetria.save(
                identity["deviceId"], fazenda_id, maquina_id, measurements, descriptors,
                observed_at, reading_id, "development" if identity["deviceId"] == "development_device" else "iot_device",
                observed_at_provided=dados.get("observedAt") is not None,
            )
            persisted_observed_at = saved_reading.get("dataHora", observed_at)
            devices.touch(identity["deviceId"])
            try:
                current = snapshots.get_machine(fazenda_id, maquina_id) or {}
                snapshots.save_machine(fazenda_id, maquina_id, {**current,
                    "deviceId": identity["deviceId"], "lastSeenAt": datetime.now(timezone.utc),
                    "deviceHealth": {"status": "online", "ageSeconds": 0},
                    "latestMeasurements": measurements, "latestMeasurementDescriptors": descriptors,
                    "latestTelemetryAt": persisted_observed_at,
                    "attention": _machine_requires_attention(current.get("machineRisk"),
                                                              current.get("operationalRisk"), {"status": "online"}),
                })
            except Exception as error:
                LOGGER.warning("machine_snapshot_ingestion_unavailable error_type=%s", type(error).__name__)
    except ValueError as erro:
        _log_iot_ingestion("rejected", dados, identity, "idempotency_conflict", observed_at)
        return _erro(str(erro), 409, "idempotency_conflict")
    except Exception as error:
        LOGGER.error("telemetry_persistence_failed error_type=%s", type(error).__name__)
        _log_iot_ingestion("rejected", dados, identity, "persistence_unavailable", observed_at)
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")
    if not (_development_bypass("ALLOW_DEV_DEVICE_BYPASS")
            and identity["deviceId"] == "development_device" and legacy):
        observed_at = persisted_observed_at
    received_at = datetime.now(timezone.utc)
    _log_iot_ingestion("accepted", dados, identity, observed_at=observed_at,
                       document_id=document_id, deduplicated=duplicate)
    return jsonify({"status": "ok", "apiContractVersion": app.config["API_CONTRACT_VERSION"],
                    "mensagem": "Telemetria recebida", "documentoId": document_id,
                    "deviceId": identity["deviceId"], "fazendaId": fazenda_id, "maquinaId": maquina_id,
                    "observedAt": observed_at, "deduplicated": duplicate, "receivedAt": received_at})


@app.route("/risco", methods=["GET"])
def consultar_risco():
    allowed_request, retry_after = rate_limiter.allow(
        f"coordinate_risk:{request.remote_addr}", app.config["EXPENSIVE_RATE_LIMIT_REQUESTS"],
        app.config["EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS"],
    )
    if not allowed_request:
        response, status = _erro("Limite de cálculos excedido.", 429, "rate_limit_exceeded")
        response.headers["Retry-After"] = str(retry_after)
        return response, status
    try:
        latitude, longitude = _coordenada("lat", -90, 90), _coordenada("lon", -180, 180)
    except ValueError as erro:
        return _erro(str(erro))
    fontes = _fontes(latitude, longitude)
    riscos = calcular_riscos(fontes)
    persistencia = {"status": "ok", "documentoId": None}
    try:
        salvo = salvar_documento(*_firebase_args(), COLECAO_ANALISES,
                                  montar_analise(latitude, longitude, riscos, fontes), timeout=20)
        persistencia["documentoId"] = salvo.get("name", "").split("/")[-1]
    except Exception as erro:
        LOGGER.warning("coordinate_risk_not_persisted error_type=%s", type(erro).__name__)
        persistencia = {"status": "erro", "codigo": "persistencia_indisponivel"}
    return jsonify({"status": "ok", "localizacao": {"latitude": latitude, "longitude": longitude},
                    "riscos": riscos, "fontes": fontes, "persistencia": persistencia})


@app.route("/fazendas", methods=["POST"])
def criar_fazenda():
    if not request.is_json:
        return _erro("Content-Type deve ser application/json.", 415, "tipo_conteudo_invalido")
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return _erro("Corpo JSON deve ser um objeto.")
    dados = dict(dados)
    fazenda_id = dados.pop("fazendaId", None)
    try:
        fazenda = propriedades.criar(fazenda_id, dados)
        _audit("property.created", "property", fazenda_id)
        return jsonify({"status": "ok", "fazenda": fazenda}), 201
    except ValidacaoPropriedadeError as erro:
        return _erro(str(erro), 400, "dados_invalidos")
    except Exception:
        LOGGER.exception("Falha ao criar propriedade")
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/fazendas", methods=["GET"])
def listar_fazendas():
    try:
        return jsonify({"status": "ok", "fazendas": propriedades.listar(request.args.get("limit", 100))})
    except (ValueError, ValidacaoPropriedadeError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception:
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/fazendas/<fazenda_id>", methods=["GET"])
def obter_fazenda(fazenda_id):
    try:
        fazenda = propriedades.obter(fazenda_id)
    except ValidacaoPropriedadeError as erro:
        return _erro(str(erro), 400, "dados_invalidos")
    except Exception:
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")
    return jsonify({"status": "ok", "fazenda": fazenda}) if fazenda else _erro("Fazenda não encontrada.", 404, "nao_encontrada")


@app.route("/fazendas/<fazenda_id>", methods=["PATCH"])
def atualizar_fazenda(fazenda_id):
    if not request.is_json:
        return _erro("Content-Type deve ser application/json.", 415, "tipo_conteudo_invalido")
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return _erro("Corpo JSON deve ser um objeto.")
    try:
        fazenda = propriedades.atualizar(fazenda_id, dados)
        if fazenda:
            _audit("property.updated", "property", fazenda_id, {"fields": sorted(dados)})
    except ValidacaoPropriedadeError as erro:
        return _erro(str(erro), 400, "dados_invalidos")
    except Exception:
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")
    return jsonify({"status": "ok", "fazenda": fazenda}) if fazenda else _erro("Fazenda não encontrada.", 404, "nao_encontrada")


@app.route("/fazendas/<fazenda_id>/maquinas", methods=["POST"])
def criar_maquina(fazenda_id):
    if not request.is_json: return _erro("Content-Type deve ser application/json.", 415, "tipo_conteudo_invalido")
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict): return _erro("Corpo JSON deve ser um objeto.")
    dados = dict(dados); maquina_id = dados.pop("maquinaId", None)
    try:
        validar_id(maquina_id, "maquinaId"); maquina = maquinas.criar(fazenda_id, maquina_id, dados)
        if maquina:
            _audit("machine.created", "machine", maquina_id, {"fazendaId": fazenda_id})
    except (ValidacaoMaquinaError, ValidacaoPropriedadeError, ValueError) as erro:
        return _erro(str(erro), 400, "dados_invalidos")
    except Exception:
        LOGGER.exception("Falha ao criar máquina"); return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")
    return (jsonify({"status": "ok", "maquina": maquina}), 201) if maquina else _erro("Fazenda não encontrada.", 404, "nao_encontrada")


@app.route("/fazendas/<fazenda_id>/maquinas", methods=["GET"])
def listar_maquinas(fazenda_id):
    try: return jsonify({"status": "ok", "maquinas": maquinas.listar(fazenda_id)})
    except (ValidacaoPropriedadeError, ValueError) as erro: return _erro(str(erro), 400, "dados_invalidos")
    except Exception: return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/fazendas/<fazenda_id>/maquinas/<maquina_id>", methods=["GET", "PATCH"])
def detalhe_maquina(fazenda_id, maquina_id):
    try:
        if request.method == "PATCH":
            if not request.is_json: return _erro("Content-Type deve ser application/json.", 415, "tipo_conteudo_invalido")
            dados = request.get_json(silent=True)
            if not isinstance(dados, dict): return _erro("Corpo JSON deve ser um objeto.")
            maquina = maquinas.atualizar(fazenda_id, maquina_id, dados)
            if maquina:
                _audit("machine.updated", "machine", maquina_id, {"fazendaId": fazenda_id, "fields": sorted(dados)})
        else: maquina = maquinas.obter(fazenda_id, maquina_id)
    except (ValidacaoMaquinaError, ValidacaoPropriedadeError, ValueError) as erro:
        return _erro(str(erro), 400, "dados_invalidos")
    except Exception: return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")
    return jsonify({"status": "ok", "maquina": maquina}) if maquina else _erro("Máquina não encontrada.", 404, "nao_encontrada")


@app.route("/fazendas/<fazenda_id>/maquinas/<maquina_id>/telemetria", methods=["GET"])
def historico_telemetria(fazenda_id, maquina_id):
    try:
        maquina = maquinas.obter(fazenda_id, maquina_id)
        if not maquina: return _erro("Máquina não encontrada.", 404, "nao_encontrada")
        itens = telemetria.historico(fazenda_id, maquina_id, request.args.get("limit"),
                                     request.args.get("startTime"), request.args.get("endTime"))
        sensores = {s.get("sensorId"): s for s in maquina.get("sensoresConfigurados", [])}
        series = [{"timestamp": item.get("dataHora"), "measurement": sensor_id, "value": valor,
                   "unit": (sensores.get(sensor_id) or {}).get("unit", "unknown")}
                  for item in itens for sensor_id, valor in (item.get("measurements") or {}).items()]
        return jsonify({"status": "ok", "items": itens, "series": series,
                        "count": len(itens), "order": "dataHora_desc"})
    except (ValueError, ValidacaoPropriedadeError) as erro: return _erro(str(erro), 400, "dados_invalidos")
    except Exception: return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/fazendas/<fazenda_id>/maquinas/<maquina_id>/risco", methods=["GET"])
def risco_maquina(fazenda_id, maquina_id):
    try:
        maquina = maquinas.obter(fazenda_id, maquina_id)
        if not maquina: return _erro("Máquina não encontrada.", 404, "nao_encontrada")
        leituras = telemetria.historico(fazenda_id, maquina_id, request.args.get("limit", 20))
        return jsonify({"status": "ok", "machineRisk": calcular_risco_maquina(maquina, leituras)})
    except (ValueError, ValidacaoPropriedadeError) as erro: return _erro(str(erro), 400, "dados_invalidos")
    except Exception: return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/fazendas/<fazenda_id>/risco", methods=["GET"])
def risco_fazenda(fazenda_id):
    allowed_request, retry_after = rate_limiter.allow(
        f"risk:{fazenda_id}:{request.remote_addr}", app.config["EXPENSIVE_RATE_LIMIT_REQUESTS"],
        app.config["EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS"],
    )
    if not allowed_request:
        response, status = _erro("Limite de cálculos excedido.", 429, "rate_limit_exceeded")
        response.headers["Retry-After"] = str(retry_after)
        return response, status
    try:
        fazenda = propriedades.obter(fazenda_id)
    except ValidacaoPropriedadeError as erro:
        return _erro(str(erro), 400, "dados_invalidos")
    except Exception:
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")
    if fazenda is None:
        return _erro("Fazenda não encontrada.", 404, "nao_encontrada")
    fontes = _fontes(fazenda["latitude"], fazenda["longitude"])
    try: maquinas_fazenda = maquinas.listar(fazenda_id)
    except Exception: maquinas_fazenda = []
    try:
        farm_telemetry = telemetria.historico_fazenda(
            fazenda_id, app.config["PROPERTY_TELEMETRY_QUERY_LIMIT"])
    except Exception:
        farm_telemetry = []
    telemetry_by_machine = {}
    for reading in farm_telemetry:
        telemetry_by_machine.setdefault(reading.get("maquinaId"), []).append(reading)
    try:
        farm_devices = devices.list(fazenda_id)
    except Exception:
        farm_devices = []
    device_by_machine = {item.get("maquinaId"): item for item in farm_devices}
    resultados_maquinas = []
    for maquina in maquinas_fazenda:
        leituras = telemetry_by_machine.get(maquina["maquinaId"], [])[:20]
        leitura = leituras[0] if leituras else None
        leituras_atuais = [l for l in leituras if telemetria.classificar(l, app.config["IOT_MAX_AGE_SECONDS"])["fresh"]]
        risco_ativo = calcular_risco_maquina(maquina, leituras_atuais)
        contexto_ativo = risk_context_service.montar(fazenda, fontes, leitura, maquina)
        device = device_by_machine.get(maquina["maquinaId"])
        last_seen = (device or {}).get("lastSeenAt") or (leitura or {}).get("receivedAt") or (leitura or {}).get("dataHora")
        resultados_maquinas.append({"machine": maquina, "iot": contexto_ativo["iot"],
            "machineRisk": risco_ativo, "operationalContextRisk": None,
            "location": contexto_ativo["machineContext"], "deviceId": (device or {}).get("deviceId"),
            "deviceHealth": devices.health(last_seen, app.config["DEVICE_STALE_AFTER_SECONDS"],
                                           app.config["DEVICE_OFFLINE_AFTER_SECONDS"])})
    contexto = risk_context_service.montar(fazenda, fontes)
    machines_with_fresh_iot = [item["machine"].get("maquinaId") for item in resultados_maquinas
                               if item["iot"].get("fresh")]
    if machines_with_fresh_iot:
        contexto["iot"].update({"available": True, "fresh": True, "status": "available_on_machine_context",
            "participou": True, "participouNoScoreAmbiental": False,
            "machineCount": len(machines_with_fresh_iot), "machineIds": machines_with_fresh_iot})
        contexto["dataCoverage"]["iotAvailable"] = True
    contexto["riskDomains"].update({
        "machineRisk": "calculated_per_machine_when_valid_data_exists",
        "operationalContextRisk": "calculated_per_machine_with_explicit_state_rules",
    })
    riscos = calcular_riscos(contexto)
    for item in resultados_maquinas:
        local = item["location"]
        hotspot_age = local.get("nearestHotspotAgeHours")
        recent_hotspot_distance = (local["nearestHotspotDistanceKm"]
            if (machine_is_operating(item["machine"]) and isinstance(hotspot_age, (int, float))
                and 0 <= hotspot_age <= app.config["HOTSPOT_MAX_AGE_HOURS"])
            else None)
        item["operationalContextRisk"] = calcular_risco_operacional(
            riscos, item["machineRisk"], local["locationCurrent"], local["insideProperty"],
            recent_hotspot_distance, app.config["OPERATIONAL_HOTSPOT_DISTANCE_KM"])
    explanations = explain_risks(riscos, contexto["dataCoverage"])
    analise = {
        "fazendaId": fazenda_id, "localizacao": contexto["property"]["localizacao"],
        "timestamp": datetime.now(timezone.utc), "riskEngineVersion": MOTOR_VERSION,
        "riskContextVersion": contexto["riskContextVersion"],
        "score": riscos["geral"]["score"], "nivel": riscos["geral"]["nivel"],
        "fatores": {nome: item.get("fatores", []) for nome, item in riscos.items() if isinstance(item, dict)},
        "fontesUtilizadas": [nome for nome, fonte in fontes.items() if fonte.get("status") in ("ok", "parcial", "sem_evidencia_na_fonte")],
        "fontesIndisponiveis": contexto["sourcesUnavailable"],
        "contextoSnapshot": {"property": contexto["property"], "dataCoverage": contexto["dataCoverage"],
                              "sourceHealth": contexto["sourceHealth"]},
        "iotParticipou": any(x["iot"]["participou"] for x in resultados_maquinas), "riscos": riscos,
        "machineResults": resultados_maquinas,
        "evidencias": {nome: item.get("fatores", []) for nome, item in riscos.items() if isinstance(item, dict)},
        "riskExplanations": explanations, "dataCoverage": contexto["dataCoverage"],
        "provenance": contexto["provenance"],
    }
    persistencia = {"status": "ok", "documentoId": None}
    generated_events, generated_alerts = [], []
    try:
        salvo = salvar_documento(*_firebase_args(), COLECAO_ANALISES, analise)
        analysis_id = salvo.get("name", "").split("/")[-1]
        persistencia["documentoId"] = analysis_id
        try:
            if app.config.get("TESTING") and not app.config.get("TEST_POST_ANALYSIS_PIPELINE"):
                raise _SkipPostAnalysis
            previous_property = _best_effort(
                "property_snapshot_read", lambda: snapshots.get_property(fazenda_id), {}) or {}
            previous_fire = (previous_property.get("environmentalRisk") or {}).get("incendio", {})
            fire = riscos.get("incendio", {})
            environmental_event = _best_effort("environmental_event_write", lambda: events.risk_transition(
                "environmental_risk_changed", fazenda_id, "incendio", fire.get("nivel"),
                previous_fire.get("nivel") if previous_fire else None, analysis_id,
                current_score=fire.get("score"), previous_score=previous_fire.get("score"),
                factors=fire.get("fatores"), evidence=explanations.get("incendio", {}).get("evidence")))
            if environmental_event:
                generated_events.append(environmental_event)
            previous_machine_items = _best_effort(
                "machine_snapshots_read", lambda: snapshots.list_machines(fazenda_id), [])
            previous_by_machine = {item.get("maquinaId"): item for item in previous_machine_items}
            for item in resultados_maquinas:
                machine_id = item["machine"]["maquinaId"]
                previous = previous_by_machine.get(machine_id, {})
                for event_type, risk_type, current_risk, previous_key in (
                    ("machine_risk_changed", "machine", item["machineRisk"], "machineRisk"),
                    ("operational_risk_changed", "operational", item["operationalContextRisk"], "operationalRisk"),
                ):
                    event = _best_effort(f"{event_type}_write", lambda: events.risk_transition(
                        event_type, fazenda_id, risk_type, current_risk.get("level"),
                        (previous.get(previous_key) or {}).get("level") if previous else None,
                        analysis_id, machine_id, current_score=current_risk.get("score"),
                        previous_score=(previous.get(previous_key) or {}).get("score") if previous else None,
                        factors=current_risk.get("factors"), evidence=current_risk.get("evidence")))
                    if event:
                        generated_events.append(event)
            generated_alerts = _best_effort("alerts_evaluation", lambda: alerts.evaluate(
                fazenda_id, riscos, resultados_maquinas, analysis_id, generated_events,
                contexto["geospatial"].get("hotspotMaisProximo")), [])
            trend = _best_effort("risk_trend_read", lambda: historico_risco.tendencias(fazenda_id),
                                 {"fazendaId": fazenda_id, "samples": 0, "risks": {}})
            _best_effort("property_snapshot_write", lambda: snapshots.save_property(fazenda_id, {
                "environmentalRisk": riscos, "riskExplanations": explanations,
                "coverage": contexto["dataCoverage"], "sourceHealth": contexto["sourceHealth"],
                "trend": trend, "analysisAt": analise["timestamp"], "sourceAnalysisId": analysis_id,
            }))
            for item in resultados_maquinas:
                machine_id = item["machine"]["maquinaId"]
                latest_reading = (telemetry_by_machine.get(machine_id) or [None])[0]
                _best_effort("machine_snapshot_write", lambda: snapshots.save_machine(fazenda_id, machine_id, {
                    "identity": {key: item["machine"].get(key) for key in
                                 ("maquinaId", "nome", "tipo", "status")},
                    "deviceId": item.get("deviceId"), "deviceHealth": item["deviceHealth"],
                    "lastSeenAt": item["deviceHealth"].get("lastSeenAt"),
                    "latestTelemetryAt": (latest_reading or {}).get("dataHora"),
                    "latestMeasurements": (latest_reading or {}).get("measurements", {}),
                    "machineRisk": item["machineRisk"], "operationalRisk": item["operationalContextRisk"],
                    "environmentalContext": {"incendio": riscos.get("incendio"), "geral": riscos.get("geral")},
                    "location": item["location"], "sourceAnalysisId": analysis_id,
                    "attention": _machine_requires_attention(item["machineRisk"],
                                                              item["operationalContextRisk"], item["deviceHealth"]),
                }))
        except _SkipPostAnalysis:
            pass
        except Exception as error:
            LOGGER.warning("core_post_analysis_pipeline_failed error_type=%s", type(error).__name__)
    except Exception as erro:
        LOGGER.warning("property_risk_not_persisted error_type=%s", type(erro).__name__)
        persistencia = {"status": "erro", "codigo": "persistencia_indisponivel"}
    return jsonify({"status": "ok", "apiContractVersion": app.config["API_CONTRACT_VERSION"],
                    "riskEngineVersion": MOTOR_VERSION, "contexto": contexto,
                    "environmentalRisk": riscos, "riscos": riscos, "machines": resultados_maquinas,
                    "hotspots": contexto["geospatial"]["queimadas"].get("dados", {}),
                    "confidenceByRisk": {n: v.get("confianca") for n, v in riscos.items() if isinstance(v, dict)},
                    "riskExplanations": explanations, "events": generated_events,
                    "alerts": [item["alert"] for item in generated_alerts
                               if item["alert"].get("status") in {"open", "acknowledged"}],
                    "persistencia": persistencia})


@app.route("/fazendas/<fazenda_id>/analises", methods=["GET"])
def analises_fazenda(fazenda_id):
    try:
        itens = historico_risco.listar(fazenda_id, request.args.get("limit"), request.args.get("startTime"), request.args.get("endTime"))
        if request.args.get("includeDetails", "false").lower() != "true":
            itens = [{"timestamp": x.get("timestamp"), "riskScore": x.get("score"), "riskLevel": x.get("nivel"),
                      "risks": {n: {"score": v.get("score"), "level": v.get("nivel"), "confidence": v.get("confianca")}
                                for n, v in (x.get("riscos") or {}).items() if isinstance(v, dict) and "score" in v}}
                     for x in itens]
        return jsonify({"status": "ok", "items": itens, "count": len(itens), "order": "timestamp_desc"})
    except (ValueError, ValidacaoPropriedadeError) as erro: return _erro(str(erro), 400, "dados_invalidos")
    except Exception: return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/fazendas/<fazenda_id>/risco/tendencia", methods=["GET"])
def tendencia_fazenda(fazenda_id):
    try: return jsonify({"status": "ok", "trend": historico_risco.tendencias(fazenda_id, request.args.get("limit"))})
    except (ValueError, ValidacaoPropriedadeError) as erro: return _erro(str(erro), 400, "dados_invalidos")
    except Exception: return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/eventos", methods=["GET"])
def listar_eventos():
    fazenda_id = request.args.get("fazendaId")
    if not fazenda_id:
        return _erro("fazendaId é obrigatório.", 400, "dados_invalidos")
    try:
        limit = int(request.args.get("limit", 50))
        if not 1 <= limit <= 100:
            raise ValueError("limit deve estar entre 1 e 100.")
        items = events.list(fazenda_id, limit)
        return jsonify({"status": "ok", "items": items, "count": len(items)})
    except (ValueError, ValidacaoPropriedadeError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception:
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


def _alert_filters(fazenda_id=None):
    filters = {key: request.args[key] for key in ("fazendaId", "maquinaId", "status", "severity", "type", "riskType")
               if request.args.get(key)}
    if fazenda_id is not None:
        filters["fazendaId"] = fazenda_id
    return filters


@app.route("/alertas", methods=["GET"])
def listar_alertas():
    try:
        items = alerts.list(_alert_filters(), request.args.get("limit", 50))
        return jsonify({"status": "ok", "items": items, "count": len(items)})
    except (AlertValidationError, ValidacaoPropriedadeError, ValueError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception:
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/fazendas/<fazenda_id>/alertas", methods=["GET"])
def listar_alertas_fazenda(fazenda_id):
    try:
        items = alerts.list(_alert_filters(fazenda_id), request.args.get("limit", 50))
        return jsonify({"status": "ok", "items": items, "count": len(items)})
    except (AlertValidationError, ValidacaoPropriedadeError, ValueError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception:
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/alertas/<alert_id>", methods=["GET", "PATCH"])
def detalhe_alerta(alert_id):
    try:
        if request.method == "GET":
            alert = alerts.get(alert_id)
        else:
            if not request.is_json:
                return _erro("Content-Type deve ser application/json.", 415, "tipo_conteudo_invalido")
            data = request.get_json(silent=True)
            if (not isinstance(data, dict) or set(data) != {"status"}
                    or data.get("status") not in {"acknowledged", "resolved"}):
                return _erro("PATCH aceita status acknowledged ou resolved.", 400, "dados_invalidos")
            alert = alerts.update_status(alert_id, data["status"], (g.auth_context or {}).get("actorId"))
            if alert:
                _audit(f"alert.{data['status']}", "alert", alert_id, {"status": data["status"]})
        if alert is None:
            return _erro("Alerta não encontrado.", 404, "nao_encontrado")
        return jsonify({"status": "ok", "alert": alert})
    except (AlertValidationError, ValidacaoPropriedadeError, ValueError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception:
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


def _list_active_alerts(filters):
    items = []
    for status in ("open", "acknowledged"):
        items.extend(alerts.list({**filters, "status": status}, 100))
    unique = {item.get("alertId") or item.get("id"): item for item in items}
    return sorted(unique.values(), key=lambda item: item.get("updatedAt")
                  if isinstance(item.get("updatedAt"), datetime)
                  else datetime.min.replace(tzinfo=timezone.utc), reverse=True)


@app.route("/dashboard", methods=["GET"])
def dashboard():
    try:
        limit = int(request.args.get("limit", 100))
        if not 1 <= limit <= 100:
            raise ValueError("limit deve estar entre 1 e 100.")
        property_items = propriedades.listar(limit)
        current_items = snapshots.list_properties(limit)
        current_by_farm = {item.get("fazendaId") or item.get("id"): item for item in current_items}
        attention_machines = snapshots.list_machines_attention(100)
        active_alerts = _list_active_alerts({})
        machine_count, alert_count = {}, {}
        for item in attention_machines:
            farm_id = item.get("fazendaId")
            machine_count[farm_id] = machine_count.get(farm_id, 0) + 1
        for item in active_alerts:
            farm_id = item.get("fazendaId")
            alert_count[farm_id] = alert_count.get(farm_id, 0) + 1
        cards = []
        for property_data in property_items:
            farm_id = property_data.get("id")
            current = current_by_farm.get(farm_id, {})
            cards.append({"property": property_data,
                "currentRisk": (current.get("environmentalRisk") or {}).get("geral"),
                "lastAnalysisAt": current.get("analysisAt"), "coverage": current.get("coverage", {}),
                "activeAlertCount": alert_count.get(farm_id, 0),
                "machinesAttentionCount": machine_count.get(farm_id, 0)})
        return jsonify({"status": "ok", "apiContractVersion": app.config["API_CONTRACT_VERSION"],
            "properties": cards, "machinesAttention": attention_machines,
            "alerts": active_alerts, "counts": {"properties": len(cards),
                "machinesAttention": len(attention_machines), "activeAlerts": len(active_alerts)}})
    except (ValueError, ValidacaoPropriedadeError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception as error:
        LOGGER.warning("dashboard_unavailable error_type=%s", type(error).__name__)
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/showcase/live-cases", methods=["GET"])
def showcase_live_cases():
    """Carteira demonstrativa com ambiente real e proveniência explícita."""
    try:
        payload = LiveCaseService.load_snapshot(app.config["LIVE_CASE_SNAPSHOT_PATH"])
        gerado_em = parse_timestamp(payload.get("generatedAt"), "generatedAt")
        idade = max(0, (datetime.now(timezone.utc) - gerado_em).total_seconds())
        payload["snapshotAgeSeconds"] = round(idade, 1)
        payload["stale"] = idade > app.config["LIVE_CASE_MAX_AGE_SECONDS"]
        payload["maxAgeSeconds"] = app.config["LIVE_CASE_MAX_AGE_SECONDS"]
        avisos = consultar_avisos_inmet()
        payload["weatherAlerts"] = {
            "status": avisos.get("status"),
            "source": avisos.get("atribuicao"),
            "consultedAt": avisos.get("consultadoEm"),
            "items": (avisos.get("dados") or {}).get("items", []),
        }
        return jsonify(payload)
    except (FileNotFoundError, ValueError):
        return _erro("Dados ambientais reais ainda não foram preparados.", 503, "live_cases_unavailable")


@app.route("/agent/query", methods=["POST"])
def consultar_agente_contextual():
    """Consulta read-only ao AgroRiskAgent; fatos vêm das tools oficiais."""
    if not request.is_json:
        return _erro("Content-Type deve ser application/json.", 415, "tipo_conteudo_invalido")
    payload = request.get_json(silent=True)
    allowed_fields = {"question", "contextPropertyId"}
    if (not isinstance(payload, dict) or "question" not in payload
            or set(payload) - allowed_fields):
        return _erro("Corpo deve conter question e, opcionalmente, contextPropertyId.", 400, "dados_invalidos")
    allowed, retry_after = rate_limiter.allow(
        f"contextual_agent:{request.remote_addr}", app.config["EXPENSIVE_RATE_LIMIT_REQUESTS"],
        app.config["EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS"],
    )
    if not allowed:
        response, status = _erro("Limite de consultas do agente excedido.", 429, "rate_limit_exceeded")
        response.headers["Retry-After"] = str(retry_after)
        return response, status
    try:
        return jsonify({"status": "ok", **agro_risk_agent.ask(
            payload.get("question"), payload.get("contextPropertyId"),
        )})
    except AgentValidationError as error:
        return _erro(str(error), 400, "dados_invalidos")
    except AgentProviderNotConfiguredError as error:
        return _erro(str(error), 503, "agent_provider_unconfigured")
    except AgentProviderError:
        return _erro("Provider de IA indisponível.", 503, "agent_provider_unavailable")


@app.route("/fazendas/<fazenda_id>/status", methods=["GET"])
def status_fazenda(fazenda_id):
    try:
        property_data = propriedades.obter(fazenda_id)
        if property_data is None:
            return _erro("Fazenda não encontrada.", 404, "nao_encontrada")
        machine_items = maquinas.listar(fazenda_id)
        machine_states = snapshots.list_machines(fazenda_id)
        state_by_id = {item.get("maquinaId"): item for item in machine_states}
        alert_items = _list_active_alerts({"fazendaId": fazenda_id})
        current = snapshots.get_property(fazenda_id)
        machine_summary = []
        for machine in machine_items:
            state = state_by_id.get(machine.get("maquinaId"), {})
            health = devices.health(state.get("lastSeenAt"), app.config["DEVICE_STALE_AFTER_SECONDS"],
                                    app.config["DEVICE_OFFLINE_AFTER_SECONDS"])
            machine_summary.append({
                "maquinaId": machine.get("maquinaId"), "nome": machine.get("nome"),
                "status": machine.get("status"), "deviceHealth": health,
                "machineRisk": state.get("machineRisk", {"status": "insufficient_data", "level": "unknown"}),
                "operationalRisk": state.get("operationalRisk", {"status": "insufficient_data", "level": "unknown"}),
                "lastSeenAt": state.get("lastSeenAt"),
            })
        return jsonify({
            "status": "ok", "apiContractVersion": app.config["API_CONTRACT_VERSION"],
            "property": property_data, "currentRisk": (current or {}).get("environmentalRisk"),
            "riskExplanations": (current or {}).get("riskExplanations", {}),
            "trend": (current or {}).get("trend"), "lastAnalysisAt": (current or {}).get("analysisAt"),
            "sourceAnalysisId": (current or {}).get("sourceAnalysisId"),
            "sourceHealth": (current or {}).get("sourceHealth", {}),
            "coverage": (current or {}).get("coverage", {}), "machines": machine_summary,
            "alerts": alert_items, "alertCount": len(alert_items),
        })
    except (ValueError, ValidacaoPropriedadeError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception as error:
        LOGGER.warning("property_status_unavailable error_type=%s", type(error).__name__)
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/fazendas/<fazenda_id>/maquinas/<maquina_id>/status", methods=["GET"])
def status_maquina(fazenda_id, maquina_id):
    try:
        machine = maquinas.obter(fazenda_id, maquina_id)
        if machine is None:
            return _erro("Máquina não encontrada.", 404, "nao_encontrada")
        property_data = propriedades.obter(fazenda_id)
        state = snapshots.get_machine(fazenda_id, maquina_id) or {}
        if not state:
            latest = telemetria.mais_recente(fazenda_id, maquina_id)
            device = next((item for item in devices.list(fazenda_id) if item.get("maquinaId") == maquina_id), None)
            last_seen = (device or {}).get("lastSeenAt") or (latest or {}).get("receivedAt") or (latest or {}).get("dataHora")
            health = devices.health(last_seen, app.config["DEVICE_STALE_AFTER_SECONDS"],
                                    app.config["DEVICE_OFFLINE_AFTER_SECONDS"])
            state = {"deviceId": (device or {}).get("deviceId"), "deviceHealth": health,
                     "lastSeenAt": last_seen, "latestMeasurements": (latest or {}).get("measurements", {}),
                     "latestMeasurementDescriptors": (latest or {}).get("measurementDescriptors", {}),
                     "latestTelemetryAt": (latest or {}).get("dataHora")}
        property_current = snapshots.get_property(fazenda_id) or {}
        try:
            alert_items = _list_active_alerts({"fazendaId": fazenda_id, "maquinaId": maquina_id})
        except Exception as error:
            LOGGER.warning("machine_status_alerts_unavailable error_type=%s", type(error).__name__)
            alert_items = []
        health = devices.health(state.get("lastSeenAt"), app.config["DEVICE_STALE_AFTER_SECONDS"],
                                app.config["DEVICE_OFFLINE_AFTER_SECONDS"])
        return jsonify({
            "status": "ok", "apiContractVersion": app.config["API_CONTRACT_VERSION"],
            "identity": machine, "property": property_data, "deviceId": state.get("deviceId"),
            "deviceHealth": health,
            "lastSeenAt": state.get("lastSeenAt"), "latestTelemetryAt": state.get("latestTelemetryAt"),
            "latestMeasurements": state.get("latestMeasurements", {}),
            "latestMeasurementDescriptors": state.get("latestMeasurementDescriptors", {}),
            "machineRisk": state.get("machineRisk", {"status": "insufficient_data", "level": "unknown"}),
            "environmentalContext": state.get("environmentalContext", property_current.get("environmentalRisk")),
            "operationalRisk": state.get("operationalRisk", {"status": "insufficient_data", "level": "unknown"}),
            "location": state.get("location", {"locationCurrent": False}),
            "alerts": alert_items, "alertCount": len(alert_items),
        })
    except (ValueError, ValidacaoPropriedadeError) as error:
        return _erro(str(error), 400, "dados_invalidos")
    except Exception as error:
        LOGGER.warning("machine_status_unavailable error_type=%s", type(error).__name__)
        return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


@app.route("/regional/risco", methods=["GET"])
def risco_regional():
    uf = (request.args.get("uf") or "").upper(); risk_type = request.args.get("riskType", "incendio")
    try: limite = int(request.args.get("limit", app.config["REGIONAL_MAX_LOCATIONS"]))
    except ValueError: return _erro("limit deve ser inteiro.", 400, "dados_invalidos")
    if uf not in ESTADOS or not 1 <= limite <= app.config["REGIONAL_READ_MAX_LIMIT"]:
        return _erro("UF ou limite inválido.", 400, "dados_invalidos")
    if risk_type != "incendio":
        return _erro("Regional V1 suporta apenas riskType=incendio.", 400, "risk_type_nao_suportado")
    try:
        itens = regional_snapshots.listar(uf, risk_type, limite, request.args.get("level"), request.args.get("municipality"))
        agora = datetime.now(timezone.utc)
        for item in itens:
            calculado = item.get("calculatedAt")
            idade = max(0, (agora - calculado).total_seconds()) if isinstance(calculado, datetime) else None
            item["dataAgeSeconds"] = round(idade, 1) if idade is not None else None
            item["stale"] = idade is None or idade > app.config["REGIONAL_STALE_AFTER_SECONDS"]
        atualizado = max((x.get("calculatedAt") for x in itens if isinstance(x.get("calculatedAt"), datetime)), default=None)
        LOGGER.info("service=regional_snapshot_read state=%s risk=%s items=%d", uf, risk_type, len(itens))
        return jsonify({"status": "ok", "apiContractVersion": app.config["API_CONTRACT_VERSION"],
                        "state": uf, "riskType": risk_type, "updatedAt": atualizado,
                        "items": itens, "count": len(itens), "source": "regional_risk_current"})
    except Exception as erro:
        LOGGER.warning("service=regional_snapshot_read error_type=%s", type(erro).__name__)
        return _erro("Dados regionais indisponíveis.", 503, "regional_indisponivel")


@app.route("/regional/risco/<ibge_code>", methods=["GET"])
def detalhe_risco_regional(ibge_code):
    risk_type = request.args.get("riskType", "incendio")
    if not ibge_code.isdigit() or risk_type != "incendio": return _erro("Parâmetros inválidos.", 400, "dados_invalidos")
    try:
        item = regional_snapshots.detalhe(ibge_code, risk_type)
        if item is None: return _erro("Snapshot municipal não encontrado.", 404, "nao_encontrada")
        try:
            historico = regional_snapshots.historico(ibge_code, risk_type, limit=20)
            item["trend"] = regional_snapshots.tendencia(historico)
        except Exception:
            item["trend"] = {"status": "unavailable", "direction": "unknown", "samples": 0}
        return jsonify({"status": "ok", "apiContractVersion": app.config["API_CONTRACT_VERSION"], "item": item})
    except ValueError as erro: return _erro(str(erro), 400, "dados_invalidos")
    except Exception: return _erro("Dados regionais indisponíveis.", 503, "regional_indisponivel")


@app.route("/regional/risco/<ibge_code>/historico", methods=["GET"])
def historico_risco_regional(ibge_code):
    risk_type = request.args.get("riskType", "incendio")
    if not ibge_code.isdigit() or risk_type != "incendio": return _erro("Parâmetros inválidos.", 400, "dados_invalidos")
    try:
        itens = regional_snapshots.historico(ibge_code, risk_type, request.args.get("limit", 50),
            request.args.get("startTime"), request.args.get("endTime"))
        serie = [{"calculatedAt": x.get("calculatedAt"), "riskScore": x.get("riskScore"),
                  "riskLevel": x.get("riskLevel"), "confidence": x.get("confidence")} for x in itens]
        return jsonify({"status": "ok", "ibgeCode": ibge_code, "riskType": risk_type,
                        "items": serie, "trend": regional_snapshots.tendencia(itens)})
    except ValueError as erro: return _erro(str(erro), 400, "dados_invalidos")
    except Exception: return _erro("Dados regionais indisponíveis.", 503, "regional_indisponivel")


@app.route("/regional/map", methods=["GET"])
def mapa_regional():
    uf = (request.args.get("uf") or "").upper(); risk_type = request.args.get("riskType", "incendio")
    if uf not in ESTADOS or risk_type != "incendio": return _erro("Parâmetros inválidos.", 400, "dados_invalidos")
    try:
        itens = regional_snapshots.listar(uf, risk_type, app.config["REGIONAL_READ_MAX_LIMIT"])
        pontos = [{"id": x.get("territory", {}).get("ibgeCode"), "municipality": x.get("territory", {}).get("municipality"),
                   "lat": x.get("coordinates", {}).get("latitude"), "lon": x.get("coordinates", {}).get("longitude"),
                   "riskLevel": x.get("riskLevel"), "riskScore": x.get("riskScore"), "type": "municipality_representative_point"}
                  for x in itens]
        return jsonify({"status": "ok", "state": uf, "riskType": risk_type, "points": pontos})
    except Exception: return _erro("Dados regionais indisponíveis.", 503, "regional_indisponivel")


@app.route("/regional/hotspots", methods=["GET"])
def hotspots_regionais():
    uf = (request.args.get("uf") or "").upper()
    if uf not in ESTADOS: return _erro("UF inválida.", 400, "dados_invalidos")
    try:
        itens = regional_snapshots.listar(uf, "incendio", app.config["REGIONAL_READ_MAX_LIMIT"])
        unicos = {}
        for item in itens:
            foco = (item.get("hotspotSummary") or {}).get("nearestHotspot")
            if foco and foco.get("latitude") is not None and foco.get("longitude") is not None:
                chave = (foco["latitude"], foco["longitude"], foco.get("detectedAt") or foco.get("dataHoraUtc"))
                unicos[chave] = {"lat": foco["latitude"], "lon": foco["longitude"],
                    "detectedAt": chave[2], "ageHours": foco.get("ageHours") or foco.get("idadeHoras"),
                    "source": foco.get("source", "INPE Programa Queimadas")}
        return jsonify({"status": "ok", "state": uf, "items": list(unicos.values()),
                        "source": "regional snapshots; not a complete statewide hotspot feed"})
    except Exception: return _erro("Dados regionais indisponíveis.", 503, "regional_indisponivel")


if app.config["ENABLE_FIREBASE_TEST_ROUTE"]:
    @app.route("/teste-firebase", methods=["POST"])
    def teste_firebase():
        try:
            resultado = salvar_no_firebase(25.0, 50.0, "fazenda_teste", "maquina_teste")
            return jsonify({"status": "ok", "documento": resultado.get("name")})
        except Exception:
            return _erro("Persistência indisponível.", 503, "persistencia_indisponivel")


if __name__ == "__main__":
    LOGGER.info("Sompo iniciado; estado Firebase=%s", firebase.status)
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=False)
