import hashlib
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import server
from services.device_service import DeviceUnauthorizedError
from services.esp_prototype_adapter import adapt_prototype
from services.machine_risk_service import calcular_risco_maquina
from services.telemetria_service import TelemetriaService


def sample():
    # Explicit test fixture, never sent to hardware or a real database.
    return dict(temperatura=25.4, umidade=61.2, ventoKmh=75,
                leituraLdrDigital=0, statusGeral="RISCO", dhtComErro=False)


class PrototypeAdapterTests(unittest.TestCase):
    def test_canonical_source_bytes(self):
        source = Path(__file__).resolve().parents[1] / "firmware/sompo_esp_prototype/sompo_esp_prototype.ino"
        self.assertEqual("0cb22569078b6b7bcca6327abec0a8eeb0fd0bd6c1d686684a47616bf755a825",
                         hashlib.sha256(source.read_bytes()).hexdigest())

    def test_units_raw_light_and_local_status_are_separate(self):
        values, descriptors, local = adapt_prototype(sample())
        self.assertEqual(75, values["ventoKmh"])
        self.assertEqual("km_h", descriptors["ventoKmh"]["unit"])
        self.assertEqual("other", descriptors["ventoKmh"]["scope"])
        self.assertEqual(0, values["leituraLdrDigital"])
        self.assertNotIn("statusGeral", values)
        self.assertEqual("RISCO", local["statusGeral"])
        reading = {"measurements": values, "measurementDescriptors": descriptors, "deviceLocal": local}
        self.assertEqual("insufficient_data", calcular_risco_maquina({"sensoresConfigurados": []}, [reading])["status"])
        # A local status is consumed verbatim, never recalculated from measurements.
        self.assertEqual("NORMAL", adapt_prototype({**sample(), "statusGeral": "NORMAL"})[2]["statusGeral"])

    def test_missing_light_and_dht_error_do_not_fabricate_readings(self):
        payload = {"ventoKmh": 0, "statusGeral": "NORMAL", "dhtComErro": True}
        self.assertEqual({"ventoKmh": 0}, adapt_prototype(payload)[0])
        with self.assertRaises(ValueError):
            adapt_prototype({**sample(), "dhtComErro": True})

    def test_invalid_and_ambiguous_input(self):
        for field, value in [("ventoKmh", -1), ("ventoKmh", 101), ("temperatura", float("nan")),
                             ("temperatura", True), ("umidade", "61"), ("umidade", 101),
                             ("leituraLdrDigital", 2), ("leituraLdrDigital", True),
                             ("statusGeral", "critical"), ("statusGeral", []), ("dhtComErro", None)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                adapt_prototype({**sample(), field: value})
        for value in [None, {}, {**sample(), "unexpected": 1}]:
            with self.assertRaises(ValueError):
                adapt_prototype(value)

    def test_local_status_participates_in_idempotency_and_history(self):
        service = TelemetriaService(Mock())
        values, descriptors, local = adapt_prototype(sample())
        args = ("dev1", "farm1", "machine1", values, descriptors, datetime.now(timezone.utc), "r1")
        with patch.object(service, "_args", return_value=("url", Mock())), \
             patch("services.telemetria_service.obter_documento", return_value=None) as get, \
             patch("services.telemetria_service.criar_documento", side_effect=lambda *a: a[-1]):
            _, duplicate, saved = service.save(*args, device_local=local)
            self.assertFalse(duplicate)
            self.assertEqual(local, saved["deviceLocal"])
            get.return_value = saved
            self.assertTrue(service.save(*args, device_local=local)[1])
            with self.assertRaisesRegex(ValueError, "readingId"):
                service.save(*args, device_local={**local, "statusGeral": "NORMAL"})

    def test_authenticated_endpoint_and_risk_snapshot_preservation(self):
        original = server.app.config.copy()
        server.app.config.update(TESTING=False, ENVIRONMENT="production", ALLOW_DEV_DEVICE_BYPASS=False)
        identity = dict(deviceId="dev1", fazendaId="farm1", maquinaId="machine1")
        payload = dict(deviceId="dev1", readingId="r1", prototype=sample())
        try:
            with patch.object(server.devices, "authenticate", return_value=identity) as auth, \
                 patch.object(server.rate_limiter, "allow", return_value=(True, 0)), \
                 patch.object(server.telemetria, "save", return_value=("doc1", False, {})) as save, \
                 patch.object(server.devices, "touch"), \
                 patch.object(server.maquinas, "obter", return_value={"fazendaId": "farm1"}) as machine, \
                 patch.object(server.snapshots, "get_machine", return_value={"machineRisk": {"level": "low"}}), \
                 patch.object(server.snapshots, "save_machine") as snapshot:
                client = server.app.test_client()
                self.assertEqual(200, client.post("/dados", json=payload, headers={"X-Device-Token": "test-only-token-123"}).status_code)
                auth.assert_called_once_with("dev1", "test-only-token-123")
                self.assertEqual("RISCO", save.call_args.kwargs["device_local"]["statusGeral"])
                self.assertEqual({"level": "low"}, snapshot.call_args.args[2]["machineRisk"])
                self.assertEqual("RISCO", snapshot.call_args.args[2]["latestDeviceLocal"]["statusGeral"])
                for extra in [{"measurements": {}}, {"temperatura": 25}, {"prototype": None}]:
                    self.assertEqual(400, client.post("/dados", json={**payload, **extra}).status_code)
                save.assert_called_once()
                machine.return_value = {"fazendaId": "farm1", "sensoresConfigurados": [
                    {"sensorId": "ventoKmh", "type": "speed", "unit": "km_h", "scope": "machine_internal"}
                ]}
                self.assertEqual(400, client.post("/dados", json=payload).status_code)
                save.assert_called_once()
                machine.return_value = None
                self.assertEqual(401, client.post("/dados", json=payload).status_code)
                auth.side_effect = DeviceUnauthorizedError()
                self.assertEqual(401, client.post("/dados", json=payload).status_code)
        finally:
            server.app.config.clear()
            server.app.config.update(original)
