import json
import logging
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from integracoes.open_meteo import consultar_clima, consultar_hidrologia, consultar_terreno
from integracoes.inmet import consultar_inmet
from integracoes.inpe_queimadas import consultar_queimadas
from integracoes.sgb import consultar_suscetibilidade
from services.firestore_service import montar_analise, salvar_documento
from services.risco_service import calcular_riscos


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)
app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FIREBASE_KEY = os.environ.get(
    "FIREBASE_KEY_PATH", os.path.join(BASE_DIR, "firebase-key.json")
)
COLECAO_SENSORES = "leituras_sensores"
COLECAO_ANALISES = "analises_risco"

if not os.path.exists(FIREBASE_KEY):
    raise FileNotFoundError("firebase-key.json não encontrado.")

with open(FIREBASE_KEY, "r", encoding="utf-8") as arquivo:
    firebase_config = json.load(arquivo)

PROJECT_ID = firebase_config["project_id"]
credentials = service_account.Credentials.from_service_account_file(
    FIREBASE_KEY, scopes=["https://www.googleapis.com/auth/datastore"]
)
auth_request = Request()
FIRESTORE_URL = (
    f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/"
    "databases/(default)/documents"
)


def obter_token():
    if not credentials.valid:
        credentials.refresh(auth_request)
    return credentials.token


def salvar_no_firebase(temperatura, umidade, fazenda_id, maquina_id):
    """Preserva o contrato de persistência usado pelo ESP32."""
    return salvar_documento(
        FIRESTORE_URL, obter_token, COLECAO_SENSORES,
        {
            "fazendaId": fazenda_id, "maquinaId": maquina_id,
            "temperatura": temperatura, "umidade": umidade,
            "dataHora": datetime.now(timezone.utc).isoformat(), "origem": "ESP32",
        },
    )


def _coordenada(nome, minimo, maximo):
    valor = request.args.get(nome)
    if valor is None or not valor.strip():
        raise ValueError(f"Parâmetro '{nome}' é obrigatório.")
    try:
        numero = float(valor)
    except ValueError as erro:
        raise ValueError(f"Parâmetro '{nome}' deve ser numérico.") from erro
    if not minimo <= numero <= maximo:
        raise ValueError(f"Parâmetro '{nome}' deve estar entre {minimo} e {maximo}.")
    return numero


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online", "projeto": "Sompo",
        "firebase": "REST", "projectId": PROJECT_ID,
    })


@app.route("/dados", methods=["POST"])
def receber_dados():
    try:
        dados = request.get_json(silent=True)
        if not dados:
            return jsonify({"status": "erro", "mensagem": "Nenhum JSON recebido"}), 400
        temperatura = dados.get("temperatura")
        umidade = dados.get("umidade")
        if temperatura is None or umidade is None:
            return jsonify({
                "status": "erro", "mensagem": "Temperatura ou umidade não recebida",
            }), 400
        temperatura = float(temperatura)
        umidade = float(umidade)
        fazenda_id = str(dados.get("fazendaId", "fazenda_01"))
        maquina_id = str(dados.get("maquinaId", "trator_01"))
        LOGGER.info(
            "Dados ESP32 recebidos: fazenda=%s máquina=%s temperatura=%.2f umidade=%.2f",
            fazenda_id, maquina_id, temperatura, umidade,
        )
        resultado = salvar_no_firebase(temperatura, umidade, fazenda_id, maquina_id)
        documento_id = resultado.get("name", "").split("/")[-1]
        return jsonify({
            "status": "ok", "mensagem": "Dados salvos no Firebase",
            "documentoId": documento_id, "temperatura": temperatura, "umidade": umidade,
        }), 200
    except ValueError:
        return jsonify({
            "status": "erro", "mensagem": "Temperatura e umidade devem ser números",
        }), 400
    except Exception as erro:
        LOGGER.exception("Erro ao processar dados do ESP32")
        return jsonify({
            "status": "erro", "tipo": type(erro).__name__, "mensagem": str(erro),
        }), 500


@app.route("/risco", methods=["GET"])
def consultar_risco():
    try:
        latitude = _coordenada("lat", -90, 90)
        longitude = _coordenada("lon", -180, 180)
    except ValueError as erro:
        return jsonify({"status": "erro", "mensagem": str(erro)}), 400

    LOGGER.info("Iniciando análise de risco para lat=%s lon=%s", latitude, longitude)
    fontes = {
        "clima": consultar_clima(latitude, longitude),
        "hidrologia": consultar_hidrologia(latitude, longitude),
        "terreno": consultar_terreno(latitude, longitude),
        "sgb": consultar_suscetibilidade(latitude, longitude),
        "queimadas": consultar_queimadas(latitude, longitude),
        "inmet": consultar_inmet(latitude, longitude),
    }
    riscos = calcular_riscos(fontes)
    persistencia = {"status": "ok", "documentoId": None}
    try:
        analise = montar_analise(latitude, longitude, riscos, fontes)
        salvo = salvar_documento(
            FIRESTORE_URL, obter_token, COLECAO_ANALISES, analise, timeout=20
        )
        persistencia["documentoId"] = salvo.get("name", "").split("/")[-1]
    except Exception as erro:
        LOGGER.exception("Análise calculada, mas não persistida no Firestore")
        persistencia = {"status": "erro", "mensagem": str(erro)}

    return jsonify({
        "status": "ok", "localizacao": {"latitude": latitude, "longitude": longitude},
        "riscos": riscos, "fontes": fontes, "persistencia": persistencia,
    })


@app.route("/teste-firebase", methods=["GET"])
def teste_firebase():
    try:
        resultado = salvar_no_firebase(25.0, 50.0, "fazenda_teste", "maquina_teste")
        return jsonify({
            "status": "ok", "mensagem": "Firebase funcionando",
            "documento": resultado.get("name"),
        })
    except Exception as erro:
        return jsonify({
            "status": "erro", "tipo": type(erro).__name__, "mensagem": str(erro),
        }), 500


if __name__ == "__main__":
    LOGGER.info("Sompo iniciado: Firebase REST, coleção ESP32=%s", COLECAO_SENSORES)
    app.run(host="0.0.0.0", port=5000, debug=False)
