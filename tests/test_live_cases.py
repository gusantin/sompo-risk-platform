import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from integracoes.inmet import _campos_aviso, _normalizar_texto
from integracoes.inpe_queimadas import contextualizar_focos
from services.live_case_service import LiveCaseService
from services.risco_service import calcular_riscos


def clima(latitude, _longitude):
    minima = 1 if latitude < -20 else 14
    return {"status": "ok", "consultadoEm": "2026-08-25T12:00:00+00:00", "cache": False,
            "atribuicao": "Open-Meteo Forecast API", "dados": {
                "temperaturaAtualC": 34 if latitude > -20 else 5,
                "umidadeRelativaAtualPct": 20, "precipitacaoAtualMm": 0,
                "chuvaAcumulada72hMm": 0, "rajadaMax72hKmh": 40,
                "umidadeSoloMin72hM3M3": 0.08, "temperaturaMinima72hC": minima,
            }}


def inmet(_latitude, _longitude):
    return {"status": "sem_observacao_recente", "consultadoEm": "2026-08-25T12:00:00+00:00",
            "cache": False, "atribuicao": "INMET WIS2 / OGC API", "dados": {}}


class LiveCaseServiceTests(unittest.TestCase):
    def test_parser_preserva_tipo_e_granizo_explicitos_do_inmet(self):
        campos = _campos_aviso(
            "<table><tr><th>Evento</th><td>Tempestade</td></tr>"
            "<tr><th>Descrição</th><td>Ventos intensos e queda de granizo.</td></tr></table>"
        )
        self.assertEqual("Tempestade", campos["evento"])
        self.assertIn("granizo", _normalizar_texto(campos["descricao"]))

    def test_contextualiza_focos_no_contrato_do_motor(self):
        focos = [{"latitude": -12.0, "longitude": -55.0, "detectedAt": "2026-08-25T11:00:00+00:00",
                  "idadeHoras": 1, "source": "INPE Programa Queimadas", "uf": "MT"}]
        resultado = contextualizar_focos(-12.0, -55.0, focos, "2026-08-25T12:00:00+00:00")
        self.assertEqual(1, resultado["dados"]["quantidadeFocos48hAte50Km"])
        self.assertEqual(0, resultado["dados"]["focoMaisProximo"]["distanciaKm"])
        self.assertEqual(48, resultado["dados"]["lookbackHours"])

    def test_descobre_incendio_e_geada_sem_alterar_motor(self):
        focos = [{"id": "f1", "latitude": -12.0, "longitude": -55.0,
                  "detectedAt": "2026-08-25T11:00:00+00:00", "dataHoraUtc": "2026-08-25T11:00:00+00:00",
                  "idadeHoras": 1, "ageHours": 1, "source": "INPE Programa Queimadas",
                  "municipio": "Local INPE", "uf": "MT"}]
        listar = lambda _ufs, _limit: {"status": "ok", "consultadoEm": "2026-08-25T12:00:00+00:00",
                                      "dados": {"items": focos, "lookbackHours": 48}}
        preparar = lambda codigo: {"ibgeCode": codigo, "municipality": "Local IBGE", "state": "PR",
                                   "latitude": -25.0, "longitude": -51.0,
                                   "coordinateSource": "IBGE Malhas v3", "method": "polygon_centroid_inside"}
        service = LiveCaseService(listar, contextualizar_focos, preparar, clima, inmet, calcular_riscos, ("MT",), 2)
        payload = service.discover(frost_codes=("1",))
        self.assertEqual(["incendio", "geada"], [case["riskType"] for case in payload["cases"]])
        self.assertTrue(all(case["environmentalDataReal"] for case in payload["cases"]))
        self.assertTrue(all(case["property"]["demoData"] for case in payload["cases"]))
        self.assertGreater(payload["cases"][0]["risk"]["score"], 0)
        self.assertGreater(payload["cases"][1]["risk"]["score"], 0)

    def test_endpoint_marca_snapshot_stale(self):
        payload = {"generatedAt": "2020-01-01T00:00:00+00:00", "cases": [], "status": "ok"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.json"
            LiveCaseService.save_snapshot(payload, path)
            old_testing = server.app.config.get("TESTING")
            server.app.config.update(TESTING=True, LIVE_CASE_SNAPSHOT_PATH=str(path), LIVE_CASE_MAX_AGE_SECONDS=60)
            try:
                with patch.object(server, "consultar_avisos_inmet", return_value={
                    "status": "ok", "atribuicao": "INMET Avisos Meteorológicos (RSS)",
                    "consultadoEm": "2026-08-25T12:00:00+00:00", "dados": {"items": [{
                        "id": "1", "eventType": "Tempestade", "hailExplicit": True,
                    }]},
                }):
                    response = server.app.test_client().get("/showcase/live-cases")
            finally:
                server.app.config["TESTING"] = old_testing
            self.assertEqual(200, response.status_code)
            self.assertTrue(response.get_json()["stale"])
            self.assertTrue(response.get_json()["weatherAlerts"]["items"][0]["hailExplicit"])

    def test_endpoint_indisponivel_sem_snapshot(self):
        old_testing = server.app.config.get("TESTING")
        with patch.object(LiveCaseService, "load_snapshot", side_effect=FileNotFoundError):
            server.app.config["TESTING"] = True
            try:
                response = server.app.test_client().get("/showcase/live-cases")
            finally:
                server.app.config["TESTING"] = old_testing
        self.assertEqual(503, response.status_code)
        self.assertEqual("live_cases_unavailable", response.get_json()["codigo"])


if __name__ == "__main__":
    unittest.main()
