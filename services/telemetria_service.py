"""Persistência idempotente e consultas temporais eficientes de telemetria."""

from datetime import datetime, timezone
import hashlib
import json
import math

from services.firestore_service import criar_documento, consultar_documentos, obter_documento, salvar_documento
from services.propriedade_service import validar_id


def parse_timestamp(valor, nome="timestamp"):
    if valor is None:
        return None
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            raise ValueError(f"{nome} deve ser ISO 8601 com fuso horário.")
        return valor.astimezone(timezone.utc)
    try:
        instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        if instante.tzinfo is None: raise ValueError
        return instante.astimezone(timezone.utc)
    except (AttributeError, ValueError) as erro:
        raise ValueError(f"{nome} deve ser ISO 8601 com fuso horário.") from erro


class TelemetriaService:
    def __init__(self, firebase, default_limit=20, max_limit=100):
        self.firebase, self.default_limit, self.max_limit = firebase, default_limit, max_limit

    def _args(self):
        self.firebase.initialize(); return self.firebase.firestore_url, self.firebase.obter_token

    def historico(self, fazenda_id, maquina_id, limit=None, start_time=None, end_time=None):
        validar_id(fazenda_id); validar_id(maquina_id, "maquinaId")
        limite = self.default_limit if limit is None else int(limit)
        if not 1 <= limite <= self.max_limit: raise ValueError(f"limit deve estar entre 1 e {self.max_limit}.")
        inicio, fim = parse_timestamp(start_time, "startTime"), parse_timestamp(end_time, "endTime")
        if inicio and fim and inicio > fim: raise ValueError("startTime deve ser anterior a endTime.")
        return consultar_documentos(*self._args(), "leituras_sensores",
            {"fazendaId": fazenda_id, "maquinaId": maquina_id}, "dataHora", "DESCENDING", limite, inicio, fim)

    def historico_fazenda(self, fazenda_id, limit=500):
        validar_id(fazenda_id)
        limite = int(limit)
        if not 1 <= limite <= 1000:
            raise ValueError("limit da telemetria da fazenda deve estar entre 1 e 1000.")
        return consultar_documentos(*self._args(), "leituras_sensores", {"fazendaId": fazenda_id},
                                    "dataHora", "DESCENDING", limite)

    def save(self, device_id, fazenda_id, maquina_id, measurements, descriptors, observed_at,
             reading_id=None, origin="iot_device", observed_at_provided=True):
        validar_id(device_id, "deviceId"); validar_id(fazenda_id); validar_id(maquina_id, "maquinaId")
        if reading_id is not None:
            validar_id(reading_id, "readingId")
        payload_for_hash = {
            "deviceId": device_id, "fazendaId": fazenda_id, "maquinaId": maquina_id,
            "measurements": measurements, "measurementDescriptors": descriptors,
            "readingId": reading_id,
        }
        if observed_at_provided:
            payload_for_hash["observedAt"] = observed_at.astimezone(timezone.utc).isoformat()
        payload_hash = hashlib.sha256(json.dumps(payload_for_hash, sort_keys=True,
            ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        scopes = {descriptor.get("scope", "unknown") for descriptor in descriptors.values()
                  if isinstance(descriptor, dict)}
        measurement_scope = scopes.pop() if len(scopes) == 1 else "mixed" if scopes else "unknown"
        document = {
            **payload_for_hash, "dataHora": observed_at, "receivedAt": now, "origem": origin,
            "payloadHash": payload_hash, "measurementScope": measurement_scope,
            "observedAtProvidedByDevice": bool(observed_at_provided),
        }
        if reading_id is None:
            saved = salvar_documento(*self._args(), "leituras_sensores", document)
            return saved.get("name", "").split("/")[-1], False, document
        document_id = "reading_" + hashlib.sha256(f"{device_id}|{reading_id}".encode("utf-8")).hexdigest()[:32]
        existing = obter_documento(*self._args(), "leituras_sensores", document_id)
        if existing:
            if existing.get("payloadHash") != payload_hash:
                raise ValueError("readingId já foi usado com outro payload.")
            return document_id, True, existing
        try:
            saved = criar_documento(*self._args(), "leituras_sensores", document_id, document)
        except RuntimeError:
            existing = obter_documento(*self._args(), "leituras_sensores", document_id)
            if not existing or existing.get("payloadHash") != payload_hash:
                raise
            return document_id, True, existing
        return document_id, False, saved

    def mais_recente(self, fazenda_id, maquina_id):
        itens = self.historico(fazenda_id, maquina_id, limit=1)
        return itens[0] if itens else None

    @staticmethod
    def classificar(leitura, max_age_seconds, now=None):
        if not leitura: return {"status": "missing", "fresh": False, "ageSeconds": None}
        try: instante = parse_timestamp(leitura.get("dataHora"))
        except ValueError: return {"status": "invalid", "fresh": False, "ageSeconds": None}
        valores = list((leitura.get("measurements") or {}).values()) or [leitura.get("temperatura"), leitura.get("umidade")]
        if instante is None or not valores or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in valores):
            return {"status": "invalid", "fresh": False, "ageSeconds": None}
        idade = ((now or datetime.now(timezone.utc)) - instante).total_seconds()
        if idade < -60: return {"status": "invalid", "fresh": False, "ageSeconds": round(idade, 1)}
        return {"status": "fresh" if idade <= max_age_seconds else "stale",
                "fresh": idade <= max_age_seconds, "ageSeconds": round(max(0, idade), 1)}
