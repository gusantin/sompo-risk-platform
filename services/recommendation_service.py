"""Authoritative operational guidance from explicit official conditions, never an LLM."""

RULES = {
    "environmental_risk": "Revisar as atividades expostas aos fatores ambientais informados e acompanhar a avaliação oficial.",
    "environmental_fire_risk": "Revisar atividades com risco de ignição e acompanhar as condições ambientais.",
    "hotspot_near_property": "Verificar o foco informado e revisar atividades com risco de ignição nas áreas expostas.",
    "machine_near_hotspot": "Revisar a operação e avaliar deslocar máquinas expostas para área apropriada.",
    "operational_combined_risk": "Revisar a operação exposta e inspecionar a máquina antes de continuar.",
    "machine_risk": "Inspecionar os componentes sinalizados antes de continuar a operação.",
    "telemetry_stale": "Inspecionar conectividade e dispositivo antes de confiar no estado da máquina.",
    "device_offline": "Inspecionar conectividade e dispositivo antes de confiar no estado da máquina.",
    "severe_weather_warning": "Suspender ou revisar operações de campo expostas ao aviso meteorológico.",
}


def recommendations(condition):
    kind = condition.get("type") or condition.get("eventType")
    text = RULES.get(kind)
    rule = kind
    if kind == "machine_risk" and any(
        e.get("type") == "temperature" and e.get("scope") in {"machine_internal", "machine_component"}
        and e.get("level") in {"high", "critical"} for e in condition.get("evidence", []) if isinstance(e, dict)
    ):
        rule = "machine_overheat"
        text = "Parar e inspecionar a máquina com temperatura elevada antes de continuar a operação."
    if not text:
        return []
    return [{"ruleId": rule, "version": "1", "text": text,
             "basis": kind, "meaning": "operational_guidance_not_safety_guarantee"}]


def machine_recommendations(machine_risk, health):
    """Same official guidance for status endpoints and read-only agent contexts."""
    result = []
    if machine_risk.get("status") != "insufficient_data" and machine_risk.get("level") in {"high", "critical"}:
        result.extend(recommendations({"type": "machine_risk", "evidence": machine_risk.get("evidence") or []}))
    if health.get("status") in {"stale", "offline"}:
        result.extend(recommendations({"type": "telemetry_stale" if health["status"] == "stale" else "device_offline"}))
    return result
