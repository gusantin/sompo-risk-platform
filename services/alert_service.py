"""Alertas internos determinísticos, com dedupe e ciclo de vida."""

import hashlib
from datetime import datetime, timezone

from services.event_service import normalize_level
from services.firestore_service import atualizar_documento, consultar_documentos, obter_documento, criar_documento
from services.operational_risk_service import machine_is_operating
from services.propriedade_service import validar_id


COLLECTION = "alerts"
STATUSES = {"open", "acknowledged", "resolved"}
TRANSITIONS = {"open": {"acknowledged", "resolved"}, "acknowledged": {"resolved"}, "resolved": set()}


class AlertValidationError(ValueError):
    pass


def _alert_id(dedupe_key):
    return "alert_" + hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:28]


class AlertService:
    def __init__(self, firebase, cooldown_seconds=3600, hotspot_distance_km=5,
                 hotspot_critical_distance_km=1, hotspot_max_age_hours=24, notification_dispatcher=None):
        self.firebase = firebase
        self.notification_dispatcher = notification_dispatcher
        self.cooldown_seconds = cooldown_seconds
        self.hotspot_distance_km = hotspot_distance_km
        self.hotspot_critical_distance_km = hotspot_critical_distance_km
        self.hotspot_max_age_hours = hotspot_max_age_hours

    def _args(self):
        self.firebase.initialize()
        return self.firebase.firestore_url, self.firebase.obter_token

    def get(self, alert_id):
        validar_id(alert_id, "alertId")
        return obter_documento(*self._args(), COLLECTION, alert_id)

    def list(self, filters=None, limit=50):
        filters = dict(filters or {})
        allowed = {"fazendaId", "maquinaId", "status", "severity", "type", "riskType"}
        if set(filters) - allowed:
            raise AlertValidationError("Filtro de alerta inválido.")
        for field in ("fazendaId", "maquinaId"):
            if filters.get(field):
                try:
                    validar_id(filters[field], field)
                except ValueError as error:
                    raise AlertValidationError(str(error)) from error
        if filters.get("status") and filters["status"] not in STATUSES:
            raise AlertValidationError("status de alerta inválido.")
        for field in ("severity", "type", "riskType"):
            value = filters.get(field)
            if value is not None and (not isinstance(value, str) or not value or len(value) > 100):
                raise AlertValidationError(f"{field} inválido.")
        limit = int(limit)
        if not 1 <= limit <= 100:
            raise AlertValidationError("limit deve estar entre 1 e 100.")
        ordered_signatures = {
            frozenset(), frozenset({"status"}), frozenset({"severity"}), frozenset({"type"}),
            frozenset({"riskType"}), frozenset({"fazendaId"}),
            frozenset({"fazendaId", "status"}), frozenset({"fazendaId", "maquinaId"}),
            frozenset({"fazendaId", "severity"}), frozenset({"fazendaId", "type"}),
            frozenset({"fazendaId", "riskType"}),
            frozenset({"fazendaId", "maquinaId", "status"}),
        }
        order_field = "updatedAt" if frozenset(filters) in ordered_signatures else None
        items = consultar_documentos(*self._args(), COLLECTION, filters, order_field, "DESCENDING", limit)
        if order_field is None:
            items.sort(key=lambda item: item.get("updatedAt") if isinstance(item.get("updatedAt"), datetime)
                       else datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return items

    def emit(self, *args, **kwargs):
        result = self._emit(*args, **kwargs)
        if self.notification_dispatcher:
            try:
                self.notification_dispatcher.enqueue(result[0])
            except Exception:
                pass  # Delivery infrastructure must never break risk processing.
        return result

    def _emit(self, alert_type, severity, fazenda_id, risk_type, factors, evidence,
             source_analysis_id, maquina_id=None, source_event_id=None, now=None):
        if severity not in {"moderate", "high", "critical"}:
            raise AlertValidationError("severity inválida.")
        validar_id(fazenda_id)
        if maquina_id is not None:
            validar_id(maquina_id, "maquinaId")
        dedupe_key = "|".join(str(x or "-") for x in (fazenda_id, maquina_id, alert_type, risk_type))
        if alert_type == "severe_weather_warning":
            dedupe_key += "|" + str(source_event_id or source_analysis_id)
        alert_id, current_time = _alert_id(dedupe_key), now or datetime.now(timezone.utc)
        existing = self.get(alert_id)
        if existing and existing.get("status") in {"open", "acknowledged"}:
            rank = {"moderate": 1, "high": 2, "critical": 3}
            weather_context_changed = (alert_type == "severe_weather_warning" and severity == existing.get("severity")
                                       and list(evidence or [])[:20] != existing.get("evidence", []))
            if rank[severity] > rank.get(existing.get("severity"), 0) or weather_context_changed:
                updated = {key: value for key, value in existing.items() if key != "id"}
                if rank[severity] > rank.get(existing.get("severity"), 0):
                    updated["escalation"] = {"previousSeverity": existing.get("severity"),
                        "previousEvidence": existing.get("evidence", []), "at": current_time}
                updated.update({"severity": severity, "updatedAt": current_time,
                    "lastTriggeredAt": current_time, "factors": list(factors or [])[:20],
                    "evidence": list(evidence or [])[:20], "sourceAnalysisId": source_analysis_id,
                    "sourceEventId": source_event_id,
                    "occurrenceCount": int(existing.get("occurrenceCount", 0)) + 1})
                return atualizar_documento(*self._args(), COLLECTION, alert_id, updated, **({"update_time": existing.update_time} if getattr(existing, "update_time", None) else {})), True
            return existing, True
        if existing and isinstance(existing.get("lastTriggeredAt"), datetime):
            elapsed = (current_time - existing["lastTriggeredAt"]).total_seconds()
            if elapsed < self.cooldown_seconds:
                return existing, True
        document = {
            "alertId": alert_id, "type": alert_type, "severity": severity, "status": "open",
            "fazendaId": fazenda_id, "maquinaId": maquina_id, "riskType": risk_type,
            "createdAt": current_time, "updatedAt": current_time, "lastTriggeredAt": current_time,
            "factors": list(factors or [])[:20], "evidence": list(evidence or [])[:20],
            "sourceAnalysisId": source_analysis_id, "sourceEventId": source_event_id,
            "dedupeKey": dedupe_key, "occurrenceCount": int((existing or {}).get("occurrenceCount", 0)) + 1,
            "acknowledgedAt": None, "resolvedAt": None,
        }
        if getattr(existing, "update_time", None):
            return atualizar_documento(*self._args(), COLLECTION, alert_id, document, update_time=existing.update_time), False
        # Creation must not overwrite an alert another evaluator just persisted.
        return criar_documento(*self._args(), COLLECTION, alert_id, document), False

    def update_status(self, alert_id, status, actor_id=None, now=None):
        if status not in STATUSES:
            raise AlertValidationError("status deve ser open, acknowledged ou resolved.")
        current = self.get(alert_id)
        if current is None:
            return None
        old = current.get("status")
        if status == old:
            if status == "resolved":
                self._queue_resolution(current)
            return current
        if status not in TRANSITIONS.get(old, set()):
            raise AlertValidationError(f"Transição de {old} para {status} não é permitida.")
        timestamp = now or datetime.now(timezone.utc)
        revision = getattr(current, "update_time", None)
        current = {key: value for key, value in current.items() if key != "id"}
        current.update({"status": status, "updatedAt": timestamp, "updatedBy": actor_id})
        if status == "acknowledged":
            current["acknowledgedAt"] = timestamp
        if status == "resolved":
            current["resolvedAt"] = timestamp
        result = atualizar_documento(*self._args(), COLLECTION, alert_id, current, **({"update_time": revision} if revision else {}))
        if status == "resolved":
            self._queue_resolution(result)
        return result

    def _queue_resolution(self, alert):
        if self.notification_dispatcher:
            try:
                self.notification_dispatcher.enqueue(alert)
            except Exception:
                pass

    def evaluate_weather(self, property_data, warnings, environmental_snapshot=None, now=None):
        """Explicit ingestion only. Exact upstream municipality/UF or region/UF membership."""
        import re
        import unicodedata
        def normalized(value):
            return " ".join("".join(c for c in unicodedata.normalize("NFD", str(value or "")).lower()
                                    if unicodedata.category(c) != "Mn").split())
        current = now or datetime.now(timezone.utc)
        labels = {normalized(f"{property_data.get('municipio', '')}/{property_data.get('estado', '')}")}
        # No fuzzy substring/state-wide matching: a broad region alone cannot establish property exposure.
        results = []
        for warning in warnings:
            areas = {normalized(v) for v in re.split(r"[;,]", str(warning.get("location") or ""))}
            if not labels.intersection(areas) or not property_data.get("municipio") or not property_data.get("estado"):
                continue
            try:
                start = datetime.fromisoformat(warning["startsAt"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(warning["endsAt"].replace("Z", "+00:00"))
                if not start <= current <= end:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            upstream = normalized(warning.get("severity"))
            level = {"perigo": "high", "grande perigo": "critical", "perigo potencial": "moderate"}.get(upstream)
            if not level or not warning.get("id") or not warning.get("eventType") or not warning.get("source"):
                continue
            snapshot = environmental_snapshot or {}
            analysis_at = snapshot.get("analysisAt")
            fresh = isinstance(analysis_at, datetime) and 0 <= (current - analysis_at).total_seconds() <= 7200
            elevated = fresh and normalize_level(((snapshot.get("environmentalRisk") or {}).get("geral") or {}).get("nivel")) in {"high", "critical"}
            evidence = {"weatherSeverity": warning["severity"], "eventType": warning["eventType"],
                        "description": warning.get("description"),
                        "source": warning["source"], "publishedAt": warning.get("publishedAt"),
                        "affectedProperty": True, "location": warning["location"], "endsAt": warning["endsAt"],
                        "contextRule": "elevated_environmental_risk" if elevated else None}
            alert, deduped = self.emit("severe_weather_warning", level, property_data["fazendaId"], "weather",
                [warning["eventType"]], [evidence], str(warning["id"]), source_event_id=str(warning["id"]), now=current)
            results.append({"alert": alert, "deduplicated": deduped})
        return results

    def evaluate(self, fazenda_id, environmental_risk, machine_results, source_analysis_id,
                 events=None, property_hotspot=None):
        created = []
        for risk_type in ("geada", "inundacao", "enxurrada", "movimentoMassa"):
            risk = environmental_risk.get(risk_type) or {}
            level = normalize_level(risk.get("nivel"))
            if level in {"high", "critical"}:
                alert, deduped = self.emit("environmental_risk", level, fazenda_id, risk_type,
                    risk.get("fatores", []), [{"level": level, "score": risk.get("score")}], source_analysis_id)
                created.append({"alert": alert, "deduplicated": deduped})
        event_by_type = {item.get("eventType"): item for item in (events or []) if item}
        fire = environmental_risk.get("incendio", {})
        fire_level = normalize_level(fire.get("nivel"))
        if fire_level in {"high", "critical"}:
            alert, deduped = self.emit(
                "environmental_fire_risk", fire_level, fazenda_id, "incendio",
                fire.get("fatores", []), [{"level": fire_level, "score": fire.get("score")}],
                source_analysis_id, source_event_id=(event_by_type.get("environmental_risk_changed") or {}).get("eventId"),
            )
            created.append({"alert": alert, "deduplicated": deduped})
        hotspot_distance = (property_hotspot or {}).get("distanciaKm")
        hotspot_age = (property_hotspot or {}).get("ageHours", (property_hotspot or {}).get("idadeHoras"))
        recent_property_hotspot = (isinstance(hotspot_age, (int, float))
            and 0 <= hotspot_age <= self.hotspot_max_age_hours)
        if (recent_property_hotspot and isinstance(hotspot_distance, (int, float))
                and hotspot_distance <= self.hotspot_distance_km):
            severity = "critical" if hotspot_distance <= self.hotspot_critical_distance_km else "high"
            alert, deduped = self.emit("hotspot_near_property", severity, fazenda_id, "incendio",
                ["recent_hotspot_near_property"], [{"distanceKm": hotspot_distance, "ageHours": hotspot_age}],
                source_analysis_id)
            created.append({"alert": alert, "deduplicated": deduped})
        for item in machine_results:
            machine_id = (item.get("machine") or {}).get("maquinaId")
            machine_risk, operational = item.get("machineRisk", {}), item.get("operationalContextRisk", {})
            machine_level = normalize_level(machine_risk.get("level"))
            if machine_level in {"high", "critical"}:
                alert, deduped = self.emit("machine_risk", machine_level, fazenda_id, "machine",
                    machine_risk.get("factors", []), machine_risk.get("evidence", []), source_analysis_id, machine_id)
                created.append({"alert": alert, "deduplicated": deduped})
            operational_level = normalize_level(operational.get("level"))
            if operational_level in {"high", "critical"}:
                alert, deduped = self.emit("operational_combined_risk", operational_level, fazenda_id, "operational",
                    operational.get("factors", []), [{"environmental": fire_level, "machine": machine_level}],
                    source_analysis_id, machine_id)
                created.append({"alert": alert, "deduplicated": deduped})
            distance = (item.get("location") or {}).get("nearestHotspotDistanceKm")
            hotspot_age = (item.get("location") or {}).get("nearestHotspotAgeHours")
            current_location = (item.get("location") or {}).get("locationCurrent")
            operating = machine_is_operating(item.get("machine"))
            recent_hotspot = isinstance(hotspot_age, (int, float)) and 0 <= hotspot_age <= self.hotspot_max_age_hours
            if (operating and current_location and recent_hotspot and distance is not None
                    and distance <= self.hotspot_distance_km and fire_level in {"high", "critical"}):
                alert, deduped = self.emit("machine_near_hotspot",
                    "critical" if distance <= self.hotspot_critical_distance_km else "high",
                    fazenda_id, "incendio", ["recent_machine_location", "nearby_hotspot"],
                    [{"distanceKm": distance, "ageHours": hotspot_age}], source_analysis_id, machine_id)
                created.append({"alert": alert, "deduplicated": deduped})
        return created
