import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from services.sompo_agro_agent.tools import AgroRiskTools, AgentValidationError


class CopilotOperationsTests(unittest.TestCase):
    def setUp(self):
        self.services = [Mock() for _ in range(7)]
        props, snapshots, machines, telemetry, devices, events, alerts = self.services
        props.listar.return_value = [{"fazendaId": "f1", "nome": "Farm One"}, {"fazendaId": "f2", "nome": "Farm Two"}, {"fazendaId": "demo_x", "demoData": True}]
        snapshots.list_properties.return_value = []
        snapshots.get_property.return_value = {"environmentalRisk": {"geral": {"nivel": "alto"}}, "analysisAt": "2026-09-12T10:00:00Z"}
        machines.listar.return_value = [{"maquinaId": "m1", "nome": "Machine One"}]
        snapshots.get_machine.return_value = {"machineRisk": {"status": "insufficient_data", "level": "low"}, "deviceHealth": {"status": "stale"}, "lastSeenAt": datetime.now(timezone.utc) - timedelta(minutes=10)}
        telemetry.mais_recente.return_value = None
        devices.list.return_value = []
        events.list.return_value = []
        alerts.list.return_value = [
            {"alertId": "ack", "fazendaId": "f1", "severity": "high", "status": "acknowledged", "type": "machine_risk"},
            {"alertId": "open", "fazendaId": "f1", "severity": "high", "status": "open", "type": "machine_risk"},
            {"alertId": "other", "fazendaId": "f2", "severity": "critical", "status": "open", "type": "machine_risk"},
            {"alertId": "demo", "fazendaId": "demo_x", "severity": "critical", "status": "open"},
        ]
        self.tools = AgroRiskTools(*self.services, lambda: {"cases": []}, lambda: {})

    def test_portfolio_queries_use_official_operations_without_selecting_one_property(self):
        for question in ("Quais propriedades devo priorizar agora?", "Quais máquinas estão em risco alto ou crítico?", "Quais alertas ainda estão abertos?", "Quais alertas já foram reconhecidos?", "Resuma o risco atual da carteira.", "Qual é o principal risco neste momento?"):
            context = self.tools.get_agent_context(question)
            self.assertIn("consultar_operacoes", context["tools_consultadas"])
            self.assertNotIn("fazenda_id", context)
            self.assertEqual(len(context["operacoes"]["properties"]), 2)
            self.assertNotIn("demo", [a["alertId"] for a in context["operacoes"]["alerts"]])

    def test_client_scope_order_recommendations_and_freshness_reach_model(self):
        for question in ("O que precisa da minha atenção agora?", "O que devo verificar primeiro?", "Qual máquina merece atenção?", "Algum dado está desatualizado?"):
            context = self.tools.get_agent_context(question, "f1")
            operations = context["operacoes"]
            self.assertEqual([p["propertyId"] for p in operations["properties"]], ["f1"])
            self.assertEqual([a["alertId"] for a in operations["alerts"]], ["open", "ack"])
            text = self.tools.format_for_llm(context, question)
            for expected in ("acknowledged", "open", "Inspecionar os componentes", "insufficient_data", "stale"):
                self.assertIn(expected, text)
            self.assertNotIn("propriedade f2", text)

    def test_unavailable_is_not_zero_and_tools_are_read_only(self):
        self.services[-1].list.side_effect = RuntimeError("offline")
        self.services[1].get_property.return_value = None
        result = self.tools.execute("consultar_operacoes", {"property_id": "f1"})
        self.assertIsNone(result["alertCounts"])
        self.assertEqual(result["properties"][0]["level"], "unknown")
        self.assertTrue(result["readOnly"])
        for service in self.services:
            self.assertFalse(any(call[0].split('.')[0] in {"update_status", "emit", "evaluate", "enqueue", "criar", "atualizar"} for call in service.mock_calls))
        with self.assertRaises(AgentValidationError):
            self.tools.execute("resolver_alerta", {})

    def test_generic_machine_query_does_not_filter_by_question_text(self):
        context = self.tools.get_agent_context("Qual máquina merece atenção?", "f1")
        self.assertEqual(len(context["maquinas_esp32"]["items"]), 1)

    def test_client_why_uses_persisted_overall_and_category_factors(self):
        self.services[1].get_property.return_value = {"environmentalRisk": {
            "geral": {"nivel": "alto", "score": 70},
            "incendio": {"nivel": "alto", "fatores": [{"descricao": "Umidade baixa observada"}]}}}
        context = self.tools.get_agent_context("Por que minha propriedade está em risco?", "f1")
        text = self.tools.format_for_llm(context)
        self.assertIn("70/100", text)
        self.assertIn("Umidade baixa observada", text)
        self.assertIn("Farm One", text)

    def test_operational_context_excludes_live_showcase(self):
        self.tools.live_case_loader = lambda: {"cases": [{"id": "demo_showcase", "property": {"nome": "Showcase", "demoData": True}, "risk": {"score": 99, "nivel": "critico"}}]}
        context = self.tools.get_agent_context("Resuma o risco atual da carteira.")
        self.assertNotIn("Showcase", self.tools.format_for_llm(context))
        self.assertEqual(context["operacoes"]["machines"][0]["machineRisk"]["level"], "unknown")

    def test_notification_queries_use_scoped_read_only_persistence(self):
        self.tools.notification_reader = Mock(return_value=[{"notificationId": "n1", "status": "delivered", "telegramMessageId": 123}])
        context = self.tools.get_agent_context("Esse alerta foi enviado ao Telegram?", "f1")
        self.assertIn("operacoes", context)
        self.assertIn("delivered", self.tools.format_for_llm(context))
        self.assertEqual({"open", "ack"}, {c.args[0] for c in self.tools.notification_reader.call_args_list})


if __name__ == "__main__":
    unittest.main()
