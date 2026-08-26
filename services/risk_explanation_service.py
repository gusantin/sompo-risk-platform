"""Explicações determinísticas: confiança descreve cobertura, não sinistro futuro."""


CONFIDENCE = {"alta": "high", "media": "medium", "baixa": "low", "insuficiente": "insufficient"}


def explain_risks(risks, data_coverage):
    missing = [name for name, available in {
        "weather": data_coverage.get("weatherAvailable"),
        "hotspot": data_coverage.get("satelliteAvailable"),
        "geospatial": data_coverage.get("geospatialAvailable"),
        "history": data_coverage.get("historyAvailable", False),
        "iot": data_coverage.get("iotAvailable", False),
    }.items() if not available]
    explanations = {}
    for risk_type, risk in risks.items():
        if not isinstance(risk, dict) or "nivel" not in risk:
            continue
        factors = list(risk.get("fatores") or [])
        explanations[risk_type] = {
            "risk": risk_type, "level": risk.get("nivel"), "score": risk.get("score"),
            "mainFactors": factors[:5], "evidence": factors[:10], "missingData": missing,
            "confidence": CONFIDENCE.get(risk.get("confianca"), "insufficient"),
            "confidenceMeaning": "quality_and_coverage_of_input_data",
        }
    return explanations
