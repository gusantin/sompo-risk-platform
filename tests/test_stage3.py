import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import server

from integracoes.geoespacial import ponto_no_geojson
from services.firestore_service import consultar_documentos
from services.machine_risk_service import calcular_risco_maquina
from services.maquina_service import ValidacaoMaquinaError, validar_maquina
from services.operational_risk_service import calcular_risco_operacional
from services.regional_risk_service import RegionalRiskService
from services.telemetria_service import TelemetriaService
from services.tendencia_service import metricas_tendencia


class MaquinaTestCase(unittest.TestCase):
    def _valida(self):
        return {"nome": "Trator 01", "tipo": "trator", "status": "ativo", "possuiGps": True,
                "latitude": -15.6, "longitude": -56.1, "lastLocationAt": "2026-08-25T10:00:00-03:00",
                "sensoresConfigurados": [{"sensorId": "temp_motor", "type": "temperature",
                    "scope": "machine_component", "target": "engine_bay", "unit": "celsius",
                    "thresholds": {"warning": 70, "high": 85, "critical": 100}}], "metadata": {}}

    def test_maquina_e_sensor_validos(self):
        self.assertEqual("machine_component", validar_maquina(self._valida())["sensoresConfigurados"][0]["scope"])

    def test_gps_invalido(self):
        dados = self._valida(); dados["latitude"] = float("nan")
        with self.assertRaises(ValidacaoMaquinaError): validar_maquina(dados)

    def test_scope_unidade_e_payload_desconhecido_invalidos(self):
        for campo, valor in (("scope", "motor_magico"), ("unit", "graus_genericos")):
            dados = self._valida(); dados["sensoresConfigurados"][0][campo] = valor
            with self.subTest(campo=campo), self.assertRaises(ValidacaoMaquinaError): validar_maquina(dados)
        dados = self._valida(); dados["campoSurpresa"] = True
        with self.assertRaises(ValidacaoMaquinaError): validar_maquina(dados)


class MaquinaEndpointTestCase(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True; self.client = server.app.test_client()

    def test_criacao_listagem_atualizacao_e_fazenda_inexistente(self):
        payload = {"maquinaId": "t1", "nome": "T1", "tipo": "trator", "status": "ativo"}
        with patch.object(server.maquinas, "criar", return_value={"maquinaId": "t1"}):
            self.assertEqual(201, self.client.post("/fazendas/f1/maquinas", json=payload).status_code)
        with patch.object(server.maquinas, "listar", return_value=[{"maquinaId": "t1"}]):
            self.assertEqual(1, len(self.client.get("/fazendas/f1/maquinas").get_json()["maquinas"]))
        with patch.object(server.maquinas, "atualizar", return_value={"maquinaId": "t1", "status": "parada"}):
            self.assertEqual(200, self.client.patch("/fazendas/f1/maquinas/t1", json={"status": "parada"}).status_code)
        with patch.object(server.maquinas, "criar", return_value=None):
            self.assertEqual(404, self.client.post("/fazendas/f1/maquinas", json=payload).status_code)

class FirestoreQueryTestCase(unittest.TestCase):
    @patch("services.firestore_service.requests.post")
    def test_structured_query_ordenada_e_limitada(self, post):
        post.return_value.status_code = 200; post.return_value.json.return_value = []
        consultar_documentos("https://x/databases/(default)/documents", lambda: "token", "leituras_sensores",
            {"fazendaId": "f1", "maquinaId": "m1"}, "dataHora", "DESCENDING", 5)
        query = post.call_args.kwargs["json"]["structuredQuery"]
        self.assertEqual(5, query["limit"]); self.assertEqual("DESCENDING", query["orderBy"][0]["direction"])
        self.assertEqual("AND", query["where"]["compositeFilter"]["op"])


class TelemetriaTestCase(unittest.TestCase):
    def test_estados_temporais(self):
        agora = datetime.now(timezone.utc)
        self.assertEqual("missing", TelemetriaService.classificar(None, 60, agora)["status"])
        self.assertEqual("fresh", TelemetriaService.classificar({"dataHora": agora, "measurements": {"x": 1}}, 60, agora)["status"])
        self.assertEqual("stale", TelemetriaService.classificar({"dataHora": agora-timedelta(seconds=61), "measurements": {"x": 1}}, 60, agora)["status"])
        self.assertEqual("invalid", TelemetriaService.classificar({"dataHora": agora, "measurements": {"x": float("nan")}}, 60, agora)["status"])
        self.assertEqual("invalid", TelemetriaService.classificar({"dataHora": "sem-data", "measurements": {"x": 1}}, 60, agora)["status"])


class MachineRiskTestCase(unittest.TestCase):
    def test_sem_threshold_ou_scope_desconhecido_e_insuficiente(self):
        maquina = {"sensoresConfigurados": [{"sensorId": "temperature", "scope": "unknown", "type": "temperature"}]}
        self.assertEqual("insufficient_data", calcular_risco_maquina(maquina, [{"measurements": {"temperature": 90}}])["status"])

    def test_threshold_configurado_e_tendencia(self):
        maquina = {"sensoresConfigurados": [{"sensorId": "temp_motor", "scope": "machine_component",
            "type": "temperature", "unit": "celsius", "thresholds": {"warning": 60, "high": 70, "critical": 90}}]}
        leituras = [{"measurements": {"temp_motor": x}} for x in (55, 62, 75)]
        risco = calcular_risco_maquina(maquina, list(reversed(leituras)))
        self.assertEqual("high", risco["level"]); self.assertEqual("rising", risco["evidence"][0]["trend"]["direction"])


class TendenciaOperacionalTestCase(unittest.TestCase):
    def test_tendencias(self):
        self.assertEqual("rising", metricas_tendencia([10, 20, 30])["direction"])
        self.assertEqual("falling", metricas_tendencia([30, 20, 10])["direction"])
        self.assertEqual("stable", metricas_tendencia([10, 10.1, 10.2])["direction"])
        self.assertEqual("insufficient_data", metricas_tendencia([10])["status"])

    def test_regras_operacionais(self):
        ambiental = {"incendio": {"nivel": "critico"}}
        insuficiente = {"level": "unknown"}; critico = {"level": "critical"}
        self.assertEqual("high", calcular_risco_operacional(ambiental, insuficiente)["level"])
        self.assertEqual("critical", calcular_risco_operacional(ambiental, critico, True, True)["level"])
        self.assertEqual("high", calcular_risco_operacional({"incendio": {"nivel": "baixo"}}, critico)["level"])


class GeoespacialTestCase(unittest.TestCase):
    def test_polygon_e_multipolygon(self):
        quadrado = [[[-57, -16], [-55, -16], [-55, -14], [-57, -14], [-57, -16]]]
        self.assertTrue(ponto_no_geojson(-15, -56, {"type": "Polygon", "coordinates": quadrado}))
        self.assertFalse(ponto_no_geojson(-10, -56, {"type": "MultiPolygon", "coordinates": [quadrado]}))


class RegionalTestCase(unittest.TestCase):
    def test_ranking_limite_cobertura_e_falha_parcial(self):
        def analisar(lat, _lon):
            if lat == 0: raise RuntimeError("offline")
            return {"riscos": {"incendio": {"score": lat, "nivel": "alto", "confianca": "media", "fatores": ["seca"]}},
                    "dataCoverage": {"weatherAvailable": True}, "hotspotInfo": {}}
        service = RegionalRiskService(analisar, max_concurrency=2, cache_ttl=1)
        locais = [{"state": "MT", "municipality": "A", "latitude": 80, "longitude": 0},
                  {"state": "MT", "municipality": "B", "latitude": 60, "longitude": 0},
                  {"state": "MT", "municipality": "C", "latitude": 0, "longitude": 0}]
        itens = service.analisar_localidades(locais)["items"]
        self.assertEqual(80, itens[0]["riskScore"]); self.assertIsNone(itens[-1]["riskScore"])
        self.assertEqual(1, len(service.ranking(itens, 1)))


if __name__ == "__main__": unittest.main()
