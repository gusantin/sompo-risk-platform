"""Persisted outbox. Only an explicit worker delivers; reads never send messages."""
import hashlib
import logging
import os
import re
from datetime import datetime, timezone, timedelta

import requests
from services.firestore_service import criar_documento, obter_documento, atualizar_documento, consultar_documentos
from services.notification_messages import message_for

LOGGER = logging.getLogger(__name__)
COLLECTION = "notifications"


def eligible(alert):
    """Only official actionable alert types. Weather retains upstream classification."""
    if alert.get("type") == "severe_weather_warning":
        evidence = next((e for e in alert.get("evidence", []) if isinstance(e, dict) and e.get("weatherSeverity")), {})
        severity = str(evidence.get("weatherSeverity", "")).casefold()
        return evidence.get("affectedProperty") is True and (
            severity in {"perigo", "grande perigo"} or
            severity == "perigo potencial" and evidence.get("contextRule") == "elevated_environmental_risk")
    return alert.get("severity") in {"high", "critical"} and alert.get("type") in {
        "environmental_risk", "environmental_fire_risk", "hotspot_near_property",
        "machine_near_hotspot", "machine_risk", "operational_combined_risk"}


def occurrence(alert):
    value = alert.get("createdAt")
    return value.isoformat() if isinstance(value, datetime) else str(value)


class TelegramSecretFilter(logging.Filter):
    """Also protect urllib3 DEBUG request logs, where Telegram's URL contains the token."""

    def filter(self, record):
        message = record.getMessage()
        for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            secret = os.getenv(name)
            if secret:
                message = message.replace(secret, "[redacted]")
        record.msg, record.args = message, ()
        record.msg = re.sub(r"/bot[^/\s]+/", "/bot[redacted]/", record.msg)
        # Exception tracebacks from HTTP libraries can carry the original request URL.
        record.exc_info, record.exc_text, record.stack_info = None, None, None
        return True


for _logger_name in ("urllib3.connectionpool", "urllib3.util.retry"):
    logging.getLogger(_logger_name).addFilter(TelegramSecretFilter())


class TelegramChannel:
    name = "telegram"
    recipient_ref = "telegram_operations"

    def send(self, message):
        return self.send_result(message)["status"]

    def send_result(self, message):
        # Neither response bodies nor exception strings may escape this boundary.
        if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
            return {"status": "failed", "failureCategory": "missing_configuration", "retryable": False}
        try:
            response = requests.post(
                "https://api.telegram.org/bot" + os.environ["TELEGRAM_BOT_TOKEN"] + "/sendMessage",
                json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": message}, timeout=10, allow_redirects=False)
            payload = response.json()
            if response.status_code == 200 and payload.get("ok") is True:
                result = {"status": "delivered", "retryable": False}
                mid = (payload.get("result") or {}).get("message_id")
                if isinstance(mid, int):
                    result["telegramMessageId"] = mid
                return result
            code = payload.get("error_code", response.status_code)
            if code == 429:
                delay = (payload.get("parameters") or {}).get("retry_after")
                return {"status": "failed", "retryable": True, "failureCategory": "rate_limit",
                        "retryAfterSeconds": delay if isinstance(delay, int) and delay > 0 else 60}
            if 500 <= code < 600 and payload.get("ok") is False:
                return {"status": "failed", "retryable": True, "failureCategory": "telegram_server"}
            if 400 <= code < 500:
                return {"status": "failed", "retryable": False, "failureCategory": "telegram_rejected"}
            return {"status": "unknown", "retryable": False, "failureCategory": "ambiguous_response"}
        except requests.ConnectTimeout:
            return {"status": "failed", "retryable": True, "failureCategory": "connection_timeout"}
        except Exception:
            return {"status": "unknown", "retryable": False, "failureCategory": "ambiguous_transport"}


class NotificationDispatcher:
    def __init__(self, firebase, channel=None):
        self.firebase = firebase
        self.channel = channel or TelegramChannel()

    def _args(self):
        self.firebase.initialize()
        return self.firebase.firestore_url, self.firebase.obter_token

    def enqueue(self, alert, allow_demo=False):
        if os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false").lower() != "true":
            return
        demo = alert.get("demoData") or str(alert.get("fazendaId", "")).startswith("demo_")
        if demo and not (allow_demo and os.getenv("ENVIRONMENT", "development") in {"development", "test"}
                         and str(alert.get("fazendaId", "")).startswith("demo_telegram_")):
            return
        if alert.get("status") not in {"open", "acknowledged", "resolved"} or not eligible(alert):
            return
        kind = "alert"
        previous = self.list_for_alert(alert["alertId"]) if alert.get("status") == "resolved" or alert.get("severity") == "critical" else []
        previous = [r for r in previous if r.get("occurrence") == occurrence(alert) and r.get("kind") != "resolution"]
        if alert.get("status") == "resolved":
            if not any(r.get("status") == "delivered" for r in previous):
                return
            kind = "resolution"
        elif alert.get("severity") == "critical" and any(r.get("severity") == "high" for r in previous):
            kind = "escalation"
        # Keep the original key encoding so an upgrade cannot resend existing outbox rows.
        key = "|".join((alert["alertId"], str(alert.get("createdAt")), "resolution" if kind == "resolution" else alert["severity"]))
        key += "|" + self.channel.name + "|" + self.channel.recipient_ref
        identifier = "notification_" + hashlib.sha256(key.encode()).hexdigest()[:32]
        try:
            if obter_documento(*self._args(), COLLECTION, identifier):
                return
            message_context = dict(alert)
            try:
                property_data = obter_documento(*self._args(), "fazendas", alert["fazendaId"]) or {}
                message_context.update({"propertyName": property_data.get("nome") or alert.get("propertyName"),
                    "municipality": property_data.get("municipio") or alert.get("municipality"),
                    "state": property_data.get("estado") or alert.get("state")})
                if alert.get("maquinaId"):
                    machine = obter_documento(*self._args(), "maquinas", f"{alert['fazendaId']}__{alert['maquinaId']}") or {}
                    if machine.get("fazendaId") == alert["fazendaId"]:
                        message_context["machineName"] = machine.get("nome")
            except Exception:
                pass
            return criar_documento(*self._args(), COLLECTION, identifier, {
                "notificationId": identifier, "alertId": alert["alertId"],
                "channel": self.channel.name, "recipientRef": self.channel.recipient_ref,
                "status": "created", "attempts": 0, "createdAt": datetime.now(timezone.utc),
                "occurrence": occurrence(alert), "kind": kind, "severity": alert["severity"],
                "fazendaId": alert["fazendaId"], "demoData": bool(demo),
                "expiresAt": next((e.get("endsAt") for e in alert.get("evidence", []) if isinstance(e, dict) and e.get("weatherSeverity")), None),
                "message": message_for(message_context, kind),
            })
        except Exception:
            LOGGER.warning("notification_enqueue_unavailable")

    def list_for_alert(self, alert_id):
        rows = consultar_documentos(*self._args(), COLLECTION, {"alertId": alert_id}, limite=100)
        fields = {"notificationId", "alertId", "channel", "status", "createdAt", "attemptedAt", "deliveredAt", "attempts",
                  "retryable", "nextAttemptAt", "failureCategory", "telegramMessageId", "occurrence", "kind", "severity", "demoData"}
        return [{k: v for k, v in row.items() if k in fields} for row in rows]

    def deliver_pending(self, notification_ids=None, now=None):
        if os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false").lower() != "true":
            return
        now = now or datetime.now(timezone.utc)
        if notification_ids is not None:
            rows = [row for identifier in notification_ids if (row := obter_documento(*self._args(), COLLECTION, identifier)) and row.get("status") in {"created", "failed"}]
        else:
            rows = consultar_documentos(*self._args(), COLLECTION, {"status": "created"}, limite=100)
            rows += consultar_documentos(*self._args(), COLLECTION, {"status": "failed", "retryable": True}, limite=100)
        for row in rows:
            revision = getattr(row, "update_time", None)
            if notification_ids is not None and row.get("notificationId") not in notification_ids:
                continue
            if row.get("status") == "failed" and row.get("retryable") is not True:
                continue
            if isinstance(row.get("nextAttemptAt"), datetime) and row["nextAttemptAt"] > now:
                continue
            if row.get("channel") != self.channel.name or row.get("recipientRef") != self.channel.recipient_ref:
                continue
            attempt = row.get("attempts", 0) + 1
            if attempt > 3:
                continue
            identifier = row["notificationId"]
            if row.get("alertId"):
                try:
                    alert = obter_documento(*self._args(), "alerts", row["alertId"])
                    obsolete = not alert or not eligible(alert) or (
                        row.get("occurrence") and occurrence(alert) != row["occurrence"]) or (
                        row.get("kind") != "resolution" and alert.get("status") == "resolved")
                    if row.get("expiresAt") and row.get("kind") != "resolution":
                        obsolete = obsolete or datetime.fromisoformat(str(row["expiresAt"]).replace("Z", "+00:00")) <= now
                    if obsolete:
                        atualizar_documento(*self._args(), COLLECTION, identifier,
                            {**{k: v for k, v in row.items() if k != "id"}, "status": "cancelled", "retryable": False},
                            **({"update_time": revision} if revision else {}))
                        continue
                except Exception:
                    LOGGER.warning("notification_alert_verification_unavailable")
                    continue
            try:
                # Atomic create arbitrates concurrent workers. A crash never auto-resends an ambiguous delivery.
                criar_documento(*self._args(), "notification_attempts", f"{identifier}_{attempt}",
                                {"notificationId": identifier, "attempt": attempt, "createdAt": datetime.now(timezone.utc)})
            except Exception:
                continue
            row = {k: v for k, v in row.items() if k != "id"}
            row.update(status="attempting", attempts=attempt, attemptedAt=now)
            try:
                attempted = atualizar_documento(*self._args(), COLLECTION, identifier, row,
                    **({"update_time": revision} if revision else {}))
                if attempted is None:
                    raise RuntimeError("attempt_not_persisted")
                revision = getattr(attempted, "update_time", None)
            except Exception:
                LOGGER.warning("notification_attempt_persistence_unavailable")
                continue
            try:
                result = self.channel.send_result(row["message"]) if isinstance(self.channel, TelegramChannel) else {"status": self.channel.send(row["message"])}
            except Exception:
                result = {"status": "unknown", "failureCategory": "ambiguous_transport"}
            status = result["status"]
            finished = max(now, datetime.now(timezone.utc))
            for field in ("failureCategory", "nextAttemptAt", "retryAfterSeconds"):
                row.pop(field, None)
            row["retryable"] = False
            row.update(result, updatedAt=finished)
            if result.get("retryable"):
                row["retryable"] = attempt < 3
                if attempt >= 3:
                    row["status"] = "permanently_failed"
                else:
                    row["nextAttemptAt"] = finished + timedelta(seconds=max(60 * 2 ** (attempt - 1), result.get("retryAfterSeconds", 0)))
            if status == "delivered":
                row["deliveredAt"] = row["updatedAt"]
            try:
                if atualizar_documento(*self._args(), COLLECTION, identifier, row,
                        **({"update_time": revision} if revision else {})) is None:
                    raise RuntimeError("result_not_persisted")
            except Exception:
                LOGGER.warning("notification_result_persistence_ambiguous")
