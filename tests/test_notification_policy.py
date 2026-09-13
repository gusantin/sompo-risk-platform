import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import requests
from tests import test_productization
from services.alert_service import AlertService
from services.notification_service import TelegramChannel, eligible, message_for


class PolicyTests(unittest.TestCase):
    setUp = test_productization.NotificationTests.setUp

    def test_risk_matrix(self):
        for kind in ("environmental_risk", "environmental_fire_risk", "machine_risk", "operational_combined_risk", "hotspot_near_property", "machine_near_hotspot"):
            for level in ("low", "moderate", "high", "critical", "unknown"):
                with self.subTest(kind=kind, level=level):
                    self.assertEqual(level in {"high", "critical"}, eligible({**self.alert, "type": kind, "severity": level}))
        for kind in ("telemetry_stale", "device_offline", "source_unavailable", "informational", "invented"):
            self.assertFalse(eligible({**self.alert, "type": kind, "severity": "critical"}))

    def test_weather_matrix(self):
        for level, expected in (("Perigo Potencial", False), ("Perigo", True), ("Grande Perigo", True), ("unknown", False)):
            alert = {**self.alert, "type": "severe_weather_warning", "evidence": [{"weatherSeverity": level, "affectedProperty": True}]}
            self.assertEqual(expected, eligible(alert))
            alert["evidence"][0]["affectedProperty"] = False
            self.assertFalse(eligible(alert))
        self.assertTrue(eligible({**self.alert, "type": "severe_weather_warning", "evidence": [{"weatherSeverity": "Perigo Potencial", "affectedProperty": True, "contextRule": "elevated_environmental_risk"}]}))

    def test_escalation_acknowledgement_resolution_once(self):
        for _ in range(10):
            self.dispatcher.enqueue(self.alert)
        self.dispatcher.deliver_pending()
        self.dispatcher.enqueue({**self.alert, "status": "acknowledged"})
        self.dispatcher.deliver_pending()
        self.channel.send.assert_called_once()
        critical = {**self.alert, "severity": "critical"}
        self.dispatcher.enqueue(critical)
        self.dispatcher.enqueue(critical)
        self.dispatcher.deliver_pending()
        self.assertEqual(2, self.channel.send.call_count)
        self.assertIn("RISCO ESCALADO PARA CRÍTICO", self.channel.send.call_args.args[0])
        resolved = {**critical, "status": "resolved", "resolvedAt": datetime.now(timezone.utc)}
        for _ in range(3):
            self.dispatcher.enqueue(resolved)
            self.dispatcher.deliver_pending()
        self.assertEqual(3, self.channel.send.call_count)
        self.assertIn("ENCERRADO", self.channel.send.call_args.args[0])

    def test_prior_occurrence_does_not_authorize_resolution(self):
        self.dispatcher.enqueue(self.alert)
        self.dispatcher.deliver_pending()
        self.dispatcher.enqueue({**self.alert, "createdAt": self.alert["createdAt"] + timedelta(hours=2), "status": "resolved"})
        self.assertEqual(1, len(self.dispatcher.list_for_alert("a1")))

    def test_demo_explicit_isolation_and_label(self):
        for pid in ("f1", "demo_f1"):
            self.dispatcher.enqueue({**self.alert, "fazendaId": pid, "demoData": True}, allow_demo=True)
        self.assertFalse(self.store)
        self.dispatcher.enqueue({**self.alert, "fazendaId": "demo_telegram_test", "demoData": True}, allow_demo=True)
        self.dispatcher.deliver_pending()
        self.assertTrue(self.channel.send.call_args.args[0].startswith("🧪 DADOS DE DEMONSTRAÇÃO"))

    def test_missing_configuration_does_not_call_network(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}), patch("services.notification_service.requests.post") as post:
            result = TelegramChannel().send_result("test")
        self.assertFalse(result["retryable"])
        self.assertEqual("missing_configuration", result["failureCategory"])
        post.assert_not_called()

    def test_adapter_results_are_safe_and_respect_retry(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "private-test-token", "TELEGRAM_CHAT_ID": "private-test-chat"}):
            for code, payload, expected, retry in [
                (200, {"ok": True, "result": {"message_id": 123}}, "delivered", False),
                (401, {"ok": False, "description": "private-test-token"}, "failed", False),
                (429, {"ok": False, "parameters": {"retry_after": 180}}, "failed", True),
                (503, {"ok": False}, "failed", True),
            ]:
                response = Mock(status_code=code)
                response.json.return_value = payload
                with patch("services.notification_service.requests.post", return_value=response):
                    result = TelegramChannel().send_result("test")
                self.assertEqual(expected, result["status"])
                self.assertEqual(retry, result["retryable"])
                self.assertNotIn("private-test", str(result))
                if code == 200: self.assertEqual(123, result["telegramMessageId"])
                if code == 429: self.assertEqual(180, result["retryAfterSeconds"])
            for error, expected in ((requests.ConnectTimeout(), "failed"), (requests.ReadTimeout(), "unknown"), (requests.ConnectionError(), "unknown")):
                with patch("services.notification_service.requests.post", side_effect=error):
                    self.assertEqual(expected, TelegramChannel().send_result("test")["status"])

    def test_backoff_and_persistence_failure_prevent_repeat(self):
        channel = TelegramChannel()
        channel.send_result = Mock(return_value={"status": "failed", "retryable": True, "retryAfterSeconds": 180})
        self.dispatcher.channel = channel
        self.dispatcher.enqueue(self.alert)
        now = datetime.now(timezone.utc)
        self.dispatcher.deliver_pending(now=now)
        self.dispatcher.deliver_pending(now=now + timedelta(seconds=179))
        channel.send_result.assert_called_once()
        channel.send_result.return_value = {"status": "delivered", "telegramMessageId": 456}
        due = self.dispatcher.list_for_alert("a1")[0]["nextAttemptAt"]
        self.assertGreaterEqual(due, now + timedelta(seconds=180))
        self.dispatcher.deliver_pending(now=due)
        self.assertEqual(2, channel.send_result.call_count)
        self.assertEqual(456, self.dispatcher.list_for_alert("a1")[0]["telegramMessageId"])
        self.assertNotIn("nextAttemptAt", self.dispatcher.list_for_alert("a1")[0])
        self.dispatcher.enqueue({**self.alert, "severity": "critical"})
        original = __import__('services.notification_service', fromlist=['atualizar_documento']).atualizar_documento
        def update(*args):
            if args[-1].get("status") == "delivered": raise RuntimeError("persistence unavailable")
            return original(*args)
        with patch("services.notification_service.atualizar_documento", side_effect=update):
            self.dispatcher.deliver_pending()
        self.dispatcher.deliver_pending()
        self.assertEqual(3, channel.send_result.call_count)
        self.assertIn("attempting", [r["status"] for r in self.dispatcher.list_for_alert("a1")])

    def test_weather_scope_freshness_and_identity(self):
        service = AlertService(Mock())
        service.emit = Mock(return_value=({}, False))
        now = datetime.now(timezone.utc)
        warning = {"id": "w1", "location": "Cuiabá/MT", "severity": "Perigo", "eventType": "Tempestade", "source": "INMET",
                   "startsAt": (now-timedelta(hours=1)).isoformat(), "endsAt": (now+timedelta(hours=1)).isoformat()}
        prop = {"fazendaId": "f1", "municipio": "Cuiabá", "estado": "MT"}
        self.assertEqual(1, len(service.evaluate_weather(prop, [warning], now=now)))
        self.assertEqual("w1", service.emit.call_args.kwargs["source_event_id"])
        for change in ({"location": "Cuiabá/MS"}, {"location": "Centro-Sul Mato-grossense"}, {"endsAt": (now-timedelta(seconds=1)).isoformat()}):
            self.assertEqual([], service.evaluate_weather(prop, [{**warning, **change}], now=now))
        service.evaluate_weather(prop, [{**warning, "severity": "Perigo Potencial"}],
                                 {"analysisAt": now, "environmentalRisk": {"geral": {"nivel": "alto"}}}, now)
        self.assertEqual("elevated_environmental_risk", service.emit.call_args.args[5][0]["contextRule"])

    def test_message_preserves_sensor_guidance_without_fake_entity(self):
        text = message_for(self.alert, "alert")
        self.assertNotIn("Trator", text)
        self.assertNotIn("hotspot", text)
        self.assertNotIn("Parar", text)
        alert = {**self.alert, "evidence": [{"type": "temperature", "scope": "machine_component", "level": "high"}]}
        self.assertIn("Parar e inspecionar", message_for(alert, "alert"))

    def test_resolved_before_worker_cancels_unsent_alert(self):
        self.dispatcher.enqueue(self.alert)
        self.alert["status"] = "resolved"
        self.dispatcher.deliver_pending()
        self.channel.send.assert_not_called()
        self.assertEqual("cancelled", self.dispatcher.list_for_alert("a1")[0]["status"])
        self.dispatcher.enqueue(self.alert)
        self.assertEqual(1, len(self.dispatcher.list_for_alert("a1")))

    def test_weather_context_can_become_actionable_without_inventing_severity(self):
        service = AlertService(Mock())
        service._args = self.dispatcher._args
        existing = {**self.alert, "severity": "moderate", "type": "severe_weather_warning", "evidence": [
            {"weatherSeverity": "Perigo Potencial", "affectedProperty": True, "contextRule": None}]}
        service.get = Mock(return_value=existing)
        evidence = [{**existing["evidence"][0], "contextRule": "elevated_environmental_risk"}]
        with patch("services.alert_service.atualizar_documento", side_effect=lambda *args: args[-1]):
            alert, _ = service.emit("severe_weather_warning", "moderate", "f1", "weather", [], evidence, "w1", source_event_id="w1")
        self.assertEqual("moderate", alert["severity"])
        self.assertTrue(eligible(alert))

    def test_full_alert_outbox_adapter_lifecycle(self):
        from scripts.seed_demo import preview
        source = next(a for a in preview("environmental_fire_high")["alerts"] if a["type"] == "environmental_fire_risk")
        import services.notification_service as persistence
        service = AlertService(Mock(), notification_dispatcher=self.dispatcher)
        service._args = self.dispatcher._args
        service.get = lambda identifier: self.store.get(("alerts", identifier))
        channel = TelegramChannel()
        self.dispatcher.channel = channel
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True, "result": {"message_id": 123}}
        with patch("services.alert_service.criar_documento", persistence.criar_documento), patch("services.alert_service.atualizar_documento", persistence.atualizar_documento), patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fixture-token", "TELEGRAM_CHAT_ID": "fixture-chat"}), patch("services.notification_service.requests.post", return_value=response) as transport:
            args = (source["type"], source["severity"], "f1", source["riskType"], source["factors"], source["evidence"], "fixture_analysis")
            alert, _ = service.emit(*args)
            self.dispatcher.deliver_pending()
            service.emit(*args)
            self.dispatcher.deliver_pending()
            self.assertEqual(1, transport.call_count)
            service.update_status(alert["alertId"], "acknowledged")
            self.dispatcher.deliver_pending()
            self.assertEqual(1, transport.call_count)
            service.update_status(alert["alertId"], "resolved")
            self.dispatcher.deliver_pending()
            service.update_status(alert["alertId"], "resolved")
            self.dispatcher.deliver_pending()
            self.assertEqual(2, transport.call_count)
            self.assertEqual("resolved", service.get(alert["alertId"])["status"])
            self.assertTrue(all(r["status"] == "delivered" and r["telegramMessageId"] == 123 for r in self.dispatcher.list_for_alert(alert["alertId"])))
