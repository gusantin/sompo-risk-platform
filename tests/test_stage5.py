import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import server
from scripts.scenario_generator import SCENARIOS, generate_scenario
from scripts.seed_demo import execute as seed_demo
from services.alert_service import AlertService, AlertValidationError
from services.device_service import DeviceService, DeviceUnauthorizedError, DeviceValidationError
from services.event_service import EventService
from services.operational_risk_service import calcular_risco_operacional
from services.risk_explanation_service import explain_risks
from services.telemetria_service import TelemetriaService
from services.unit_service import UnitValidationError, validate_measurements


class FirebaseFake:
    firestore_url = "https://firestore.invalid/documents"

    def initialize(self):
        return None

    def obter_token(self):
        return "firebase-token"


MACHINE = {
    "fazendaId": "f1", "maquinaId": "m1", "sensoresConfigurados": [
        {"sensorId": "temp_motor", "type": "temperature", "scope": "machine_component",
         "target": "engine", "unit": "celsius", "thresholds": {"warning": 70, "high": 85, "critical": 95}},
    ],
}


class UnitSemanticsTestCase(unittest.TestCase):
    def test_unidade_exata_e_contexto_preservados(self):
        values, descriptors = validate_measurements(
            {"temp_motor": {"value": 80, "unit": "celsius"}}, MACHINE,
        )
        self.assertEqual(80, values["temp_motor"])
        self.assertEqual("machine_component", descriptors["temp_motor"]["scope"])

    def test_nao_converte_fahrenheit_kelvin_ou_unidade_desconhecida(self):
        for unit in ("fahrenheit", "kelvin", "graus"):
            with self.subTest(unit=unit), self.assertRaises(UnitValidationError):
                validate_measurements({"temp_motor": {"value": 80, "unit": unit}}, MACHINE)

    def test_sensor_nao_configurado_e_rejeitado(self):
        with self.assertRaises(UnitValidationError):
            validate_measurements({"temperatura_ar": 30}, MACHINE)

    def test_valid_range_configuravel_rejeita_valor_invalido(self):
        machine = {"sensoresConfigurados": [{**MACHINE["sensoresConfigurados"][0],
            "metadata": {"validRange": {"min": -40, "max": 150}}}]}
        with self.assertRaises(UnitValidationError):
            validate_measurements({"temp_motor": 500}, machine)


class DeviceServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.machines = Mock()
        self.machines.obter.return_value = MACHINE
        self.service = DeviceService(FirebaseFake(), self.machines, hash_iterations=1_000)
        self.token = "token-device-valid-123456"

    def test_token_e_hashado_e_nunca_retorna(self):
        captured = {}

        def create(_url, _token, _collection, _id, document):
            captured.update(document)
            return {**document, "id": "d1"}

        with patch("services.device_service.criar_documento", side_effect=create):
            result = self.service.create("d1", "f1", "m1", self.token)
        self.assertNotIn("tokenHash", result)
        self.assertNotIn("tokenSalt", result)
        self.assertNotIn(self.token, repr(captured))
        self.assertEqual("pbkdf2_sha256", captured["tokenHashAlgorithm"])

    def test_autorizado_token_invalido_e_revogado(self):
        captured = {}
        with patch("services.device_service.criar_documento", side_effect=lambda *args: captured.update(args[-1]) or args[-1]):
            self.service.create("d1", "f1", "m1", self.token)
        with patch.object(self.service, "get", return_value=captured):
            self.assertEqual("m1", self.service.authenticate("d1", self.token)["maquinaId"])
            with self.assertRaises(DeviceUnauthorizedError):
                self.service.authenticate("d1", "token-device-invalid-xxxx")
        captured["status"] = "revoked"
        with patch.object(self.service, "get", return_value=captured), self.assertRaises(DeviceUnauthorizedError):
            self.service.authenticate("d1", self.token)

    def test_maquina_ou_fazenda_errada_nao_provisiona(self):
        self.machines.obter.return_value = None
        with self.assertRaises(DeviceValidationError):
            self.service.create("d1", "f1", "m1", self.token)
        self.machines.obter.return_value = {**MACHINE, "fazendaId": "outra"}
        with self.assertRaises(DeviceValidationError):
            self.service.create("d1", "f1", "m1", self.token)

    def test_device_health_online_stale_offline_unknown(self):
        now = datetime.now(timezone.utc)
        self.assertEqual("unknown", self.service.health(None, 60, 120, now)["status"])
        self.assertEqual("online", self.service.health(now - timedelta(seconds=30), 60, 120, now)["status"])
        self.assertEqual("stale", self.service.health(now - timedelta(seconds=90), 60, 120, now)["status"])
        self.assertEqual("offline", self.service.health(now - timedelta(seconds=121), 60, 120, now)["status"])

    def test_rotacao_reativa_revogado_sem_expor_nova_credencial(self):
        captured = {}
        with patch("services.device_service.criar_documento", side_effect=lambda *args: captured.update(args[-1]) or args[-1]):
            self.service.create("d1", "f1", "m1", self.token)
        captured["status"] = "revoked"
        with patch.object(self.service, "get", return_value=captured), \
             patch("services.device_service.atualizar_documento", side_effect=lambda *args: args[-1]):
            rotated = self.service.rotate("d1", "new-device-token-123456789")
        self.assertEqual("active", rotated["status"])
        self.assertEqual(2, rotated["tokenVersion"])
        self.assertNotIn("tokenHash", rotated)


class TelemetryIdempotencyTestCase(unittest.TestCase):
    def test_reenvio_idempotente_e_conflito(self):
        service = TelemetriaService(FirebaseFake())
        observed_at = datetime.now(timezone.utc)
        descriptors = {"temp_motor": {"type": "temperature", "scope": "machine_component",
                                       "target": "engine", "unit": "celsius"}}
        with patch("services.telemetria_service.obter_documento", return_value=None), \
             patch("services.telemetria_service.criar_documento", side_effect=lambda *args: args[-1]):
            document_id, duplicate, saved = service.save("d1", "f1", "m1", {"temp_motor": 80},
                                                          descriptors, observed_at, "r1")
        self.assertFalse(duplicate)
        with patch("services.telemetria_service.obter_documento", return_value=saved):
            repeated_id, duplicate, _ = service.save("d1", "f1", "m1", {"temp_motor": 80},
                                                       descriptors, observed_at, "r1")
            self.assertTrue(duplicate)
            self.assertEqual(document_id, repeated_id)
            with self.assertRaises(ValueError):
                service.save("d1", "f1", "m1", {"temp_motor": 81}, descriptors, observed_at, "r1")


class EventAlertServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.event_service = EventService(FirebaseFake(), significant_score_delta=15)
        self.alert_service = AlertService(FirebaseFake(), cooldown_seconds=3600, hotspot_distance_km=5)

    @patch("services.event_service.upsert_documento", side_effect=lambda *args: args[-1])
    def test_evento_somente_em_transicao_relevante_e_idempotente(self, _upsert):
        self.assertIsNone(self.event_service.risk_transition(
            "environmental_risk_changed", "f1", "incendio", "moderate"))
        event1 = self.event_service.risk_transition(
            "environmental_risk_changed", "f1", "incendio", "high", source_analysis_id="a1")
        event2 = self.event_service.risk_transition(
            "environmental_risk_changed", "f1", "incendio", "high", source_analysis_id="a1")
        self.assertEqual(event1["eventId"], event2["eventId"])
        self.assertIsNone(self.event_service.risk_transition(
            "environmental_risk_changed", "f1", "incendio", "high", "high",
            "a2", current_score=71, previous_score=70))

    @patch("services.event_service.upsert_documento", side_effect=lambda *args: args[-1])
    def test_modelo_extensivel_cria_evento_operacional_idempotente(self, _upsert):
        first = self.event_service.create("device_offline", "f1", "d1:offline", "m1",
                                          evidence=[{"lastSeenAt": "old"}])
        second = self.event_service.create("device_offline", "f1", "d1:offline", "m1")
        self.assertEqual(first["eventId"], second["eventId"])
        self.assertEqual("device_offline", first["eventType"])

    @patch("services.alert_service.upsert_documento", side_effect=lambda *args: args[-1])
    def test_alerta_criacao_dedupe_e_campos_explicaveis(self, _upsert):
        with patch.object(self.alert_service, "get", return_value=None):
            alert, deduped = self.alert_service.emit("machine_risk", "high", "f1", "machine",
                ["temp_motor:high"], [{"sensorId": "temp_motor", "value": 90}], "a1", "m1")
        self.assertFalse(deduped)
        self.assertTrue({"alertId", "type", "severity", "status", "fazendaId", "maquinaId", "riskType",
                         "createdAt", "updatedAt", "factors", "evidence", "sourceAnalysisId"}.issubset(alert))
        with patch.object(self.alert_service, "get", return_value=alert):
            same, deduped = self.alert_service.emit("machine_risk", "high", "f1", "machine", [], [], "a2", "m1")
        self.assertTrue(deduped)
        self.assertEqual(alert["alertId"], same["alertId"])

    @patch("services.alert_service.atualizar_documento", side_effect=lambda *args: args[-1])
    def test_ciclo_acknowledged_resolved_e_transicao_invalida(self, _update):
        alert = {"alertId": "alert_1", "status": "open", "createdAt": datetime.now(timezone.utc)}
        with patch.object(self.alert_service, "get", return_value=alert):
            acknowledged = self.alert_service.update_status("alert_1", "acknowledged", "user1")
        self.assertEqual("acknowledged", acknowledged["status"])
        with patch.object(self.alert_service, "get", return_value=acknowledged):
            resolved = self.alert_service.update_status("alert_1", "resolved", "user1")
        self.assertEqual("resolved", resolved["status"])
        with patch.object(self.alert_service, "get", return_value=resolved), self.assertRaises(AlertValidationError):
            self.alert_service.update_status("alert_1", "open")

    def test_hotspot_sem_gps_atual_nao_afirma_proximidade(self):
        machine_result = {"machine": {"maquinaId": "m1", "status": "ativo"}, "machineRisk": {"level": "low"},
            "operationalContextRisk": {"level": "high"},
            "location": {"locationCurrent": False, "nearestHotspotDistanceKm": 1}}
        with patch.object(self.alert_service, "emit", return_value=({}, False)) as emit:
            self.alert_service.evaluate("f1", {"incendio": {"nivel": "alto"}}, [machine_result], "a1")
        self.assertNotIn("machine_near_hotspot", [call.args[0] for call in emit.call_args_list])

    def test_hotspot_recente_com_gps_atual_gera_alerta(self):
        machine_result = {"machine": {"maquinaId": "m1", "status": "ativo"}, "machineRisk": {"level": "low"},
            "operationalContextRisk": {"level": "high"},
            "location": {"locationCurrent": True, "nearestHotspotDistanceKm": 2,
                         "nearestHotspotAgeHours": 1}}
        with patch.object(self.alert_service, "emit", return_value=({}, False)) as emit:
            self.alert_service.evaluate("f1", {"incendio": {"nivel": "alto"}}, [machine_result], "a1")
        self.assertIn("machine_near_hotspot", [call.args[0] for call in emit.call_args_list])

    def test_hotspot_recente_proximo_da_propriedade_gera_alerta_ambiental(self):
        with patch.object(self.alert_service, "emit", return_value=({}, False)) as emit:
            self.alert_service.evaluate("f1", {"incendio": {"nivel": "baixo"}}, [], "a1",
                                        property_hotspot={"distanciaKm": 2, "ageHours": 1})
        self.assertIn("hotspot_near_property", [call.args[0] for call in emit.call_args_list])


class RiskRulesTestCase(unittest.TestCase):
    def test_matriz_operacional_sem_score_combinado(self):
        cases = [
            ("baixo", "low", "low"), ("moderado", "low", "moderate"),
            ("alto", "high", "high"), ("critico", "high", "critical"),
            ("baixo", "critical", "high"),
        ]
        for environmental, machine, expected in cases:
            with self.subTest(environmental=environmental, machine=machine):
                result = calcular_risco_operacional({"incendio": {"nivel": environmental}},
                    {"level": machine}, location_current=True, inside_property=True)
                self.assertEqual(expected, result["level"])
                self.assertIsNone(result["score"])
        combined = calcular_risco_operacional({"incendio": {"nivel": "critico"}}, {"level": "high"})
        self.assertEqual("critical", combined["level"])
        self.assertIn("machine_location_unavailable_or_stale", combined["factors"])

    def test_explicacao_confidence_significa_cobertura(self):
        result = explain_risks({"incendio": {"score": 80, "nivel": "critico", "confianca": "alta", "fatores": []}},
                               {"weatherAvailable": True, "satelliteAvailable": False, "geospatialAvailable": True})
        self.assertEqual("quality_and_coverage_of_input_data", result["incendio"]["confidenceMeaning"])
        self.assertIn("hotspot", result["incendio"]["missingData"])


class SecurityApiTestCase(unittest.TestCase):
    def setUp(self):
        self.original = {key: server.app.config.get(key) for key in (
            "TESTING", "ENVIRONMENT", "ALLOW_DEV_AUTH_BYPASS", "ALLOW_DEV_DEVICE_BYPASS", "APP_API_KEYS", "JSON_MAX_BYTES")}

    def tearDown(self):
        server.app.config.update(self.original)

    def test_api_de_aplicacao_protegida_e_health_publico(self):
        server.app.config.update(TESTING=False, ENVIRONMENT="production", ALLOW_DEV_AUTH_BYPASS=False,
                                 APP_API_KEYS=("application-secret-key",))
        client = server.app.test_client()
        self.assertEqual(200, client.get("/health").status_code)
        self.assertEqual(401, client.get("/fazendas").status_code)
        with patch.object(server.propriedades, "listar", return_value=[]):
            response = client.get("/fazendas", headers={"Authorization": "Bearer application-secret-key",
                                                         "X-Request-ID": "req-test-1"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("req-test-1", response.headers["X-Request-ID"])

    def test_ingestao_autorizada_token_invalido_revogado_e_ids_errados(self):
        server.app.config.update(TESTING=False, ENVIRONMENT="production", ALLOW_DEV_DEVICE_BYPASS=False)
        client = server.app.test_client()
        identity = {"deviceId": "d1", "fazendaId": "f1", "maquinaId": "m1", "status": "active"}
        payload = {"deviceId": "d1", "readingId": "r1",
                   "measurements": {"temp_motor": {"value": 80, "unit": "celsius"}}}
        with patch.object(server.devices, "authenticate", return_value=identity), \
             patch.object(server.maquinas, "obter", return_value=MACHINE), \
             patch.object(server.telemetria, "save", return_value=("doc1", False, {})), \
             patch.object(server.devices, "touch"), patch.object(server.snapshots, "get_machine", return_value={}), \
             patch.object(server.snapshots, "save_machine"):
            self.assertEqual(200, client.post("/dados", json=payload, headers={"X-Device-Token": "valid-token"}).status_code)
            wrong = {**payload, "fazendaId": "other"}
            self.assertEqual(401, client.post("/dados", json=wrong, headers={"X-Device-Token": "valid-token"}).status_code)
        for error in (DeviceUnauthorizedError("invalid"), DeviceUnauthorizedError("revoked")):
            with patch.object(server.devices, "authenticate", side_effect=error):
                self.assertEqual(401, client.post("/dados", json=payload, headers={"X-Device-Token": "bad"}).status_code)

    def test_request_id_erro_padronizado_e_payload_limit(self):
        server.app.config.update(TESTING=True, JSON_MAX_BYTES=20)
        client = server.app.test_client()
        response = client.post("/dados", data="{" + "x" * 100 + "}", content_type="application/json",
                               headers={"X-Request-ID": "invalid id with spaces"})
        self.assertEqual(413, response.status_code)
        self.assertIn("error", response.get_json())
        self.assertNotEqual("invalid id with spaces", response.headers["X-Request-ID"])

    def test_provisionamento_nao_devolve_token(self):
        server.app.config["TESTING"] = True
        client = server.app.test_client()
        sanitized = {"deviceId": "d1", "fazendaId": "f1", "maquinaId": "m1", "status": "active"}
        with patch.object(server.devices, "create", return_value=sanitized):
            response = client.post("/devices", json={"deviceId": "d1", "fazendaId": "f1",
                "maquinaId": "m1", "token": "token-device-valid-123456"})
        self.assertEqual(201, response.status_code)
        self.assertNotIn("token", json.dumps(response.get_json()).lower())


class StatusApiTestCase(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()

    def test_fazenda_sem_analise(self):
        with patch.object(server.propriedades, "obter", return_value={"id": "f1"}), \
             patch.object(server.maquinas, "listar", return_value=[]), \
             patch.object(server.snapshots, "list_machines", return_value=[]), \
             patch.object(server.snapshots, "get_property", return_value=None), \
             patch.object(server.alerts, "list", return_value=[]):
            payload = self.client.get("/fazendas/f1/status").get_json()
        self.assertIsNone(payload["currentRisk"])
        self.assertEqual([], payload["machines"])

    def test_maquina_sem_telemetria_e_com_snapshot(self):
        with patch.object(server.maquinas, "obter", return_value=MACHINE), \
             patch.object(server.snapshots, "get_machine", return_value=None), \
             patch.object(server.telemetria, "mais_recente", return_value=None), \
             patch.object(server.devices, "list", return_value=[]), \
             patch.object(server.snapshots, "get_property", return_value=None), \
             patch.object(server.alerts, "list", return_value=[]):
            missing = self.client.get("/fazendas/f1/maquinas/m1/status").get_json()
        self.assertEqual("unknown", missing["deviceHealth"]["status"])
        snapshot = {"deviceHealth": {"status": "online"}, "latestMeasurements": {"temp_motor": 80},
                    "machineRisk": {"level": "high"}, "operationalRisk": {"level": "high"}}
        with patch.object(server.maquinas, "obter", return_value=MACHINE), \
             patch.object(server.snapshots, "get_machine", return_value=snapshot), \
             patch.object(server.snapshots, "get_property", return_value={}), \
             patch.object(server.alerts, "list", return_value=[]):
            current = self.client.get("/fazendas/f1/maquinas/m1/status").get_json()
        self.assertEqual(80, current["latestMeasurements"]["temp_motor"])
        self.assertEqual("high", current["machineRisk"]["level"])

    def test_dashboard_agrega_snapshots_sem_fontes_externas(self):
        property_data = {"id": "f1", "nome": "Fazenda"}
        current = {"fazendaId": "f1", "environmentalRisk": {"geral": {"nivel": "alto"}},
                   "analysisAt": datetime.now(timezone.utc)}
        machine_state = {"fazendaId": "f1", "maquinaId": "m1", "attention": True}

        def list_alerts(filters, _limit):
            return [{"alertId": "a1", "fazendaId": "f1", "status": "open"}] if filters.get("status") == "open" else []

        with patch.object(server.propriedades, "listar", return_value=[property_data]), \
             patch.object(server.snapshots, "list_properties", return_value=[current]), \
             patch.object(server.snapshots, "list_machines_attention", return_value=[machine_state]), \
             patch.object(server.alerts, "list", side_effect=list_alerts), patch("server._fontes") as sources:
            payload = self.client.get("/dashboard").get_json()
        sources.assert_not_called()
        self.assertEqual("alto", payload["properties"][0]["currentRisk"]["nivel"])
        self.assertEqual(1, payload["properties"][0]["activeAlertCount"])
        self.assertEqual(1, payload["counts"]["machinesAttention"])

    def test_endpoints_de_alerta_listam_reconhecem_resolvem_e_validam(self):
        alert = {"alertId": "alert_1", "fazendaId": "f1", "status": "open"}
        with patch.object(server.alerts, "list", return_value=[alert]):
            self.assertEqual(1, self.client.get("/alertas?status=open").get_json()["count"])
            self.assertEqual(1, self.client.get("/fazendas/f1/alertas").get_json()["count"])
        with patch.object(server.alerts, "get", return_value=alert):
            self.assertEqual("alert_1", self.client.get("/alertas/alert_1").get_json()["alert"]["alertId"])
        acknowledged = {**alert, "status": "acknowledged"}
        with patch.object(server.alerts, "update_status", return_value=acknowledged) as update:
            response = self.client.patch("/alertas/alert_1", json={"status": "acknowledged"})
        self.assertEqual(200, response.status_code)
        update.assert_called_once()
        self.assertEqual(400, self.client.patch("/alertas/alert_1", json={"status": "open"}).status_code)


class CoreEndToEndTestCase(unittest.TestCase):
    def test_property_machine_telemetry_risk_events_alerts_snapshots_history_trend(self):
        client = server.app.test_client()
        now = datetime.now(timezone.utc)
        property_data = {"id": "f_e2e", "nome": "Fazenda E2E", "municipio": "Teste", "estado": "MT",
            "latitude": -15.6, "longitude": -56.1, "areaHectares": 100,
            "atividadePrincipal": "agricultura", "culturas": [], "poligonoGeoJson": None}
        machine = {**MACHINE, "fazendaId": "f_e2e", "maquinaId": "m_e2e", "nome": "Trator",
                   "latitude": -15.6, "longitude": -56.1, "lastLocationAt": now}
        readings = [
            {"fazendaId": "f_e2e", "maquinaId": "m_e2e", "dataHora": now,
             "receivedAt": now, "measurements": {"temp_motor": 96}},
            {"fazendaId": "f_e2e", "maquinaId": "m_e2e", "dataHora": now - timedelta(hours=2),
             "receivedAt": now - timedelta(hours=2), "measurements": {"temp_motor": 40}},
        ]
        source_error = {"status": "erro_api", "dados": {}}
        sources = {name: dict(source_error) for name in ("clima", "hidrologia", "terreno", "sgb", "inmet")}
        sources["queimadas"] = {"status": "ok", "dados": {"focoMaisProximo": {
            "latitude": -15.6, "longitude": -56.1, "distanciaKm": 0.2, "ageHours": 1}}}
        risks = {"incendio": {"score": 90, "nivel": "critico", "confianca": "alta", "fatores": []},
                 "geral": {"score": 90, "nivel": "critico"}}
        event_counter = iter(range(10))

        def event(*_args, **_kwargs):
            number = next(event_counter)
            return {"eventId": f"evt_{number}", "eventType": _args[0]}

        with patch.dict(server.app.config, {"TESTING": True, "TEST_POST_ANALYSIS_PIPELINE": True}), \
             patch.object(server.propriedades, "obter", return_value=property_data), \
             patch.object(server.maquinas, "listar", return_value=[machine]), \
             patch.object(server.telemetria, "historico_fazenda", return_value=readings), \
             patch.object(server.devices, "list", return_value=[{"deviceId": "d_e2e", "maquinaId": "m_e2e", "lastSeenAt": now}]), \
             patch("server._fontes", return_value=sources), patch("server.calcular_riscos", return_value=risks), \
             patch("server.salvar_documento", return_value={"name": "documents/analises_risco/analysis_e2e"}) as save_analysis, \
             patch("server._firebase_args", return_value=("url", lambda: "token")), \
             patch.object(server.snapshots, "get_property", return_value=None), \
             patch.object(server.snapshots, "list_machines", return_value=[]), \
             patch.object(server.snapshots, "save_property") as save_property, \
             patch.object(server.snapshots, "save_machine") as save_machine, \
             patch.object(server.events, "risk_transition", side_effect=event), \
             patch.object(server.alerts, "evaluate", return_value=[{"alert": {"alertId": "alert_e2e", "status": "open"}, "deduplicated": False}]) as evaluate, \
             patch.object(server.historico_risco, "tendencias", return_value={"samples": 1, "risks": {}}):
            response = client.get("/fazendas/f_e2e/risco")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual("critical", payload["machines"][0]["machineRisk"]["level"])
        self.assertEqual("critical", payload["machines"][0]["operationalContextRisk"]["level"])
        self.assertTrue(payload["machines"][0]["iot"]["fresh"])
        self.assertEqual(0.0, payload["machines"][0]["location"]["nearestHotspotDistanceKm"])
        self.assertEqual("analysis_e2e", payload["persistencia"]["documentoId"])
        self.assertEqual("alert_e2e", payload["alerts"][0]["alertId"])
        save_analysis.assert_called_once()
        save_property.assert_called_once()
        save_machine.assert_called_once()
        evaluate.assert_called_once()

        with patch.object(server.historico_risco, "listar", return_value=[{"timestamp": now, "score": 90,
                "nivel": "critico", "riscos": risks}]), \
             patch.object(server.historico_risco, "tendencias", return_value={"samples": 1, "risks": {}}):
            self.assertEqual(1, client.get("/fazendas/f_e2e/analises").get_json()["count"])
            self.assertEqual(1, client.get("/fazendas/f_e2e/risco/tendencia").get_json()["trend"]["samples"])


class DemoAndSchemaTestCase(unittest.TestCase):
    def test_seed_dry_run_nao_inicializa_firebase(self):
        with patch("scripts.seed_demo.FirebaseClient") as firebase:
            summary = seed_demo(dry_run=True, scenario="normal")
        firebase.assert_not_called()
        self.assertTrue(summary["dryRun"])
        self.assertTrue(summary["propertyId"].startswith("demo_"))

    def test_todos_cenarios_sao_sinteticos(self):
        for name in SCENARIOS:
            scenario = generate_scenario(name)
            self.assertTrue(scenario["demoData"])
            self.assertTrue(all(item["readingId"].startswith("demo_") for item in scenario["telemetry"]))

    def test_indices_do_nucleo_estao_declarados(self):
        with open("firestore.indexes.json", encoding="utf-8") as file:
            data = json.load(file)
        collections = {item["collectionGroup"] for item in data["indexes"]}
        self.assertTrue({"devices", "domain_events", "alerts", "machine_state_current",
                         "leituras_sensores"}.issubset(collections))


if __name__ == "__main__":
    unittest.main()
