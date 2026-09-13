"""Intentional isolated DEMO through persisted AlertService -> outbox -> worker -> adapter."""
import argparse
import json
import os
import re
import hashlib
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from config import Config


def portfolio_message(client, path=None):
    """Read the canonical snapshot without refreshing providers or calculating risk."""
    from services.presentation_portfolio_service import configured_portfolio, PORTFOLIO
    from services.sompo_agro_agent.presentation import portfolio_context
    service = configured_portfolio()
    raw = service.read(path or Config.PRESENTATION_PORTFOLIO_PATH)
    identity = next((p for p in PORTFOLIO if p["clientName"] == "Cliente " + client), None)
    if not identity:
        raise ValueError("Unknown portfolio client.")
    snapshot = service.snapshot(raw)
    projected = portfolio_context(snapshot, identity["fazendaId"])["items"][0]
    case = next(c for c in snapshot["cases"] if c["id"] == identity["fazendaId"])
    if projected["provenance"]["environmental"]["state"] in {"unavailable", "insufficient_data"}:
        raise ValueError("Real snapshot evidence unavailable or insufficient.")
    risk = case["risk"]
    severity = {"alto": "high", "critico": "critical", "moderado": "moderate", "baixo": "low"}.get(risk.get("nivel"), risk.get("nivel"))
    evidence = deepcopy(case.get("environmentalEvidence") or [])
    # Prioritize the stored satellite observation; retain its original observation time.
    evidence.sort(key=lambda e: 0 if e.get("unit") == "km" else 1)
    if case.get("riskType") == "incendio":
        for item in evidence:
            if item.get("unit") == "km":
                item["label"] = "Foco de calor — distância ao ponto municipal (não confirma incêndio)"
    kind = "environmental_fire_risk" if case.get("riskType") == "incendio" else "environmental_risk"
    if case.get("riskType") == "weather":
        warning = next((w for w in case.get("weatherWarnings", []) if w.get("severity") == severity), None)
        if not warning:
            raise ValueError("Matched official weather warning unavailable.")
        kind, evidence = "severe_weather_warning", deepcopy(warning["evidence"])
    prop = case["property"]
    original = next(c for c in raw["cases"] if c["id"] == case["id"])
    fingerprint = hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    return {"type": kind, "severity": severity, "riskType": case["riskType"],
        "propertyName": prop["nome"], "municipality": prop["municipio"], "state": prop["estado"],
        "presentationTimezone": prop.get("timezone") or "America/Sao_Paulo",
        "presentationPortfolioId": case["id"], "presentationSnapshotHash": fingerprint,
        "provenance": projected["provenance"], "factors": deepcopy(projected["factors"]),
        "evidence": evidence, "demoData": True, "score": risk.get("score"),
        "sourceAnalysisId": "presentation_snapshot_" + fingerprint,
        "environmentalContext": case.get("environmentalContext") or {}}


def run(run_id, action=None, deliver=False, portfolio_client=None):
    if Config.ENVIRONMENT not in {"development", "test"} or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", run_id):
        raise ValueError("Use development/test and a valid isolated run ID.")
    presentation = portfolio_message(portfolio_client) if portfolio_client else None
    if presentation:
        from services.notification_service import eligible
        if action is not None:
            raise ValueError("Portfolio severity comes from the snapshot; do not use --action.")
        if not eligible(presentation):
            return {"delivered": False, "queued": False, "severity": presentation["severity"],
                    "blocked": "Stored classification is not eligible for Telegram; no writes performed."}
    action = action or "high"
    configured = (os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false").lower() == "true"
                  and bool(os.getenv("TELEGRAM_BOT_TOKEN")) and bool(os.getenv("TELEGRAM_CHAT_ID")))
    if not configured or not Path(Config.FIREBASE_KEY_PATH).is_file():
        return {"configured": bool(configured), "firebaseCredentialPresent": Path(Config.FIREBASE_KEY_PATH).is_file(),
                "delivered": False, "blocked": "Configure server environment and Firebase credentials; no writes performed."}
    from server import alerts, notifications, firebase
    from scripts.seed_demo import preview, definitions
    from services.alert_service import _alert_id
    from services.firestore_service import criar_documento, obter_documento, atualizar_documento
    firebase.initialize()
    args = (firebase.firestore_url, firebase.obter_token)
    pid = "demo_telegram_" + run_id
    if presentation:
        pid += "_" + portfolio_client
    prop = obter_documento(*args, "fazendas", pid)
    if prop and prop.get("demoData") is not True:
        raise ValueError("Existing document is not DEMO.")
    if presentation and prop and prop.get("presentationSnapshotHash") != presentation["presentationSnapshotHash"]:
        raise ValueError("Run ID already belongs to another snapshot. Use a new run ID intentionally.")
    if not prop:
        prop = ({"nome": presentation["propertyName"], "municipio": presentation["municipality"],
                 "estado": presentation["state"], "presentationSnapshotHash": presentation["presentationSnapshotHash"],
                 "presentationPortfolioId": presentation["presentationPortfolioId"]} if presentation else definitions()[0])
        prop.update(fazendaId=pid, demoData=True, nome="DEMO Telegram " + run_id,
                    createdAt=datetime.now(timezone.utc))
        if presentation:
            prop["nome"] = presentation["propertyName"]
        criar_documento(*args, "fazendas", pid, prop)
    key = f"{pid}|-|{presentation['type']}|{presentation['riskType']}" if presentation else f"{pid}|-|environmental_fire_risk|incendio"
    if presentation and presentation["type"] == "severe_weather_warning":
        key += "|" + presentation["sourceAnalysisId"]
    identifier = _alert_id(key)
    if presentation:
        scenario = "presentation_portfolio_snapshot"
        alert = alerts.get(identifier)
        if alert and (alert.get("status") != "open" or alert.get("sourceAnalysisId") != presentation["sourceAnalysisId"]):
            raise ValueError("Existing run is closed or belongs to another snapshot.")
        if not alert:
            alert, _ = alerts.emit(presentation["type"], presentation["severity"], pid, presentation["riskType"],
                presentation["factors"], presentation["evidence"], presentation["sourceAnalysisId"])
        alert = {**alert, **presentation}
        if atualizar_documento(*args, "alerts", identifier, alert) is None:
            raise ValueError("Presentation metadata was not persisted.")
    elif action in {"acknowledge", "resolve"}:
        alert = alerts.update_status(identifier, "resolved" if action == "resolve" else "acknowledged", actor_id="demo_telegram_validation")
        if not alert:
            raise ValueError("Create the isolated alert first.")
        scenario = "persisted_alert_action"
    else:
        scenario = "combined_critical" if action == "critical" else "environmental_fire_high"
        source = next(a for a in preview(scenario)["alerts"] if a["type"] == "environmental_fire_risk")
        alert, _ = alerts.emit(source["type"], source["severity"], pid, source["riskType"],
                               source["factors"], source["evidence"], "demo_telegram_" + scenario)
    notifications.enqueue(alert, allow_demo=True)
    rows = notifications.list_for_alert(identifier)
    ids = {row["notificationId"] for row in rows}
    before = {r["notificationId"]: r.get("attempts", 0) for r in rows}
    if deliver:
        notifications.deliver_pending(notification_ids=ids)
    first = notifications.list_for_alert(identifier)
    if deliver:
        notifications.enqueue(alert, allow_demo=True)
        notifications.deliver_pending(notification_ids=ids)
    second = notifications.list_for_alert(identifier)
    return {"configured": True, "scenario": scenario, "alertId": identifier, "alertPersisted": alerts.get(identifier) is not None,
            "alertStatus": alert["status"], "queued": bool(ids), "workerProcessed": deliver,
            "deduplicated": {r["notificationId"]: r.get("attempts") for r in first} == {r["notificationId"]: r.get("attempts") for r in second},
            "delivered": any(r.get("status") == "delivered" for r in second), "previousAttempts": before, "notifications": second}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--action", choices=("high", "critical", "acknowledge", "resolve"))
    parser.add_argument("--portfolio-client", choices=("A", "B", "C"))
    parser.add_argument("--preview", action="store_true", help="Render the portfolio message locally, without persistence or delivery.")
    parser.add_argument("--deliver", action="store_true", help="Intentionally send only this isolated DEMO's outbox entries.")
    args = parser.parse_args()
    try:
        if args.preview:
            if not args.portfolio_client or args.deliver or args.action:
                parser.error("--preview requires --portfolio-client and excludes --deliver/--action")
            from services.notification_messages import message_for
            from services.notification_service import eligible
            presentation = portfolio_message(args.portfolio_client)
            print(message_for(presentation, "alert") if eligible(presentation) else
                  "Classificação armazenada não elegível para Telegram: " + str(presentation["severity"]))
        else:
            print(json.dumps(run(args.run_id, args.action, args.deliver, args.portfolio_client), default=str, ensure_ascii=False))
    except Exception:
        raise SystemExit("Isolated Telegram validation failed; inspect safe persisted delivery status and server configuration.") from None
