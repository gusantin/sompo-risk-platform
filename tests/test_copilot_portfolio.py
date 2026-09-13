import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from services.presentation_portfolio_service import PORTFOLIO
from services.sompo_agro_agent.agent import AgroRiskAgent
from services.sompo_agro_agent.presentation import portfolio_context
from services.sompo_agro_agent.tools import AgentValidationError


class CopilotPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc).isoformat()
        self.snapshot = {"schema": "presentation_real_portfolio_v1", "generatedAt": self.now, "cases": []}
        for identity, level, score in zip(PORTFOLIO, ["moderado", "alto", "baixo"], [48, 65, 16]):
            self.snapshot["cases"].append({"id": identity["fazendaId"], "property": dict(identity),
                "riskType": "incendio", "risk": {"nivel": level, "score": score,
                    "fatores": [{"descricao": "Evidência positiva de teste", "contribuicao": 5},
                                {"descricao": "Fator sem contribuição", "contribuicao": 0}]},
                "provenance": {"identity": "demo", "environmental": {"origin": "real", "state": "real_live", "acquiredAt": self.now}},
                "sourceHealth": {"queimadas": {"attribution": "INPE fixture", "status": "ok", "consultedAt": self.now}},
                "hotspots": {"nearest": {"distanciaKm": 15.36}}})
        self.tools = Mock()
        self.agent = AgroRiskAgent(self.tools, provider="unconfigured", session=Mock())

    def ask(self, question, scope=None):
        return self.agent.ask(question, scope, presentation_snapshot=self.snapshot)

    def test_priority_and_official_score_without_provider_or_other_portfolio(self):
        original = deepcopy(self.snapshot)
        for question in ("Qual cliente precisa mais de atenção agora?", "Qual propriedade está com maior exposição?"):
            result = self.ask(question)
            self.assertIn("Cliente A", result["answer"])
            self.assertIn("alta (índice 65/100)", result["answer"])
            self.assertNotIn("Cliente B", result["answer"])
            self.assertTrue(result["readOnly"])
        self.assertEqual(self.snapshot, original)
        self.assertEqual(self.tools.mock_calls, [])
        self.agent.session.post.assert_not_called()

    def test_named_client_why_and_no_zero_contribution(self):
        text = self.ask("Por que o Cliente A está em risco alto?")["answer"]
        self.assertIn("Evidência positiva de teste", text)
        self.assertNotIn("Fator sem contribuição", text)
        self.assertNotIn("Cliente B", text)

    def test_low_is_not_asserted_as_physical_normality(self):
        text = self.ask("Qual cliente está em situação normal?")["answer"]
        self.assertIn("Cliente C", text)
        self.assertIn("exposição na captura baixa", text)
        self.assertNotIn("situação normal", text)

    def test_hotspot_is_not_confirmed_fire(self):
        text = self.ask("Existe algum foco de calor relevante?")["answer"]
        self.assertIn("15.36 km do ponto municipal", text)
        self.assertIn("não confirma incêndio", text)
        self.assertNotIn("incêndio confirmado", text)

    def test_demo_identity_real_cache_and_original_timestamp(self):
        for question in ("Quais dados são reais e quais são demonstrativos?", "Quando esses dados foram atualizados?"):
            text = self.ask(question)["answer"]
            self.assertIn("não representam segurados SOMPO", text)
            self.assertIn("real em cache", text)
            self.assertIn(self.now, text)
            self.assertNotIn("ao vivo", text)

    def test_stale_unknown_and_synthetic_are_explicit(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        self.snapshot["cases"][0]["provenance"]["environmental"]["acquiredAt"] = old
        self.snapshot["cases"][1]["provenance"]["environmental"]["origin"] = "synthetic"
        self.snapshot["cases"][2]["provenance"]["environmental"]["acquiredAt"] = None
        text = self.ask("Quais dados são reais?")["answer"]
        self.assertIn("desatualizada", text)
        self.assertIn("sintética/demonstrativa", text)
        self.assertIn("indisponíveis", text)
        self.assertNotIn("65/100", text)
        self.assertNotIn("16/100", text)

    def test_insufficient_future_and_missing_source(self):
        case = self.snapshot["cases"][0]
        case["risk"] = {"score": None, "nivel": "dados_insuficientes"}
        case["provenance"]["environmental"]["state"] = "insufficient_data"
        self.assertIn("insuficientes", self.ask("Cliente B")["answer"])
        case["provenance"]["environmental"]["acquiredAt"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        self.assertEqual(portfolio_context(self.snapshot)["items"][0]["level"], "indisponível")
        self.snapshot["cases"][1]["sourceHealth"] = {}
        self.assertNotIn("65/100", self.ask("Cliente A")["answer"])

    def test_weather_critical_without_score_outranks_high(self):
        self.snapshot["cases"][2]["risk"] = {"nivel": "critical", "score": None}
        self.snapshot["cases"][2]["riskType"] = "weather"
        text = self.ask("Qual propriedade está com maior exposição?")["answer"]
        self.assertIn("Cliente C", text)
        self.assertIn("crítica", text)
        self.assertNotIn("Cliente A", text)

    def test_scope_mutations_and_missing_operational_facts(self):
        scope = PORTFOLIO[0]["fazendaId"]
        text = self.ask("Por que o Cliente A está em risco alto?", scope)["answer"]
        self.assertNotIn("Cliente A", text)
        with self.assertRaises(AgentValidationError):
            self.ask("risco", "unknown")
        self.assertIn("somente leitura", self.ask("Envie Telegram e altere o risco")["answer"])
        self.assertIn("não estão disponíveis", self.ask("Telegram entregue?")["answer"])

    def test_route_snapshot_pin_and_no_refresh_or_delivery(self):
        from server import app, rate_limiter
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.json"
            path.write_text(json.dumps(self.snapshot), encoding="utf-8")
            with patch.dict(app.config, {"PRESENTATION_PORTFOLIO_PATH": str(path), "ALLOW_DEV_AUTH_BYPASS": True, "ENVIRONMENT": "development", "APP_API_KEYS": []}), patch.object(rate_limiter, "allow", return_value=(True, 0)), patch("services.presentation_portfolio_service.PresentationPortfolio.capture") as capture, patch("server.notifications.enqueue") as enqueue:
                client = app.test_client()
                body = {"mode": "portfolio", "question": "Qual cliente precisa mais de atenção agora?", "snapshotGeneratedAt": self.now}
                response = client.post("/agent/query", json=body)
                self.assertEqual(response.status_code, 200, response.get_json())
                self.assertIn("Cliente A", response.get_json()["answer"])
                self.assertEqual(response.get_json()["snapshotGeneratedAt"], self.now)
                self.assertEqual(client.post("/agent/query", json={**body, "snapshotGeneratedAt": "old"}).status_code, 409)
                self.assertEqual(client.post("/agent/query", json={**body, "mode": "arbitrary"}).status_code, 400)
                path.write_text("{}", encoding="utf-8")
                self.assertEqual(client.post("/agent/query", json=body).status_code, 503)
                capture.assert_not_called()
                enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
