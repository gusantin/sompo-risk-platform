"""Read-only projection of the UI's existing snapshot. No risk calculation or delivery."""
from copy import deepcopy
from datetime import datetime, timezone

from services.presentation_portfolio_service import age
from services.environmental_context import presentation_risk_factors
from .tools import AgentValidationError, _normalize

LEVELS = {"baixo": "baixa", "moderado": "moderada", "alto": "alta", "critico": "crítica",
          "low": "baixa", "moderate": "moderada", "high": "alta", "critical": "crítica"}
RANK = {"baixa": 1, "moderada": 2, "alta": 3, "crítica": 4}
STATES = {"real_cached": "última leitura ambiental real em cache", "stale": "leitura ambiental real desatualizada",
          "unavailable": "dados ambientais indisponíveis", "insufficient_data": "dados ambientais insuficientes"}


def portfolio_context(snapshot, property_id=None):
    now = datetime.now(timezone.utc)
    items = []
    for case in snapshot.get("cases", []):
        if property_id and case.get("id") != property_id:
            continue
        prop = case.get("property") or {}
        env = deepcopy((case.get("provenance") or {}).get("environmental") or {})
        valid = (env.get("origin") == "real" and age(env.get("acquiredAt"), now) != float("inf")
                 and any(s.get("attribution") and s.get("consultedAt") for s in (case.get("sourceHealth") or {}).values()))
        # Match the real-portfolio UI: synthetic/unproven evidence cannot supply a real risk.
        env["state"] = "unavailable" if not valid else "stale" if age(env.get("acquiredAt"), now) > 21600 else "insufficient_data" if env.get("state") == "insufficient_data" else "real_cached"
        risk = deepcopy(case.get("risk") or {}) if valid else {}
        items.append({"id": case.get("id"), "client": prop.get("clientName"), "property": prop.get("nome"),
            "municipality": prop.get("municipio"), "state": prop.get("estado"),
            "provenance": {"identity": "demo", "environmental": env},
            "level": LEVELS.get(risk.get("nivel"), "indisponível"), "score": risk.get("score"),
            "riskType": case.get("riskType") if valid else None,
            "factors": presentation_risk_factors(case, now) if valid else [],
            "evidence": deepcopy(case.get("environmentalEvidence") or []) if valid else [],
            "hotspots": deepcopy(case.get("hotspots") or {}) if valid else {},
            "sources": deepcopy(case.get("sourceHealth") or {}),
            "operationalState": deepcopy(case.get("operationalState")),
            "environmentalContext": deepcopy(case.get("environmentalContext") or {}) if valid else {}})
    if property_id and not items:
        raise AgentValidationError("Propriedade não pertence à captura demonstrativa exibida.")
    return {"readOnly": True, "generatedAt": snapshot.get("generatedAt"), "items": items,
            "contextPropertyId": property_id, "perspective": snapshot.get("perspective"), "source": "presentation_portfolio_snapshot"}


def portfolio_answer(context, question):
    """Deterministic interpretation preserves official severity and all numeric facts."""
    q, items = _normalize(question), context["items"]
    named = [p for p in items if any(_normalize(p.get(k)) in q for k in ("client", "property", "municipality") if p.get(k))]
    selected = named or items
    if any(word in q for word in ("envie", "enviar", "resolva", "resolver", "altere", "alterar", "recalcule", "recalcular", "notifique")):
        return "O Copilot é somente leitura: não altera riscos, encerra alertas ou envia notificações."
    if not items:
        return "A captura da carteira demonstrativa está indisponível; não há dados para classificar os clientes."
    if any(word in q for word in ("normal", "menor", "baixo", "baixa")):
        selected = [p for p in selected if p["level"] == "baixa"]
        if not selected:
            return "A captura da carteira demonstrativa não contém propriedade com exposição baixa no escopo consultado. Isso não comprova normalidade das condições atuais."
    elif not named and any(word in q for word in ("mais", "maior", "prioriz")):
        known = [p for p in items if p["level"] in RANK]
        if known:
            rank = lambda p: (RANK[p["level"]], p["score"] if isinstance(p["score"], (int, float)) else -1)
            top = max(map(rank, known))
            selected = [p for p in known if rank(p) == top]
    lines = ["Na captura da carteira demonstrativa, os clientes e propriedades são fictícios; não representam segurados SOMPO."]
    if context.get("perspective") == "segurado":
        lines = ["Nesta conta demonstrativa, suas fazendas são fictícias; não representam segurados SOMPO. A avaliação abaixo vem da captura ambiental disponível."]
    for item in selected:
        if any(word in q for word in ("chover", "chuva", "pancada", "umidade", "condicoes ambientais", "tempestade", "proximos dias")):
            environmental = item.get("environmentalContext") or {}
            identity = item['property'] if context.get("perspective") == "segurado" else f"{item['client']} — {item['property']}"
            lines.append(f"{identity}: exposição oficial na captura {item['level']}. Condições adicionais não alteram a classificação registrada.")
            from services.environmental_context import environmental_text
            lines.append(environmental_text(environmental, question))
            continue
        env = item["provenance"]["environmental"]
        label = f"{item['client']} — {item['property']}, {item['municipality']}/{item['state']}"
        if context.get("perspective") == "segurado":
            label = f"{item['property']}, {item['municipality']}/{item['state']}"
        if any(word in q for word in ("notific", "telegram", "alerta", "reconhec", "resolvid")):
            operational = item.get("operationalState")
            if operational is None:
                lines.append(label + ": estados de alertas e entregas não consultados; não é possível confirmar notificação.")
            else:
                lines.append(label + f": {operational['openAlerts']} alertas não resolvidos no recorte de até 20 alertas recentes.")
                for alert in operational.get("alerts", []):
                    status = {"open": "aberto", "acknowledged": "reconhecido", "resolved": "resolvido"}.get(alert.get("status"), "indisponível")
                    deliveries = [n.get("status", "unknown") for n in alert.get("notifications", [])]
                    lines.append("Alerta " + status + "; entrega: " + (", ".join(deliveries) if deliveries else "não registrada") + ".")
        historical = "última exposição registrada" if env["state"] == "stale" else "exposição na captura"
        lines.append(f"{label}: {historical} {item['level']}" + (f" (índice {item['score']}/100)." if item["score"] is not None else "."))
        lines.append(STATES[env["state"]].capitalize() + (f"; aquisição: {env['acquiredAt']}." if env.get("acquiredAt") else "."))
        if env.get("origin") in {"demo", "synthetic"}:
            lines.append("A origem informada é sintética/demonstrativa e foi excluída da avaliação real desta carteira.")
        factors = [f.get("descricao") or f.get("description") for f in item["factors"]]
        if any(factors):
            lines.append("Motivos registrados: " + "; ".join(f for f in factors[:3] if f) + ".")
        elif item["level"] in {"alta", "crítica"}:
            lines.append("Não há fatores detalhados disponíveis para explicar a classificação registrada.")
        if any(word in q for word in ("foco", "incendio", "calor")):
            hotspot = item["hotspots"].get("nearest")
            if hotspot:
                distance = hotspot.get("distanciaKm")
                lines.append("Foco de calor registrado" + (f" a {distance} km do ponto municipal configurado" if distance is not None else " na fonte consultada") + "; isso não confirma incêndio na propriedade.")
            else:
                lines.append("Não há foco de calor próximo disponível nesta captura; isso não comprova ausência de incêndio.")
        sources = [f"{s.get('attribution', name)}: {s.get('status', 'unavailable')}" + (f", consulta {s['consultedAt']}" if s.get("consultedAt") else "") for name, s in item["sources"].items()]
        if sources:
            lines.append("Fontes: " + "; ".join(sources) + ".")
    if any(p["provenance"]["environmental"]["state"] == "stale" for p in items):
        lines.append("Há dados desatualizados: a comparação representa a captura, não confirma a situação agora.")
    if any(p["level"] == "indisponível" for p in items):
        lines.append("A comparação é limitada às propriedades com classificação disponível.")
    if any(word in q for word in ("telegram", "alerta", "maquina")) and not any(p.get("operationalState") is not None for p in items):
        lines.append("Estados de alertas, entregas e máquinas não estão disponíveis nesta consulta ambiental da captura.")
    return "\n\n".join(lines)
