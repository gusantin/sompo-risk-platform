"""Fusão explícita de propriedade, fontes externas e telemetria opcional."""

import math
from datetime import datetime, timedelta, timezone

from integracoes.geoespacial import distancia_km, ponto_no_geojson
from services.telemetria_service import TelemetriaService


MOTOR_VERSION = "1.0.0"
RISK_CONTEXT_VERSION = "2.1.0"


def _timestamp(valor):
    if isinstance(valor, datetime):
        return valor.astimezone(timezone.utc) if valor.tzinfo is not None else None
    if isinstance(valor, str):
        try:
            return datetime.fromisoformat(valor.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _leitura_valida(item):
    temperatura = item.get("temperatura")
    umidade = item.get("umidade")
    if temperatura is None and umidade is None and isinstance(item.get("measurements"), dict):
        valores = list(item["measurements"].values())
        return bool(valores) and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in valores) and _timestamp(item.get("dataHora")) is not None
    return (
        isinstance(temperatura, (int, float)) and not isinstance(temperatura, bool)
        and math.isfinite(temperatura)
        and isinstance(umidade, (int, float)) and not isinstance(umidade, bool)
        and math.isfinite(umidade) and 0 <= umidade <= 100
        and _timestamp(item.get("dataHora")) is not None
    )


class RiskContextService:
    def __init__(self, firebase, iot_max_age_minutes=15, telemetria_service=None, maquina_service=None,
                 machine_location_max_age_seconds=900, iot_max_age_seconds=None,
                 property_telemetry_query_limit=1000):
        self.firebase = firebase
        self.iot_max_age_minutes = iot_max_age_minutes
        self.iot_max_age_seconds = iot_max_age_seconds or iot_max_age_minutes * 60
        self.telemetria = telemetria_service or TelemetriaService(firebase)
        self.maquinas = maquina_service
        self.machine_location_max_age_seconds = machine_location_max_age_seconds
        self.property_telemetry_query_limit = property_telemetry_query_limit

    def leitura_recente(self, fazenda_id):
        try:
            if self.maquinas is None: return None
            maquinas = self.maquinas.listar(fazenda_id)
            machine_ids = {item.get("maquinaId") for item in maquinas}
            if not machine_ids:
                return None
            leituras = self.telemetria.historico_fazenda(fazenda_id, self.property_telemetry_query_limit)
            candidatas = [leitura for leitura in leituras
                if leitura.get("fazendaId") == fazenda_id and leitura.get("maquinaId") in machine_ids
                and _leitura_valida(leitura)]
        except (RuntimeError, ValueError): return None
        if not candidatas:
            return None
        leitura = max(candidatas, key=lambda item: _timestamp(item["dataHora"]))
        instante = _timestamp(leitura["dataHora"])
        idade = datetime.now(timezone.utc) - instante
        if idade < timedelta(minutes=-1) or idade > timedelta(seconds=self.iot_max_age_seconds):
            return None
        return leitura

    def montar(self, propriedade, fontes, leitura=None, maquina=None):
        clima = fontes.get("clima", {})
        queimadas = fontes.get("queimadas", {})
        indisponiveis = [
            nome for nome, fonte in fontes.items()
            if fonte.get("status") in ("erro_api", "timeout", "invalid", "fonte_sem_cobertura")
        ]
        proveniencia = {
            nome: {
                "origem": fonte.get("atribuicao", nome),
                "consultadoEm": fonte.get("consultadoEm"),
                "observadoEm": fonte.get("dados", {}).get("dataHoraObservacaoUtc"),
                "cache": fonte.get("cache", False),
                "stale": fonte.get("stale", False),
                "disponibilidade": fonte.get("status"),
                "participouNoScore": nome in {"clima", "hidrologia", "terreno", "sgb", "queimadas"}
                and fonte.get("status") in ("ok", "parcial", "sem_evidencia_na_fonte"),
            }
            for nome, fonte in fontes.items()
        }
        iot = {"available": False, "fresh": False, "status": "missing", "participou": False,
               "participouNoScoreAmbiental": False, "ageSeconds": None, "measurementScope": "unknown"}
        if leitura:
            estado = self.telemetria.classificar(leitura, self.iot_max_age_seconds)
            instante = _timestamp(leitura.get("dataHora"))
            sensor_scope = "unknown"
            if maquina:
                scopes = {s.get("scope", "unknown") for s in maquina.get("sensoresConfigurados", [])}
                sensor_scope = scopes.pop() if len(scopes) == 1 else "mixed" if scopes else "unknown"
            iot = {
                "available": estado["fresh"], "fresh": estado["fresh"], "status": estado["status"],
                "ageSeconds": estado["ageSeconds"], "participou": estado["fresh"],
                "participouNoScoreAmbiental": False, "measurementScope": sensor_scope,
                "fazendaId": leitura.get("fazendaId"),
                "maquinaId": leitura.get("maquinaId"),
                "temperaturaC": leitura.get("temperatura"),
                "umidadePct": leitura.get("umidade"),
                "measurements": leitura.get("measurements", {}),
                "measurementDescriptors": leitura.get("measurementDescriptors", {}),
                "observadoEm": _timestamp(leitura.get("dataHora")),
                "origem": leitura.get("origem", "ESP32"),
            }
        foco = queimadas.get("dados", {}).get("focoMaisProximo")
        localizacao_atual = False; dentro = None; distancia_foco = None
        idade_foco_horas = (foco or {}).get("ageHours", (foco or {}).get("idadeHoras"))
        if maquina and maquina.get("latitude") is not None and maquina.get("lastLocationAt"):
            instante_local = _timestamp(maquina["lastLocationAt"])
            localizacao_atual = bool(instante_local and 0 <= (datetime.now(timezone.utc) - instante_local).total_seconds() <= self.machine_location_max_age_seconds)
            if localizacao_atual:
                dentro = ponto_no_geojson(maquina["latitude"], maquina["longitude"], propriedade.get("poligonoGeoJson"))
                if foco:
                    distancia_foco = round(distancia_km(maquina["latitude"], maquina["longitude"], foco["latitude"], foco["longitude"]), 2)
        source_health = {nome: {"status": fonte.get("status", "invalid"), "cacheHit": fonte.get("cache", False)} for nome, fonte in fontes.items()}
        return {
            "riskContextVersion": RISK_CONTEXT_VERSION,
            "generatedAt": datetime.now(timezone.utc),
            "property": {
                "fazendaId": propriedade["id"],
                "localizacao": {"latitude": propriedade["latitude"], "longitude": propriedade["longitude"]},
                "areaHectares": propriedade["areaHectares"],
                "atividadePrincipal": propriedade["atividadePrincipal"],
                "culturas": propriedade.get("culturas", []),
                "caracteristicas": {
                    chave: propriedade.get(chave) for chave in (
                        "irrigacao", "tipoSolo", "texturaSolo", "riscoEncharcamento",
                        "riscoAtolamento", "decliveAcentuado", "riscoErosao",
                        "presencaPalhadaVegetacaoSeca",
                    )
                },
                "historico": {
                    "incendio": propriedade.get("historicoIncendio"),
                    "principioIncendioMaquinas": propriedade.get("historicoPrincipioIncendioMaquinas"),
                },
                "evidencias": {"palhadaVegetacaoSeca": propriedade.get("presencaPalhadaVegetacaoSeca"),
                    "pontosAreasCriticas": propriedade.get("pontosAreasCriticas", []),
                    "descricaoPontosCriticos": propriedade.get("descricaoPontosCriticos")},
            },
            "weather": clima,
            "geospatial": {
                "queimadas": queimadas, "sgb": fontes.get("sgb", {}),
                "terreno": fontes.get("terreno", {}), "hidrologia": fontes.get("hidrologia", {}),
                "hotspotMaisProximo": queimadas.get("dados", {}).get("focoMaisProximo"),
                "hotspotsPorRaioKm": queimadas.get("dados", {}).get("quantidadePorRaioKm", {}),
            },
            "satellite": {"hotspots": queimadas},
            "history": {
                "incendio": propriedade.get("historicoIncendio"),
                "principioIncendioMaquinas": propriedade.get("historicoPrincipioIncendioMaquinas"),
            },
            "observations": {"inmet": fontes.get("inmet", {})},
            "iot": iot,
            "machineContext": {"machine": maquina, "locationCurrent": localizacao_atual,
                "insideProperty": dentro, "nearestHotspotDistanceKm": distancia_foco,
                "nearestHotspotAgeHours": idade_foco_horas},
            "provenance": proveniencia,
            "sourceHealth": source_health,
            "dataCoverage": {"weatherAvailable": clima.get("status") in ("ok", "parcial"),
                "satelliteAvailable": queimadas.get("status") in ("ok", "parcial"),
                "geospatialAvailable": any(fontes.get(n, {}).get("status") in ("ok", "parcial") for n in ("terreno", "sgb", "hidrologia")),
                "historyAvailable": any(propriedade.get(name) is not None for name in
                    ("historicoIncendio", "historicoPrincipioIncendioMaquinas")),
                "propertyContextAvailable": True, "iotAvailable": iot["available"]},
            "sourcesUnavailable": indisponiveis,
            "cropRiskFactors": {
                "status": "nao_calibrado", "comportamento": "neutro", "contribuicaoScore": 0,
            },
            "cropProfile": [{"name": c.get("nome"), "areaHa": c.get("areaHectares"),
                "stage": c.get("estagioSafra"), "notes": c.get("observacoes"),
                "riskMetadata": {"status": "not_calibrated"}} for c in propriedade.get("culturas", [])],
            "riskDomains": {
                "environmentalRisk": "calculado_pelo_motor_deterministico",
                "machineRisk": "calculado_por_maquina_quando_ha_dados_validos",
                "operationalContextRisk": "calculado_por_maquina_com_regras_de_estado_explicitas",
            },
            "rawSources": fontes,
        }
