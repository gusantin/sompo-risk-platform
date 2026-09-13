"""Canonical environmental facts. Presentation only; never computes risk or alerts."""
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

OK = {"ok", "parcial", "sem_evidencia_na_fonte", "sem_observacao_recente"}
WMO = {0: "Céu limpo", 1: "Predominantemente limpo", 2: "Parcialmente nublado", 3: "Nublado",
       45: "Nevoeiro", 48: "Nevoeiro com deposição de gelo", 51: "Garoa fraca", 53: "Garoa moderada", 55: "Garoa intensa",
       56: "Garoa congelante fraca", 57: "Garoa congelante intensa", 61: "Chuva fraca", 63: "Chuva moderada", 65: "Chuva intensa",
       66: "Chuva congelante fraca", 67: "Chuva congelante intensa", 71: "Neve fraca", 73: "Neve moderada", 75: "Neve intensa",
       77: "Grãos de neve", 80: "Pancadas de chuva fracas", 81: "Pancadas de chuva moderadas", 82: "Pancadas de chuva violentas",
       85: "Pancadas de neve fracas", 86: "Pancadas de neve intensas", 95: "Tempestade", 96: "Tempestade com granizo fraco", 99: "Tempestade com granizo forte"}


def instant(value, zone="UTC"):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt.replace(tzinfo=ZoneInfo(zone)) if dt.tzinfo is None else dt).astimezone(timezone.utc)
    except (ValueError, TypeError, KeyError):
        return None


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def presentation_risk_factors(case, now=None):
    """Audit causal presentation against the stored engine inputs; never alter risk."""
    from copy import deepcopy
    from services.notification_messages import stamp
    now = now or datetime.now(timezone.utc)
    source = (case.get("rawSources") or {}).get("clima") or {}
    data = source.get("dados") or {}
    fetched = instant(source.get("consultadoEm"))
    real = source.get("status") in OK and source.get("atribuicao") and fetched and fetched <= now and not source.get("demoData")
    state = "leitura real desatualizada" if fetched and (now - fetched).total_seconds() > 21600 else "última leitura real em cache"
    result = []
    for original in (case.get("risk") or {}).get("fatores", []):
        if not isinstance(original, dict) or (numeric(original.get("contribuicao")) and original["contribuicao"] <= 0):
            continue
        factor = deepcopy(original)
        key = factor.get("fator")
        if key in {"ausencia_chuva", "umidade_solo_baixa"}:
            if not real or not numeric(factor.get("contribuicao")) or factor["contribuicao"] <= 0:
                continue
            field = "chuvaAcumulada72hMm" if key == "ausencia_chuva" else "umidadeSoloMin72hM3M3"
            value = data.get(field)
            if not numeric(value) or value < 0:
                continue
            if key == "ausencia_chuva":
                forecast = data.get("environmentalForecast") or {}
                window = (forecast.get("windows") or {}).get("72") or {}
                period = window.get("forecastFor") or {}
                start, end = instant(period.get("start")), instant(period.get("end"))
                # Legacy engine slices from current.time only when it is an exact hourly entry.
                # Without that alignment, a new context forecast is not proof of the scored window.
                if not start or not end or end <= now or end - start != timedelta(hours=72) or start != instant(forecast.get("observedAt")) or not numeric(window.get("precipitationSum")) or window["precipitationSum"] != value:
                    continue
                description = f"Acumulado de chuva previsto na janela de 72h usada pelo motor: {value:g} mm ({stamp(start)} a {stamp(end)})"
            else:
                description = f"Mínima modelada de umidade superficial do solo usada pelo motor: {value:g} m³/m³ (agregado armazenado)"
            factor["descricao"] = description.replace(f"{value:g}", f"{value:g}".replace(".", ",")) + f" — {source['atribuicao']}; {state}, consulta em {stamp(fetched)} (Brasília)."
            factor["evidence"] = {"field": field, "value": value, "source": source["atribuicao"], "fetchedAt": source["consultadoEm"], "freshness": state}
        result.append(factor)
    return result


def aggregate_forecast(raw):
    """Full hourly windows only. Missing points never become zero or partial totals."""
    zone = raw.get("timezone") or "UTC"
    current = raw.get("current") or {}
    anchor = instant(current.get("time"), zone)
    hourly = raw.get("hourly") or {}
    times = [instant(t, zone) for t in hourly.get("time", [])]
    result = {"observedAt": anchor.isoformat() if anchor else None, "current": current, "windows": {}}
    if not anchor:
        return result
    start = anchor.replace(minute=0, second=0, microsecond=0)
    if start < anchor:
        start += timedelta(hours=1)
    for hours in (6, 12, 24, 72):
        expected = [start + timedelta(hours=i) for i in range(hours)]
        indices = [times.index(t) if t in times else None for t in expected]
        def values(field):
            array = hourly.get(field) or []
            v = [array[i] if i is not None and i < len(array) else None for i in indices]
            return v if all(numeric(x) for x in v) else []
        data = {"forecastFor": {"start": start.isoformat(), "end": (start + timedelta(hours=hours)).isoformat()}, "hours": hours}
        for field, name, operation in (("temperature_2m", "temperatureMax", max), ("temperature_2m", "temperatureMin", min),
            ("relative_humidity_2m", "humidityMin", min), ("precipitation_probability", "precipitationProbabilityMax", max),
            ("precipitation", "precipitationSum", sum), ("rain", "rainSum", sum), ("showers", "showersSum", sum),
            ("wind_speed_10m", "windMax", max), ("wind_gusts_10m", "gustMax", max)):
            v = values(field)
            if field == "precipitation_probability" and any(not 0 <= x <= 100 for x in v):
                v = []
            data[name] = round(operation(v), 3) if v else None
        codes = values("weather_code")
        data["weatherCodes"] = list(dict.fromkeys(codes)) if codes else None
        data["conditions"] = list(dict.fromkeys(WMO[c] for c in codes if c in WMO)) or None
        data["dryForecast"] = data["precipitationSum"] == 0 if data["precipitationSum"] is not None else None
        result["windows"][str(hours)] = data
    first, last = result["windows"]["24"], result["windows"]["72"]
    for key in ("temperatureMax", "humidityMin"):
        # Bounds across nested windows, not an invented trend or risk forecast.
        last[key + "RangeChange"] = round(last[key] - first[key], 3) if last[key] is not None and first[key] is not None else None
    return result


def build_environmental_context(sources, property_data=None, *, cached=False, now=None):
    now = now or datetime.now(timezone.utc)
    property_data = property_data or {}
    def fact(value, provider, *, observed=None, forecast=None, unit=None, kind="observation"):
        source = sources.get(provider) or {}
        fetched = instant(source.get("consultadoEm"))
        valid = source.get("status") in OK and fetched and fetched <= now and source.get("atribuicao")
        state = "unavailable" if value is None or not valid else "stale" if (now - fetched).total_seconds() > 21600 else "real_cached" if cached or source.get("cache") else "real_live"
        end = instant((forecast or {}).get("end"))
        if state != "unavailable" and ((end and end <= now) or (instant(observed) and (now - instant(observed)).total_seconds() > 21600)):
            state = "stale"
        return {"value": value if valid else None, "unit": unit, "kind": kind, "source": source.get("atribuicao", provider),
                "observedAt": observed, "forecastFor": forecast, "fetchedAt": source.get("consultadoEm"),
                "freshness": state, "provenance": "real" if valid else "unavailable"}
    climate = (sources.get("clima") or {}).get("dados") or {}
    weather = climate.get("environmentalForecast") or {}
    current = weather.get("current") or {}
    observation = {}
    for field, key, legacy, unit in (("temperature", "temperature_2m", "temperaturaAtualC", "°C"),
        ("humidity", "relative_humidity_2m", "umidadeRelativaAtualPct", "%"), ("precipitation", "precipitation", "precipitacaoAtualMm", "mm"),
        ("wind", "wind_speed_10m", "velocidadeVentoAtualKmh", "km/h"), ("gust", "wind_gusts_10m", "rajadaAtualKmh", "km/h")):
        value = current.get(key, climate.get(legacy))
        observation[field] = fact(value if numeric(value) else None, "clima", observed=weather.get("observedAt"), unit=unit, kind="model_current")
    observation["condition"] = fact(WMO.get(current.get("weather_code")), "clima", observed=weather.get("observedAt"), kind="model_current")
    forecasts = {}
    units = {"temperatureMax": "°C", "temperatureMin": "°C", "humidityMin": "%", "precipitationProbabilityMax": "%",
             "precipitationSum": "mm", "rainSum": "mm", "showersSum": "mm", "windMax": "km/h", "gustMax": "km/h"}
    for hours in ("6", "12", "24", "72"):
        window = (weather.get("windows") or {}).get(hours) or {}
        forecasts[hours] = {key: fact(window.get(key), "clima", forecast=window.get("forecastFor"), unit=unit, kind="forecast") for key, unit in units.items()}
        for key in ("conditions", "weatherCodes", "dryForecast", "temperatureMaxRangeChange", "humidityMinRangeChange"):
            forecasts[hours][key] = fact(window.get(key), "clima", forecast=window.get("forecastFor"), kind="forecast")
    fire_data = (sources.get("queimadas") or {}).get("dados") or {}
    nearest = fire_data.get("focoMaisProximo") or {}
    fire = {"nearestDistance": fact(nearest.get("distanciaKm"), "queimadas", observed=nearest.get("dataHoraUtc"), unit="km"),
            "hotspotCount48h": fact(fire_data.get("quantidadeFocos48hAte50Km"), "queimadas", kind="satellite_window_48h")}
    from integracoes.inpe_queimadas import produtos_secundarios
    fire["products"] = produtos_secundarios()
    cap = sources.get("avisos_contexto") or {}
    from integracoes.inmet import avisos_aplicaveis
    matched = avisos_aplicaveis((cap.get("dados") or {}).get("items", []), property_data, now)
    warnings = fact(matched if cap.get("status") == "ok" else None, "avisos_contexto", kind="official_warning")
    # Partial CAP coverage cannot establish that no warning exists.
    if cap.get("status") == "parcial" and matched:
        warnings = fact(matched, "avisos_contexto", kind="official_warning")
    context = {"schema": "environmental_context_v1", "identity": "demo" if property_data.get("demoData") else "registered",
        "observation": observation, "forecast": forecasts, "fire": fire, "warnings": warnings,
        "station": fact((sources.get("inmet") or {}).get("dados") or None, "inmet", observed=((sources.get("inmet") or {}).get("dados") or {}).get("dataHoraObservacaoUtc")),
        "riskContribution": "Additional context; only existing risk factors explain the authoritative classification."}
    context["sections"] = environmental_sections(context)
    return context


def cached_context(context, now=None):
    from copy import deepcopy
    context = deepcopy(context or {})
    now = now or datetime.now(timezone.utc)
    def visit(value):
        if isinstance(value, dict):
            if value.get("freshness") in {"real_live", "real_cached", "stale"}:
                fetched, observed = instant(value.get("fetchedAt")), instant(value.get("observedAt"))
                end = instant((value.get("forecastFor") or {}).get("end"))
                value["freshness"] = "stale" if not fetched or (now - fetched).total_seconds() > 21600 or (observed and (now - observed).total_seconds() > 21600) or (end and end <= now) else "real_cached"
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(context)
    return context


def environmental_text(context, question=""):
    from services.sompo_agro_agent.tools import _normalize
    q = _normalize(question)
    lines = []
    for section in cached_context(context).get("sections", []):
        title = section["title"]
        if any(w in q for w in ("tempestade", "aviso")) and title != "Avisos oficiais":
            continue
        elif "proximos dias" in q and title != "Fogo" and not title.startswith("Previsão de 72h"):
            continue
        elif not any(w in q for w in ("tempestade", "aviso", "proximos dias")):
            if "umidade" in q and title != "Última leitura ambiental":
                continue
            if any(w in q for w in ("chover", "chuva", "pancada")) and not title.startswith("Previsão de 24h"):
                continue
            if "condicoes ambientais" in q and title.startswith(("Previsão de 6h", "Previsão de 12h", "Previsão de 72h")):
                continue
        lines.append(section["title"] + ": " + " · ".join(section["lines"]))
        facts = [f for f in section["facts"] if f.get("value") is not None]
        for f in facts[:1]:
            state = {"real_cached": "última leitura real em cache", "stale": "leitura real desatualizada"}.get(f["freshness"], "não disponível")
            lines.append(f"Fonte: {f['source']}; consulta: {f['fetchedAt']}; {state}; observação: {f.get('observedAt') or 'não informada'}; janela prevista: {f.get('forecastFor') or 'não se aplica'}.")
    return "\n".join(lines) or "Contexto ambiental não disponível nesta captura."


def environmental_sections(context):
    """One pt-BR narrative reused by the UI, Copilot and Telegram."""
    def show(f):
        value = f.get("value")
        if value is None:
            return "Não disponível"
        value = (f"{value:.1f}" if f.get("unit") == "km" else f"{value:g}").replace(".", ",") if numeric(value) else str(value)
        return (value + ("" if f.get("unit") == "%" else " ") + (f.get("unit") or "")).strip()
    obs = context["observation"]
    observation = [f"{label}: {show(obs[key])}" for key, label in (("condition", "Condição na última leitura"), ("temperature", "Temperatura na última leitura"),
        ("humidity", "Umidade na última leitura"), ("precipitation", "Precipitação na última leitura"), ("wind", "Vento na última leitura"), ("gust", "Rajada na última leitura")) if obs[key]["value"] is not None]
    sections = [{"title": "Última leitura ambiental", "lines": observation or ["Não disponível"], "facts": list(obs.values())}]
    for hours in ("6", "12", "24", "72"):
        forecast = context["forecast"][hours]
        conditions = forecast["conditions"]["value"]
        lines = ["Previsão: " + "; ".join(conditions)] if conditions else []
        for key, label in (("precipitationProbabilityMax", "Probabilidade máxima de precipitação"), ("precipitationSum", "Precipitação prevista acumulada"),
            ("temperatureMax", "Temperatura máxima prevista"), ("humidityMin", "Umidade mínima prevista"), ("windMax", "Vento máximo previsto"), ("gustMax", "Rajada máxima prevista")):
            if forecast[key]["value"] is not None:
                lines.append(f"{label}: {show(forecast[key])}")
        if hours == "72" and forecast["dryForecast"]["value"] is True:
            lines.append("Sem precipitação prevista nesta janela; não indica dias passados sem chuva.")
        for key, label in (("temperatureMaxRangeChange", "Diferença entre máxima de 72h e máxima de 24h (°C)"), ("humidityMinRangeChange", "Diferença entre mínima de umidade de 72h e de 24h (pontos percentuais)")):
            if hours == "72" and forecast[key]["value"] is not None:
                lines.append(label + ": " + show(forecast[key]))
        sections.append({"title": f"Previsão de {hours}h da captura · condição adicional", "lines": lines or ["Não disponível"], "facts": list(forecast.values())})
    nearest = context["fire"]["nearestDistance"]
    fire = ["Foco de calor registrado: " + show(nearest) + " do ponto de referência monitorado. Detecção por satélite; não confirma incêndio."] if nearest["value"] is not None else ["Foco de calor próximo: não disponível nesta leitura."]
    fire.append("Risco INPE observado/previsto e dias sem chuva: não disponíveis.")
    sections.append({"title": "Fogo", "lines": fire, "facts": [nearest, context["fire"]["hotspotCount48h"]]})
    warning = context["warnings"]
    severity_labels = {"Moderate": "Perigo potencial", "Severe": "Perigo", "Extreme": "Grande perigo"}
    lines = [f"{w['eventType']} · {severity_labels.get(w['severity'], w['severity'])} · {'vigente na consulta' if w['temporalState'] == 'active' else 'início posterior à consulta'} · {w['description']} · vigência {w['startsAt']} a {w['endsAt']} · vínculo: {w['geographicEvidence']}" for w in warning["value"] or []]
    if not lines:
        lines = ["Nenhum aviso CAP vigente ou futuro vinculado ao ponto monitorado na consulta registrada." if warning["value"] == [] else "Avisos INMET: cobertura indisponível ou incompleta."]
    sections.append({"title": "Avisos oficiais", "lines": lines, "facts": [warning]})
    return sections
