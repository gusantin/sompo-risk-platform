"""Provisiona o ESP32 físico sem reutilizar identidade ou credencial DEMO."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from config import Config
from services.device_service import DeviceService, DeviceUnauthorizedError
from services.firebase_client import FirebaseClient
from services.firestore_service import obter_documento
from services.maquina_service import MaquinaService
from services.propriedade_service import PropriedadeService
from services.snapshot_service import SnapshotService


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_SECRETS = ROOT / "firmware" / "secrets.h"
BACKEND_ENV = ROOT / ".env"
FRONTEND_ENV = ROOT / "frontend" / ".env.local"
FARM_ID = "demo_fazenda_01"
MACHINE_ID = "trator_fisico_01"
DEVICE_ID = "esp32_trator_01"
SERVER_URL = "http://192.168.68.103:5000/dados"


def _env_value(path: Path, name: str) -> str | None:
    if not path.exists():
        return None
    match = re.search(rf"^{re.escape(name)}=(.*)$", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return match.group(1).strip().strip('"').strip("'") if match else None


def _upsert_env(path: Path, values: dict[str, str]) -> None:
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = content.splitlines()
    remaining = dict(values)
    output = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)
    if output and output[-1]:
        output.append("")
    output.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _ensure_application_auth() -> None:
    app_key = _env_value(BACKEND_ENV, "APP_API_KEYS")
    if not app_key:
        app_key = secrets.token_urlsafe(32)
        _upsert_env(BACKEND_ENV, {"APP_API_KEYS": app_key})
    _upsert_env(FRONTEND_ENV, {
        "SOMPO_BACKEND_URL": "http://127.0.0.1:5000",
        "SOMPO_BACKEND_API_KEY": app_key.split(",", 1)[0],
        "SOMPO_PHYSICAL_FARM_ID": FARM_ID,
        "SOMPO_PHYSICAL_MACHINE_ID": MACHINE_ID,
    })


def _read_define(name: str) -> str | None:
    if not FIRMWARE_SECRETS.exists():
        return None
    match = re.search(
        rf'^#define\s+{re.escape(name)}\s+"([^"]*)"\s*$',
        FIRMWARE_SECRETS.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    return match.group(1) if match else None


def _write_firmware_secrets(token: str) -> None:
    ssid = _read_define("WIFI_SSID_VALUE") or "PREENCHA_SEU_WIFI"
    password = _read_define("WIFI_PASSWORD_VALUE") or "PREENCHA_SUA_SENHA"
    content = (
        "#pragma once\n\n"
        "// Arquivo local ignorado pelo Git. Não compartilhe nem versione.\n"
        f'#define WIFI_SSID_VALUE "{ssid}"\n'
        f'#define WIFI_PASSWORD_VALUE "{password}"\n'
        f'#define SERVER_URL_VALUE "{SERVER_URL}"\n'
        f'#define DEVICE_ID_VALUE "{DEVICE_ID}"\n'
        f'#define DEVICE_TOKEN_VALUE "{token}"\n'
    )
    FIRMWARE_SECRETS.write_text(content, encoding="utf-8")


def _provision() -> tuple[FirebaseClient, str, dict]:
    _ensure_application_auth()
    firebase = FirebaseClient(Config.FIREBASE_KEY_PATH)
    properties = PropriedadeService(firebase)
    machines = MaquinaService(firebase, properties)
    devices = DeviceService(firebase, machines, Config.DEVICE_TOKEN_HASH_ITERATIONS)

    farm = properties.obter(FARM_ID)
    if farm is None:
        raise RuntimeError(f"Fazenda existente '{FARM_ID}' não encontrada; nenhum vínculo foi inventado.")

    machine = machines.obter(FARM_ID, MACHINE_ID)
    if machine is None:
        machine = machines.criar(FARM_ID, MACHINE_ID, {
            "nome": "Trator 01",
            "tipo": "trator",
            "status": "ativo",
            "possuiGps": False,
            "sensoresConfigurados": [],
            "metadata": {
                "deviceModel": "ESP32 + DHT11",
                "physicalTelemetry": True,
            },
        })
    elif machine.get("demoData") is True:
        raise RuntimeError("A identidade reservada para o trator físico está marcada como DEMO.")

    device = devices.get(DEVICE_ID)
    token = _read_define("DEVICE_TOKEN_VALUE")
    token_is_local = bool(token and token != "TOKEN_PROVISIONADO_FORA_DO_GIT")
    if device is None:
        token = secrets.token_urlsafe(32)
        devices.create(DEVICE_ID, FARM_ID, MACHINE_ID, token, {
            "hardwareModel": "ESP32",
            "sensorModel": "DHT11",
            "physicalDevice": True,
        })
        _write_firmware_secrets(token)
    else:
        if device.get("fazendaId") != FARM_ID or device.get("maquinaId") != MACHINE_ID:
            raise RuntimeError("O deviceId físico já existe com associação diferente.")
        if not token_is_local:
            token = secrets.token_urlsafe(32)
            devices.rotate(DEVICE_ID, token)
            _write_firmware_secrets(token)
        else:
            try:
                devices.authenticate(DEVICE_ID, token)
            except DeviceUnauthorizedError:
                token = secrets.token_urlsafe(32)
                devices.rotate(DEVICE_ID, token)
                _write_firmware_secrets(token)

    return firebase, token, {
        "farmName": farm.get("nome", FARM_ID),
        "machineName": machine.get("nome", MACHINE_ID),
    }


def _smoke(firebase: FirebaseClient, token: str) -> dict:
    payload = {
        "deviceId": DEVICE_ID,
        "readingId": "esp32_migration_test_001",
        "temperatura": 25.4,
        "umidade": 61.2,
    }
    request = urllib.request.Request(
        SERVER_URL,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Device-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        safe_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Smoke test HTTP {error.code}: {safe_body}") from error
    if status != 200:
        raise RuntimeError(f"Smoke test retornou HTTP {status}.")
    expected = {"deviceId": DEVICE_ID, "fazendaId": FARM_ID, "maquinaId": MACHINE_ID}
    if any(body.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Resposta do smoke test não preservou a associação provisionada.")

    document_id = body.get("documentoId")
    latest = obter_documento(firebase.firestore_url, firebase.obter_token, "leituras_sensores", document_id)
    if not latest or latest.get("deviceId") != DEVICE_ID:
        raise RuntimeError("Leitura do smoke test não foi encontrada na persistência.")
    if latest.get("measurements") != {"temperature": 25.4, "humidity": 61.2}:
        raise RuntimeError("Valores persistidos pelo smoke test divergem do payload.")
    snapshot = SnapshotService(firebase).get_machine(FARM_ID, MACHINE_ID) or {}
    if snapshot.get("deviceId") != DEVICE_ID:
        raise RuntimeError("Snapshot da máquina não foi associado ao dispositivo físico.")
    return {
        "httpStatus": status,
        "deduplicated": body.get("deduplicated") is True,
        "documentId": document_id,
        "persistence": "verified",
        "snapshot": "verified",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Envia e verifica a leitura física simulada.")
    args = parser.parse_args()
    firebase, token, identity = _provision()
    result = {
        "status": "provisioned",
        "farmId": FARM_ID,
        "farmName": identity["farmName"],
        "machineId": MACHINE_ID,
        "machineName": identity["machineName"],
        "deviceId": DEVICE_ID,
        "serverUrl": SERVER_URL,
        "firmwareSecrets": str(FIRMWARE_SECRETS.relative_to(ROOT)),
    }
    if args.smoke:
        result["smoke"] = _smoke(firebase, token)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
