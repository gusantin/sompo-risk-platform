import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from services.presentation_portfolio_service import PORTFOLIO, SECOND_PROPERTY, PresentationPortfolio
from services.product_perspective_service import scope_snapshot, create_property, analyze_property
from services.sompo_agro_agent.agent import AgroRiskAgent
from services.sompo_agro_agent.tools import AgentValidationError


class ProductPerspectiveTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc).isoformat()
        self.snapshot = {"schema": "presentation_real_portfolio_v1", "generatedAt": self.now, "cases": []}
        for prop in (*PORTFOLIO, SECOND_PROPERTY):
            self.snapshot["cases"].append({"id": prop["fazendaId"], "property": dict(prop), "riskType": "incendio",
                "risk": {"nivel": "alto", "score": 61, "fatores": []}, "rawSources": {},
                "provenance": {"identity": "demo", "environmental": {"origin": "real", "state": "real_cached", "acquiredAt": self.now}},
                "sourceHealth": {"clima": {"attribution": "fixture", "consultedAt": self.now}},
                "environmentalContext": {"schema": "environmental_context_v1"}})
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "portfolio.json"
        self.path.write_text(json.dumps(self.snapshot), encoding="utf8")

    def test_insurer_and_insured_scopes_reuse_canonical_evidence(self):
        original = deepcopy(self.snapshot)
        insurer = scope_snapshot(self.snapshot, "seguradora")
        insured = scope_snapshot(self.snapshot, "segurado", "Cliente C")
        self.assertEqual(4, len(insurer["cases"]))
        self.assertEqual(2, len(insured["cases"]))
        self.assertEqual({"Fazenda Araguaia", "Fazenda Horizonte"}, {c["property"]["nome"] for c in insured["cases"]})
        serialized = json.dumps(insured)
        for forbidden in ("Cliente B", "Cliente C", "demo_portfolio_pocone", "demo_portfolio_dourados"):
            self.assertNotIn(forbidden, serialized)
        for c in insured["cases"]:
            source = next(p for p in self.snapshot["cases"] if p["id"] == c["id"])
            self.assertEqual(source["risk"], c["risk"])
            self.assertEqual(source["environmentalContext"], c["environmentalContext"])
        self.assertEqual(original, self.snapshot)

    def test_insured_copilot_rejects_cross_client_context(self):
        agent = AgroRiskAgent(Mock(), provider="unconfigured", session=Mock())
        scoped = scope_snapshot(self.snapshot, "segurado")
        answer = agent.ask("Qual das minhas fazendas está com maior risco?", presentation_snapshot=scoped)
        self.assertTrue(answer["readOnly"])
        self.assertEqual(2, len(answer["trace"]["consultedIds"]))
        self.assertNotIn("Cliente B", json.dumps(answer))
        self.assertNotIn("carteira", answer["answer"])
        with self.assertRaises(AgentValidationError):
            agent.ask("Cliente B", "demo_portfolio_pocone", presentation_snapshot=scoped)
        insurer = agent.ask("Qual cliente exige atenção?", presentation_snapshot=scope_snapshot(self.snapshot, "seguradora"))
        self.assertEqual(4, len(insurer["trace"]["consultedIds"]))
        agent.session.post.assert_not_called()

    def test_create_saves_waiting_without_environment_or_firebase(self):
        with patch("services.propriedade_service.criar_documento") as firestore, patch("integracoes.ibge.listar_municipios") as locate:
            prop = create_property(self.path, {"nome": "Fazenda Nova", "municipio": "Sorriso", "estado": "MT"})
        stored = json.loads(self.path.read_text(encoding="utf8"))["cases"][-1]
        self.assertEqual(prop["fazendaId"], stored["id"])
        self.assertEqual("waiting", stored["processingState"])
        self.assertIsNone(stored["risk"]["score"])
        self.assertEqual({}, stored["rawSources"])
        firestore.assert_not_called()
        locate.assert_not_called()
        with self.assertRaises(ValueError):
            create_property(self.path, {"nome": "Fake", "municipio": "Sorriso", "estado": "MT", "score": 99})

    def test_analysis_failure_keeps_property_and_no_fabricated_risk(self):
        prop = create_property(self.path, {"nome": "Fazenda Nova", "municipio": "Sorriso", "estado": "MT"})
        with patch("integracoes.ibge.listar_municipios", side_effect=RuntimeError("offline")):
            result = analyze_property(self.path, prop["fazendaId"])
        self.assertEqual("unavailable", result["processingState"])
        self.assertIsNone(result["risk"]["score"])
        self.assertEqual(5, len(json.loads(self.path.read_text(encoding="utf8"))["cases"]))
        with self.assertRaises(ValueError):
            analyze_property(self.path, "demo_portfolio_pocone")

    def test_refresh_preserves_registration_waiting_for_location(self):
        prop = create_property(self.path, {"nome": "Fazenda Nova", "municipio": "Sorriso", "estado": "MT"})
        before = json.loads(self.path.read_text(encoding="utf8"))
        service = PresentationPortfolio(Mock(side_effect=RuntimeError("offline")), {})
        result = service.capture(before)
        pending = next(c for c in result["cases"] if c["id"] == prop["fazendaId"])
        self.assertEqual("waiting", pending["processingState"])
        self.assertIsNone(pending["risk"]["score"])
        self.assertEqual(5, len(result["cases"]))

    def test_analysis_calls_existing_pipeline_and_preserves_other_cases(self):
        prop = create_property(self.path, {"nome": "Fazenda Nova", "municipio": "Sorriso", "estado": "MT"})
        service = Mock(wraps=PresentationPortfolio(None, {}))
        captured = {"id": prop["fazendaId"], "property": prop, "risk": {"score": 14, "nivel": "baixo"}}
        service.capture.return_value = {"cases": [captured]}
        with patch("services.product_perspective_service.configured_portfolio", return_value=service), patch("integracoes.ibge.listar_municipios", return_value=[{"municipality": "Sorriso", "ibgeCode": "5107925"}]):
            result = analyze_property(self.path, prop["fazendaId"])
        self.assertEqual(14, result["risk"]["score"])
        self.assertEqual("5107925", service.capture.call_args.kwargs["identities"][0]["ibgeCode"])
        self.assertEqual(self.snapshot["cases"], json.loads(self.path.read_text(encoding="utf8"))["cases"][:4])

    def test_backend_scope_and_copilot_operational_facts(self):
        import server
        with patch.dict(server.app.config, {"TESTING": True, "ENVIRONMENT": "test", "PRESENTATION_PORTFOLIO_PATH": str(self.path), "EXPENSIVE_RATE_LIMIT_REQUESTS": 10000}), patch.object(server.alerts, "list", return_value=[]) as reader, patch.object(server.notifications, "enqueue") as enqueue:
            client = server.app.test_client()
            response = client.get("/showcase/perspectives/segurado?client=Cliente%20C")
            self.assertEqual(200, response.status_code)
            self.assertEqual(2, len(response.json["cases"]))
            self.assertEqual({"demo_portfolio_confresa", "demo_portfolio_horizonte"}, {c.args[0]["fazendaId"] for c in reader.call_args_list})
            answer = client.post("/agent/query", json={"question": "Quem foi notificado?", "mode": "portfolio", "perspective": "segurado", "snapshotGeneratedAt": self.now})
            self.assertEqual(200, answer.status_code)
            self.assertNotIn("Cliente B", json.dumps(answer.json))
            self.assertIn("0 alertas", answer.json["answer"])
            denied = client.post("/agent/query", json={"question": "risco", "mode": "portfolio", "perspective": "segurado", "contextPropertyId": "demo_portfolio_dourados", "snapshotGeneratedAt": self.now})
            self.assertEqual(400, denied.status_code)
            enqueue.assert_not_called()
