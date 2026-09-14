"""Explicit bridge contract for the immutable SOMPO ESP prototype.

No transport, generated readings, threshold evaluation or platform risk mapping.
"""

import math


def adapt_prototype(payload):
    fields = {"temperatura", "umidade", "ventoKmh", "leituraLdrDigital", "statusGeral", "dhtComErro"}
    if not isinstance(payload, dict) or set(payload) - fields:
        raise ValueError("prototype deve conter somente campos do protótipo SOMPO ESP.")
    status = payload.get("statusGeral")
    if not isinstance(status, str) or status not in {"NORMAL", "ATENCAO", "RISCO"}:
        raise ValueError("statusGeral deve ser NORMAL, ATENCAO ou RISCO.")
    if not isinstance(payload.get("dhtComErro"), bool):
        raise ValueError("dhtComErro deve ser booleano explícito.")
    values, descriptors = {}, {}
    for field, sensor_type, unit in (
        ("temperatura", "temperature", "celsius"),
        ("umidade", "relative_humidity", "percent"),
        ("ventoKmh", "speed", "km_h"),
        ("leituraLdrDigital", "digital_light", "unknown"),
    ):
        if field == "leituraLdrDigital" and field not in payload:
            continue
        if field in {"temperatura", "umidade"} and payload["dhtComErro"]:
            # Firmware retains old DHT values on error: never ingest them as fresh.
            if payload.get(field) is not None:
                raise ValueError("Omita temperatura/umidade ou envie null quando dhtComErro=true.")
            continue
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{field} deve ser número finito.")
        if field in {"umidade", "ventoKmh"} and not 0 <= value <= 100:
            raise ValueError(f"{field} deve estar entre 0 e 100.")
        if field == "leituraLdrDigital" and (type(value) is not int or value not in (0, 1)):
            raise ValueError("leituraLdrDigital deve ser 0 ou 1; polaridade não inferida.")
        values[field] = value
        descriptors[field] = {
            "type": sensor_type, "unit": unit,
            "scope": "other" if field == "ventoKmh" else "unknown",
            "target": "potentiometer_simulated_wind" if field == "ventoKmh" else None,
        }
    return values, descriptors, {
        "firmware": "sompo_esp_prototype_v1", "statusGeral": status,
        "dhtComErro": payload["dhtComErro"], "windSource": "potentiometer_simulation",
    }
