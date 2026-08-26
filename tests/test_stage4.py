import math
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import server
from integracoes.ibge import IbgeError, ponto_representativo, preparar_localidades
from scripts.sync_regional_locations import executar as executar_sync
from services.regional_snapshot_service import RegionalSnapshotService, hotspot_summary


class IbgeTestCase(unittest.TestCase):
    def setUp(self):
        self.geometria = {"type": "Polygon", "coordinates": [[
            [-57, -16], [-55, -16], [-55, -14], [-57, -14], [-57, -16],
        ]]}

    def test_ponto_representativo_realmente_interno(self):
        ponto = ponto_representativo(self.geometria)
        self.assertTrue(math.isfinite(ponto["latitude"]))
        self.assertAlmostEqual(-15, ponto["latitude"])

    def test_geometria_malformada(self):
        with self.assertRaises(IbgeError): ponto_representativo({"type": "Polygon", "coordinates": []})

    @patch("integracoes.ibge.obter_malhas_municipais")
    @patch("integracoes.ibge.listar_municipios")
    def test_preparo_registra_municipio_sem_malha_sem_inventar_coordenada(self, municipios, malhas):
        municipios.return_value = [
            {"ibgeCode": "1", "municipality": "Com malha", "state": "MT"},
            {"ibgeCode": "2", "municipality": "Sem malha", "state": "MT"},
        ]
        malhas.return_value = {"1": self.geometria}
        resultado = preparar_localidades("MT")
        self.assertEqual(1, len(resultado["locations"])); self.assertEqual("2", resultado["unresolved"][0]["ibgeCode"])

    @patch("scripts.sync_regional_locations.preparar_localidades")
    def test_sync_dry_run_nao_grava(self, preparar):
        preparar.return_value = {"status": "ok", "locations": [{"ibgeCode": "1"}], "unresolved": [], "source": "IBGE"}
        with patch("scripts.sync_regional_locations.upsert_documento") as gravar:
            resumo = executar_sync("MT", dry_run=True)
        gravar.assert_not_called(); self.assertEqual(1, resumo["prepared"])


class SnapshotServiceTestCase(unittest.TestCase):
    def test_hotspot_summary(self):
        dados = {"quantidadePorRaioKm": {"5": {"ultimas48h": 2}}, "quantidadeFocos24hAte50Km": 3,
                 "focoMaisProximo": {"distanciaKm": 4}}
        resumo = hotspot_summary(dados)
        self.assertEqual(2, resumo["count5km"]); self.assertEqual(4, resumo["nearestDistanceKm"])

    def test_listagem_unica_ordenada_preserva_null_no_final(self):
        service = RegionalSnapshotService(server.firebase, 200)
        itens = [{"riskScore": 80, "riskLevel": "critico"}, {"riskScore": None, "riskLevel": "dados_insuficientes"}]
        with patch("services.regional_snapshot_service.consultar_documentos", return_value=itens):
            resultado = service.listar("MT", "incendio", 20)
        self.assertEqual(80, resultado[0]["riskScore"]); self.assertIsNone(resultado[-1]["riskScore"])


class FrontendContractTestCase(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        server.app.config["CORS_ALLOWED_ORIGINS"] = ("http://localhost:3000",)
        self.client = server.app.test_client()

    def test_health_independe_firebase_e_contrato_header(self):
        resposta = self.client.get("/health")
        self.assertEqual(200, resposta.status_code); self.assertEqual("1", resposta.headers["X-API-Contract-Version"])

    def test_readiness_sem_credencial(self):
        with patch.dict(server.app.config, {"FIREBASE_KEY_PATH": "arquivo-que-nao-existe.json"}):
            self.assertEqual(503, self.client.get("/ready").status_code)

    def test_cors_somente_origem_permitida(self):
        permitido = self.client.get("/health", headers={"Origin": "http://localhost:3000"})
        negado = self.client.get("/health", headers={"Origin": "https://nao-permitido.example"})
        self.assertEqual("http://localhost:3000", permitido.headers.get("Access-Control-Allow-Origin"))
        self.assertIsNone(negado.headers.get("Access-Control-Allow-Origin"))

    def test_listagem_fazendas_e_telemetria_tem_contrato_para_frontend(self):
        with patch.object(server.propriedades, "listar", return_value=[]):
            corpo = self.client.get("/fazendas").get_json()
            self.assertIsInstance(corpo["fazendas"], list)
        maquina = {"maquinaId": "m1", "sensoresConfigurados": [{"sensorId": "temperature", "unit": "celsius"}]}
        leitura = {"dataHora": datetime.now(timezone.utc), "measurements": {"temperature": 20}}
        with patch.object(server.maquinas, "obter", return_value=maquina), patch.object(server.telemetria, "historico", return_value=[leitura]):
            serie = self.client.get("/fazendas/f1/maquinas/m1/telemetria").get_json()["series"][0]
        self.assertIn("T", serie["timestamp"]); self.assertEqual("celsius", serie["unit"])

    def test_ranking_snapshot_nao_calcula_fontes(self):
        item = {"territory": {"ibgeCode": "1", "municipality": "A"}, "coordinates": {"latitude": -15, "longitude": -56},
                "riskScore": 80, "riskLevel": "critico", "calculatedAt": datetime.now(timezone.utc)}
        with patch.object(server.regional_snapshots, "listar", return_value=[item]), patch("server._fontes") as fontes:
            resposta = self.client.get("/regional/risco?uf=MT&riskType=incendio&limit=20")
        self.assertEqual(200, resposta.status_code); fontes.assert_not_called()
        self.assertIn("items", resposta.get_json()); self.assertIn("stale", resposta.get_json()["items"][0])

    def test_ranking_limite_staleness_e_firestore_indisponivel(self):
        antigo = {"territory": {"ibgeCode": "1"}, "riskScore": None,
                  "calculatedAt": datetime.now(timezone.utc)-timedelta(days=1)}
        with patch.object(server.regional_snapshots, "listar", return_value=[antigo]):
            self.assertTrue(self.client.get("/regional/risco?uf=MT&limit=20").get_json()["items"][0]["stale"])
        self.assertEqual(400, self.client.get("/regional/risco?uf=MT&limit=9999").status_code)
        with patch.object(server.regional_snapshots, "listar", side_effect=RuntimeError("offline")):
            self.assertEqual(503, self.client.get("/regional/risco?uf=MT").status_code)

    def test_detalhe_historico_mapa_e_municipio_desconhecido(self):
        agora = datetime.now(timezone.utc)
        item = {"territory": {"ibgeCode": "1", "municipality": "A"}, "coordinates": {"latitude": -15, "longitude": -56},
                "riskScore": 80, "riskLevel": "critico", "calculatedAt": agora}
        with patch.object(server.regional_snapshots, "detalhe", return_value=item), \
             patch.object(server.regional_snapshots, "historico", return_value=[item, {**item, "riskScore": 70, "calculatedAt": agora-timedelta(hours=1)}]):
            self.assertEqual(200, self.client.get("/regional/risco/1").status_code)
            self.assertIn("trend", self.client.get("/regional/risco/1/historico").get_json())
        with patch.object(server.regional_snapshots, "listar", return_value=[item]):
            ponto = self.client.get("/regional/map?uf=MT").get_json()["points"][0]
            self.assertEqual({"id", "municipality", "lat", "lon", "riskLevel", "riskScore", "type"}, set(ponto))
        with patch.object(server.regional_snapshots, "detalhe", return_value=None):
            self.assertEqual(404, self.client.get("/regional/risco/9999999").status_code)

    def test_openapi_existe_e_nao_declara_probability(self):
        texto = Path("openapi.yaml").read_text(encoding="utf-8")
        self.assertIn("openapi: 3.0.3", texto); self.assertNotIn("probability:", texto)


if __name__ == "__main__": unittest.main()
