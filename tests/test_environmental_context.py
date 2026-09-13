import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from services.environmental_context import WMO, aggregate_forecast, build_environmental_context, cached_context
from services.notification_messages import message_for
from services.sompo_agro_agent.agent import AgroRiskAgent
from services.sompo_agro_agent.presentation import portfolio_answer, portfolio_context
from integracoes.inmet import parse_cap, avisos_aplicaveis


class EnvironmentalContextTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc).replace(minute=15, second=0, microsecond=0)
        start = self.now.replace(minute=0)
        self.raw = {"timezone": "UTC", "current": {"time": self.now.isoformat(), "temperature_2m": 29.6,
            "relative_humidity_2m": 48, "precipitation": 0, "wind_speed_10m": 8.1, "wind_gusts_10m": 12, "weather_code": 2},
            "hourly": {"time": [(start + timedelta(hours=h)).isoformat() for h in range(75)]}}
        for key, value in {"temperature_2m": 30, "relative_humidity_2m": 31, "precipitation_probability": 68,
            "precipitation": .3, "rain": .2, "showers": .1, "wind_speed_10m": 18, "wind_gusts_10m": 38, "weather_code": 80}.items():
            self.raw["hourly"][key] = [value] * 75
        self.source = {"status": "ok", "atribuicao": "Open-Meteo fixture", "consultadoEm": self.now.isoformat(),
                       "dados": {"environmentalForecast": aggregate_forecast(self.raw)}}

    def context(self, sources=None):
        return build_environmental_context(sources or {"clima": self.source}, {"demoData": True}, cached=True, now=self.now)

    def test_complete_future_windows_not_midnight_or_past(self):
        data = aggregate_forecast(self.raw)
        for hours in (6, 12, 24, 72):
            window = data["windows"][str(hours)]
            self.assertEqual(window["precipitationSum"], round(hours * .3, 3))
            self.assertEqual(window["precipitationProbabilityMax"], 68)
            self.assertEqual(window["gustMax"], 38)
            self.assertEqual(window["humidityMin"], 31)
            self.assertGreater(datetime.fromisoformat(window["forecastFor"]["start"]), self.now)
        self.assertEqual(data["observedAt"], self.now.isoformat())

    def test_missing_or_invalid_values_are_not_zero(self):
        self.raw["hourly"]["precipitation"][5] = None
        self.raw["hourly"]["precipitation_probability"][2] = 120
        data = aggregate_forecast(self.raw)
        self.assertIsNone(data["windows"]["24"]["precipitationSum"])
        self.assertIsNone(data["windows"]["24"]["precipitationProbabilityMax"])
        self.assertIsNone(data["windows"]["72"]["dryForecast"])
        self.raw["hourly"]["time"] = self.raw["hourly"]["time"][:4]
        self.assertIsNone(aggregate_forecast(self.raw)["windows"]["6"]["gustMax"])

    def test_timezone_and_weather_code_semantics(self):
        self.raw["timezone"] = "America/Sao_Paulo"
        self.raw["current"]["time"] = "2026-09-12T10:15"
        self.assertEqual(aggregate_forecast(self.raw)["observedAt"], "2026-09-12T13:15:00+00:00")
        self.assertEqual(WMO[0], "Céu limpo")
        self.assertEqual(WMO[2], "Parcialmente nublado")
        self.assertEqual(WMO[95], "Tempestade")
        self.assertNotIn("granizo", WMO[95])
        self.assertIn("granizo", WMO[96])
        self.assertIsNone(WMO.get(999))

    def test_provider_independence_and_secondary_products(self):
        fire = {"status": "ok", "atribuicao": "INPE fixture", "consultadoEm": self.now.isoformat(),
                "dados": {"focoMaisProximo": {"distanciaKm": 15.36, "dataHoraUtc": self.now.isoformat()}}}
        context = self.context({"clima": {"status": "erro_api"}, "queimadas": fire})
        self.assertEqual(context["fire"]["nearestDistance"]["value"], 15.36)
        self.assertIsNone(context["forecast"]["24"]["precipitationSum"]["value"])
        self.assertIsNone(context["fire"]["products"]["forecastFireRisk3d"]["value"])
        context = self.context({"clima": self.source, "queimadas": {"status": "erro_api"}, "avisos_contexto": {"status": "parcial", "dados": {"items": []}}})
        self.assertEqual(context["forecast"]["24"]["precipitationSum"]["value"], 7.2)
        self.assertIsNone(context["warnings"]["value"])

    def test_cache_stale_original_timestamps_and_model_observation(self):
        context = self.context()
        original = deepcopy(context)
        old = cached_context(context, self.now + timedelta(hours=8))
        self.assertEqual(old["observation"]["temperature"]["freshness"], "stale")
        self.assertEqual(old["forecast"]["6"]["gustMax"]["freshness"], "stale")
        self.assertEqual(context, original)
        self.assertEqual(old["observation"]["temperature"]["observedAt"], self.now.isoformat())
        self.assertEqual(context["observation"]["temperature"]["kind"], "model_current")

    def test_cap_applicability_expiration_and_possibility(self):
        onset = (self.now - timedelta(hours=1)).isoformat()
        expires = (self.now + timedelta(hours=2)).isoformat()
        cap = f'''<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><status>Actual</status><msgType>Alert</msgType><identifier>fixture</identifier><info><language>pt-BR</language><event>Tempestade</event><severity>Severe</severity><onset>{onset}</onset><expires>{expires}</expires><description>Possibilidade de granizo.</description><area><polygon>-16,-56 -16,-54 -14,-54 -14,-56 -16,-56</polygon></area></info></alert>'''
        items = parse_cap(cap)
        matched = avisos_aplicaveis(items, {"latitude": -15, "longitude": -55}, self.now)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["description"], "Possibilidade de granizo.")
        self.assertEqual(matched[0]["temporalState"], "active")
        self.assertEqual(avisos_aplicaveis(items, {"latitude": 0, "longitude": 0}, self.now), [])
        self.assertEqual(avisos_aplicaveis(items, {"latitude": -15, "longitude": -55}, self.now + timedelta(hours=3)), [])
        with self.assertRaises(ValueError):
            parse_cap("<html/>")

    def test_telegram_context_is_not_new_causal_evidence(self):
        alert = {"severity": "high", "type": "environmental_fire_risk", "riskType": "incendio", "propertyName": "Fixture",
                 "environmentalContext": self.context(), "factors": [{"descricao": "Fator oficial do motor", "contribuicao": 5}]}
        text = message_for(alert, "alert")
        self.assertIn("Fator oficial do motor", text)
        self.assertIn("Probabilidade máxima de precipitação: 68%", text)
        self.assertIn("condição adicional", text)
        self.assertNotIn("vai chover", text.lower())
        self.assertNotIn("INPE", text)

    def test_copilot_environmental_questions_are_deterministic(self):
        agent = AgroRiskAgent(Mock(), session=Mock())
        context = {"propriedade": {"environmentalContext": self.context()}}
        for q in ("Vai chover nessa fazenda?", "Como estão as condições ambientais?", "Existe previsão de pancadas de chuva?", "Qual a umidade?", "Tem aviso de tempestade?", "Existe risco de fogo nos próximos dias?"):
            answer = agent.answer(context, q)["resposta"]
            if "tempestade" in q:
                self.assertIn("cobertura indisponível", answer)
            elif "umidade" in q:
                self.assertIn("48%", answer)
                self.assertIn("real em cache", answer)
            elif "próximos dias" in q:
                self.assertIn("Risco INPE", answer)
                self.assertIn("não disponíveis", answer)
            else:
                self.assertIn("68%", answer)
                self.assertIn("real em cache", answer)
            self.assertNotIn("vai chover", answer.lower())
        agent.session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
