import copy
import unittest
from unittest.mock import patch

import server
from services.sompo_agro_agent import AgentProviderError, AgroRiskAgent, AgroRiskTools


class EmptyService:
    def listar(self, *_args, **_kwargs):
        return []

    def list(self, *_args, **_kwargs):
        return []

    def list_properties(self, *_args, **_kwargs):
        return []

    def get_property(self, *_args, **_kwargs):
        return None

    def get_machine(self, *_args, **_kwargs):
        return None

    def mais_recente(self, *_args, **_kwargs):
        return None


def live_payload():
    return {
        "generatedAt": "2026-08-25T22:19:19+00:00",
        "limitations": ["Propriedades são demonstrativas; condições ambientais são reais."],
        "cases": [{
            "id": "live_incendio_mt_novo_mundo", "riskType": "incendio",
            "risk": {"score": 68, "nivel": "alto", "confianca": "alta", "coberturaDadosPct": 100,
                     "fatores": [
                         {"fator": "temperatura_alta", "contribuicao": 25,
                          "descricao": "Temperatura elevada."},
                         {"fator": "umidade_baixa", "contribuicao": 80,
                          "descricao": "Umidade relativa baixa."},
                     ]},
            "riskExplanation": {"level": "alto", "mainFactors": [{"fator": "temperatura_alta"}]},
            "property": {"fazendaId": "live_incendio_mt_novo_mundo", "nome": "Fazenda Demo — Novo Mundo",
                         "municipio": "Novo Mundo", "estado": "MT", "latitude": -9.96,
                         "longitude": -55.2, "demoData": True},
            "environmentalDataReal": True, "analysisAt": "2026-08-25T22:19:19+00:00",
            "environmentalEvidence": [{"label": "Temperatura atual", "value": 34, "unit": "°C",
                                       "source": "Open-Meteo Forecast API"}],
            "hotspots": {"items": [{"id": "h1", "detectedAt": "2026-08-25T20:00:00+00:00",
                                      "source": "INPE Programa Queimadas", "satelite": "AQUA"}],
                         "nearest": {"id": "h1", "distanciaKm": 4.2,
                                     "source": "INPE Programa Queimadas"}},
            "provenance": {
                "clima": {"source": "Open-Meteo Forecast API", "consultedAt": "2026-08-25T22:00:00+00:00"},
                "inmet": {"source": "INMET WIS2 / OGC API", "consultedAt": "2026-08-25T22:00:00+00:00"},
                "queimadas": {"source": "INPE Programa Queimadas", "consultedAt": "2026-08-25T22:00:00+00:00"},
            },
            "sourceHealth": {}, "dataCoverage": {"weatherAvailable": True, "satelliteAvailable": True},
        }],
    }


def weather_alerts():
    return {"status": "ok", "atribuicao": "INMET Avisos Meteorológicos (RSS)", "dados": {"items": [{
        "id": "55491", "eventType": "Tempestade", "severity": "Perigo Potencial",
        "hailExplicit": True, "description": "Aviso com queda de granizo.",
        "source": "INMET Avisos Meteorológicos",
    }]}}


class MachineService:
    def listar(self, _property_id):
        return [{"maquinaId": "trator_01", "nome": "Trator 01", "sensoresConfigurados": [{
            "sensorId": "temp_01", "type": "temperature", "scope": "unknown",
            "target": None, "unit": "C",
        }]}]


class PropertyService:
    def listar(self, _limit=100):
        return [{"fazendaId": "f1", "nome": "Fazenda Teste"}]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


EXECUTIVE_ANSWER = (
    "Novo Mundo/MT exige atenção porque o risco de incêndio está em nível ALTO, com índice 68/100. "
    "Os principais fatores oficiais são umidade relativa baixa e temperatura elevada, e há um foco "
    "de calor próximo detectado pelo satélite "
    "AQUA via Programa Queimadas do INPE. As condições ambientais vieram de Open-Meteo e INMET. "
    "O foco de calor é uma evidência recente e não confirma incêndio em andamento."
)


class FakeSession:
    def __init__(self, answer=EXECUTIVE_ANSWER):
        self.calls = []
        self.answer = answer

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse({"message": {"content": self.answer}})


class AgroRiskAgentTests(unittest.TestCase):
    def make_tools(self, properties=None, machines=None, live_loader=live_payload):
        empty = EmptyService()
        return AgroRiskTools(
            properties or empty, empty, machines or empty, empty, empty, empty, empty,
            live_loader, weather_alerts,
        )

    def test_novo_mundo_e_explicado_sem_hardcode_no_servico(self):
        result = self.make_tools().property_context("Novo Mundo/MT")
        self.assertEqual(68, result["risk"]["score"])
        self.assertEqual("alto", result["risk"]["nivel"])
        self.assertIn("temperatura_alta", [item["fator"] for item in result["risk"]["fatores"]])
        self.assertEqual("Propriedade demonstrativa com condições ambientais reais.", result["propertyDisclosure"])
        self.assertIn("INPE Programa Queimadas", [item["source"] for item in result["sources"].values()])

    def test_hotspot_preserva_fonte_e_nao_confirma_incendio(self):
        result = self.make_tools().alerts_events("live_incendio_mt_novo_mundo")
        hotspot = next(item for item in result["events"] if item["eventType"] == "hotspot_detected")
        self.assertEqual("INPE Programa Queimadas", hotspot["source"])
        self.assertFalse(hotspot["confirmedFire"])
        self.assertIn("não confirma incêndio", hotspot["meaning"])
        weather = result["weatherAlerts"][0]
        self.assertEqual("Tempestade", weather["eventType"])
        self.assertIn("não confirma ocorrência", weather["hailMeaning"])

    def test_trator_sem_scope_e_telemetria_nao_inventa_temperatura(self):
        result = self.make_tools(PropertyService(), MachineService()).machines_esp32(None, "Trator 01")
        machine = result["items"][0]
        self.assertEqual("Dispositivo físico ainda sem telemetria disponível.", machine["physicalDeviceMessage"])
        self.assertEqual("insufficient_data", machine["engineTemperature"]["status"])
        self.assertNotIn("value", machine["engineTemperature"])

    def test_novo_mundo_responde_diretamente_com_fatores_oficiais(self):
        session = FakeSession()
        agent = AgroRiskAgent(self.make_tools(), session=session)
        result = agent.ask("Por que Novo Mundo exige atenção?")
        answer = result["answer"]
        self.assertLessEqual(answer.count(".") + answer.count("!"), 4)
        self.assertIn("Novo Mundo/MT", answer)
        self.assertIn("ALTO", result["answer"])
        self.assertIn("umidade relativa baixa", answer)
        self.assertIn("temperatura elevada", answer)
        for forbidden in ("json", "dados estruturados", "algoritmo", "componentes da resposta"):
            self.assertNotIn(forbidden, answer.lower())
        for internal_disclosure in ("demonstrativa", "demo", "mock", "teste"):
            self.assertNotIn(internal_disclosure, answer.lower())
        cited_descriptions = [item["descricao"] for item in live_payload()["cases"][0]["risk"]["fatores"]]
        self.assertTrue(all(description in cited_descriptions for description in (
            "Umidade relativa baixa.", "Temperatura elevada.",
        )))
        self.assertIn("consultar_contexto_da_propriedade", result["trace"]["tools"])
        self.assertIn("INPE Programa Queimadas", result["trace"]["sources"])
        self.assertEqual("live_incendio_mt_novo_mundo", result["contextPropertyId"])
        self.assertEqual("Ollama", result["provider"])
        self.assertEqual("llama3.2:3b", result["model"])
        self.assertTrue(result["readOnly"])
        self.assertEqual([], session.calls)
        context = self.make_tools().get_agent_context("Por que Novo Mundo exige atenção?")
        llm_context = self.make_tools().format_for_llm(context, "Por que Novo Mundo exige atenção?")
        for section in ("LOCAL:", "RISCO OFICIAL:",
                        "FATORES REAIS DO MOTOR — MAIOR CONTRIBUIÇÃO PRIMEIRO:",
                        "METEOROLOGIA E AMBIENTE:", "FOCO DE CALOR MAIS PRÓXIMO:",
                        "FONTES:", "ATUALIZAÇÃO DOS DADOS:"):
            self.assertIn(section, llm_context)
        self.assertIn("68/100 — ALTO", llm_context)
        self.assertIn("Confiança informada pelo motor: alta", llm_context)
        self.assertIn("Cobertura dos dados: 100%", llm_context)
        self.assertIn("AQUA", llm_context)
        self.assertLess(llm_context.index("Umidade relativa baixa."),
                        llm_context.index("Temperatura elevada."))
        for internal_name in ('"score"', "dataCoverage", "sourceHealth", "fazenda_id", "tools_consultadas"):
            self.assertNotIn(internal_name, llm_context)

    def test_divulgacao_demo_so_aparece_quando_usuario_pergunta(self):
        agent = AgroRiskAgent(self.make_tools(), session=FakeSession())
        regular = agent.ask("Por que Novo Mundo exige atenção?")["answer"]
        explicit = agent.ask("Novo Mundo é uma propriedade demo ou usa dados reais?")["answer"]
        self.assertNotIn("demonstrativa", regular.lower())
        self.assertIn("Propriedade demonstrativa com condições ambientais reais.", explicit)

    def test_resposta_meta_do_modelo_e_substituida_por_explicacao_natural(self):
        meta_answer = (
            "O JSON contém dados estruturados. Essa é uma resposta detalhada; você gostaria "
            "que eu explique os componentes da resposta e o algoritmo?"
        )
        session = FakeSession(meta_answer)
        agent = AgroRiskAgent(self.make_tools(), session=session)
        result = agent.ask("Detalhe Novo Mundo para mim.")
        self.assertEqual(1, len(session.calls))
        self.assertIn("Novo Mundo/MT exige atenção", result["answer"])
        for forbidden in ("json", "dados estruturados", "algoritmo", "componentes da resposta"):
            self.assertNotIn(forbidden, result["answer"].lower())

    def test_contexto_rota_inmet_hotspots_e_maquinas_sem_hardcode(self):
        tools = self.make_tools(PropertyService(), MachineService())
        weather_context = tools.get_agent_context("Há alerta INMET ou hotspot em Novo Mundo?")
        self.assertIn("consultar_alertas_e_eventos", weather_context["tools_consultadas"])
        self.assertEqual("Tempestade", weather_context["alertas_eventos"]["weatherAlerts"][0]["eventType"])
        machine_context = tools.get_agent_context("Qual é o status do Trator 01 e do ESP32?")
        self.assertIn("consultar_maquinas_e_esp32", machine_context["tools_consultadas"])
        self.assertEqual("insufficient_data",
                         machine_context["maquinas_esp32"]["items"][0]["engineTemperature"]["status"])

    def test_pergunta_sobre_maior_risco_recebe_detalhe_sem_nome_hardcoded(self):
        context = self.make_tools().get_agent_context("Por que a propriedade de maior risco exige atenção?")
        self.assertEqual(68, context["analise"]["score"])
        self.assertIn("consultar_contexto_da_propriedade", context["tools_consultadas"])

    def test_perguntas_de_continuacao_recebem_analise_atual(self):
        tools = self.make_tools()
        for question in (
                "Qual é o maior risco dessa fazenda?", "Tem incêndio perto?", "Como está o clima?",
                "Posso confiar nessa análise?", "O que merece mais atenção agora?",
        ):
            with self.subTest(question=question):
                context = tools.get_agent_context(question)
                self.assertIn("propriedade", context)
                formatted = tools.format_for_llm(context, question)
                self.assertIn("68/100 — ALTO", formatted)
        trend_context = tools.get_agent_context("Por que o score aumentou?")
        self.assertIn("Histórico insuficiente", tools.format_for_llm(
            trend_context, "Por que o score aumentou?",
        ))

    def test_follow_up_mantem_novo_mundo_em_vez_do_topo_da_carteira(self):
        def two_properties():
            payload = copy.deepcopy(live_payload())
            other = copy.deepcopy(payload["cases"][0])
            other["id"] = "f_santa_helena"
            other["property"].update({
                "fazendaId": "f_santa_helena", "nome": "Fazenda Santa Helena",
                "municipio": "Santa Helena", "estado": "GO",
            })
            other["risk"]["score"] = 99
            other["risk"]["fatores"] = [{
                "fator": "fator_santa_helena", "contribuicao": 100,
                "descricao": "Fator exclusivo de Santa Helena.",
            }]
            payload["cases"].append(other)
            return payload

        agent = AgroRiskAgent(self.make_tools(live_loader=two_properties), session=FakeSession())
        first = agent.ask("Por que Novo Mundo exige atenção?")
        follow_up = agent.ask("E qual é o maior deles?", first["contextPropertyId"])
        self.assertEqual("live_incendio_mt_novo_mundo", follow_up["contextPropertyId"])
        self.assertIn("umidade relativa baixa", follow_up["answer"])
        self.assertNotIn("Fator exclusivo de Santa Helena", follow_up["answer"])

    def test_matching_ignora_caixa_acentos_espacos_e_aceita_parcial_sem_ambiguidade(self):
        tools = self.make_tools()
        for query in ("NOVO MUNDO", "  novo   mundo  ", "novo mund"):
            with self.subTest(query=query):
                context = tools.get_agent_context(f"Por que {query} exige atenção?")
                self.assertEqual("live_incendio_mt_novo_mundo", context["fazenda_id"])

    def test_satelite_real_e_exposto_e_ausencia_fica_explicita(self):
        tools = self.make_tools()
        context = tools.get_agent_context("Qual satélite detectou o foco?")
        formatted = tools.format_for_llm(context)
        self.assertIn("Satélite informado pelo backend: AQUA", formatted)
        answer = AgroRiskAgent(tools, session=FakeSession()).ask("Qual satélite detectou o foco?")["answer"]
        self.assertIn("AQUA", answer)

        def payload_without_satellite():
            payload = copy.deepcopy(live_payload())
            hotspots = payload["cases"][0]["hotspots"]
            for hotspot in [hotspots["nearest"], *hotspots["items"]]:
                for key in ("satellite", "satelite", "satellite_name", "satellite_id"):
                    hotspot.pop(key, None)
            return payload

        tools_without_satellite = self.make_tools(live_loader=payload_without_satellite)
        context_without_satellite = tools_without_satellite.get_agent_context("Qual satélite detectou o foco?")
        formatted_without_satellite = tools_without_satellite.format_for_llm(context_without_satellite)
        self.assertIn("Satélite específico: não disponível no contexto atual.", formatted_without_satellite)
        self.assertNotIn("AQUA", formatted_without_satellite)
        answer_without_satellite = AgroRiskAgent(
            tools_without_satellite, session=FakeSession(),
        ).ask("Qual satélite detectou o foco?")["answer"]
        self.assertIn("não está disponível", answer_without_satellite)
        self.assertNotIn("AQUA", answer_without_satellite)

    def test_guardrail_rejeita_incendio_confirmado_sem_evidencia(self):
        with self.assertRaises(AgentProviderError):
            AgroRiskAgent._validate_grounded_answer(
                "Existe incêndio confirmado na propriedade.", {"fireConfirmed": False},
            )

    def test_guardrail_oculta_estrutura_interna_salvo_pedido_tecnico(self):
        with self.assertRaises(AgentProviderError):
            AgroRiskAgent._validate_grounded_answer(
                "Na raiz do documento, dataCoverage e sourceHealth indicam os dados.", {},
                "Por que esta propriedade exige atenção?",
            )
        AgroRiskAgent._validate_grounded_answer(
            "O campo dataCoverage está disponível no JSON.", {},
            "Mostre detalhes técnicos do JSON e do campo dataCoverage.",
        )

    def test_guardrail_rejeita_satelite_ausente_ou_diferente(self):
        with self.assertRaises(AgentProviderError):
            AgroRiskAgent._validate_grounded_answer(
                "Foco detectado pelo satélite INVENTADO via INPE.", {}, "Qual satélite detectou o foco?",
            )
        with self.assertRaises(AgentProviderError):
            AgroRiskAgent._validate_grounded_answer(
                "Foco detectado pelo satélite INVENTADO via INPE.", {"satelite": "AQUA"},
                "Qual satélite detectou o foco?",
            )
        AgroRiskAgent._validate_grounded_answer(
            "A fonte é o Programa Queimadas do INPE, mas o satélite específico não está disponível.",
            {}, "Qual satélite detectou o foco?",
        )

    def test_endpoint_informa_provider_invalido_sem_mock(self):
        old_testing = server.app.config.get("TESTING")
        server.app.config["TESTING"] = True
        try:
            with patch.object(server.agro_risk_agent, "provider", ""):
                response = server.app.test_client().post(
                    "/agent/query", json={"question": "Qual é o status do ESP32?"},
                )
        finally:
            server.app.config["TESTING"] = old_testing
        self.assertEqual(503, response.status_code)
        self.assertEqual("agent_provider_unconfigured", response.get_json()["codigo"])
        self.assertIn("LLM_PROVIDER=ollama", response.get_json()["mensagem"])
        self.assertNotIn("mock", response.get_json()["mensagem"].lower())

    def test_endpoint_retorna_resposta_natural_e_contexto_para_follow_up(self):
        old_testing = server.app.config.get("TESTING")
        server.app.config["TESTING"] = True
        try:
            with patch.object(server.agro_risk_agent, "session", FakeSession()):
                response = server.app.test_client().post(
                    "/agent/query", json={"question": "Por que Novo Mundo exige atenção?"},
                )
                follow_up = server.app.test_client().post("/agent/query", json={
                    "question": "E qual é o maior deles?",
                    "contextPropertyId": "live_incendio_mt_novo_mundo",
                })
        finally:
            server.app.config["TESTING"] = old_testing
        self.assertEqual(200, response.status_code)
        self.assertEqual("Ollama", response.get_json()["provider"])
        self.assertIn("Novo Mundo/MT exige atenção", response.get_json()["answer"])
        self.assertEqual("live_incendio_mt_novo_mundo", response.get_json()["contextPropertyId"])

        self.assertEqual(200, follow_up.status_code)
        self.assertEqual("live_incendio_mt_novo_mundo", follow_up.get_json()["contextPropertyId"])


if __name__ == "__main__":
    unittest.main()
