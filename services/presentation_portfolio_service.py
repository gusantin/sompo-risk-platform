"""Fictional fixed identities, real provider responses, existing deterministic engines."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone

from services.live_case_service import LiveCaseService
from services.risco_service import calcular_riscos
from services.risk_explanation_service import explain_risks
from services.recommendation_service import recommendations

PORTFOLIO = (
    {"fazendaId": "demo_portfolio_pocone", "clientName": "Cliente B", "nome": "Fazenda Pantanal Norte", "municipio": "Poconé", "estado": "MT", "ibgeCode": "5106505"},
    {"fazendaId": "demo_portfolio_confresa", "clientName": "Cliente A", "nome": "Fazenda Araguaia", "municipio": "Confresa", "estado": "MT", "ibgeCode": "5103353"},
    {"fazendaId": "demo_portfolio_dourados", "clientName": "Cliente C", "nome": "Fazenda Campo Sul", "municipio": "Dourados", "estado": "MS", "ibgeCode": "5003702"},
)
SECOND_PROPERTY = {"fazendaId": "demo_portfolio_horizonte", "clientName": "Cliente A", "nome": "Fazenda Horizonte", "municipio": "Sorriso", "estado": "MT", "ibgeCode": "5107925"}
SUCCESS = {"ok", "parcial", "sem_evidencia_na_fonte", "sem_observacao_recente"}


def age(value, now):
    try:
        result = (now - datetime.fromisoformat(str(value).replace("Z", "+00:00"))).total_seconds()
        return result if result >= 0 else float("inf")
    except (TypeError, ValueError):
        return float("inf")


class PresentationPortfolio:
    def __init__(self, locate, providers, max_age=21600):
        self.locate, self.providers, self.max_age = locate, providers, max_age

    @staticmethod
    def read(path):
        try:
            payload = LiveCaseService.load_snapshot(path)
            return payload if payload.get("schema") == "presentation_real_portfolio_v1" else {}
        except (OSError, ValueError):
            return {}

    def capture(self, previous=None, now=None, identities=None):
        now = now or datetime.now(timezone.utc)
        previous = previous if (previous or {}).get("schema") == "presentation_real_portfolio_v1" else {}
        old = {c.get("id"): c for c in previous.get("cases", [])}
        if identities is None:
            fixed = {p["fazendaId"] for p in PORTFOLIO}
            identities = list(PORTFOLIO) + [c["property"] for c in old.values() if c.get("id") not in fixed]

        def one(identity):
            prior = old.get(identity["fazendaId"], {})
            if not identity.get("ibgeCode") and prior:
                # Registrations awaiting geocoding must survive portfolio refreshes.
                return deepcopy(prior)
            prop = {**identity, "demoData": True, "identityOrigin": "demonstration"}
            try:
                local = self.locate(identity["ibgeCode"])
                if local.get("ibgeCode") != identity["ibgeCode"] or local.get("state") != identity["estado"]:
                    raise ValueError("location_mismatch")
                prop.update({k: local.get(k) for k in ("latitude", "longitude", "coordinateSource", "representativeness", "preparedAt")})
            except Exception:
                stored = prior.get("property", {})
                if stored.get("ibgeCode") == identity["ibgeCode"] and stored.get("coordinateSource"):
                    prop.update({k: stored.get(k) for k in ("latitude", "longitude", "coordinateSource", "representativeness", "preparedAt")})
            sources, health = {}, {}

            def fetch(pair):
                name, provider = pair
                try:
                    if not all(isinstance(prop.get(k), (int, float)) for k in ("latitude", "longitude")):
                        raise ValueError("coordinates_unavailable")
                    raw = provider(prop["latitude"], prop["longitude"])
                    if raw.get("status") not in SUCCESS or age(raw.get("consultadoEm"), max(now, datetime.now(timezone.utc))) == float("inf"):
                        raise ValueError("provider_unavailable")
                    return name, raw, bool(raw.get("cache")), False
                except Exception:
                    stored = prior.get("rawSources", {}).get(name, {})
                    if stored.get("status") in SUCCESS and stored.get("atribuicao") and age(stored.get("consultadoEm"), now) != float("inf"):
                        return name, deepcopy(stored), True, True
                    return name, {"status": "unavailable", "dados": {}}, False, True
            with ThreadPoolExecutor(max_workers=4) as executor:
                for name, raw, cached, failed in executor.map(fetch, self.providers.items()):
                    raw["cache"] = cached
                    sources[name] = raw
                    health[name] = {"status": raw["status"], "attribution": raw.get("atribuicao", name),
                                    "consultedAt": raw.get("consultadoEm"), "cacheHit": cached, "refreshFailed": failed}
            risks = calcular_riscos(sources)
            evaluated = max(now, datetime.now(timezone.utc))
            candidates = [(name, risk) for name, risk in risks.items() if name not in {"geral", "terrenoOperacional"} and isinstance(risk, dict) and isinstance(risk.get("score"), (int, float))]
            risk_type, risk = max(candidates, key=lambda pair: pair[1]["score"]) if candidates else ("ambiental", {"score": None, "nivel": "dados_insuficientes", "fatores": []})
            usable = [h for h in health.values() if h.get("consultedAt")]
            acquired = min((h["consultedAt"] for h in usable), default=None)
            state = "unavailable" if not usable else "insufficient_data" if not candidates else "stale" if any(age(h["consultedAt"], evaluated) > self.max_age for h in usable) else "real_cached" if any(h["cacheHit"] for h in usable) else "real_live"
            coverage = {"weatherAvailable": sources.get("clima", {}).get("status") in SUCCESS,
                        "satelliteAvailable": sources.get("queimadas", {}).get("status") in SUCCESS,
                        "geospatialAvailable": False, "historyAvailable": False, "propertyContextAvailable": True, "iotAvailable": False}
            hotspot = sources.get("queimadas", {}).get("dados", {})
            kind = "environmental_fire_risk" if risk_type == "incendio" else "environmental_risk"
            guidance = recommendations({"type": kind}) if risk.get("nivel") in {"alto", "critico"} else []
            # Reuse the official property-match and severity rules without persisting alerts.
            from services.alert_service import AlertService
            class WeatherPreview(AlertService):
                def emit(self, alert_type, severity, fazenda_id, risk_type, factors, evidence, source_analysis_id, **kwargs):
                    return {"type": alert_type, "severity": severity, "fazendaId": fazenda_id,
                            "factors": factors, "evidence": evidence, "sourceEventId": source_analysis_id}, False
            matched = WeatherPreview(None).evaluate_weather(prop, sources.get("avisos", {}).get("dados", {}).get("items", []), now=evaluated)
            weather = [item["alert"] for item in matched]
            ranks = {"baixo": 1, "moderado": 2, "alto": 3, "critico": 4, "moderate": 2, "high": 3, "critical": 4}
            if weather:
                strongest = max(weather, key=lambda a: ranks.get(a["severity"], 0))
                if ranks.get(strongest["severity"], 0) > ranks.get(risk.get("nivel"), 0):
                    risk_type, kind = "weather", "severe_weather_warning"
                    risk = {"score": None, "nivel": strongest["severity"], "fatores": [{"fator": "official_weather_warning", "descricao": strongest["factors"][0]}]}
                    guidance = recommendations({"type": kind}) if strongest["severity"] in {"high", "critical"} else []
                    state = "stale" if any(age(h["consultedAt"], evaluated) > self.max_age for h in usable) else "real_cached" if any(h["cacheHit"] for h in usable) else "real_live"
            return {"id": prop["fazendaId"], "property": prop, "riskType": risk_type, "risk": risk, "environmentalRisk": risks,
                    "analysisAt": evaluated.isoformat(), "environmentalDataReal": bool(usable), "rawSources": sources, "weatherWarnings": weather,
                    "environmentalEvidence": LiveCaseService._evidence(sources, "incendio"), "sourceHealth": health,
                    "dataCoverage": coverage, "riskExplanation": explain_risks(risks, coverage).get(risk_type, {}),
                    "recommendations": guidance, "hotspots": {"items": (hotspot.get("focosRecentes") or ([hotspot["focoMaisProximo"]] if hotspot.get("focoMaisProximo") else []))[:8],
                        "nearest": hotspot.get("focoMaisProximo"), "lookbackHours": hotspot.get("lookbackHours", 48), "count48hWithin50Km": hotspot.get("quantidadeFocos48hAte50Km"), "sampleOnly": True},
                    "provenance": {"identity": "demo", "environmental": {"origin": "real" if usable else "unavailable", "state": state, "acquiredAt": acquired}},
                    "alertState": "not_queried", "notificationState": "not_queried"}
        with ThreadPoolExecutor(max_workers=3) as executor:
            cases = list(executor.map(one, identities if identities is not None else PORTFOLIO))
        from services.environmental_context import build_environmental_context, presentation_risk_factors
        for case in cases:
            case["environmentalContext"] = build_environmental_context(case.get("rawSources") or {}, case["property"])
            case["presentationFactors"] = presentation_risk_factors(case)
        return {"schema": "presentation_real_portfolio_v1", "mode": "live", "generatedAt": now.isoformat(), "cases": cases,
                "limitations": ["Clientes e propriedades fictícios; não representam segurados SOMPO.", "Coordenadas representam pontos municipais do IBGE, não limites de fazendas reais.", "Focos de calor não confirmam incêndio na propriedade."]}

    def snapshot(self, payload, now=None):
        now = now or datetime.now(timezone.utc)
        payload = deepcopy(payload)
        payload["mode"] = "snapshot"
        for case in payload.get("cases", []):
            from services.environmental_context import build_environmental_context, presentation_risk_factors
            case["environmentalContext"] = build_environmental_context(case.get("rawSources") or {}, case.get("property"), cached=True, now=now)
            case["presentationFactors"] = presentation_risk_factors(case, now)
            provenance = case.get("provenance", {}).get("environmental", {})
            if provenance.get("origin") == "real":
                provenance["state"] = "stale" if age(provenance.get("acquiredAt"), now) > self.max_age else "insufficient_data" if case.get("risk", {}).get("score") is None and case.get("riskType") != "weather" else "real_cached"
        return payload


def configured_portfolio():
    from integracoes.ibge import preparar_localidade
    from integracoes.inmet import consultar_inmet, consultar_avisos_inmet, consultar_contexto_avisos_inmet
    from integracoes.inpe_queimadas import consultar_queimadas
    from integracoes.open_meteo import consultar_clima
    return PresentationPortfolio(preparar_localidade, {"clima": consultar_clima, "queimadas": consultar_queimadas,
        "inmet": consultar_inmet, "avisos": lambda lat, lon: consultar_avisos_inmet(),
        "avisos_contexto": lambda lat, lon: consultar_contexto_avisos_inmet()})
