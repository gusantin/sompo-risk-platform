"""Presentation scopes over the same portfolio snapshot; no tenant authentication."""
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from services.live_case_service import LiveCaseService
from services.presentation_portfolio_service import PORTFOLIO, configured_portfolio
from services.propriedade_service import PropriedadeService, ValidacaoPropriedadeError

LOCK = RLock()


def scope_snapshot(snapshot, perspective, client=None):
    if perspective not in {"seguradora", "segurado"}:
        raise ValidacaoPropriedadeError("Perspectiva inválida.")
    result = deepcopy(snapshot)
    identities = {p["fazendaId"]: p for p in PORTFOLIO}
    for case in result.get("cases", []):
        if case.get("id") in identities:
            case["property"].update(identities[case["id"]])
    allowed_client = "Cliente A" if perspective == "segurado" else client
    result["cases"] = [c for c in result.get("cases", [])
                       if not allowed_client or c.get("property", {}).get("clientName") == allowed_client]
    result["perspective"] = perspective
    result["clientScope"] = allowed_client
    return result


def attach_operations(snapshot, alerts, notifications):
    for case in snapshot.get("cases", []):
        try:
            rows = alerts.list({"fazendaId": case["id"]}, limit=20)
            case["operationalState"] = {"openAlerts": sum(a.get("status") != "resolved" for a in rows),
                "scope": "20 recent alerts", "alerts": [{"alertId": a["alertId"], "status": a.get("status"),
                    "severity": a.get("severity"), "notifications": [{k: n.get(k) for k in
                        ("channel", "status", "deliveredAt")} for n in notifications.list_for_alert(a["alertId"])]} for a in rows]}
        except Exception:
            case["operationalState"] = None
    return snapshot


def create_property(path, data):
    service = configured_portfolio()
    with LOCK:
        snapshot = service.read(path)
        if not snapshot.get("cases"):
            raise ValidacaoPropriedadeError("Capture a apresentação antes de cadastrar uma fazenda.")
        def save(prop):
            snapshot["cases"].append({"id": prop["fazendaId"], "property": prop,
                "processingState": "waiting", "risk": {"score": None, "nivel": "dados_insuficientes", "fatores": []},
                "rawSources": {}, "provenance": {"identity": "demo", "environmental": {"origin": "unavailable", "state": "unavailable"}}})
            snapshot["generatedAt"] = datetime.now(timezone.utc).isoformat()
            LiveCaseService.save_snapshot(snapshot, path)
        return PropriedadeService.criar_demonstrativa("demo_portfolio_" + uuid4().hex, data, save)


def analyze_property(path, property_id):
    from integracoes.ibge import listar_municipios
    from services.sompo_agro_agent.tools import _normalize
    service = configured_portfolio()
    with LOCK:
        snapshot = scope_snapshot(service.read(path), "segurado")
        case = next((c for c in snapshot["cases"] if c["id"] == property_id), None)
        if not case:
            raise ValidacaoPropriedadeError("Fazenda fora do escopo permitido.")
        identity = deepcopy(case["property"])
    try:
        if not identity.get("ibgeCode"):
            municipality = next(m for m in listar_municipios(identity["estado"])
                                if _normalize(m["municipality"]) == _normalize(identity["municipio"]))
            identity["ibgeCode"] = municipality["ibgeCode"]
        captured = service.capture(snapshot, identities=[identity])["cases"][0]
        captured["processingState"] = "complete"
    except Exception:
        captured = deepcopy(case)
        captured["processingState"] = "unavailable"
    with LOCK:
        latest = service.read(path)
        latest["cases"] = [captured if c["id"] == property_id else c for c in latest["cases"]]
        latest["generatedAt"] = datetime.now(timezone.utc).isoformat()
        LiveCaseService.save_snapshot(latest, path)
    return captured
