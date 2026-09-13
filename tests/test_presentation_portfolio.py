import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from services.presentation_portfolio_service import PresentationPortfolio, PORTFOLIO
from services.notification_messages import message_for


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.raw = {"status": "ok", "atribuicao": "Provider fixture", "consultadoEm": self.now.isoformat(), "dados": {
            "temperaturaAtualC": 22, "umidadeRelativaAtualPct": 90, "chuvaAcumulada72hMm": 30,
            "rajadaMax72hKmh": 5, "umidadeSoloMin72hM3M3": 0.4}}
        self.provider = Mock(side_effect=lambda *args: copy.deepcopy(self.raw))
        def locate(code):
            return {"ibgeCode": code, "state": next(p["estado"] for p in PORTFOLIO if p["ibgeCode"] == code),
                    "latitude": -15, "longitude": -55, "coordinateSource": "IBGE fixture", "representativeness": "municipality_representative_point_only"}
        self.service = PresentationPortfolio(locate, {"clima": self.provider})

    def test_fixed_identity_does_not_force_elevated_risk(self):
        result = self.service.capture(now=self.now)
        self.assertEqual(3, len(result["cases"]))
        self.assertEqual([p["fazendaId"] for p in PORTFOLIO], [c["id"] for c in result["cases"]])
        for c in result["cases"]:
            self.assertTrue(c["property"]["demoData"])
            self.assertEqual("real", c["provenance"]["environmental"]["origin"])
            self.assertNotIn(c["risk"]["nivel"], {"alto", "critico"})
            self.assertIsNone(c.get("operationalState"))

    def test_real_fallback_keeps_acquisition_and_coordinates(self):
        first = self.service.capture(now=self.now)
        self.provider.side_effect = RuntimeError("network unavailable")
        self.service.locate = Mock(side_effect=RuntimeError("IBGE unavailable"))
        fallback = self.service.capture(first, self.now + timedelta(hours=1))
        for c in fallback["cases"]:
            self.assertEqual(self.now.isoformat(), c["provenance"]["environmental"]["acquiredAt"])
            self.assertEqual("real_cached", c["provenance"]["environmental"]["state"])
            self.assertEqual(-15, c["property"]["latitude"])
        stale = self.service.snapshot(first, self.now + timedelta(hours=7))
        self.assertTrue(all(c["provenance"]["environmental"]["state"] == "stale" for c in stale["cases"]))

    def test_missing_provider_never_becomes_synthetic_or_zero(self):
        self.provider.side_effect = RuntimeError("offline")
        result = self.service.capture(now=self.now)
        for c in result["cases"]:
            self.assertEqual("unavailable", c["provenance"]["environmental"]["state"])
            self.assertIsNone(c["risk"]["score"])
            self.assertEqual([], c["environmentalEvidence"])

    def test_synthetic_or_unproven_snapshot_cannot_supply_real_fallback(self):
        first = self.service.capture(now=self.now)
        first["schema"] = "synthetic_demo"
        self.provider.side_effect = RuntimeError("offline")
        result = self.service.capture(first, self.now)
        self.assertTrue(all(c["provenance"]["environmental"]["origin"] == "unavailable" for c in result["cases"]))

    def test_wrong_coordinates_do_not_query_environment(self):
        self.service.locate = lambda code: {"ibgeCode": "wrong", "state": "MT", "latitude": 0, "longitude": 0}
        result = self.service.capture(now=self.now)
        self.provider.assert_not_called()
        self.assertTrue(all(c["property"].get("latitude") is None for c in result["cases"]))

    def test_weather_stays_official_and_scoped(self):
        warning = {"id": "fixture_warning", "severity": "Perigo", "eventType": "Tempestade",
                   "source": "INMET fixture", "location": "Poconé/MT", "startsAt": (self.now-timedelta(hours=1)).isoformat(), "endsAt": (self.now+timedelta(hours=1)).isoformat()}
        self.service.providers["avisos"] = lambda *args: {"status": "ok", "atribuicao": "INMET fixture", "consultadoEm": self.now.isoformat(), "dados": {"items": [warning]}}
        result = self.service.capture(now=self.now)
        self.assertEqual("weather", result["cases"][0]["riskType"])
        self.assertEqual("high", result["cases"][0]["risk"]["nivel"])
        self.assertIsNone(result["cases"][0]["risk"]["score"])
        self.assertEqual([], result["cases"][2]["weatherWarnings"])

    def test_snapshot_route_exposes_only_queried_operational_state(self):
        import server
        service = Mock()
        payload = self.service.capture(now=self.now)
        service.snapshot.return_value = payload
        with patch.dict(server.app.config, {"TESTING": True}), patch("services.presentation_portfolio_service.configured_portfolio", return_value=service), patch.object(server.alerts, "list", return_value=[]), patch.object(server.notifications, "enqueue") as enqueue:
            result = server.app.test_client().get("/showcase/portfolio").get_json()
        self.assertTrue(all(c["operationalState"]["openAlerts"] == 0 for c in result["cases"]))
        service.capture.assert_not_called()
        enqueue.assert_not_called()


class MessagePresentationTests(unittest.TestCase):
    def setUp(self):
        self.alert = {"fazendaId": "demo_fixture", "propertyName": "Fazenda de Teste", "municipality": "Poconé", "state": "MT",
            "severity": "critical", "riskType": "incendio", "type": "environmental_fire_risk", "createdAt": "2026-09-12T18:00:00+00:00",
            "factors": [{"descricao": "Baixa umidade informada pela fonte de teste."}],
            "evidence": [{"label": "Umidade relativa", "value": 19, "unit": "%", "source": "Provider fixture"}]}

    def test_clear_heading_real_identity_split_and_optional_fields(self):
        text = message_for(self.alert, "alert")
        self.assertTrue(text.startswith("🧪 DADOS DE DEMONSTRAÇÃO"))
        self.assertIn("RISCO CRÍTICO", text)
        self.assertIn("Poconé — MT", text)
        self.assertIn("Umidade relativa: 19 %", text)
        self.assertNotIn("None", text)
        self.assertNotIn("notification_", text)
        unnamed = message_for({**self.alert, "propertyName": None, "maquinaId": "internal_machine_id"}, "alert")
        self.assertNotIn("demo_fixture", unnamed)
        self.assertNotIn("internal_machine_id", unnamed)
        self.assertNotIn("🚜", text)
        zero = {**self.alert, "factors": [{"descricao": "Unsupported elevated condition", "contribuicao": 0}]}
        self.assertNotIn("Unsupported elevated condition", message_for(zero, "alert"))
        provenance = {"identity": "demo", "environmental": {"origin": "real", "state": "stale", "acquiredAt": self.alert["createdAt"]}}
        text = message_for({**self.alert, "provenance": provenance}, "alert")
        self.assertIn("Cliente demonstrativo · Leitura ambiental real desatualizada", text)

    def test_forecast_is_not_observation_and_expiry_is_visible(self):
        alert = {**self.alert, "type": "severe_weather_warning", "evidence": [{"weatherSeverity": "Perigo", "eventType": "Tempestade", "description": "Possibilidade de granizo.", "endsAt": "2026-09-12T23:00:00+00:00", "source": "INMET fixture"}]}
        text = message_for(alert, "alert")
        self.assertIn("SOMPO LIVE — PERIGO", text)
        self.assertIn("Possibilidade de granizo", text)
        self.assertIn("Validade:", text)
        self.assertNotIn("granizo observado", text)

    def test_machine_scope_and_escalation_delta(self):
        ambient = {"sensorId": "s1", "type": "temperature", "scope": "ambient_local", "value": 42, "unit": "celsius"}
        self.assertNotIn("Temperatura do componente", message_for({**self.alert, "evidence": [ambient]}, "alert"))
        current = {**ambient, "scope": "machine_component", "value": 105, "level": "critical"}
        alert = {**self.alert, "type": "machine_risk", "maquinaId": "m1", "machineName": "Trator de Teste", "evidence": [current],
                 "escalation": {"previousEvidence": [{**current, "value": 95}]}}
        text = message_for(alert, "escalation")
        self.assertIn("95 → 105", text)
        self.assertIn("Parar e inspecionar", text)

    def test_closure_does_not_claim_observed_normalization(self):
        text = message_for({**self.alert, "resolvedAt": "2026-09-12T19:00:00+00:00"}, "resolution")
        self.assertIn("ALERTA ENCERRADO", text)
        self.assertNotIn("19 %", text)
        self.assertNotIn("SITUAÇÃO NORMALIZADA", text)
