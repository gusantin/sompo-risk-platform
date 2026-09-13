import os
import logging
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

import server
from services.alert_service import AlertService
from services.notification_service import NotificationDispatcher, TelegramChannel, TelegramSecretFilter
from services.recommendation_service import recommendations


class RecommendationTests(unittest.TestCase):
    def test_official_mapping_and_unknown(self):
        for kind in ("machine_risk", "environmental_fire_risk", "hotspot_near_property", "machine_near_hotspot", "operational_combined_risk", "telemetry_stale", "device_offline", "severe_weather_warning"):
            self.assertEqual(kind, recommendations({"type": kind})[0]["ruleId"])
        self.assertEqual([], recommendations({"type": "invented_condition"}))

    def test_temperature_requires_semantics_and_elevated_level(self):
        evidence = {"type": "temperature", "scope": "machine_component", "level": "high"}
        self.assertEqual("machine_overheat", recommendations({"type": "machine_risk", "evidence": [evidence]})[0]["ruleId"])
        for change in ({"scope": "ambient_local"}, {"level": "low"}, {"type": "humidity"}):
            self.assertEqual("machine_risk", recommendations({"type": "machine_risk", "evidence": [{**evidence, **change}]})[0]["ruleId"])


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.store = {}
        self.channel = Mock(name="channel")
        self.channel.name = "telegram"
        self.channel.recipient_ref = "telegram_operations"
        self.channel.send.return_value = "delivered"
        self.dispatcher = NotificationDispatcher(Mock(), self.channel)
        self.dispatcher._args = lambda: ("test", lambda: "test")
        self.alert = {"alertId": "a1", "fazendaId": "f1", "type": "machine_risk", "severity": "high", "status": "open", "createdAt": datetime.now(timezone.utc)}
        def create(_, __, collection, identifier, doc):
            key = (collection, identifier)
            if key in self.store: raise RuntimeError("already exists")
            self.store[key] = dict(doc)
            return dict(doc)
        def update(_, __, collection, identifier, doc):
            self.store[(collection, identifier)] = dict(doc)
            return dict(doc)
        def query(_, __, collection, filters, **kwargs):
            return [dict(v) for (c, _), v in self.store.items() if c == collection and all(v.get(k) == x for k, x in filters.items())]
        patches = [patch.dict(os.environ, {"TELEGRAM_NOTIFICATIONS_ENABLED": "true"}),
                   patch("services.notification_service.criar_documento", side_effect=create),
                   patch("services.notification_service.atualizar_documento", side_effect=update),
                   patch("services.notification_service.obter_documento", side_effect=lambda _, __, c, i: self.store.get((c, i), self.alert if c == "alerts" else None)),
                   patch("services.notification_service.consultar_documentos", side_effect=query)]
        for p in patches: p.start(); self.addCleanup(p.stop)

    def test_dedupe_read_does_not_deliver_and_delivered_not_retried(self):
        self.dispatcher.enqueue(self.alert)
        self.dispatcher.enqueue(self.alert)
        self.assertEqual(1, len(self.store))
        self.assertEqual("created", self.dispatcher.list_for_alert("a1")[0]["status"])
        self.channel.send.assert_not_called()
        self.dispatcher.deliver_pending()
        self.dispatcher.deliver_pending()
        self.channel.send.assert_called_once()
        self.assertEqual("delivered", self.dispatcher.list_for_alert("a1")[0]["status"])

    def test_failure_retry_and_ambiguous_delivery(self):
        self.channel = TelegramChannel()
        self.channel.send_result = Mock(return_value={"status": "failed", "retryable": True})
        self.dispatcher.channel = self.channel
        self.dispatcher.enqueue(self.alert)
        now = datetime.now(timezone.utc)
        for i in range(4): self.dispatcher.deliver_pending(now=now + timedelta(minutes=i * 5))
        self.assertEqual(3, self.channel.send_result.call_count)
        self.assertEqual("permanently_failed", self.dispatcher.list_for_alert("a1")[0]["status"])
        self.dispatcher.enqueue({**self.alert, "severity": "critical"})
        self.channel.send_result.side_effect = RuntimeError("secret-token")
        self.dispatcher.deliver_pending()
        self.dispatcher.deliver_pending()
        self.assertEqual(4, self.channel.send_result.call_count)
        self.assertIn("unknown", [r["status"] for r in self.dispatcher.list_for_alert("a1")])

    def test_demo_disabled_and_resolved_never_queue(self):
        self.dispatcher.enqueue({**self.alert, "fazendaId": "demo_f1"})
        self.dispatcher.enqueue({**self.alert, "demoData": True})
        self.dispatcher.enqueue({**self.alert, "status": "resolved"})
        with patch.dict(os.environ, {"TELEGRAM_NOTIFICATIONS_ENABLED": "false"}): self.dispatcher.enqueue(self.alert)
        self.assertFalse(self.store)

    def test_existing_claim_prevents_concurrent_send(self):
        self.dispatcher.enqueue(self.alert)
        identifier = self.dispatcher.list_for_alert("a1")[0]["notificationId"]
        self.store[("notification_attempts", identifier + "_1")] = {}
        self.dispatcher.deliver_pending()
        self.channel.send.assert_not_called()

    def test_notification_failure_does_not_change_alert_result(self):
        dispatcher = Mock()
        dispatcher.enqueue.side_effect = RuntimeError("secret-token")
        service = AlertService(Mock(), notification_dispatcher=dispatcher)
        with patch.object(service, "_emit", return_value=(self.alert, False)):
            self.assertEqual((self.alert, False), service.emit())
        self.assertEqual("open", self.alert["status"])

    def test_transport_does_not_log_secrets(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "secret-token", "TELEGRAM_CHAT_ID": "secret-chat"}), patch("services.notification_service.requests.post", side_effect=RuntimeError("secret-token secret-chat")), patch("services.notification_service.LOGGER") as logger:
            self.assertEqual("unknown", TelegramChannel().send("test"))
            logger.warning.assert_not_called()
            logger.error.assert_not_called()
        self.dispatcher.enqueue(self.alert)
        self.assertNotIn("secret-token", str(self.store))
        self.assertNotIn("secret-chat", str(self.store))

    def test_transport_success_rejection_and_server_ambiguity(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "test"}):
            for code, ok, expected in [(200, True, "delivered"), (400, False, "failed"), (500, False, "failed")]:
                response = Mock(status_code=code)
                response.json.return_value = {"ok": ok}
                with patch("services.notification_service.requests.post", return_value=response):
                    self.assertEqual(expected, TelegramChannel().send("fixture"))

    def test_http_debug_logs_redact_token_and_chat(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "secret-token", "TELEGRAM_CHAT_ID": "secret-chat"}):
            record = logging.LogRecord("urllib3.connectionpool", logging.DEBUG, "", 1,
                                       "POST %s chat=%s", ("/botsecret-token/sendMessage", "secret-chat"), None)
            self.assertTrue(TelegramSecretFilter().filter(record))
            self.assertNotIn("secret-token", record.getMessage())
            self.assertNotIn("secret-chat", record.getMessage())


class ProductApiTests(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()

    def test_recommendations_additive_and_no_delivery_on_read(self):
        item = {"alertId": "a1", "status": "acknowledged", "type": "machine_risk"}
        with patch.object(server.alerts, "list", return_value=[item]), patch.object(server.notifications, "enqueue") as enqueue:
            response = self.client.get("/alertas").get_json()
        self.assertEqual("acknowledged", response["items"][0]["status"])
        self.assertEqual("machine_risk", response["items"][0]["recommendations"][0]["ruleId"])
        enqueue.assert_not_called()

    def test_notification_read_auth_remains_required(self):
        with patch.dict(server.app.config, {"TESTING": False, "ENVIRONMENT": "production", "APP_API_KEYS": ("private-key",)}):
            self.assertEqual(401, self.client.get("/alertas/a1/notifications").status_code)

    def test_notification_failure_is_explicit(self):
        with patch.object(server.notifications, "list_for_alert", side_effect=RuntimeError("secret-token")):
            response = self.client.get("/alertas/a1/notifications")
        self.assertEqual(503, response.status_code)
        self.assertNotIn("secret-token", response.text)

    def test_weather_recommendation_uses_official_severity_only(self):
        with patch("server.consultar_avisos_inmet", return_value={"status": "ok", "dados": {"items": [
            {"severity": "Perigo", "eventType": "Tempestade"},
            {"severity": "unknown", "eventType": "Tempestade"},
        ]}}):
            items = self.client.get("/weather/alerts").get_json()["items"]
        self.assertEqual("severe_weather_warning", items[0]["recommendations"][0]["ruleId"])
        self.assertEqual([], items[1]["recommendations"])
