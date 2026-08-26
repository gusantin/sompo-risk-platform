"""Eventos de domínio persistidos e idempotentes."""

import hashlib
from datetime import datetime, timezone

from services.firestore_service import consultar_documentos, obter_documento, upsert_documento
from services.propriedade_service import validar_id


COLLECTION = "domain_events"
EVENT_TYPES = {
    "environmental_risk_changed", "machine_risk_changed", "operational_risk_changed",
    "hotspot_detected", "telemetry_stale", "device_offline", "source_unavailable",
}
LEVELS = {
    "baixo": "low", "low": "low", "moderado": "moderate", "moderate": "moderate",
    "alto": "high", "high": "high", "critico": "critical", "crítico": "critical",
    "critical": "critical", "dados_insuficientes": "unknown", "insufficient_data": "unknown",
    "unknown": "unknown", None: "unknown",
}


def normalize_level(value):
    return LEVELS.get(str(value).lower() if value is not None else None, "unknown")


def _event_id(key):
    return "evt_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


class EventService:
    def __init__(self, firebase, significant_score_delta=15):
        self.firebase = firebase
        self.significant_score_delta = significant_score_delta

    def _args(self):
        self.firebase.initialize()
        return self.firebase.firestore_url, self.firebase.obter_token

    def get(self, event_id):
        validar_id(event_id, "eventId")
        return obter_documento(*self._args(), COLLECTION, event_id)

    def list(self, fazenda_id, limit=50):
        validar_id(fazenda_id)
        return consultar_documentos(*self._args(), COLLECTION, {"fazendaId": fazenda_id},
                                    "createdAt", "DESCENDING", int(limit))

    def create(self, event_type, fazenda_id, event_key, maquina_id=None, risk_type=None,
               factors=None, evidence=None, source_analysis_id=None, occurred_at=None):
        if event_type not in EVENT_TYPES:
            raise ValueError("Tipo de evento inválido.")
        validar_id(fazenda_id)
        if maquina_id is not None:
            validar_id(maquina_id, "maquinaId")
        if not isinstance(event_key, str) or not event_key or len(event_key) > 500:
            raise ValueError("event_key inválida.")
        event_id = _event_id(f"{event_type}|{fazenda_id}|{maquina_id or '-'}|{event_key}")
        timestamp = occurred_at or datetime.now(timezone.utc)
        document = {"eventId": event_id, "eventType": event_type, "fazendaId": fazenda_id,
            "maquinaId": maquina_id, "riskType": risk_type, "factors": list(factors or [])[:20],
            "evidence": list(evidence or [])[:20], "sourceAnalysisId": source_analysis_id,
            "dedupeKey": event_key, "createdAt": timestamp, "occurredAt": timestamp}
        return upsert_documento(*self._args(), COLLECTION, event_id, document)

    def risk_transition(self, event_type, fazenda_id, risk_type, current_level,
                        previous_level=None, source_analysis_id=None, maquina_id=None,
                        current_score=None, previous_score=None, factors=None, evidence=None):
        if event_type not in {"environmental_risk_changed", "machine_risk_changed", "operational_risk_changed"}:
            raise ValueError("Tipo de transição de risco inválido.")
        validar_id(fazenda_id)
        if maquina_id is not None:
            validar_id(maquina_id, "maquinaId")
        current, previous = normalize_level(current_level), normalize_level(previous_level)
        score_changed = (
            isinstance(current_score, (int, float)) and isinstance(previous_score, (int, float))
            and abs(current_score - previous_score) >= self.significant_score_delta
        )
        if previous_level is None and current not in {"high", "critical"}:
            return None
        if previous == current and not score_changed:
            return None
        transition_key = "|".join(str(x or "-") for x in (
            event_type, fazenda_id, maquina_id, risk_type, previous, current, source_analysis_id,
        ))
        event_id = _event_id(transition_key)
        now = datetime.now(timezone.utc)
        document = {
            "eventId": event_id, "eventType": event_type, "fazendaId": fazenda_id,
            "maquinaId": maquina_id, "riskType": risk_type, "previousLevel": previous,
            "currentLevel": current, "previousScore": previous_score, "currentScore": current_score,
            "factors": list(factors or [])[:20], "evidence": list(evidence or [])[:20],
            "sourceAnalysisId": source_analysis_id, "dedupeKey": transition_key,
            "createdAt": now, "occurredAt": now,
        }
        return upsert_documento(*self._args(), COLLECTION, event_id, document)
