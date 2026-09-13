import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from config import Config
from scripts.telegram_demo import portfolio_message, run
from services.alert_service import AlertService
from services.notification_messages import message_for, stamp
from services.notification_service import NotificationDispatcher
from services.presentation_portfolio_service import PORTFOLIO


class TelegramPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "snapshot.json"
        self.now = datetime.now(timezone.utc).isoformat()
        self.case = {"id": PORTFOLIO[1]["fazendaId"], "property": deepcopy(PORTFOLIO[1]),
            "riskType": "incendio", "risk": {"nivel": "alto", "score": 65, "fatores": []},
            "environmentalEvidence": [{"label": "Umidade relativa", "value": 48, "unit": "%", "source": "Weather fixture", "observedAt": self.now}],
            "sourceHealth": {"clima": {"status": "ok", "attribution": "Weather fixture", "consultedAt": self.now}},
            "provenance": {"identity": "demo", "environmental": {"origin": "real", "state": "real_live", "acquiredAt": self.now}}}
        self.save()

    def save(self):
        self.path.write_text(json.dumps({"schema": "presentation_real_portfolio_v1", "cases": [self.case]}), encoding="utf-8")

    def test_entity_evidence_source_and_provenance(self):
        alert = portfolio_message("A", self.path)
        text = message_for(alert, "alert")
        for expected in ("Fazenda Araguaia", "Confresa — MT", "Umidade relativa: 48%", "Weather fixture", "Propriedade demonstrativa · Última leitura ambiental real"):
            self.assertIn(expected, text)
        for absent in ("Município fictício", "DEMO Telegram", "Cliente A", "DADOS DE DEMONSTRAÇÃO", "km", "°C", "não estão disponíveis"):
            self.assertNotIn(absent, text)
        self.assertEqual(alert["evidence"], self.case["environmentalEvidence"])
        self.assertEqual(alert["provenance"]["environmental"]["acquiredAt"], self.now)

    def test_local_timestamp_and_timezone_override(self):
        self.assertEqual(stamp("2026-09-12T22:06:14+00:00"), "12/09/2026 às 19:06")
        self.assertEqual(stamp("2026-09-12T22:06:14+00:00", "America/Cuiaba"), "12/09/2026 às 18:06")
        self.case["property"]["timezone"] = "America/Cuiaba"
        self.save()
        self.assertEqual(portfolio_message("A", self.path)["presentationTimezone"], "America/Cuiaba")

    def test_stale_and_missing_evidence(self):
        self.case["provenance"]["environmental"]["acquiredAt"] = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        self.case["environmentalEvidence"] = []
        self.save()
        text = message_for(portfolio_message("A", self.path), "alert")
        self.assertIn("atualmente desatualizada", text)
        self.assertIn("Evidências detalhadas não estão disponíveis nesta captura", text)
        self.assertNotIn("ao vivo", text)

    def test_no_forced_high_or_synthetic_fallback(self):
        self.case["risk"]["nivel"] = "moderado"
        self.save()
        with patch.object(Config, "PRESENTATION_PORTFOLIO_PATH", str(self.path)), patch.object(Config, "ENVIRONMENT", "test"):
            result = run("fixture", deliver=True, portfolio_client="A")
            self.assertEqual(result["severity"], "moderate")
            self.assertFalse(result["queued"])
            with self.assertRaises(ValueError):
                run("fixture", action="high", portfolio_client="A")
        self.case["provenance"]["environmental"]["origin"] = "synthetic"
        self.save()
        with self.assertRaises(ValueError):
            portfolio_message("A", self.path)

    def test_only_stored_hotspot_distance_and_observation(self):
        self.case["environmentalEvidence"].append({"label": "Distância", "value": 15.36, "unit": "km", "source": "INPE fixture", "observedAt": "2026-09-11T16:24:00+00:00"})
        self.save()
        text = message_for(portfolio_message("A", self.path), "alert")
        self.assertIn("15,4 km do ponto de referência monitorado; observado em 11/09/2026 às 13:24", text)
        self.assertIn("Detecção de calor por satélite; não significa incêndio confirmado.", text)
        self.assertNotIn("ponto municipal", text)
        self.assertNotIn("km da propriedade", text)

    def test_cached_wording_brazilian_numbers_and_unchanged_input(self):
        self.case["environmentalEvidence"] = [
            {"label": label, "value": value, "unit": unit}
            for label, value, unit in (("Temperatura atual", 29.6, "°C"),
                ("Umidade relativa atual", 48, "%"), ("Precipitação atual", 0.0, "mm"),
                ("Vento atual", 8.1, "km/h"))]
        self.save()
        alert = portfolio_message("A", self.path)
        before = deepcopy(alert)
        snapshot_bytes = self.path.read_bytes()
        text = message_for(alert, "alert")
        for expected in ("Temperatura na última leitura: 29,6 °C", "Umidade na última leitura: 48%",
                         "Precipitação na última leitura: 0 mm", "Vento na última leitura: 8,1 km/h"):
            self.assertIn(expected, text)
        self.assertEqual(alert, before)
        self.assertEqual(self.path.read_bytes(), snapshot_bytes)
        legacy = {k: v for k, v in alert.items() if k != "presentationPortfolioId"}
        self.assertIn("Temperatura atual: 29.6 °C", message_for(legacy, "alert"))

    def test_real_outbox_deduplication_and_legacy_path_with_fake_transport(self):
        import server
        store = {}
        def get(_, __, c, i):
            return deepcopy(store.get((c, i)))
        def create(_, __, c, i, data):
            if (c, i) in store:
                raise RuntimeError("already exists")
            store[c, i] = deepcopy(data)
            return deepcopy(data)
        def update(_, __, c, i, data, **kwargs):
            store[c, i] = deepcopy(data)
            return deepcopy(data)
        def query(_, __, c, filters, *args, **kwargs):
            return [deepcopy(v) for (collection, _), v in store.items() if collection == c and all(v.get(k) == x for k, x in filters.items())]
        firebase = Mock(firestore_url="fixture")
        channel = Mock()
        channel.name, channel.recipient_ref = "telegram", "fixture"
        channel.send.return_value = "delivered"
        dispatcher = NotificationDispatcher(firebase, channel)
        alerts = AlertService(firebase, notification_dispatcher=dispatcher)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"ENVIRONMENT": "test", "TELEGRAM_NOTIFICATIONS_ENABLED": "true", "TELEGRAM_BOT_TOKEN": "fixture", "TELEGRAM_CHAT_ID": "fixture"}))
            for key, value in {"ENVIRONMENT": "test", "PRESENTATION_PORTFOLIO_PATH": str(self.path), "FIREBASE_KEY_PATH": str(self.path)}.items():
                stack.enter_context(patch.object(Config, key, value))
            for module in ("services.firestore_service", "services.alert_service", "services.notification_service"):
                for name, func in (("obter_documento", get), ("criar_documento", create), ("atualizar_documento", update), ("consultar_documentos", query)):
                    stack.enter_context(patch(module + "." + name, side_effect=func))
            for name, obj in (("firebase", firebase), ("alerts", alerts), ("notifications", dispatcher)):
                stack.enter_context(patch.object(server, name, obj))
            first = run("presentation_fixture", deliver=True, portfolio_client="A")
            second = run("presentation_fixture", deliver=True, portfolio_client="A")
            self.assertTrue(first["alertPersisted"])
            self.assertTrue(second["deduplicated"])
            self.assertTrue(second["delivered"])
            channel.send.assert_called_once()
            self.assertIn("Fazenda Araguaia", channel.send.call_args.args[0])
            self.assertEqual(len([1 for c, _ in store if c == "notifications"]), 1)
            self.case["risk"]["score"] = 66
            self.save()
            with self.assertRaises(ValueError):
                run("presentation_fixture", deliver=True, portfolio_client="A")
            legacy = run("legacy_fixture", deliver=True)
            self.assertTrue(legacy["delivered"])
            self.assertEqual(channel.send.call_count, 2)
            self.assertIn("DEMO Telegram legacy_fixture", channel.send.call_args.args[0])
            self.assertTrue(channel.send.call_args.args[0].startswith("🧪 DADOS DE DEMONSTRAÇÃO"))


if __name__ == "__main__":
    unittest.main()
