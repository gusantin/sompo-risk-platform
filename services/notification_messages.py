"""Presentation only: no risk decisions, persistence or transport."""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from services.recommendation_service import recommendations

LEVELS = {"high": "ALTO", "critical": "CRÍTICO", "moderate": "MODERADO"}
RISKS = {"incendio": "Incêndio", "machine": "Máquina", "operational": "Contexto operacional", "geada": "Geada", "inundacao": "Inundação", "enxurrada": "Enxurrada", "weather": "Aviso meteorológico"}
FACTORS = {"recent_hotspot_near_property": "Foco de calor recente detectado próximo à propriedade.",
           "nearby_hotspot": "Foco de calor recente próximo da localização registrada.",
           "recent_machine_location": "Localização recente da máquina disponível.",
           "environmental_fire_elevated": "Risco ambiental de incêndio elevado.",
           "machine_risk_elevated": "Risco interno da máquina elevado."}


def stamp(value, timezone_name="America/Sao_Paulo"):
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo(timezone_name)).strftime("%d/%m/%Y às %H:%M")
    except ValueError:
        return str(value)


def evidence_lines(alert):
    result = []
    for item in alert.get("evidence", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"temperature", "vibration"} and item.get("scope") in {"machine_internal", "machine_component"}:
            value = item.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                label = "Temperatura do componente" if item["type"] == "temperature" else "Vibração do componente"
                unit = {"celsius": "°C", "percent": "%"}.get(item.get("unit"), item.get("unit", ""))
                result.append(f"{label}{' (' + str(item['target']) + ')' if item.get('target') else ''}: {value:g} {unit}; nível {LEVELS.get(item.get('level'), str(item.get('level', 'não informado'))).lower()} conforme configuração.")
        elif item.get("label") and item.get("value") is not None:
            if alert.get("presentationPortfolioId"):
                label = {"Temperatura atual": "Temperatura na última leitura",
                         "Umidade relativa atual": "Umidade na última leitura",
                         "Umidade atual": "Umidade na última leitura",
                         "Precipitação atual": "Precipitação na última leitura",
                         "Vento atual": "Vento na última leitura"}.get(item["label"], item["label"])
                value, unit = item["value"], item.get("unit") or ""
                numeric = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                rendered = (f"{value:.1f}".rstrip("0").rstrip(".") if unit == "km" else f"{value:g}").replace(".", ",") if numeric else str(value)
                if unit == "km":
                    line = f"Foco de calor identificado na região — {rendered} km do ponto de referência monitorado"
                    if item.get("observedAt"):
                        line += "; observado em " + stamp(item["observedAt"], alert.get("presentationTimezone") or "America/Sao_Paulo")
                    line += ". Detecção de calor por satélite; não significa incêndio confirmado."
                else:
                    line = f"{label}: {rendered}{'' if unit == '%' else ' '}{unit}".strip()
                result.append(line)
            else:
                result.append(f"{item['label']}: {item['value']} {item.get('unit') or ''}".strip())
        elif isinstance(item.get("distanceKm"), (int, float)):
            result.append(f"Foco de calor a {item['distanceKm']:g} km da localização avaliada; não confirma incêndio.")
        if item.get("description"):
            result.append(str(item["description"]))
    for factor in alert.get("factors", []):
        if isinstance(factor, dict):
            if factor.get("contribuicao") == 0:
                continue
            value = factor.get("descricao") or factor.get("description") or factor.get("label")
        else:
            value = FACTORS.get(str(factor)) or (factor if isinstance(factor, str) and "_" not in factor and ":" not in factor else None)
        if value and value not in result:
            result.append(str(value))
    return list(dict.fromkeys(result))[:6]


def message_for(alert, kind):
    display_time = lambda value: stamp(value, alert.get("presentationTimezone") or "America/Sao_Paulo")
    context = alert.get("environmentalContext") or {}
    context_sections = [s for s in context.get("sections", []) if any(f.get("value") is not None for f in s.get("facts", []))]
    environmental_sections = [s for s in context_sections if s["title"] in {"Última leitura ambiental", "Fogo"} or s["title"].startswith("Previsão de 24h")]
    weather = next((e for e in alert.get("evidence", []) if isinstance(e, dict) and e.get("weatherSeverity")), {})
    title = f"🚨 SOMPO RISK — RISCO {LEVELS.get(alert.get('severity'), 'ELEVADO')}"
    if alert.get("type") == "machine_risk":
        title = "🚜 SOMPO RISK — ALERTA DE MÁQUINA"
    if weather:
        title = "⛈️ SOMPO LIVE — " + str(weather["weatherSeverity"]).upper()
    if kind == "escalation":
        title = "🔴 SOMPO RISK — RISCO ESCALADO PARA CRÍTICO"
    if kind == "resolution":
        # A human closing an alert does not prove the physical condition normalized.
        title = "✅ SOMPO RISK — ALERTA ENCERRADO"
    lines = [title, "", "📍 " + str(alert.get("propertyName") or "Propriedade com nome indisponível")]
    location = " — ".join(str(alert[k]) for k in ("municipality", "state") if alert.get(k))
    if location:
        lines.append(location)
    if alert.get("maquinaId"):
        lines.append("🚜 " + str(alert.get("machineName") or "Máquina com nome indisponível"))
    if kind == "resolution":
        lines += ["", "O alerta anteriormente notificado foi encerrado pelo responsável."]
        if alert.get("resolvedAt"):
            lines.append("Resolvido em: " + display_time(alert["resolvedAt"]))
    else:
        if weather and weather.get("eventType"):
            lines += ["", "Evento: " + str(weather["eventType"])]
        else:
            lines += ["", ("🔥 " if alert.get("riskType") == "incendio" else "") + "Risco principal: " + RISKS.get(alert.get("riskType"), "Avaliação preventiva"), "Severidade: " + LEVELS.get(alert.get("severity"), "Não informada")]
        if kind == "escalation":
            lines += ["", "A classificação oficial passou de ALTO para CRÍTICO. Evidências desta avaliação:"]
            previous = {e.get("sensorId"): e for e in (alert.get("escalation") or {}).get("previousEvidence", []) if isinstance(e, dict) and e.get("sensorId")}
            for current in alert.get("evidence", []):
                old = previous.get(current.get("sensorId")) if isinstance(current, dict) else None
                if old and current.get("value") is not None and old.get("value") is not None and current.get("value") != old.get("value") and current.get("scope") in {"machine_internal", "machine_component"} and old.get("unit") == current.get("unit"):
                    lines.append(f"Medição do componente: {old['value']} → {current['value']} {current.get('unit') or ''}.")
        else:
            lines += ["", "Por que este alerta foi gerado:"]
        evidence = evidence_lines(alert)
        if environmental_sections:
            evidence = evidence_lines({**alert, "evidence": [], "factors": sorted(alert.get("factors", []), key=lambda f: f.get("contribuicao", 0) if isinstance(f, dict) else 0, reverse=True)})[:3]
        lines += ["• " + text[:400] for text in evidence] if evidence else ["Classificação elevada registrada pelo motor de risco. Evidências detalhadas não estão disponíveis nesta captura."]
        for section in environmental_sections:
            supported = [line for line in section["lines"] if "não disponív" not in line.lower()]
            if section["title"] == "Última leitura ambiental":
                supported = [line for line in supported if any(word in line for word in ("Temperatura", "Umidade", "Vento", "Rajada"))][:4]
            elif section["title"].startswith("Previsão"):
                supported = [line for line in supported if any(word in line for word in ("Previsão:", "Probabilidade", "acumulada", "Rajada"))][:4]
            else:
                supported = supported[:1]
            if supported:
                lines += ["", section["title"] + ":", *supported]
                first = next((f for f in section["facts"] if f.get("value") is not None), {})
                if first.get("forecastFor"):
                    lines.append("Janela: " + display_time(first["forecastFor"]["start"]) + " a " + display_time(first["forecastFor"]["end"]))
                elif first.get("observedAt"):
                    lines.append("Observação: " + display_time(first["observedAt"]))
        guidance = recommendations(alert)
        if guidance:
            lines += ["", "O que fazer agora:", *["• " + r["text"] for r in guidance]]
        sources = list(dict.fromkeys(str(e["source"]) for e in alert.get("evidence", []) if isinstance(e, dict) and e.get("source")))
        if environmental_sections:
            sources = list(dict.fromkeys(f["source"] for s in environmental_sections for f in s["facts"] if f.get("value") is not None))
        if sources:
            lines += ["", "Fonte: " + " + ".join(sources)]
        updated = (alert.get("provenance") or {}).get("environmental", {}).get("acquiredAt") or alert.get("lastTriggeredAt") or alert.get("createdAt")
        if updated:
            lines.append("Atualizado: " + display_time(updated))
        for key, label in (("publishedAt", "Emitido"), ("endsAt", "Validade")):
            if weather.get(key):
                lines.append(label + ": " + display_time(weather[key]))
    demo = alert.get("demoData") or str(alert.get("fazendaId", "")).startswith("demo_") or (alert.get("provenance") or {}).get("identity") == "demo"
    origin = (alert.get("provenance") or {}).get("environmental", {})
    if demo:
        label = "🧪 DADOS DE DEMONSTRAÇÃO"
        if origin.get("origin") == "real" and origin.get("acquiredAt"):
            suffix = {"real_live": "Dados ambientais reais", "real_cached": "Última leitura ambiental real", "stale": "Leitura ambiental real desatualizada", "insufficient_data": "Dados reais insuficientes"}.get(origin.get("state"), "Origem ambiental indisponível")
            label = "🧪 Cliente demonstrativo · " + suffix
            if alert.get("presentationPortfolioId"):
                suffix = "Última leitura real, atualmente desatualizada" if origin.get("state") == "stale" else suffix
                label = "🧪 Propriedade demonstrativa · " + suffix
        # Synthetic data stays explicit at the top; identity-only demo uses a compact footer.
        if origin.get("origin") != "real":
            lines.insert(0, label)
        else:
            return "\n".join(lines)[:3998 - len(label)] + "\n\n" + label
    return "\n".join(lines)[:4000]
