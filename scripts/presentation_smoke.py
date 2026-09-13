"""Read-only readiness plus isolated official-engine fixtures; never sends notifications."""
import argparse
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch
import requests
from scripts.seed_demo import preview, PROPERTY_ID, MACHINE_ID
from services.notification_service import NotificationDispatcher
from services.sompo_agro_agent.tools import AgroRiskTools


def check_fixture():
    bundle = preview("combined_critical")
    prop_status = bundle["responses"][f"/fazendas/{PROPERTY_ID}/status"]
    state = bundle["responses"][f"/fazendas/{PROPERTY_ID}/maquinas/{MACHINE_ID}/status"]
    assert state["machineRisk"]["level"] == "critical"
    assert state["operationalRisk"]["level"] == "critical"
    assert bundle["alerts"] and all(a["recommendations"] for a in bundle["alerts"])
    print("PASS fixture: property, machine, authoritative risks, alerts and recommendations")
    services = [Mock() for _ in range(7)]
    props, snapshots, machines, telemetry, devices, events, alerts = services
    props.listar.return_value = [prop_status["property"]]
    snapshots.list_properties.return_value = []
    snapshots.get_property.return_value = {"environmentalRisk": prop_status["currentRisk"], "analysisAt": bundle["generatedAt"]}
    snapshots.get_machine.return_value = state
    machines.listar.return_value = [state["identity"]]
    devices.list.return_value = []
    telemetry.mais_recente.return_value = None
    events.list.return_value = []
    alerts.list.return_value = bundle["alerts"]
    tools = AgroRiskTools(*services, lambda: {}, lambda: {})
    context = tools.get_agent_context("Por que esta propriedade está em risco?", PROPERTY_ID)
    assert context["somente_leitura"] and context["fazenda_id"] == PROPERTY_ID
    assert "critical" in str(tools.machines_esp32(PROPERTY_ID))
    print("PASS fixture: read-only Copilot context (not a live model response)")
    channel = Mock(name="fixture_channel")
    channel.name, channel.recipient_ref = "fixture", "fixture_operations"
    dispatcher = NotificationDispatcher(Mock(), channel)
    # All persistence boundaries are replaced before enabling enqueue in this isolated check.
    with patch.object(dispatcher, "_args", return_value=("fixture", lambda: "fixture")), patch.dict(os.environ, {"TELEGRAM_NOTIFICATIONS_ENABLED": "true"}), patch("services.notification_service.obter_documento", return_value=None), patch("services.notification_service.consultar_documentos", return_value=[]), patch("services.notification_service.criar_documento") as create:
        dispatcher.enqueue(bundle["alerts"][0])
        create.assert_not_called()  # DEMO must be excluded.
        dispatcher.enqueue({**bundle["alerts"][0], "fazendaId": "fixture_property", "demoData": False})
        create.assert_called_once()
    channel.send.assert_not_called()
    print("PASS fixture: outbox enqueue possible; DEMO excluded; zero deliveries")
    return bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://127.0.0.1:5000")
    parser.add_argument("--frontend", default="http://127.0.0.1:3100")
    parser.add_argument("--offline", action="store_true", help="Read explicitly exported DEMO, without requiring Firebase")
    args = parser.parse_args()
    failures = 0
    check_fixture()
    for label, url in (("backend healthy", args.backend + "/health"), ("frontend reachable", args.frontend + ("/?mode=demo" if args.offline else "/"))):
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            print("PASS " + label)
        except requests.RequestException:
            print("FAIL " + label); failures += 1
    try:
        payload = requests.get(args.frontend + "/api/command-center" + ("?mode=demo" if args.offline else ""), timeout=30).json()
        if payload.get("properties") and payload.get("machines"):
            print("PASS loaded property/machine scope: " + payload.get("source", "unknown"))
        else:
            print("WARNING property/machine data unavailable; use --offline after export")
        if payload.get("source") != ("demo" if args.offline else "backend"):
            failures += 1; print("FAIL requested data source unavailable")
    except (requests.RequestException, ValueError):
        print("FAIL frontend data contract"); failures += 1
    print("WARNING live Firebase, upstream sources and Ollama require separate local configuration")
    if args.offline and not failures:
        result = subprocess.run(["node", "scripts/presentation-check.mjs"], cwd=Path(__file__).resolve().parents[1] / "frontend",
                                env={**os.environ, "FRONTEND_URL": args.frontend}, check=False)
        failures += result.returncode != 0
    elif not args.offline:
        print("WARNING automated scenario browser smoke requires --offline; use product-check for isolated real-contract fixtures")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
