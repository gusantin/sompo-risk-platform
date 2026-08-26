import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import server
from services.telemetria_service import TelemetriaService


IDENTITY = {
    "deviceId": "esp32_real_01",
    "fazendaId": "fazenda_real_01",
    "maquinaId": "maquina_real_01",
    "status": "active",
}
TOKEN = "device-token-kept-out-of-logs"


class Esp32EndpointPreflightTestCase(unittest.TestCase):
    def setUp(self):
        self.original = {key: server.app.config.get(key) for key in (
            "TESTING", "ENVIRONMENT", "ALLOW_DEV_DEVICE_BYPASS", "JSON_MAX_BYTES",
            "TEMPERATURA_MIN_C", "TEMPERATURA_MAX_C", "IOT_RATE_LIMIT_REQUESTS",
            "IOT_RATE_LIMIT_WINDOW_SECONDS",
        )}
        server.app.config.update(
            TESTING=False,
            ENVIRONMENT="production",
            ALLOW_DEV_DEVICE_BYPASS=False,
            JSON_MAX_BYTES=16_384,
            TEMPERATURA_MIN_C=-40,
            TEMPERATURA_MAX_C=85,
            IOT_RATE_LIMIT_REQUESTS=120,
            IOT_RATE_LIMIT_WINDOW_SECONDS=60,
        )
        self.client = server.app.test_client()
        self.patchers = [
            patch.object(server.devices, "authenticate", return_value=IDENTITY),
            patch.object(server.rate_limiter, "allow", return_value=(True, 0)),
            patch.object(server.telemetria, "save", return_value=("reading_doc_01", False, {})),
            patch.object(server.devices, "touch"),
            patch.object(server.snapshots, "get_machine", return_value={}),
            patch.object(server.snapshots, "save_machine"),
        ]
        self.mocks = [item.start() for item in self.patchers]
        (self.authenticate, self.rate_allow, self.save, self.touch,
         self.get_snapshot, self.save_snapshot) = self.mocks

    def tearDown(self):
        for item in reversed(self.patchers):
            item.stop()
        server.app.config.update(self.original)

    @staticmethod
    def payload(reading_id="esp32_boot_1"):
        return {
            "deviceId": IDENTITY["deviceId"],
            "readingId": reading_id,
            "temperatura": 25.4,
            "umidade": 61.2,
        }

    def post(self, payload=None, **kwargs):
        return self.client.post(
            "/dados",
            json=self.payload() if payload is None else payload,
            headers={"X-Device-Token": TOKEN},
            **kwargs,
        )

    def test_payload_real_autenticado_persiste_associacao_timestamp_e_snapshot(self):
        response = self.post()

        self.assertEqual(200, response.status_code)
        body = response.get_json()
        self.assertEqual("ok", body["status"])
        self.assertEqual(IDENTITY["deviceId"], body["deviceId"])
        self.assertEqual(IDENTITY["fazendaId"], body["fazendaId"])
        self.assertEqual(IDENTITY["maquinaId"], body["maquinaId"])
        self.assertFalse(body["deduplicated"])
        self.assertIsNotNone(datetime.fromisoformat(body["observedAt"]))
        self.assertIsNotNone(datetime.fromisoformat(body["receivedAt"]))
        self.authenticate.assert_called_once_with(IDENTITY["deviceId"], TOKEN)
        args = self.save.call_args.args
        self.assertEqual((IDENTITY["deviceId"], IDENTITY["fazendaId"], IDENTITY["maquinaId"]), args[:3])
        self.assertEqual({"temperature": 25.4, "humidity": 61.2}, args[3])
        self.assertEqual("unknown", args[4]["temperature"]["scope"])
        self.assertEqual("unknown", args[4]["humidity"]["scope"])
        self.assertIsNotNone(args[5].tzinfo)
        self.assertEqual("esp32_boot_1", args[6])
        self.assertFalse(self.save.call_args.kwargs["observed_at_provided"])
        self.touch.assert_called_once_with(IDENTITY["deviceId"])
        snapshot = self.save_snapshot.call_args.args[2]
        self.assertEqual({"temperature": 25.4, "humidity": 61.2}, snapshot["latestMeasurements"])
        self.assertEqual("unknown", snapshot["latestMeasurementDescriptors"]["temperature"]["scope"])

    def test_campos_ausentes_null_texto_booleano_e_json_invalido_sao_rejeitados(self):
        cases = [
            {"deviceId": IDENTITY["deviceId"], "umidade": 61.2},
            {"deviceId": IDENTITY["deviceId"], "temperatura": 25.4},
            {**self.payload(), "temperatura": None},
            {**self.payload(), "umidade": None},
            {**self.payload(), "temperatura": "25.4"},
            {**self.payload(), "umidade": "61.2"},
            {**self.payload(), "temperatura": True},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(400, self.post(payload).status_code)

        response = self.client.post(
            "/dados",
            data='{"deviceId":"esp32_real_01","temperatura":25.4,',
            content_type="application/json",
            headers={"X-Device-Token": TOKEN},
        )
        self.assertEqual(400, response.status_code)
        self.assertEqual("requisicao_invalida", response.get_json()["codigo"])

    def test_valores_fora_da_faixa_razoavel_sao_rejeitados(self):
        for field, value in (("temperatura", -40.1), ("temperatura", 85.1),
                             ("umidade", -0.1), ("umidade", 100.1)):
            with self.subTest(field=field, value=value):
                self.assertEqual(400, self.post({**self.payload(), field: value}).status_code)

    def test_reenvio_retorna_deduplicacao_e_conflito_retorna_409(self):
        self.save.side_effect = [
            ("reading_doc_01", False, {}),
            ("reading_doc_01", True, {}),
            ValueError("readingId já foi usado com outro payload."),
        ]
        first = self.post()
        repeated = self.post()
        conflict = self.post({**self.payload(), "temperatura": 25.5})
        self.assertEqual(200, first.status_code)
        self.assertEqual(200, repeated.status_code)
        self.assertTrue(repeated.get_json()["deduplicated"])
        self.assertEqual(409, conflict.status_code)

    def test_fluxo_suporta_envio_a_cada_poucos_segundos(self):
        for sequence in range(20):
            response = self.post(self.payload(f"esp32_boot_{sequence}"))
            self.assertEqual(200, response.status_code)
        self.assertEqual(20, self.save.call_count)

    def test_auth_rate_limit_e_persistencia_indisponivel_tem_erros_controlados(self):
        self.authenticate.side_effect = server.DeviceUnauthorizedError("invalid")
        self.assertEqual(401, self.post().status_code)
        self.authenticate.side_effect = None
        self.authenticate.return_value = IDENTITY

        self.rate_allow.return_value = (False, 7)
        limited = self.post()
        self.assertEqual(429, limited.status_code)
        self.assertEqual("7", limited.headers["Retry-After"])
        self.rate_allow.return_value = (True, 0)

        self.save.side_effect = RuntimeError("firestore offline")
        unavailable = self.post()
        self.assertEqual(503, unavailable.status_code)
        self.assertEqual("persistencia_indisponivel", unavailable.get_json()["codigo"])

    def test_logs_identificam_aceite_rejeicao_e_nao_expoem_token(self):
        with self.assertLogs(server.LOGGER.name, level="INFO") as captured:
            self.assertEqual(200, self.post().status_code)
            self.assertEqual(400, self.post({**self.payload(), "temperatura": "25.4"}).status_code)
        logs = "\n".join(captured.output)
        self.assertIn('"event":"iot_ingestion"', logs)
        self.assertIn('"outcome":"accepted"', logs)
        self.assertIn('"outcome":"rejected"', logs)
        self.assertIn('"deviceId":"esp32_real_01"', logs)
        self.assertIn('"temperatura":25.4', logs)
        self.assertIn('"umidade":61.2', logs)
        self.assertIn("devem ser números JSON", logs)
        self.assertNotIn(TOKEN, logs)


class PhysicalMachineStatusTestCase(unittest.TestCase):
    def test_status_expoe_fazenda_descritores_e_nao_falha_sem_indice_de_alertas(self):
        now = datetime.now(timezone.utc)
        state = {
            "deviceId": "esp32_trator_01",
            "lastSeenAt": now,
            "latestTelemetryAt": now,
            "latestMeasurements": {"temperature": 25.4, "humidity": 61.2},
            "latestMeasurementDescriptors": {
                "temperature": {"type": "temperature", "scope": "unknown", "target": None, "unit": "celsius"},
                "humidity": {"type": "relative_humidity", "scope": "unknown", "target": None, "unit": "percent"},
            },
        }
        original_testing = server.app.config.get("TESTING")
        server.app.config["TESTING"] = True
        try:
            with patch.object(server.maquinas, "obter", return_value={
                "fazendaId": "demo_fazenda_01", "maquinaId": "trator_fisico_01", "nome": "Trator 01",
            }), patch.object(server.propriedades, "obter", return_value={
                "fazendaId": "demo_fazenda_01", "nome": "DEMO Fazenda SOMPO",
            }), patch.object(server.snapshots, "get_machine", return_value=state), \
                    patch.object(server.snapshots, "get_property", return_value={}), \
                    patch.object(server, "_list_active_alerts", side_effect=RuntimeError("missing index")):
                response = server.app.test_client().get(
                    "/fazendas/demo_fazenda_01/maquinas/trator_fisico_01/status"
                )
        finally:
            server.app.config["TESTING"] = original_testing

        self.assertEqual(200, response.status_code)
        body = response.get_json()
        self.assertEqual("DEMO Fazenda SOMPO", body["property"]["nome"])
        self.assertEqual("esp32_trator_01", body["deviceId"])
        self.assertEqual("online", body["deviceHealth"]["status"])
        self.assertEqual("unknown", body["latestMeasurementDescriptors"]["temperature"]["scope"])


class Esp32ResilienceAndPersistenceTestCase(unittest.TestCase):
    def test_retry_sem_relogio_deduplica_mesmo_com_novo_timestamp_do_servidor(self):
        class FirebaseFake:
            firestore_url = "https://firestore.invalid/documents"

            def initialize(self):
                return None

            def obter_token(self):
                return "firebase-token"

        service = TelemetriaService(FirebaseFake())
        descriptors = {
            "temperature": {"type": "temperature", "scope": "unknown", "target": None, "unit": "celsius"},
            "humidity": {"type": "relative_humidity", "scope": "unknown", "target": None, "unit": "percent"},
        }
        saved = {}

        def create(_url, _token, _collection, _document_id, document):
            saved.update(document)
            return document

        first_time = datetime.now(timezone.utc)
        with patch("services.telemetria_service.obter_documento", return_value=None), \
             patch("services.telemetria_service.criar_documento", side_effect=create):
            document_id, duplicate, _ = service.save(
                IDENTITY["deviceId"], IDENTITY["fazendaId"], IDENTITY["maquinaId"],
                {"temperature": 25.4, "humidity": 61.2}, descriptors, first_time,
                "esp32_boot_1", "iot_device", observed_at_provided=False,
            )
        self.assertFalse(duplicate)
        self.assertFalse(saved["observedAtProvidedByDevice"])

        retry_time = first_time + timedelta(seconds=5)
        with patch("services.telemetria_service.obter_documento", return_value=saved):
            repeated_id, duplicate, repeated = service.save(
                IDENTITY["deviceId"], IDENTITY["fazendaId"], IDENTITY["maquinaId"],
                {"temperature": 25.4, "humidity": 61.2}, descriptors, retry_time,
                "esp32_boot_1", "iot_device", observed_at_provided=False,
            )
        self.assertTrue(duplicate)
        self.assertEqual(document_id, repeated_id)
        self.assertEqual(first_time, repeated["dataHora"])

    def test_documento_persistido_preserva_associacao_timestamps_e_scope_desconhecido(self):
        class FirebaseFake:
            firestore_url = "https://firestore.invalid/documents"

            def initialize(self):
                return None

            def obter_token(self):
                return "firebase-token"

        service = TelemetriaService(FirebaseFake())
        observed_at = datetime.now(timezone.utc)
        descriptors = {
            "temperature": {"type": "temperature", "scope": "unknown", "target": None, "unit": "celsius"},
            "humidity": {"type": "relative_humidity", "scope": "unknown", "target": None, "unit": "percent"},
        }
        captured = {}

        def create(_url, _token, _collection, _document_id, document):
            captured.update(document)
            return document

        with patch("services.telemetria_service.obter_documento", return_value=None), \
             patch("services.telemetria_service.criar_documento", side_effect=create):
            _, duplicate, _ = service.save(
                IDENTITY["deviceId"], IDENTITY["fazendaId"], IDENTITY["maquinaId"],
                {"temperature": 25.4, "humidity": 61.2}, descriptors, observed_at,
                "esp32_boot_1", "iot_device",
            )

        self.assertFalse(duplicate)
        self.assertEqual(IDENTITY["fazendaId"], captured["fazendaId"])
        self.assertEqual(IDENTITY["maquinaId"], captured["maquinaId"])
        self.assertEqual("unknown", captured["measurementScope"])
        self.assertEqual("iot_device", captured["origem"])
        self.assertEqual(observed_at, captured["dataHora"])
        self.assertIsNotNone(captured["receivedAt"].tzinfo)

    def test_telemetria_ausente_antiga_e_recente_nao_quebra(self):
        now = datetime.now(timezone.utc)
        self.assertEqual("missing", TelemetriaService.classificar(None, 900, now)["status"])
        stale = {"dataHora": now - timedelta(minutes=16), "measurements": {"temperature": 25.4}}
        fresh = {"dataHora": now - timedelta(seconds=5), "measurements": {"temperature": 25.4}}
        self.assertEqual("stale", TelemetriaService.classificar(stale, 900, now)["status"])
        self.assertEqual("fresh", TelemetriaService.classificar(fresh, 900, now)["status"])

    def test_firmware_tem_auth_timeout_reconexao_e_retry_idempotente(self):
        source = Path("firmware/esp32.example.ino").read_text(encoding="utf-8")
        self.assertIn('http.addHeader("X-Device-Token", DEVICE_TOKEN_VALUE)', source)
        self.assertIn("http.setTimeout(TIMEOUT_HTTP_MS)", source)
        self.assertIn("conectarWiFi();", source)
        self.assertIn('\\"readingId\\"', source)
        self.assertIn("INTERVALO_RETRY_HTTP_MS", source)
        self.assertIn("pendente.ativa", source)
        self.assertNotIn("WIFI_PASSWORD_VALUE);\n    Serial", source)


if __name__ == "__main__":
    unittest.main()
