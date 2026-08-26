import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import server
from services.propriedade_service import ValidacaoPropriedadeError, validar_propriedade
from services.risk_context_service import RiskContextService


PROPRIEDADE = {
    "id": "fazenda_01", "nome": "Fazenda Teste", "municipio": "Cuiabá",
    "estado": "MT", "latitude": -15.6, "longitude": -56.1,
    "areaHectares": 100, "atividadePrincipal": "agricultura",
    "culturas": [{"nome": "soja"}],
}


class FirebaseFake:
    firestore_url = "https://firestore.invalid/documents"

    def initialize(self):
        return None

    def obter_token(self):
        return "token"


class ValidacaoTestCase(unittest.TestCase):
    def test_propriedade_valida_e_culturas_extensiveis(self):
        dados = dict(PROPRIEDADE)
        dados.pop("id")
        dados["culturas"] = [{"nome": "cana-de-açúcar", "areaHectares": 40, "estagioSafra": "maturação"}]
        self.assertEqual("cana-de-açúcar", validar_propriedade(dados)["culturas"][0]["nome"])

    def test_propriedade_invalida_rejeita_nan(self):
        dados = dict(PROPRIEDADE)
        dados.pop("id")
        dados["latitude"] = math.nan
        with self.assertRaises(ValidacaoPropriedadeError):
            validar_propriedade(dados)

    def test_culturas_diferentes_sao_preservadas_sem_peso_inventado(self):
        dados = dict(PROPRIEDADE)
        dados.pop("id")
        dados["culturas"] = ["soja", "milho"]
        self.assertEqual([{"nome": "soja"}, {"nome": "milho"}], validar_propriedade(dados)["culturas"])


class DadosEndpointTestCase(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()

    def _post(self, temperatura=20, umidade=50):
        return self.client.post("/dados", json={
            "temperatura": temperatura, "umidade": umidade,
            "fazendaId": "fazenda_01", "maquinaId": "trator_01",
        })

    def test_rejeita_umidade_negativa_e_acima_de_cem(self):
        self.assertEqual(400, self._post(umidade=-1).status_code)
        self.assertEqual(400, self._post(umidade=101).status_code)

    def test_rejeita_nan_e_infinity(self):
        self.assertEqual(400, self._post(temperatura=math.nan).status_code)
        self.assertEqual(400, self._post(temperatura=math.inf).status_code)

    def test_rejeita_conteudo_nao_json(self):
        self.assertEqual(415, self.client.post("/dados", data="x").status_code)

    def test_firebase_indisponivel_retorna_erro_controlado(self):
        with patch("server.salvar_no_firebase", side_effect=RuntimeError("offline")):
            resposta = self._post()
        self.assertEqual(503, resposta.status_code)
        self.assertEqual("persistencia_indisponivel", resposta.get_json()["codigo"])


class RiskContextTestCase(unittest.TestCase):
    def setUp(self):
        self.service = RiskContextService(FirebaseFake(), iot_max_age_minutes=15)
        self.service.maquinas = Mock()
        self.service.telemetria = Mock(wraps=self.service.telemetria)

    def _leitura(self, instante, **extras):
        item = {"fazendaId": "fazenda_01", "maquinaId": "trator_01",
                "temperatura": 70.0, "umidade": 30.0, "dataHora": instante, "origem": "ESP32"}
        item.update(extras)
        return item

    def test_fazenda_sem_esp32(self):
        self.service.maquinas.listar.return_value = []
        self.assertIsNone(self.service.leitura_recente("fazenda_01"))

    def test_leitura_recente_de_maquina_associada(self):
        leitura = self._leitura(datetime.now(timezone.utc))
        self.service.maquinas.listar.return_value = [{"maquinaId": "trator_01", "fazendaId": "fazenda_01"}]
        self.service.telemetria.historico_fazenda.return_value = [leitura]
        self.assertEqual("trator_01", self.service.leitura_recente("fazenda_01")["maquinaId"])

    def test_leitura_expirada_invalida_ou_sem_vinculo_e_ignorada(self):
        casos = [
            self._leitura(datetime.now(timezone.utc) - timedelta(minutes=16)),
            self._leitura(datetime.now(timezone.utc), umidade=-1),
            self._leitura(datetime.now(timezone.utc), maquinaId="outra"),
        ]
        for leitura in casos:
            with self.subTest(leitura=leitura):
                self.service.maquinas.listar.return_value = [{"maquinaId": "trator_01", "fazendaId": "fazenda_01"}]
                self.service.telemetria.historico_fazenda.return_value = [leitura]
                self.assertIsNone(self.service.leitura_recente("fazenda_01"))

    def test_iot_nao_participa_do_score_ambiental(self):
        contexto = self.service.montar(PROPRIEDADE, {}, self._leitura(datetime.now(timezone.utc)))
        self.assertTrue(contexto["iot"]["available"])
        self.assertFalse(contexto["iot"]["participouNoScoreAmbiental"])
        self.assertIn("satellite", contexto)


class FazendaEndpointTestCase(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()

    def test_fazenda_inexistente(self):
        with patch.object(server.propriedades, "obter", return_value=None):
            self.assertEqual(404, self.client.get("/fazendas/inexistente/risco").status_code)

    def test_persistencia_de_analise_com_fontes_parciais(self):
        erro = {"status": "erro_api", "dados": {}}
        fontes = {nome: erro for nome in ("clima", "hidrologia", "terreno", "sgb", "queimadas", "inmet")}
        with (
            patch.object(server.propriedades, "obter", return_value=PROPRIEDADE),
            patch("server._fontes", return_value=fontes),
            patch.object(server.maquinas, "listar", return_value=[]),
            patch.object(server.telemetria, "historico_fazenda", return_value=[]),
            patch.object(server.devices, "list", return_value=[]),
            patch("server.salvar_documento", return_value={"name": "documents/analises_risco/abc"}) as salvar,
            patch("server._firebase_args", return_value=("url", lambda: "token")),
        ):
            resposta = self.client.get("/fazendas/fazenda_01/risco")
        self.assertEqual(200, resposta.status_code)
        self.assertEqual("abc", resposta.get_json()["persistencia"]["documentoId"])
        self.assertTrue({"apiContractVersion", "contexto", "environmentalRisk", "machines", "hotspots"}.issubset(resposta.get_json()))
        analise = salvar.call_args.args[3]
        self.assertEqual("fazenda_01", analise["fazendaId"])
        self.assertFalse(analise["iotParticipou"])
        self.assertTrue(analise["fontesIndisponiveis"])


if __name__ == "__main__":
    unittest.main()
