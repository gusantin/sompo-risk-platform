import os
import unittest
import uuid


@unittest.skipUnless(os.getenv("RUN_INTEGRATION_TESTS") == "1", "integrações reais são opt-in")
class IntegracoesPublicasTestCase(unittest.TestCase):
    def test_ibge_mt_responde_com_identidades_e_malhas(self):
        from integracoes.ibge import listar_municipios, obter_malhas_municipais
        municipios, malhas = listar_municipios("MT"), obter_malhas_municipais("MT")
        self.assertGreater(len(municipios), 100); self.assertGreater(len(malhas), 100)
        self.assertTrue(all(item["ibgeCode"].isdigit() for item in municipios))

    def test_open_meteo_contrato_controlado(self):
        from integracoes.open_meteo import consultar_clima
        resultado = consultar_clima(-15.6, -56.1)
        self.assertIn(resultado.get("status"), {"ok", "parcial"})
        self.assertIn("dados", resultado)


@unittest.skipUnless(os.getenv("RUN_FIREBASE_INTEGRATION_TESTS") == "1",
                     "integração Firebase real é opt-in e exige confirmação do projeto")
class FirebaseRestIntegrationTestCase(unittest.TestCase):
    def test_roundtrip_remove_somente_documento_criado_pelo_teste(self):
        from config import Config
        from services.firebase_client import FirebaseClient
        from services.firestore_service import criar_documento, deletar_documento, obter_documento

        if Config.ENVIRONMENT not in {"development", "test"}:
            self.skipTest("ENVIRONMENT deve ser development ou test")
        firebase = FirebaseClient(Config.FIREBASE_KEY_PATH)
        firebase.initialize()
        if os.getenv("FIREBASE_TEST_PROJECT_ACK") != firebase.project_id:
            self.skipTest("FIREBASE_TEST_PROJECT_ACK deve coincidir exatamente com o projectId")
        document_id = f"test_core_{uuid.uuid4().hex}"
        args = (firebase.firestore_url, firebase.obter_token)
        try:
            created = criar_documento(*args, "test_sompo_core", document_id,
                                      {"testData": True, "owner": document_id})
            self.assertEqual(document_id, created["id"])
            self.assertEqual(document_id, obter_documento(*args, "test_sompo_core", document_id)["owner"])
        finally:
            deletar_documento(*args, "test_sompo_core", document_id)


if __name__ == "__main__": unittest.main()
