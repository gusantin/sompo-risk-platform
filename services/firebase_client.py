"""Inicialização tardia e tolerante a falhas do Firestore REST."""

import json
import logging
import os

from google.auth.transport.requests import Request
from google.oauth2 import service_account


LOGGER = logging.getLogger(__name__)


class FirebaseClient:
    def __init__(self, key_path):
        self.key_path = key_path
        self._credentials = None
        self._auth_request = Request()
        self.firestore_url = None
        self.project_id = None
        self.error = None

    def initialize(self):
        if self._credentials is not None:
            return
        try:
            if not os.path.isfile(self.key_path):
                raise FileNotFoundError("Credencial Firebase não encontrada.")
            with open(self.key_path, "r", encoding="utf-8") as arquivo:
                config = json.load(arquivo)
            self.project_id = config["project_id"]
            self._credentials = service_account.Credentials.from_service_account_file(
                self.key_path, scopes=["https://www.googleapis.com/auth/datastore"]
            )
            self.firestore_url = (
                f"https://firestore.googleapis.com/v1/projects/{self.project_id}/"
                "databases/(default)/documents"
            )
            self.error = None
        except Exception as erro:
            self.error = str(erro)
            LOGGER.warning("Firebase indisponível: %s", erro)
            raise RuntimeError("Firebase indisponível.") from erro

    def obter_token(self):
        self.initialize()
        if not self._credentials.valid:
            self._credentials.refresh(self._auth_request)
        return self._credentials.token

    @property
    def status(self):
        if self._credentials is not None:
            return "configurado"
        return "indisponivel" if self.error else "nao_inicializado"
