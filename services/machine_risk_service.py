"""Motor determinístico de risco interno da máquina, dirigido por configuração."""

import math

from services.tendencia_service import metricas_tendencia
from services.unit_service import value_in_valid_range


MACHINE_RISK_VERSION = "1.0.0"


def _nivel(valor, thresholds):
    if valor >= thresholds.get("critical", math.inf): return "critical"
    if valor >= thresholds.get("high", math.inf): return "high"
    if valor >= thresholds.get("warning", math.inf): return "moderate"
    return "low"


def calcular_risco_maquina(maquina, leituras):
    sensores = {s.get("sensorId"): s for s in maquina.get("sensoresConfigurados", [])}
    componentes, evidencias = [], []
    for sensor_id, perfil in sensores.items():
        if perfil.get("scope") not in ("machine_internal", "machine_component") or not perfil.get("thresholds"):
            continue
        valores = []
        for leitura in reversed(leituras):
            medicoes = leitura.get("measurements", {})
            valor = medicoes.get(sensor_id)
            if (isinstance(valor, (int, float)) and not isinstance(valor, bool)
                    and math.isfinite(valor) and value_in_valid_range(valor, perfil)):
                valores.append(valor)
        if not valores: continue
        nivel = _nivel(valores[-1], perfil["thresholds"])
        tendencia = metricas_tendencia(valores)
        componentes.append(nivel)
        evidencias.append({"sensorId": sensor_id, "type": perfil.get("type"), "scope": perfil.get("scope"),
                           "target": perfil.get("target"), "value": valores[-1], "unit": perfil.get("unit"),
                           "level": nivel, "trend": tendencia})
    if not componentes:
        return {"version": MACHINE_RISK_VERSION, "status": "insufficient_data", "score": None,
                "level": "unknown", "confidence": "insufficient", "factors": [], "evidence": []}
    ordem = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
    level = max(componentes, key=ordem.get)
    return {"version": MACHINE_RISK_VERSION, "status": "ok", "score": None, "level": level,
            "confidence": "medium" if len(componentes) == 1 else "high",
            "factors": [f"{e['sensorId']}:{e['level']}" for e in evidencias], "evidence": evidencias,
            "method": "configured_threshold_categories_without_combined_numeric_score"}
