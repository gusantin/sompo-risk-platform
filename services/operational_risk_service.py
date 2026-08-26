"""Regras auditáveis de risco operacional contextual, sem falsa precisão."""


OPERATIONAL_RISK_VERSION = "1.0.0"
ORDEM = {"unknown": -1, "dados_insuficientes": -1, "low": 0, "baixo": 0, "moderate": 1, "moderado": 1,
         "high": 2, "alto": 2, "critical": 3, "critico": 3, "crítico": 3}
OPERATING_STATUSES = {"ativo", "operando", "active", "operating", "em_operacao", "em operação"}


def machine_is_operating(machine):
    return str((machine or {}).get("status", "")).strip().lower() in OPERATING_STATUSES


def calcular_risco_operacional(environmental_risk, machine_risk, location_current=False, inside_property=None,
                               nearest_hotspot_distance_km=None, hotspot_distance_threshold_km=10):
    ambiental = environmental_risk.get("incendio", {}).get("nivel", "unknown")
    maquina = machine_risk.get("level", "unknown")
    a, m = ORDEM.get(str(ambiental).lower(), -1), ORDEM.get(str(maquina).lower(), -1)
    fatores = []
    if a >= 2: fatores.append("environmental_fire_elevated")
    if m >= 2: fatores.append("machine_risk_elevated")
    if not location_current: fatores.append("machine_location_unavailable_or_stale")
    if inside_property is False: fatores.append("machine_outside_property")
    hotspot_proximo = (nearest_hotspot_distance_km is not None
                       and nearest_hotspot_distance_km <= hotspot_distance_threshold_km)
    if hotspot_proximo: fatores.append(f"recent_hotspot_within_{hotspot_distance_threshold_km:g}km_of_machine")
    if a < 0 and m < 0:
        nivel, status = "unknown", "insufficient_data"
    elif a >= 3 and m >= 2 and inside_property is not False:
        nivel, status = "critical", "ok"
    elif m >= 3 or a >= 3 or (a >= 2 and m >= 2) or (a >= 2 and hotspot_proximo):
        nivel, status = "high", "ok"
    elif max(a, m) >= 1:
        nivel, status = "moderate", "ok"
    else:
        nivel, status = "low", "ok"
    return {"version": OPERATIONAL_RISK_VERSION, "status": status, "score": None, "level": nivel,
            "factors": fatores, "locationCurrent": location_current, "insideProperty": inside_property,
            "nearestHotspotDistanceKm": nearest_hotspot_distance_km,
            "method": "explicit_state_rules_v1"}
