"""Cenários sintéticos exclusivamente para desenvolvimento e testes."""

from datetime import datetime, timedelta, timezone


SCENARIOS = {"normal", "machine_overheat", "environmental_fire_high", "combined_critical", "stale_device"}


def generate_scenario(name, now=None):
    if name not in SCENARIOS:
        raise ValueError(f"Cenário deve ser um de: {', '.join(sorted(SCENARIOS))}.")
    current = now or datetime.now(timezone.utc)
    overheat = name in {"machine_overheat", "combined_critical"}
    environmental_high = name in {"environmental_fire_high", "combined_critical"}
    stale = name == "stale_device"
    values = [68, 76, 96] if overheat else [55, 57, 58]
    telemetry = [{
        "deviceId": "demo_device_01", "fazendaId": "demo_fazenda_01", "maquinaId": "demo_trator_01",
        "readingId": f"demo_{name}_{index}",
        "observedAt": current - timedelta(minutes=(30 if stale else 2 - index)),
        "measurements": {"demo_temp_motor": value, "demo_vibracao": 2.0 + index * 0.1},
        "demoData": True, "scenario": name,
    } for index, value in enumerate(values)]
    environmental = {
        "incendio": {"score": 90 if environmental_high else 20,
                     "nivel": "critico" if environmental_high else "baixo",
                     "confianca": "alta", "fatores": []},
        "geral": {"score": 90 if environmental_high else 20,
                  "nivel": "critico" if environmental_high else "baixo"},
    }
    return {"name": name, "demoData": True, "generatedAt": current,
            "telemetry": telemetry, "environmentalRisk": environmental}
