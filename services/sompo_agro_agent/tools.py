"""Tools read-only que adaptam o backend oficial ao AgroRiskAgent."""

import logging
import unicodedata
from datetime import datetime, timezone


LOGGER = logging.getLogger(__name__)


class AgentValidationError(ValueError):
    pass


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _normalize(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    normalized = "".join(char for char in text if unicodedata.category(char) != "Mn").lower()
    return " ".join(normalized.split())


def _json_safe(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _best_effort(operation, default):
    try:
        return operation(), None
    except Exception as error:
        LOGGER.warning("agent_read_unavailable error_type=%s", type(error).__name__)
        return default, type(error).__name__


class AgroRiskTools:
    """Adapters de leitura; não calculam nem modificam risco."""

    def __init__(self, properties, snapshots, machines, telemetry, devices, events, alerts,
                 live_case_loader, weather_alert_provider):
        self.properties = properties
        self.snapshots = snapshots
        self.machines = machines
        self.telemetry = telemetry
        self.devices = devices
        self.events = events
        self.alerts = alerts
        self.live_case_loader = live_case_loader
        self.weather_alert_provider = weather_alert_provider

    @staticmethod
    def definitions():
        return [
            {
                "type": "function", "name": "listar_propriedades_em_atencao",
                "description": "Lista propriedades e os riscos correntes já calculados, sem recalcular scores.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                "strict": True,
            },
            {
                "type": "function", "name": "consultar_contexto_da_propriedade",
                "description": "Consulta risco, fatores, evidências, hotspots, fontes, timestamps e tendência de uma propriedade ou município.",
                "parameters": {
                    "type": "object", "properties": {
                        "query": {"type": "string", "description": "Nome, ID ou município/UF."},
                    }, "required": ["query"], "additionalProperties": False,
                }, "strict": True,
            },
            {
                "type": "function", "name": "consultar_alertas_e_eventos",
                "description": "Consulta alertas ativos e eventos detectados, preservando a diferença entre alerta e evento.",
                "parameters": {
                    "type": "object", "properties": {
                        "property_id": {"type": ["string", "null"], "description": "ID opcional da propriedade."},
                    }, "required": ["property_id"], "additionalProperties": False,
                }, "strict": True,
            },
            {
                "type": "function", "name": "consultar_maquinas_e_esp32",
                "description": "Consulta máquinas, vínculo de dispositivo, telemetria, risco da máquina e risco operacional existentes.",
                "parameters": {
                    "type": "object", "properties": {
                        "property_id": {"type": ["string", "null"]},
                        "machine_query": {"type": ["string", "null"], "description": "Nome ou ID opcional da máquina."},
                    }, "required": ["property_id", "machine_query"], "additionalProperties": False,
                }, "strict": True,
            },
        ]

    def _live_payload(self):
        payload, error = _best_effort(self.live_case_loader, {})
        return payload if isinstance(payload, dict) else {}, error

    @staticmethod
    def _live_property(case):
        prop = case.get("property") or {}
        risk = case.get("risk") or {}
        return {
            "propertyId": prop.get("fazendaId") or case.get("id"),
            "name": prop.get("nome"), "municipality": prop.get("municipio"),
            "state": prop.get("estado"), "latitude": prop.get("latitude"),
            "longitude": prop.get("longitude"), "propertyDemo": prop.get("demoData") is True,
            "environmentalDataReal": case.get("environmentalDataReal") is True,
            "riskType": case.get("riskType"), "riskScore": risk.get("score"),
            "riskLevel": risk.get("nivel"), "confidence": risk.get("confianca"),
            "coveragePercent": risk.get("coberturaDadosPct"), "analysisAt": case.get("analysisAt"),
        }

    def list_properties_attention(self):
        live, live_error = self._live_payload()
        items = [self._live_property(case) for case in live.get("cases", [])]
        persisted, persisted_error = _best_effort(lambda: self.snapshots.list_properties(100), [])
        properties_by_id, properties_error = _best_effort(
            lambda: {item.get("fazendaId") or item.get("id"): item for item in self.properties.listar(100)}, {})
        for snapshot in persisted:
            property_id = snapshot.get("fazendaId") or snapshot.get("id")
            prop = properties_by_id.get(property_id, {})
            risks = snapshot.get("environmentalRisk") or {}
            candidates = [risk for risk in risks.values() if isinstance(risk, dict) and risk.get("score") is not None]
            highest = max(candidates, key=lambda risk: risk.get("score", -1), default={})
            items.append({
                "propertyId": property_id, "name": prop.get("nome"), "municipality": prop.get("municipio"),
                "state": prop.get("estado"), "propertyDemo": prop.get("demoData") is True,
                "environmentalDataReal": True, "riskScore": highest.get("score"),
                "riskLevel": highest.get("nivel"), "analysisAt": snapshot.get("analysisAt"),
            })
        items.sort(key=lambda item: item.get("riskScore") if isinstance(item.get("riskScore"), (int, float)) else -1,
                   reverse=True)
        return _json_safe({
            "tool": "listar_propriedades_em_atencao", "readOnly": True, "consultedAt": _now_iso(),
            "items": items[:20], "sourceStatus": {
                "liveSnapshot": "unavailable" if live_error else "ok",
                "propertySnapshots": "unavailable" if persisted_error else "ok",
                "properties": "unavailable" if properties_error else "ok",
            },
            "semantics": "Scores são índices operacionais /100, não probabilidades.",
        })

    def property_context(self, query):
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise AgentValidationError("query deve ser texto não vazio com até 200 caracteres.")
        normalized = _normalize(query)
        live, live_error = self._live_payload()
        for case in live.get("cases", []):
            prop = case.get("property") or {}
            candidates = (
                prop.get("fazendaId"), prop.get("nome"), prop.get("municipio"),
                f"{prop.get('municipio')}/{prop.get('estado')}",
            )
            if not any(normalized in _normalize(candidate) or _normalize(candidate) in normalized
                       for candidate in candidates if candidate):
                continue
            nearest = (case.get("hotspots") or {}).get("nearest")
            return _json_safe({
                "tool": "consultar_contexto_da_propriedade", "readOnly": True,
                "consultedAt": _now_iso(), "consultedIds": [prop.get("fazendaId") or case.get("id")],
                "property": self._live_property(case),
                "propertyDisclosure": "Propriedade demonstrativa com condições ambientais reais."
                    if prop.get("demoData") is True and case.get("environmentalDataReal") is True else None,
                "risk": case.get("risk"), "explanation": case.get("riskExplanation"),
                "environmentalEvidence": case.get("environmentalEvidence") or [],
                "hotspots": case.get("hotspots") or {}, "nearestHotspot": nearest,
                "fireConfirmed": False if nearest else None,
                "fireConfirmationMeaning": "Foco de calor por satélite não confirma incêndio na propriedade."
                    if nearest else "Nenhuma confirmação de incêndio está disponível.",
                "sources": case.get("provenance") or {}, "sourceHealth": case.get("sourceHealth") or {},
                "dataCoverage": case.get("dataCoverage") or {}, "analysisAt": case.get("analysisAt"),
                "snapshotGeneratedAt": live.get("generatedAt"), "limitations": live.get("limitations") or [],
                "trend": None, "trendStatus": "indisponível no snapshot deste caso",
            })

        properties, properties_error = _best_effort(lambda: self.properties.listar(100), [])
        prop = next((item for item in properties if any(
            normalized in _normalize(candidate) or _normalize(candidate) in normalized
            for candidate in (item.get("fazendaId") or item.get("id"), item.get("nome"), item.get("municipio"),
                              f"{item.get('municipio')}/{item.get('estado')}") if candidate)), None)
        if prop:
            property_id = prop.get("fazendaId") or prop.get("id")
            snapshot, snapshot_error = _best_effort(lambda: self.snapshots.get_property(property_id), None)
            return _json_safe({
                "tool": "consultar_contexto_da_propriedade", "readOnly": True,
                "consultedAt": _now_iso(), "consultedIds": [property_id], "property": prop,
                "propertyDisclosure": "Propriedade demonstrativa."
                    if prop.get("demoData") is True else None,
                "risk": (snapshot or {}).get("environmentalRisk"),
                "explanation": (snapshot or {}).get("riskExplanations"),
                "sources": (snapshot or {}).get("sourceHealth"), "dataCoverage": (snapshot or {}).get("coverage"),
                "analysisAt": (snapshot or {}).get("analysisAt"), "trend": (snapshot or {}).get("trend"),
                "status": "unavailable" if snapshot_error or not snapshot else "ok",
            })
        return {
            "tool": "consultar_contexto_da_propriedade", "readOnly": True, "consultedAt": _now_iso(),
            "status": "not_found" if not properties_error and not live_error else "unavailable",
            "message": "Propriedade não encontrada nos dados disponíveis."
                if not properties_error and not live_error else "Dados de propriedades indisponíveis.",
        }

    def alerts_events(self, property_id=None):
        if property_id is not None and (not isinstance(property_id, str) or len(property_id) > 100):
            raise AgentValidationError("property_id inválido.")
        live, live_error = self._live_payload()
        domain_events = []
        for case in live.get("cases", []):
            prop = case.get("property") or {}
            current_id = prop.get("fazendaId") or case.get("id")
            if property_id and current_id != property_id:
                continue
            for hotspot in (case.get("hotspots") or {}).get("items", []):
                domain_events.append({
                    "category": "event", "eventType": "hotspot_detected", "propertyId": current_id,
                    "occurredAt": hotspot.get("detectedAt") or hotspot.get("dataHoraUtc"),
                    "source": hotspot.get("source", "INPE Programa Queimadas"),
                    "satellite": hotspot.get("satelite") or hotspot.get("satellite"),
                    "distanceKm": hotspot.get("distanciaKm"), "confirmedFire": False,
                    "meaning": "Foco de calor detectado por satélite; não confirma incêndio.",
                })
        event_property_ids = [property_id] if property_id else []
        if not event_property_ids:
            persisted_properties, property_error = _best_effort(lambda: self.properties.listar(20), [])
            event_property_ids = [item.get("fazendaId") or item.get("id") for item in persisted_properties]
        else:
            property_error = None
        event_errors = []
        for event_property_id in filter(None, event_property_ids):
            persisted_events, event_error = _best_effort(
                lambda pid=event_property_id: self.events.list(pid, 10), [])
            domain_events.extend({**item, "category": "event"} for item in persisted_events)
            if event_error:
                event_errors.append(event_error)
        filters = {"fazendaId": property_id} if property_id else {}
        active_alerts = []
        alert_errors = []
        for status in ("open", "acknowledged"):
            result, error = _best_effort(lambda current=status: self.alerts.list({**filters, "status": current}, 50), [])
            active_alerts.extend({**item, "category": "alert"} for item in result)
            if error:
                alert_errors.append(error)
        weather, weather_error = _best_effort(self.weather_alert_provider, {})
        weather_items = []
        for item in (weather.get("dados") or {}).get("items", [])[:10]:
            weather_items.append({
                **item, "category": "alert", "source": item.get("source") or weather.get("atribuicao"),
                "hailMeaning": "Alerta menciona granizo; não confirma ocorrência de queda de granizo."
                    if item.get("hailExplicit") else None,
            })
        return _json_safe({
            "tool": "consultar_alertas_e_eventos", "readOnly": True, "consultedAt": _now_iso(),
            "consultedIds": [property_id] if property_id else [], "events": domain_events[:30],
            "alerts": active_alerts[:30], "weatherAlerts": weather_items,
            "semantics": {
                "event": "Algo mudou ou foi detectado.", "alert": "Situação que exige atenção.",
                "hotspot": "Foco de calor não confirma incêndio.",
            },
            "sourceStatus": {
                "liveSnapshot": "unavailable" if live_error else "ok",
                "domainEvents": "unavailable" if event_errors or property_error else "ok",
                "alerts": "unavailable" if alert_errors else "ok",
                "weatherAlerts": "unavailable" if weather_error else weather.get("status", "ok"),
            },
        })

    @staticmethod
    def _engine_temperature(machine, state):
        sensors = machine.get("sensoresConfigurados") or []
        sensor = next((item for item in sensors
                       if _normalize(item.get("type")) in {"temperature", "temperatura"}
                       and item.get("scope") in {"machine_internal", "machine_component"}
                       and _normalize(item.get("target")) in {"motor", "engine"}), None)
        if not sensor:
            return {"status": "insufficient_data", "message": "Sensor de temperatura do motor não configurado."}
        measurements = state.get("latestMeasurements") or {}
        value = measurements.get(sensor.get("sensorId"))
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return {"status": "insufficient_data", "message": "Telemetria de temperatura do motor não disponível."}
        return {"status": "available", "value": value, "unit": sensor.get("unit"),
                "sensorId": sensor.get("sensorId"), "scope": sensor.get("scope"), "target": sensor.get("target")}

    def machines_esp32(self, property_id=None, machine_query=None):
        if property_id is not None and (not isinstance(property_id, str) or len(property_id) > 100):
            raise AgentValidationError("property_id inválido.")
        if machine_query is not None and (not isinstance(machine_query, str) or len(machine_query) > 200):
            raise AgentValidationError("machine_query inválido.")
        property_ids = [property_id] if property_id else []
        errors = []
        if not property_ids:
            properties, error = _best_effort(lambda: self.properties.listar(100), [])
            property_ids = [item.get("fazendaId") or item.get("id") for item in properties]
            if error:
                errors.append(error)
        results = []
        query = _normalize(machine_query)
        for current_property_id in filter(None, property_ids):
            machine_items, error = _best_effort(lambda pid=current_property_id: self.machines.listar(pid), [])
            if error:
                errors.append(error)
            for machine in machine_items:
                machine_id = machine.get("maquinaId") or machine.get("id")
                if query and not any(query in _normalize(candidate) or _normalize(candidate) in query
                                     for candidate in (machine_id, machine.get("nome")) if candidate):
                    continue
                state, state_error = _best_effort(
                    lambda pid=current_property_id, mid=machine_id: self.snapshots.get_machine(pid, mid), {})
                latest = state or {}
                if not latest:
                    reading, reading_error = _best_effort(
                        lambda pid=current_property_id, mid=machine_id: self.telemetry.mais_recente(pid, mid), None)
                    if reading:
                        latest = {"latestMeasurements": reading.get("measurements") or {},
                                  "latestTelemetryAt": reading.get("dataHora")}
                    if reading_error:
                        errors.append(reading_error)
                devices, device_error = _best_effort(lambda pid=current_property_id: self.devices.list(pid, 100), [])
                linked = next((item for item in devices if item.get("maquinaId") == machine_id), None)
                if state_error:
                    errors.append(state_error)
                if device_error:
                    errors.append(device_error)
                has_telemetry = bool(latest.get("latestTelemetryAt") or latest.get("lastSeenAt"))
                results.append({
                    "propertyId": current_property_id, "machineId": machine_id, "name": machine.get("nome"),
                    "machine": machine, "device": linked,
                    "physicalDeviceStatus": "telemetry_available" if has_telemetry else "no_physical_telemetry",
                    "physicalDeviceMessage": None if has_telemetry else "Dispositivo físico ainda sem telemetria disponível.",
                    "latestTelemetryAt": latest.get("latestTelemetryAt"), "lastSeenAt": latest.get("lastSeenAt"),
                    "deviceHealth": latest.get("deviceHealth"), "machineRisk": latest.get("machineRisk"),
                    "operationalRisk": latest.get("operationalRisk"),
                    "engineTemperature": self._engine_temperature(machine, latest),
                })
        message = None
        if not results:
            message = "Dispositivo físico ainda sem telemetria disponível." if errors else "Nenhuma máquina encontrada."
        return _json_safe({
            "tool": "consultar_maquinas_e_esp32", "readOnly": True, "consultedAt": _now_iso(),
            "consultedIds": [item.get("machineId") for item in results], "items": results,
            "status": "unavailable" if errors and not results else "ok", "message": message,
            "semantics": "Temperatura do motor só é exposta para sensor configurado com scope e target de motor.",
        })

    def execute(self, name, arguments):
        if name == "listar_propriedades_em_atencao":
            return self.list_properties_attention()
        if name == "consultar_contexto_da_propriedade":
            return self.property_context(arguments.get("query"))
        if name == "consultar_alertas_e_eventos":
            return self.alerts_events(arguments.get("property_id"))
        if name == "consultar_maquinas_e_esp32":
            return self.machines_esp32(arguments.get("property_id"), arguments.get("machine_query"))
        raise AgentValidationError("Tool desconhecida.")

    @staticmethod
    def _matches_question(question, item):
        normalized_question = _normalize(question)
        candidates = (
            item.get("propertyId"), item.get("name"), item.get("municipality"),
            f"{item.get('municipality')}/{item.get('state')}",
        )
        matches = [candidate for candidate in candidates
                   if len(_normalize(candidate)) >= 3 and _normalize(candidate) in normalized_question]
        exact_score = max((len(_normalize(candidate)) for candidate in matches), default=0)
        if exact_score:
            return exact_score + 1000

        generic = {"fazenda", "demo", "propriedade", "municipio", "estado"}
        question_words = [word.strip(".,;:!?()[]{}—-") for word in normalized_question.split()]
        partial_scores = []
        for candidate in candidates:
            candidate_words = [word.strip(".,;:!?()[]{}—-") for word in _normalize(candidate).split()]
            candidate_words = [word for word in candidate_words if len(word) >= 3 and word not in generic]
            if not candidate_words:
                continue
            if all(any(question_word.startswith(word) or word.startswith(question_word)
                       for question_word in question_words if len(question_word) >= 3)
                   for word in candidate_words):
                partial_scores.append(sum(len(word) for word in candidate_words))
        return max(partial_scores, default=0)

    def get_agent_context(self, question, context_property_id=None):
        """Monta contexto limitado e rastreável sem delegar seleção factual ao LLM."""
        portfolio = self.list_properties_attention()
        ranked = sorted(
            portfolio.get("items", []), key=lambda item: self._matches_question(question, item), reverse=True,
        )
        top_score = self._matches_question(question, ranked[0]) if ranked else 0
        tied = [item for item in ranked if self._matches_question(question, item) == top_score] if top_score else []
        matched = ranked[0] if top_score and len(tied) == 1 else None
        normalized_question = _normalize(question)
        detail_terms = ("por que", "fator", "explic", "tendencia", "dado falt", "fonte",
                        "maior risco", "mais crit", "acontecendo", "regiao", "essa propriedade",
                        "essa fazenda", "em risco", "satelite", "incendio", "foco", "perto",
                        "clima", "confi", "cobertura", "qualidade", "merece", "atencao")
        previous = next((item for item in ranked if item.get("propertyId") == context_property_id), None)
        asks_other = any(term in normalized_question for term in ("outra fazenda", "outra propriedade"))
        if not matched and asks_other and previous:
            alternatives = [item for item in ranked if item.get("propertyId") != context_property_id]
            matched = alternatives[0] if len(alternatives) == 1 else None
        if not matched and previous:
            matched = previous
        if not matched and ranked and any(term in normalized_question for term in detail_terms):
            matched = ranked[0]
        property_id = matched.get("propertyId") if matched else None
        context = {
            "origem_contexto": "backend_oficial_sompo",
            "somente_leitura": True,
            "carteira": portfolio,
            "orientacoes_semanticas": {
                "score": "Índice operacional /100; não é probabilidade.",
                "hotspot": "Foco de calor por satélite não confirma incêndio.",
                "granizo": "Alerta com menção a granizo não confirma ocorrência.",
                "telemetria": "Dado ausente deve permanecer indisponível.",
            },
        }
        used_tools = ["listar_propriedades_em_atencao"]
        if matched:
            detail = self.property_context(property_id or matched.get("name"))
            context["propriedade"] = detail
            context["fazenda_id"] = property_id
            context["analise"] = detail.get("risk")
            used_tools.append("consultar_contexto_da_propriedade")
            if previous and previous.get("propertyId") != property_id and any(
                    term in normalized_question for term in ("compar", "outra fazenda", "outra propriedade")):
                context["propriedade_anterior"] = self.property_context(previous.get("propertyId"))

        alert_terms = ("alerta", "evento", "hotspot", "foco", "incendio", "queimada",
                       "granizo", "tempestade", "inmet", "meteorolog")
        if any(term in normalized_question for term in alert_terms):
            context["alertas_eventos"] = self.alerts_events(property_id)
            used_tools.append("consultar_alertas_e_eventos")

        machine_terms = ("maquina", "trator", "esp32", "sensor", "telemetria", "motor", "dispositivo")
        if any(term in normalized_question for term in machine_terms):
            context["maquinas_esp32"] = self.machines_esp32(property_id, question)
            used_tools.append("consultar_maquinas_e_esp32")

        context["tools_consultadas"] = used_tools
        return _json_safe(context)

    @staticmethod
    def _satellite_name(hotspot):
        if not isinstance(hotspot, dict):
            return None
        for key in ("satellite", "satelite", "satellite_name", "satellite_id",
                    "satelliteName", "satelliteId"):
            value = hotspot.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    @staticmethod
    def _risk_type_label(value):
        labels = {"incendio": "incêndio", "geada": "geada", "inundacao": "inundação",
                  "enxurrada": "enxurrada", "movimento_massa": "movimento de massa",
                  "terreno": "terreno"}
        normalized = _normalize(value)
        return labels.get(normalized, str(value or "não disponível").replace("_", " "))

    @staticmethod
    def _append_section(lines, title, items):
        values = [str(item).strip() for item in items if item is not None and str(item).strip()]
        if not values:
            return
        lines.extend(["", f"{title}:"])
        lines.extend(f"- {item}" for item in values)

    def format_for_llm(self, context, question=""):
        """Converte contratos internos em texto executivo, sem enviar o JSON bruto ao modelo."""
        lines = []
        detail = context.get("propriedade") or {}
        prop = detail.get("property") or {}
        risk = detail.get("risk") or {}
        if detail:
            municipality = prop.get("municipality")
            state = prop.get("state")
            location = "/".join(str(value) for value in (municipality, state) if value)
            local_items = [location or prop.get("name") or "Local não disponível"]
            if prop.get("name") and prop.get("name") != location:
                local_items.append(f"Ativo monitorado: {prop.get('name')}")
            if detail.get("propertyDisclosure"):
                local_items.append(detail["propertyDisclosure"])
            self._append_section(lines, "LOCAL", local_items)

            score = risk.get("score")
            level = risk.get("nivel")
            score_text = f"{score}/100" if score is not None else "índice não disponível"
            level_text = str(level).upper() if level else "nível não disponível"
            self._append_section(lines, "RISCO OFICIAL", [
                f"Tipo: {self._risk_type_label(prop.get('riskType'))}",
                f"{score_text} — {level_text}",
                (f"Confiança informada pelo motor: {risk.get('confianca') or prop.get('confidence')}"
                 if risk.get("confianca") or prop.get("confidence") else None),
                (f"Cobertura dos dados: {risk.get('coberturaDadosPct', prop.get('coveragePercent'))}%"
                 if risk.get("coberturaDadosPct", prop.get("coveragePercent")) is not None else None),
            ])

            factors = []
            factor_items = [factor for factor in risk.get("fatores") or [] if isinstance(factor, dict)]
            factor_items.sort(
                key=lambda factor: factor.get("contribuicao")
                if isinstance(factor.get("contribuicao"), (int, float)) else float("-inf"),
                reverse=True,
            )
            for factor in factor_items:
                if not isinstance(factor, dict):
                    continue
                description = factor.get("descricao")
                name = str(factor.get("fator") or "").replace("_", " ").strip()
                factors.append(description or name)
            self._append_section(lines, "FATORES REAIS DO MOTOR — MAIOR CONTRIBUIÇÃO PRIMEIRO", factors or [
                "Dados insuficientes para explicar este nível.",
            ])

            weather = []
            evidence_sources = []
            for evidence in detail.get("environmentalEvidence") or []:
                if not isinstance(evidence, dict):
                    continue
                label = evidence.get("label")
                if not label or "distancia" in _normalize(label):
                    continue
                value = evidence.get("value")
                unit = evidence.get("unit") or ""
                if value is None:
                    continue
                source = evidence.get("source")
                source_suffix = f"; fonte: {source}" if source else ""
                weather.append(f"{label}: {value} {unit}".strip() + source_suffix)
                if source:
                    evidence_sources.append(source)
            self._append_section(lines, "METEOROLOGIA E AMBIENTE", weather)

            hotspot_context = detail.get("hotspots") or {}
            hotspot = detail.get("nearestHotspot") or hotspot_context.get("nearest")
            hotspot_items = hotspot_context.get("items") or []
            satellite = self._satellite_name(hotspot)
            if not satellite and hotspot_items:
                hotspot_id = (hotspot or {}).get("id")
                matching = next((item for item in hotspot_items if hotspot_id and item.get("id") == hotspot_id),
                                hotspot_items[0])
                satellite = self._satellite_name(matching)
            if hotspot:
                hotspot_lines = []
                if hotspot_items:
                    hotspot_lines.append(f"Focos encontrados no recorte consultado: {len(hotspot_items)}")
                if hotspot_context.get("lookbackHours") is not None:
                    hotspot_lines.append(f"Período analisado: últimas {hotspot_context.get('lookbackHours')} horas")
                detected_at = hotspot.get("detectedAt") or hotspot.get("dataHoraUtc")
                distance = hotspot.get("distanciaKm")
                if detected_at:
                    hotspot_lines.append(f"Horário da detecção: {detected_at}")
                if distance is not None:
                    hotspot_lines.append(f"Distância da área analisada: {distance} km")
                hotspot_lines.append(
                    f"Satélite informado pelo backend: {satellite}"
                    if satellite else "Satélite específico: não disponível no contexto atual."
                )
                hotspot_lines.append(f"Fonte: {hotspot.get('source') or 'INPE Programa Queimadas'}")
                hotspot_lines.append("Foco de calor não confirma incêndio em andamento.")
                self._append_section(lines, "FOCO DE CALOR MAIS PRÓXIMO", hotspot_lines)

            sources = list(evidence_sources)
            source_freshness = []
            for source_data in (detail.get("sources") or {}).values():
                if not isinstance(source_data, dict):
                    continue
                source = source_data.get("source")
                if source:
                    sources.append(source)
                if source and source_data.get("consultedAt"):
                    source_freshness.append(f"{source}: consultado em {source_data.get('consultedAt')}")
            if hotspot and hotspot.get("source"):
                sources.append(hotspot.get("source"))
            self._append_section(lines, "FONTES", list(dict.fromkeys(sources)))
            freshness = []
            if detail.get("analysisAt"):
                freshness.append(f"Análise oficial: {detail.get('analysisAt')}")
            if detail.get("snapshotGeneratedAt"):
                freshness.append(f"Snapshot: {detail.get('snapshotGeneratedAt')}")
            freshness.extend(source_freshness)
            self._append_section(lines, "ATUALIZAÇÃO DOS DADOS", freshness)

            normalized_question = _normalize(question)
            trend_requested = any(term in normalized_question for term in (
                "tendencia", "aumentou", "diminuiu", "mudou", "evolucao",
            ))
            trend = detail.get("trend")
            if trend:
                if isinstance(trend, dict):
                    trend_items = [f"{str(key).replace('_', ' ')}: {value}" for key, value in trend.items()
                                   if value is not None]
                else:
                    trend_items = [trend]
                self._append_section(lines, "TENDÊNCIA", trend_items)
            elif trend_requested:
                self._append_section(lines, "TENDÊNCIA", [
                    "Histórico insuficiente para afirmar aumento, queda ou estabilidade do risco.",
                ])
        else:
            portfolio_items = []
            for item in (context.get("carteira") or {}).get("items", []):
                location = "/".join(str(value) for value in (item.get("municipality"), item.get("state")) if value)
                score = item.get("riskScore")
                level = str(item.get("riskLevel") or "não disponível").upper()
                score_text = f"{score}/100" if score is not None else "índice não disponível"
                portfolio_items.append(f"{item.get('name') or location}: {score_text} — {level}")
            self._append_section(lines, "RESUMO DA CARTEIRA", portfolio_items or ["Dados indisponíveis."])

        alerts = context.get("alertas_eventos") or {}
        alert_lines = []
        for item in alerts.get("weatherAlerts") or []:
            alert_lines.append(" | ".join(str(value) for value in (
                item.get("eventType"), item.get("severity"), item.get("source"),
            ) if value))
        for item in alerts.get("events") or []:
            event = item.get("meaning") or item.get("eventType")
            suffix = f"; {item.get('occurredAt')}" if item.get("occurredAt") else ""
            alert_lines.append(f"{event}{suffix}")
        self._append_section(lines, "ALERTAS E EVENTOS", alert_lines)

        machine_lines = []
        for item in (context.get("maquinas_esp32") or {}).get("items", []):
            machine_lines.append(item.get("name") or item.get("machineId"))
            if item.get("physicalDeviceMessage"):
                machine_lines.append(item.get("physicalDeviceMessage"))
            engine = item.get("engineTemperature") or {}
            if engine.get("status") == "available":
                machine_lines.append(f"Temperatura do motor: {engine.get('value')} {engine.get('unit') or ''}".strip())
            elif engine.get("message"):
                machine_lines.append(engine.get("message"))
            machine_risk = item.get("machineRisk") or {}
            operational_risk = item.get("operationalRisk") or {}
            if machine_risk:
                machine_lines.append(f"Risco da máquina: {machine_risk.get('nivel') or machine_risk.get('status')}")
            if operational_risk:
                machine_lines.append(
                    f"Risco operacional: {operational_risk.get('nivel') or operational_risk.get('status')}",
                )
        if context.get("maquinas_esp32") and not machine_lines:
            machine_lines.append(context["maquinas_esp32"].get("message") or "Dados de máquinas indisponíveis.")
        self._append_section(lines, "MÁQUINAS E ESP32", machine_lines)

        return "\n".join(lines).strip()

    @staticmethod
    def trace_context(context):
        trace = {"tools": list(context.get("tools_consultadas") or []),
                 "consultedIds": [], "sources": [], "timestamps": []}

        def walk(value, key=None):
            if isinstance(value, dict):
                trace["consultedIds"].extend(value.get("consultedIds") or [])
                for child_key, child in value.items():
                    walk(child, child_key)
            elif isinstance(value, list):
                for child in value:
                    walk(child, key)
            elif isinstance(value, str):
                normalized_key = _normalize(key)
                if normalized_key in {"source", "fonte", "atribuicao", "attribution"}:
                    trace["sources"].append(value)
                if normalized_key.endswith("at") or normalized_key in {
                    "consultadoem", "detectadoem", "generatedat", "observedat", "occurredat",
                }:
                    trace["timestamps"].append(value)

        walk(context)
        for key in trace:
            trace[key] = list(dict.fromkeys(filter(None, trace[key])))
        return trace
