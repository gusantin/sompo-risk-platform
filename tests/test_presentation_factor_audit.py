import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from services.environmental_context import presentation_risk_factors
from services.presentation_portfolio_service import PresentationPortfolio
from services.sompo_agro_agent.presentation import portfolio_context


class PresentationFactorAuditTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        self.case = {"id": "demo_portfolio_confresa", "property": {"clientName": "Cliente B"},
            "risk": {"nivel": "alto", "score": 65, "fatores": [
                {"fator": "ausencia_chuva", "contribuicao": 100, "descricao": "Pouca chuva prevista mantém condições secas."},
                {"fator": "umidade_solo_baixa", "contribuicao": 100, "descricao": "Baixa umidade superficial do solo indica secura."}]},
            "rawSources": {"clima": {"status": "ok", "cache": True, "atribuicao": "Open-Meteo fixture", "consultadoEm": self.now.isoformat(),
                "dados": {"chuvaAcumulada72hMm": 0.0, "umidadeSoloMin72hM3M3": .064, "umidadeSoloAtualM3M3": .105}}},
            "sourceHealth": {"clima": {"attribution": "Open-Meteo fixture", "consultedAt": self.now.isoformat()}},
            "provenance": {"identity": "demo", "environmental": {"origin": "real", "acquiredAt": self.now.isoformat()}}}

    def forecast(self):
        self.case["rawSources"]["clima"]["dados"]["environmentalForecast"] = {"observedAt": self.now.isoformat(), "windows": {"72": {
            "precipitationSum": 0.0, "forecastFor": {"start": self.now.isoformat(), "end": (self.now + timedelta(hours=72)).isoformat()}}}}

    def test_legacy_zero_is_not_proof_of_a_valid_forecast_window(self):
        original = deepcopy(self.case)
        result = presentation_risk_factors(self.case, self.now)
        self.assertEqual([f["fator"] for f in result], ["umidade_solo_baixa"])
        self.assertEqual(self.case, original)
        self.assertIn("0,064 m³/m³", result[0]["descricao"])
        self.assertNotIn("0,105", result[0]["descricao"])
        self.assertIn("Open-Meteo fixture", result[0]["descricao"])
        self.assertIn("real em cache", result[0]["descricao"])
        self.assertEqual(result[0]["evidence"]["fetchedAt"], self.now.isoformat())

    def test_valid_scored_forecast_window_can_be_explained_explicitly(self):
        self.forecast()
        result = presentation_risk_factors(self.case, self.now)
        self.assertIn("janela de 72h usada pelo motor: 0 mm", result[0]["descricao"])
        self.assertEqual(result[0]["evidence"]["field"], "chuvaAcumulada72hMm")

    def test_unscored_or_expired_forecast_does_not_become_a_cause(self):
        self.forecast()
        forecast = self.case["rawSources"]["clima"]["dados"]["environmentalForecast"]
        forecast["observedAt"] = (self.now + timedelta(minutes=15)).isoformat()
        self.assertEqual(len(presentation_risk_factors(self.case, self.now)), 1)
        self.forecast()
        self.assertEqual(len(presentation_risk_factors(self.case, self.now + timedelta(hours=73))), 1)

    def test_absent_soil_or_nonpositive_contribution_is_not_inferred(self):
        del self.case["rawSources"]["clima"]["dados"]["umidadeSoloMin72hM3M3"]
        self.assertEqual(presentation_risk_factors(self.case, self.now), [])
        self.case["rawSources"]["clima"]["dados"]["umidadeSoloMin72hM3M3"] = .064
        self.case["risk"]["fatores"][1]["contribuicao"] = 0
        self.assertEqual(presentation_risk_factors(self.case, self.now), [])

    def test_canonical_snapshot_and_copilot_share_audited_factors(self):
        snapshot = PresentationPortfolio(None, {}).snapshot({"cases": [self.case]}, self.now)
        case = snapshot["cases"][0]
        self.assertEqual(case["risk"], self.case["risk"])
        self.assertEqual(case["presentationFactors"], portfolio_context(snapshot)["items"][0]["factors"])
        self.assertEqual([f["fator"] for f in case["presentationFactors"]], ["umidade_solo_baixa"])


if __name__ == "__main__":
    unittest.main()
