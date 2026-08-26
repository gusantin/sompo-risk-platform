"""Seed explícito e idempotente de uma fazenda DEMO; nunca roda no startup."""

import argparse
import os
from datetime import datetime, timedelta, timezone

from config import Config
from scripts.scenario_generator import generate_scenario
from services.device_service import DeviceService
from services.alert_service import AlertService
from services.firebase_client import FirebaseClient
from services.firestore_service import upsert_documento
from services.maquina_service import MaquinaService, validar_maquina
from services.machine_risk_service import calcular_risco_maquina
from services.operational_risk_service import calcular_risco_operacional
from services.propriedade_service import PropriedadeService, validar_propriedade
from services.telemetria_service import TelemetriaService
from services.risk_explanation_service import explain_risks
from services.snapshot_service import SnapshotService
from services.unit_service import validate_measurements


PROPERTY_ID = "demo_fazenda_01"
MACHINE_ID = "demo_trator_01"
DEVICE_ID = "demo_device_01"


def definitions(now=None):
    current = now or datetime.now(timezone.utc)
    property_data = validar_propriedade({
        "nome": "DEMO Fazenda SOMPO", "municipio": "Município fictício", "estado": "MT",
        "latitude": -15.6, "longitude": -56.1, "areaHectares": 120,
        "atividadePrincipal": "agricultura_demo", "culturas": [{"nome": "soja_demo", "atual": True}],
        "quantidadeMaquinas": 1, "tiposMaquinas": ["trator_demo"],
    })
    machine_data = validar_maquina({
        "nome": "DEMO Trator 01", "tipo": "trator_demo", "status": "ativo", "possuiGps": True,
        "latitude": -15.6, "longitude": -56.1, "lastLocationAt": current,
        "sensoresConfigurados": [
            {"sensorId": "demo_temp_motor", "type": "temperature", "scope": "machine_component",
             "target": "engine", "unit": "celsius", "thresholds": {"warning": 70, "high": 85, "critical": 95},
             "metadata": {"validRange": {"min": -40, "max": 150}, "demoData": True}},
            {"sensorId": "demo_vibracao", "type": "vibration", "scope": "machine_component",
             "target": "engine", "unit": "m_s2", "thresholds": {"warning": 4, "high": 6, "critical": 8},
             "metadata": {"validRange": {"min": 0, "max": 50}, "demoData": True}},
        ],
        "metadata": {"demoData": True},
    })
    return property_data, machine_data


def execute(dry_run=True, scenario="normal"):
    property_data, machine_data = definitions()
    generated = generate_scenario(scenario)
    summary = {"dryRun": dry_run, "demoData": True, "propertyId": PROPERTY_ID,
               "machineId": MACHINE_ID, "deviceId": DEVICE_ID, "telemetryCount": len(generated["telemetry"]),
               "scenario": scenario}
    if dry_run:
        return summary
    token = os.getenv("DEMO_DEVICE_TOKEN")
    if not token:
        raise RuntimeError("DEMO_DEVICE_TOKEN é obrigatório no modo --write e não deve ser versionado.")
    firebase = FirebaseClient(Config.FIREBASE_KEY_PATH)
    firebase.initialize()
    args = (firebase.firestore_url, firebase.obter_token)
    now = datetime.now(timezone.utc)
    upsert_documento(*args, "fazendas", PROPERTY_ID, {**property_data, "fazendaId": PROPERTY_ID, "demoData": True,
                       "createdAt": now, "updatedAt": now})
    upsert_documento(*args, "maquinas", f"{PROPERTY_ID}__{MACHINE_ID}", {**machine_data,
                       "fazendaId": PROPERTY_ID, "maquinaId": MACHINE_ID, "demoData": True,
                       "createdAt": now, "updatedAt": now})
    machines = MaquinaService(firebase, PropriedadeService(firebase))
    device_service = DeviceService(firebase, machines, Config.DEVICE_TOKEN_HASH_ITERATIONS)
    current_device = device_service.get(DEVICE_ID)
    if current_device is None:
        device_service.create(DEVICE_ID, PROPERTY_ID, MACHINE_ID, token, {"demoData": True})
    else:
        device_service.rotate(DEVICE_ID, token)
    telemetry_service = TelemetriaService(firebase)
    normalized_readings = []
    for reading in generated["telemetry"]:
        values, descriptors = validate_measurements(reading["measurements"], {"sensoresConfigurados": machine_data["sensoresConfigurados"]})
        telemetry_service.save(DEVICE_ID, PROPERTY_ID, MACHINE_ID, values, descriptors,
                               reading["observedAt"], reading["readingId"], "DEMO_SEED")
        normalized_readings.append({"dataHora": reading["observedAt"], "measurements": values})
    last_seen = now - timedelta(minutes=30) if scenario == "stale_device" else now
    device_service.touch(DEVICE_ID, last_seen)
    fresh_readings = [item for item in normalized_readings
                      if telemetry_service.classificar(item, Config.IOT_MAX_AGE_SECONDS, now)["fresh"]]
    machine_risk = calcular_risco_maquina(machine_data, list(reversed(fresh_readings)))
    operational_risk = calcular_risco_operacional(
        generated["environmentalRisk"], machine_risk, True, True,
        2 if scenario in {"environmental_fire_high", "combined_critical"} else None,
        Config.OPERATIONAL_HOTSPOT_DISTANCE_KM,
    )
    analysis_id = f"demo_analysis_{scenario}"
    machine_results = [{"machine": {**machine_data, "maquinaId": MACHINE_ID},
        "machineRisk": machine_risk, "operationalContextRisk": operational_risk,
        "location": {"locationCurrent": True, "insideProperty": True,
                     "nearestHotspotDistanceKm": 2 if scenario in {"environmental_fire_high", "combined_critical"} else None,
                     "nearestHotspotAgeHours": 1 if scenario in {"environmental_fire_high", "combined_critical"} else None}}]
    upsert_documento(*args, "analises_risco", analysis_id, {
        "fazendaId": PROPERTY_ID, "timestamp": now, "demoData": True, "scenario": scenario,
        "riskEngineVersion": "demo_seed", "riskContextVersion": "demo_seed",
        "score": generated["environmentalRisk"]["geral"]["score"],
        "nivel": generated["environmentalRisk"]["geral"]["nivel"],
        "riscos": generated["environmentalRisk"], "machineResults": machine_results,
    })
    coverage = {"weatherAvailable": False, "satelliteAvailable": False, "geospatialAvailable": False,
                "historyAvailable": False, "iotAvailable": bool(fresh_readings), "syntheticDemoData": True}
    snapshot_service = SnapshotService(firebase)
    snapshot_service.save_property(PROPERTY_ID, {
        "environmentalRisk": generated["environmentalRisk"],
        "riskExplanations": explain_risks(generated["environmentalRisk"], coverage),
        "coverage": coverage, "sourceHealth": {"demo_seed": {"status": "synthetic_demo"}},
        "trend": {"samples": 1, "risks": {}}, "analysisAt": now,
        "sourceAnalysisId": analysis_id, "demoData": True, "scenario": scenario,
    })
    health = device_service.health(last_seen, Config.DEVICE_STALE_AFTER_SECONDS,
                                   Config.DEVICE_OFFLINE_AFTER_SECONDS, now)
    latest = normalized_readings[-1] if normalized_readings else {}
    snapshot_service.save_machine(PROPERTY_ID, MACHINE_ID, {
        "identity": {"maquinaId": MACHINE_ID, "nome": machine_data["nome"],
                     "tipo": machine_data["tipo"], "status": machine_data["status"]},
        "deviceId": DEVICE_ID, "deviceHealth": health, "lastSeenAt": last_seen,
        "latestTelemetryAt": latest.get("dataHora"), "latestMeasurements": latest.get("measurements", {}),
        "machineRisk": machine_risk, "operationalRisk": operational_risk,
        "environmentalContext": generated["environmentalRisk"],
        "location": machine_results[0]["location"], "sourceAnalysisId": analysis_id,
        "attention": (machine_risk.get("level") in {"high", "critical"}
                      or operational_risk.get("level") in {"high", "critical"}
                      or health.get("status") in {"stale", "offline"}),
        "demoData": True, "scenario": scenario,
    })
    alert_service = AlertService(firebase, Config.ALERT_COOLDOWN_SECONDS, Config.ALERT_HOTSPOT_DISTANCE_KM,
                                 Config.ALERT_HOTSPOT_CRITICAL_DISTANCE_KM, Config.HOTSPOT_MAX_AGE_HOURS)
    property_hotspot = ({"distanciaKm": 2, "ageHours": 1}
                        if scenario in {"environmental_fire_high", "combined_critical"} else None)
    emitted = alert_service.evaluate(PROPERTY_ID, generated["environmentalRisk"], machine_results,
                                     analysis_id, property_hotspot=property_hotspot)
    active_ids = {item["alert"].get("alertId") for item in emitted}
    for existing in alert_service.list({"fazendaId": PROPERTY_ID}, 100):
        if existing.get("status") in {"open", "acknowledged"} and existing.get("alertId") not in active_ids:
            alert_service.update_status(existing["alertId"], "resolved", "demo_seed")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Cria dados sintéticos prefixados com demo_.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Mostra o plano sem gravar (padrão).")
    mode.add_argument("--write", action="store_true", help="Grava explicitamente no Firebase configurado.")
    parser.add_argument("--scenario", default="normal", choices=sorted({
        "normal", "machine_overheat", "environmental_fire_high", "combined_critical", "stale_device",
    }))
    args = parser.parse_args()
    print(execute(dry_run=not args.write, scenario=args.scenario))


if __name__ == "__main__":
    main()
