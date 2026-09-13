"""Seed explícito e idempotente de uma fazenda DEMO; nunca roda no startup."""

import argparse
import os
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from config import Config
from scripts.scenario_generator import generate_scenario
from services.device_service import DeviceService
from services.alert_service import AlertService, _alert_id
from services.recommendation_service import recommendations, machine_recommendations
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


def preview(scenario="normal", now=None):
    """Offline fixtures from the existing scenario/risk/alert engines. Never calls Firebase."""
    now = now or datetime.now(timezone.utc)
    prop, machine = definitions(now)
    prop.update(fazendaId=PROPERTY_ID, demoData=True)
    machine.update(maquinaId=MACHINE_ID, fazendaId=PROPERTY_ID, demoData=True)
    generated = generate_scenario(scenario, now)
    readings = [{"dataHora": r["observedAt"], "measurements": r["measurements"]} for r in generated["telemetry"]]
    fresh = [r for r in readings if TelemetriaService.classificar(r, Config.IOT_MAX_AGE_SECONDS, now)["fresh"]]
    internal = calcular_risco_maquina(machine, list(reversed(fresh)))
    near = scenario in {"environmental_fire_high", "combined_critical"}
    operational = calcular_risco_operacional(generated["environmentalRisk"], internal, True, True,
                                           2 if near else None, Config.OPERATIONAL_HOTSPOT_DISTANCE_KM)
    last_seen = now - timedelta(minutes=30) if scenario == "stale_device" else now
    health = DeviceService.health(last_seen, Config.DEVICE_STALE_AFTER_SECONDS, Config.DEVICE_OFFLINE_AFTER_SECONDS, now)
    class PreviewAlerts(AlertService):
        # Only persistence is replaced; official evaluate decides every alert condition.
        def emit(self, alert_type, severity, fazenda_id, risk_type, factors, evidence,
                 source_analysis_id, maquina_id=None, source_event_id=None, now=None):
            key = "|".join(str(v or "-") for v in (fazenda_id, maquina_id, alert_type, risk_type))
            row = {"alertId": _alert_id(key), "fazendaId": fazenda_id, "maquinaId": maquina_id,
                   "type": alert_type, "severity": severity, "riskType": risk_type, "status": "open",
                   "factors": factors, "evidence": evidence, "sourceAnalysisId": source_analysis_id,
                   "sourceEventId": source_event_id, "createdAt": generated["generatedAt"],
                   "lastTriggeredAt": generated["generatedAt"], "demoData": True}
            return {**row, "recommendations": recommendations(row)}, False
    emitted = PreviewAlerts(None).evaluate(PROPERTY_ID, generated["environmentalRisk"], [{
        "machine": machine, "machineRisk": internal, "operationalContextRisk": operational,
        "location": {"locationCurrent": scenario != "stale_device", "nearestHotspotDistanceKm": 2 if near else None,
                     "nearestHotspotAgeHours": 1 if near else None}}], "demo_preview_" + scenario,
        property_hotspot={"distanciaKm": 2, "ageHours": 1} if near else None)
    alerts = [item["alert"] for item in emitted]
    status = {"identity": machine, "deviceId": DEVICE_ID, "demoData": True, "deviceHealth": health,
        "latestTelemetryAt": readings[-1]["dataHora"], "lastSeenAt": last_seen,
        "latestMeasurements": readings[-1]["measurements"],
        "telemetryFreshness": TelemetriaService.classificar(readings[-1], Config.IOT_MAX_AGE_SECONDS, now),
        "machineRisk": internal, "operationalRisk": operational, "environmentalContext": generated["environmentalRisk"],
        "recommendations": machine_recommendations(internal, health),
        "mapLocation": {"latitude": machine["latitude"], "longitude": machine["longitude"], "current": scenario != "stale_device"}}
    property_status = {"property": prop, "currentRisk": generated["environmentalRisk"], "lastAnalysisAt": now,
        "machines": [machine], "alerts": alerts, "alertCount": len(alerts),
        "riskExplanations": explain_risks(generated["environmentalRisk"], {"syntheticDemoData": True}),
        "sourceHealth": {"demo": {"status": "synthetic_demo"}}}
    return {"demoData": True, "scenario": scenario, "generatedAt": now, "alerts": alerts, "responses": {
        "/dashboard?limit=20": {"properties": [{"property": prop, "currentRisk": generated["environmentalRisk"]["geral"]}], "alerts": alerts},
        f"/fazendas/{PROPERTY_ID}/status": property_status,
        f"/fazendas/{PROPERTY_ID}/maquinas/{MACHINE_ID}/status": status}}


def export_preview(path, scenario):
    target = Path(path).resolve()
    # Exports never overwrite an existing unrelated file or anything outside ignored artifacts.
    root = (Path(__file__).resolve().parents[1] / "frontend" / "artifacts").resolve()
    if root not in target.parents or target.suffix != ".json":
        raise ValueError("Exportação deve ser um .json dentro de frontend/artifacts.")
    if target.exists() and json.loads(target.read_text(encoding="utf-8")).get("demoData") is not True:
        raise ValueError("Arquivo existente não é uma exportação DEMO.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(preview(scenario), default=lambda v: v.isoformat(), ensure_ascii=False), encoding="utf-8")
    return {"demoData": True, "scenario": scenario, "exported": str(target), "firebaseWrites": 0}


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
    if Config.ENVIRONMENT not in {"development", "test"}:
        raise RuntimeError("Seed --write permitido apenas em development/test.")
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
                               reading["observedAt"], reading["readingId"] + "_" + now.strftime("%Y%m%d%H%M%S%f"), "DEMO_SEED")
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
    mode.add_argument("--export", metavar="PATH", help="Exporta o cenário offline em frontend/artifacts; não grava Firebase.")
    parser.add_argument("--scenario", default="normal", choices=sorted({
        "normal", "machine_overheat", "environmental_fire_high", "combined_critical", "stale_device",
    }))
    args = parser.parse_args()
    print(export_preview(args.export, args.scenario) if args.export else execute(dry_run=not args.write, scenario=args.scenario))


if __name__ == "__main__":
    main()
