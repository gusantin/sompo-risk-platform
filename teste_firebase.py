import json
import requests

from google.oauth2 import service_account
from google.auth.transport.requests import Request


ARQUIVO_CHAVE = "firebase-key.json"


# ============================================
# LER FIREBASE
# ============================================

with open(ARQUIVO_CHAVE, "r", encoding="utf-8") as arquivo:
    config = json.load(arquivo)


PROJECT_ID = config["project_id"]

print("Projeto:", PROJECT_ID)


# ============================================
# AUTENTICAÇÃO
# ============================================

credentials = service_account.Credentials.from_service_account_file(
    ARQUIVO_CHAVE,
    scopes=[
        "https://www.googleapis.com/auth/datastore"
    ]
)

credentials.refresh(Request())

token = credentials.token

print("Autenticacao Google: OK")


# ============================================
# FIRESTORE REST
# ============================================

url = (
    f"https://firestore.googleapis.com/v1/"
    f"projects/{PROJECT_ID}/databases/(default)/documents/"
    f"teste_conexao/teste_01"
)


payload = {
    "fields": {
        "status": {
            "stringValue": "ok"
        },

        "mensagem": {
            "stringValue": "Firebase conectado via REST"
        }
    }
}


headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}


print("Enviando para Firestore...")


resposta = requests.patch(
    url,
    headers=headers,
    json=payload,
    timeout=30
)


print("HTTP:", resposta.status_code)
print(resposta.text)


if resposta.status_code == 200:
    print()
    print("==============================")
    print("FIREBASE FUNCIONANDO!")
    print("==============================")
else:
    print()
    print("==============================")
    print("ERRO AO CONECTAR")
    print("==============================")