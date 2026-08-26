"""Validação central de unidades e medições, sem conversões implícitas."""

import json
import math


UNITS_BY_TYPE = {
    "temperature": {"celsius", "fahrenheit", "kelvin"},
    "humidity": {"percent"},
    "relative_humidity": {"percent"},
    "vibration": {"m_s2"},
    "smoke": {"ppm"},
    "gas": {"ppm"},
    "voltage": {"volt"},
    "current": {"ampere"},
    "pressure": {"pascal"},
    "rpm": {"rpm"},
    "speed": {"m_s", "km_h"},
}
KNOWN_UNITS = {unit for units in UNITS_BY_TYPE.values() for unit in units} | {"unknown"}


class UnitValidationError(ValueError):
    pass


def validate_metadata(metadata, max_keys=20, max_bytes=4096):
    if not isinstance(metadata, dict) or len(metadata) > max_keys:
        raise UnitValidationError(f"metadata deve ser objeto com até {max_keys} chaves.")
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise UnitValidationError("metadata deve conter apenas valores JSON.") from error
    if len(encoded.encode("utf-8")) > max_bytes:
        raise UnitValidationError(f"metadata excede {max_bytes} bytes.")
    if any(isinstance(value, str) and len(value) > 500 for value in metadata.values()):
        raise UnitValidationError("Strings de metadata devem ter até 500 caracteres.")
    return metadata


def validate_sensor_metadata(metadata):
    validate_metadata(metadata)
    valid_range = metadata.get("validRange")
    if valid_range is None:
        return metadata
    if not isinstance(valid_range, dict) or set(valid_range) != {"min", "max"}:
        raise UnitValidationError("metadata.validRange deve conter min e max.")
    minimum, maximum = valid_range["min"], valid_range["max"]
    if (not isinstance(minimum, (int, float)) or isinstance(minimum, bool) or not math.isfinite(minimum)
            or not isinstance(maximum, (int, float)) or isinstance(maximum, bool) or not math.isfinite(maximum)
            or minimum >= maximum):
        raise UnitValidationError("metadata.validRange deve ter números finitos com min menor que max.")
    return metadata


def value_in_valid_range(value, profile):
    valid_range = (profile.get("metadata") or {}).get("validRange")
    if valid_range is None:
        return True
    return (isinstance(valid_range, dict) and isinstance(valid_range.get("min"), (int, float))
            and isinstance(valid_range.get("max"), (int, float))
            and valid_range["min"] <= value <= valid_range["max"])


def validate_sensor_unit(sensor_type, unit):
    if unit not in KNOWN_UNITS:
        raise UnitValidationError("'unit' do sensor é inválida.")
    compatible = UNITS_BY_TYPE.get(sensor_type)
    if compatible and unit not in compatible:
        raise UnitValidationError(f"Unidade '{unit}' é incompatível com o tipo '{sensor_type}'.")
    return unit


def validate_measurements(measurements, machine, max_measurements=50, strict=True):
    """Normaliza valores e exige correspondência exata com o perfil semântico."""
    if not isinstance(measurements, dict) or not 1 <= len(measurements) <= max_measurements:
        raise UnitValidationError(f"measurements deve ser objeto com 1 a {max_measurements} medições.")
    profiles = {item.get("sensorId"): item for item in machine.get("sensoresConfigurados", [])}
    values, descriptors = {}, {}
    for sensor_id, raw in measurements.items():
        profile = profiles.get(sensor_id)
        if profile is None and strict:
            raise UnitValidationError(f"Sensor '{sensor_id}' não está configurado para a máquina.")
        if isinstance(raw, dict):
            if set(raw) - {"value", "unit"} or "value" not in raw or "unit" not in raw:
                raise UnitValidationError("Medição estruturada deve conter somente value e unit.")
            value, sent_unit = raw["value"], raw["unit"]
        else:
            value, sent_unit = raw, None
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise UnitValidationError("Todas as medições devem ser números finitos.")
        configured_unit = (profile or {}).get("unit", "unknown")
        if sent_unit is not None:
            if sent_unit not in KNOWN_UNITS:
                raise UnitValidationError(f"Unidade '{sent_unit}' não é suportada.")
            if profile and sent_unit != configured_unit:
                raise UnitValidationError(
                    f"Unidade de '{sensor_id}' deve ser '{configured_unit}'; conversão implícita não é permitida."
                )
        validate_sensor_unit((profile or {}).get("type"), configured_unit)
        if profile and not value_in_valid_range(value, profile):
            raise UnitValidationError(f"Valor de '{sensor_id}' está fora do validRange configurado.")
        values[sensor_id] = value
        descriptors[sensor_id] = {
            "type": (profile or {}).get("type", "unknown"),
            "scope": (profile or {}).get("scope", "unknown"),
            "target": (profile or {}).get("target"),
            "unit": configured_unit if sent_unit is None else sent_unit,
        }
    return values, descriptors
