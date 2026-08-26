"""Identidade, credencial e saúde de dispositivos IoT."""

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from services.firestore_service import (
    atualizar_campos_documento, atualizar_documento, criar_documento, consultar_documentos, obter_documento,
)
from services.propriedade_service import validar_id
from services.unit_service import UnitValidationError, validate_metadata


COLLECTION = "devices"
HASH_ALGORITHM = "pbkdf2_sha256"


class DeviceValidationError(ValueError):
    pass


class DeviceUnauthorizedError(PermissionError):
    pass


def _validate_token(token):
    if not isinstance(token, str) or not 16 <= len(token) <= 512:
        raise DeviceValidationError("Token do dispositivo deve ter entre 16 e 512 caracteres.")
    return token


def _credential(token, iterations):
    _validate_token(token)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, iterations)
    return {
        "tokenHash": base64.b64encode(digest).decode("ascii"),
        "tokenSalt": base64.b64encode(salt).decode("ascii"),
        "tokenHashAlgorithm": HASH_ALGORITHM,
        "tokenHashIterations": iterations,
    }


def sanitize_device(device):
    if device is None:
        return None
    return {key: value for key, value in device.items() if key not in {
        "tokenHash", "tokenSalt", "tokenHashAlgorithm", "tokenHashIterations",
    }}


class DeviceService:
    def __init__(self, firebase, machine_service, hash_iterations=120_000):
        self.firebase, self.machines = firebase, machine_service
        self.hash_iterations = hash_iterations

    def _args(self):
        self.firebase.initialize()
        return self.firebase.firestore_url, self.firebase.obter_token

    def create(self, device_id, fazenda_id, maquina_id, token, metadata=None):
        validar_id(device_id, "deviceId")
        validar_id(fazenda_id)
        validar_id(maquina_id, "maquinaId")
        machine = self.machines.obter(fazenda_id, maquina_id)
        if machine is None or machine.get("fazendaId") != fazenda_id:
            raise DeviceValidationError("Máquina não existe ou não pertence à fazenda informada.")
        try:
            validate_metadata(metadata or {})
        except UnitValidationError as error:
            raise DeviceValidationError(str(error)) from error
        now = datetime.now(timezone.utc)
        document = {
            "deviceId": device_id, "fazendaId": fazenda_id, "maquinaId": maquina_id,
            "status": "active", "tokenVersion": 1, "lastSeenAt": None,
            "metadata": metadata or {}, "createdAt": now, "updatedAt": now,
            **_credential(token, self.hash_iterations),
        }
        return sanitize_device(criar_documento(*self._args(), COLLECTION, device_id, document))

    def get(self, device_id, include_credential=False):
        validar_id(device_id, "deviceId")
        device = obter_documento(*self._args(), COLLECTION, device_id)
        return device if include_credential else sanitize_device(device)

    def list(self, fazenda_id=None, limit=100):
        filters = {}
        if fazenda_id is not None:
            validar_id(fazenda_id)
            filters["fazendaId"] = fazenda_id
        items = consultar_documentos(*self._args(), COLLECTION, filters, "updatedAt", "DESCENDING", limit)
        return [sanitize_device(item) for item in items]

    def authenticate(self, device_id, token):
        try:
            _validate_token(token)
        except DeviceValidationError as error:
            raise DeviceUnauthorizedError("Dispositivo não autorizado.") from error
        device = self.get(device_id, include_credential=True)
        if not device or device.get("status") != "active":
            raise DeviceUnauthorizedError("Dispositivo não autorizado.")
        try:
            salt = base64.b64decode(device["tokenSalt"], validate=True)
            expected = base64.b64decode(device["tokenHash"], validate=True)
            iterations = int(device["tokenHashIterations"])
        except (KeyError, TypeError, ValueError):
            raise DeviceUnauthorizedError("Dispositivo não autorizado.") from None
        actual = hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, iterations)
        if not hmac.compare_digest(actual, expected):
            raise DeviceUnauthorizedError("Dispositivo não autorizado.")
        return sanitize_device(device)

    def rotate(self, device_id, token):
        current = self.get(device_id, include_credential=True)
        if current is None:
            return None
        current = {key: value for key, value in current.items() if key != "id"}
        changes = {
            **_credential(token, self.hash_iterations),
            "tokenVersion": int(current.get("tokenVersion", 0)) + 1,
            "status": "active", "updatedAt": datetime.now(timezone.utc),
        }
        return sanitize_device(atualizar_documento(*self._args(), COLLECTION, device_id, {**current, **changes}))

    def set_status(self, device_id, status):
        if status not in {"active", "revoked"}:
            raise DeviceValidationError("status deve ser active ou revoked.")
        current = self.get(device_id, include_credential=True)
        if current is None:
            return None
        if current.get("status") == "revoked" and status == "active":
            raise DeviceValidationError("Dispositivo revogado deve ser reativado por rotação de credencial.")
        return sanitize_device(atualizar_campos_documento(*self._args(), COLLECTION, device_id, {
            "status": status, "updatedAt": datetime.now(timezone.utc),
        }))

    def touch(self, device_id, when=None):
        timestamp = when or datetime.now(timezone.utc)
        return sanitize_device(atualizar_campos_documento(*self._args(), COLLECTION, device_id, {
            "lastSeenAt": timestamp, "updatedAt": datetime.now(timezone.utc),
        }))

    @staticmethod
    def health(last_seen_at, stale_after_seconds, offline_after_seconds, now=None):
        if not isinstance(last_seen_at, datetime) or last_seen_at.tzinfo is None:
            return {"status": "unknown", "lastSeenAt": last_seen_at, "ageSeconds": None}
        current = now or datetime.now(timezone.utc)
        age = max(0, (current - last_seen_at.astimezone(timezone.utc)).total_seconds())
        status = "online" if age <= stale_after_seconds else "stale" if age <= offline_after_seconds else "offline"
        return {"status": status, "lastSeenAt": last_seen_at, "ageSeconds": round(age, 1)}
