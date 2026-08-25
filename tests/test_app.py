import unittest
from unittest.mock import patch

import server
from integracoes.open_meteo import calcular_metricas_terreno
from services.firestore_service import salvar_documento
from services.risco_service import calcular_riscos


FONTE_OK = {"status": "ok", "consultadoEm": "2026-01-01T00:00:00+00:00", "dados": {}}


class RotasTestCase(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.cliente = server.app.test_client()

    def test_home_continua_online(self):
        resposta = self.cliente.get("/")
        self.assertEqual(200, resposta.status_code)
        self.assertEqual("online", resposta.get_json()["status"])

    def test_risco_exige_coordenadas(self):
        resposta = self.cliente.get("/risco")
        self.assertEqual(400, resposta.status_code)

    def test_risco_valida_faixas(self):
        resposta = self.cliente.get("/risco?lat=91&lon=0")
        self.assertEqual(400, resposta.status_code)

    @patch("server.salvar_documento", side_effect=RuntimeError("offline"))
    @patch("server.consultar_suscetibilidade", return_value=FONTE_OK)
    @patch("server.consultar_terreno", return_value=FONTE_OK)
    @patch("server.consultar_hidrologia", return_value=FONTE_OK)
    @patch("server.consultar_clima", return_value=FONTE_OK)
    @patch("server.consultar_queimadas", return_value=FONTE_OK)
    @patch("server.consultar_inmet", return_value=FONTE_OK)
    def test_falhas_nao_impedem_resposta(self, *_mocks):
        resposta = self.cliente.get("/risco?lat=-17.79&lon=-50.92")
        corpo = resposta.get_json()
        self.assertEqual(200, resposta.status_code)
        self.assertEqual("ok", corpo["status"])
        self.assertEqual("erro", corpo["persistencia"]["status"])
        self.assertIsNone(corpo["riscos"]["geral"]["score"])

    def test_dados_mantem_validacao(self):
        resposta = self.cliente.post("/dados", json={"temperatura": 20})
        self.assertEqual(400, resposta.status_code)

    @patch("server.salvar_no_firebase", return_value={"name": "documents/leituras_sensores/abc"})
    def test_dados_validos_preservam_fluxo_esp32(self, salvar):
        resposta = self.cliente.post("/dados", json={
            "temperatura": 27.5, "umidade": 63,
            "fazendaId": "fazenda_01", "maquinaId": "trator_01",
        })
        self.assertEqual(200, resposta.status_code)
        self.assertEqual("abc", resposta.get_json()["documentoId"])
        salvar.assert_called_once_with(27.5, 63.0, "fazenda_01", "trator_01")

    def test_falhas_inpe_e_inmet_nao_quebram_risco(self):
        erro = {"status": "erro_api", "dados": {}, "mensagem": "offline"}
        with (
            patch("server.consultar_clima", return_value=FONTE_OK),
            patch("server.consultar_hidrologia", return_value=FONTE_OK),
            patch("server.consultar_terreno", return_value=FONTE_OK),
            patch("server.consultar_suscetibilidade", return_value=FONTE_OK),
            patch("server.consultar_queimadas", return_value=erro),
            patch("server.consultar_inmet", return_value=erro),
            patch("server.salvar_documento", side_effect=RuntimeError("offline")),
        ):
            resposta = self.cliente.get("/risco?lat=-17.79&lon=-50.92")
        self.assertEqual(200, resposta.status_code)
        self.assertEqual("erro_api", resposta.get_json()["fontes"]["queimadas"]["status"])
        self.assertEqual("erro_api", resposta.get_json()["fontes"]["inmet"]["status"])


class CalculosTestCase(unittest.TestCase):
    def _fontes_incendio(self, foco):
        return {
            "clima": {"status": "ok", "dados": {
                "temperaturaAtualC": 35, "umidadeRelativaAtualPct": 25,
                "rajadaMax72hKmh": 45, "chuvaAcumulada72hMm": 0,
                "umidadeSoloMin72hM3M3": 0.09, "temperaturaMinima72hC": 18,
            }},
            "queimadas": {"status": "ok", "dados": {
                "quantidadeFocos24hAte50Km": 1 if foco else 0,
                "focoMaisProximo": {"distanciaKm": 3} if foco else None,
            }},
        }

    def test_declividade_com_grade_simulada(self):
        metricas = calcular_metricas_terreno([
            90, 100, 110,
            90, 100, 110,
            90, 100, 110,
        ], espacamento_metros=200)
        self.assertEqual(100, metricas["altitudeMetros"])
        self.assertEqual(20, metricas["variacaoAltitudeMetros"])
        self.assertAlmostEqual(5, metricas["declividadePct"])
        self.assertAlmostEqual(2.86, metricas["declividadeGraus"], places=2)

    def test_foco_proximo_aumenta_score_incendio(self):
        sem_foco = calcular_riscos(self._fontes_incendio(False))["incendio"]["score"]
        com_foco = calcular_riscos(self._fontes_incendio(True))["incendio"]["score"]
        self.assertGreater(com_foco, sem_foco)

    def test_ausencia_foco_nao_gera_risco_zero(self):
        risco = calcular_riscos(self._fontes_incendio(False))["incendio"]
        self.assertGreater(risco["score"], 0)
        self.assertFalse(risco["focoCalorObservadoProximo"])

    def test_dados_ausentes_nao_viram_zero(self):
        risco = calcular_riscos({})["incendio"]
        self.assertIsNone(risco["score"])
        self.assertEqual("dados_insuficientes", risco["nivel"])

    def test_divergencia_inmet_e_registrada(self):
        fontes = self._fontes_incendio(False)
        fontes["inmet"] = {"status": "ok", "dados": {
            "observacaoRecente": True,
            "temperaturaObservadaC": 20,
            "umidadeObservadaPct": 70,
        }}
        riscos = calcular_riscos(fontes)
        variaveis = {item["variavel"] for item in riscos["divergenciasMeteorologicas"]}
        self.assertEqual({"temperatura", "umidade_relativa"}, variaveis)

    def test_terreno_operacional_com_dados(self):
        riscos = calcular_riscos({"terreno": {"status": "ok", "dados": {
            "declividadePct": 20, "variacaoAltitudeMetros": 55, "rugosidade": 18,
        }}})
        self.assertIsNotNone(riscos["terrenoOperacional"]["score"])


class FirestoreRestTestCase(unittest.TestCase):
    @patch("services.firestore_service.requests.post")
    def test_firestore_permanece_rest(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"name": "documents/colecao/id"}
        salvar_documento("https://firestore.googleapis.com/v1/documents", lambda: "token", "colecao", {"valor": 1})
        post.assert_called_once()
        self.assertEqual(
            "https://firestore.googleapis.com/v1/documents/colecao",
            post.call_args.args[0],
        )


if __name__ == "__main__":
    unittest.main()
