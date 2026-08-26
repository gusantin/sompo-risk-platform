"""AgroRiskAgent original integrado ao contexto oficial do SOMPO Risk Platform."""

import json
import re
import unicodedata
from datetime import datetime, timezone

import requests

from .prompts import SYSTEM_PROMPT
from .tools import AgentValidationError


class AgentProviderNotConfiguredError(RuntimeError):
    pass


class AgentProviderError(RuntimeError):
    pass


def _normalize(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    normalized = "".join(char for char in text if unicodedata.category(char) != "Mn").lower()
    return " ".join(normalized.split())


def _join_natural(items):
    values = [str(item).strip().rstrip(".") for item in items if str(item).strip()]
    if len(values) < 2:
        return "".join(values)
    return ", ".join(values[:-1]) + f" e {values[-1]}"


class AgroRiskAgent:
    """Interpreta resultados oficiais via Ollama; não calcula risco nem executa mutações."""

    def __init__(self, tools, provider="ollama", ollama_url="http://localhost:11434",
                 model="llama3.2:3b", timeout_seconds=120, session=None):
        self.tools = tools
        self.provider = str(provider or "").lower().strip()
        self.ollama_url = str(ollama_url or "").rstrip("/")
        self.model = str(model or "").strip()
        self.timeout_seconds = timeout_seconds
        self.session = session or requests

    @property
    def configured(self):
        return self.provider == "ollama" and bool(self.ollama_url and self.model)

    def _ollama(self, prompt):
        if not self.configured:
            raise AgentProviderNotConfiguredError(
                "Configure LLM_PROVIDER=ollama, OLLAMA_URL e OLLAMA_MODEL.",
            )
        try:
            response = self.session.post(
                f"{self.ollama_url}/api/chat",
                json={"model": self.model, "stream": False, "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            text = (payload.get("message") or {}).get("content")
            if not isinstance(text, str) or not text.strip():
                raise AgentProviderError("Ollama não retornou resposta textual.")
            return text.strip()
        except AgentProviderError:
            raise
        except (requests.RequestException, ValueError, TypeError, AttributeError) as error:
            raise AgentProviderError("Ollama indisponível.") from error

    @staticmethod
    def _property_label(detail):
        prop = detail.get("property") or {}
        municipality = str(prop.get("municipality") or "").title()
        state = str(prop.get("state") or "").upper()
        location = "/".join(value for value in (municipality, state) if value)
        return location or prop.get("name") or "A propriedade"

    @staticmethod
    def _ordered_factors(detail):
        risk = detail.get("risk") or {}
        factors = [item for item in risk.get("fatores") or [] if isinstance(item, dict)]
        return sorted(
            factors,
            key=lambda item: item.get("contribuicao")
            if isinstance(item.get("contribuicao"), (int, float)) else float("-inf"),
            reverse=True,
        )

    @staticmethod
    def _factor_phrase(factor):
        text = str(factor.get("descricao") or factor.get("fator") or "").replace("_", " ").strip()
        text = text.split(";", 1)[0].rstrip(".")
        normalized = _normalize(text)
        for marker in (" favorece ", " eleva ", " podem ", " pode ", " mantem ", " indica "):
            position = normalized.find(marker)
            if position > 0:
                text = text[:position].rstrip()
                break
        return text[:1].lower() + text[1:] if text else ""

    def _risk_summary(self, detail, question=""):
        risk = detail.get("risk") or {}
        prop = detail.get("property") or {}
        label = self._property_label(detail)
        score = risk.get("score")
        level = str(risk.get("nivel") or "não disponível").upper()
        risk_type = self.tools._risk_type_label(prop.get("riskType"))
        score_text = f", com índice {score}/100" if score is not None else ""
        sentences = [f"{label} exige atenção porque o risco de {risk_type} está em nível {level}{score_text}."]

        factors = self._ordered_factors(detail)
        descriptions = [self._factor_phrase(item) for item in factors[:3]]
        descriptions = [item for item in descriptions if item]
        if descriptions:
            sentences.append("Os fatores de maior peso são " + _join_natural(descriptions) + ".")
        else:
            sentences.append("Não há fatores suficientes na análise atual para explicar esse nível.")

        hotspot = detail.get("nearestHotspot") or (detail.get("hotspots") or {}).get("nearest")
        joined = _normalize(" ".join(sentences))
        if hotspot and "nao confirma incendio" not in joined:
            sentences.append("O foco de calor é uma evidência recente e não confirma incêndio em andamento.")
        disclosure_requested = any(term in _normalize(question) for term in (
            "demo", "mock", "demonstrativ", "sintetic", "dados reais", "propriedade real",
        ))
        if disclosure_requested and detail.get("propertyDisclosure"):
            sentences.append(str(detail["propertyDisclosure"]).rstrip(".") + ".")
        return " ".join(sentences[:4])

    def _deterministic_answer(self, context, question, fallback=False):
        detail = context.get("propriedade") or {}
        if not detail:
            return None
        normalized_question = _normalize(question)
        label = self._property_label(detail)
        risk = detail.get("risk") or {}
        factors = self._ordered_factors(detail)

        previous = context.get("propriedade_anterior") or {}
        if previous and any(term in normalized_question for term in ("compar", "outra fazenda", "outra propriedade")):
            previous_risk = previous.get("risk") or {}
            current_score, previous_score = risk.get("score"), previous_risk.get("score")
            if current_score is None or previous_score is None:
                return "Não há índices atuais suficientes para comparar as duas propriedades com segurança."
            relation = "maior" if current_score > previous_score else "menor" if current_score < previous_score else "igual"
            return (
                f"{label} está com índice {current_score}/100, {relation} que "
                f"{self._property_label(previous)}, com {previous_score}/100. "
                "A comparação usa os níveis oficiais atuais de cada propriedade."
            )

        if any(term in normalized_question for term in ("maior deles", "principal fator", "mais pesa")):
            if not factors:
                return f"Não há fatores suficientes para apontar o maior risco de {label} neste momento."
            top_value = factors[0].get("contribuicao")
            top = [item for item in factors if item.get("contribuicao") == top_value] if top_value is not None else factors[:1]
            descriptions = [self._factor_phrase(item) for item in top]
            return f"Os maiores pontos de atenção em {label} são {_join_natural(descriptions)}."

        if any(term in normalized_question for term in ("umidade", "como esta seco", "regiao esta seca")):
            evidence = next((item for item in detail.get("environmentalEvidence") or []
                             if "umidade relativa" in _normalize(item.get("label"))
                             and item.get("value") is not None), None)
            if not evidence:
                return (f"Não tenho uma leitura recente de umidade para {label}, então não consigo afirmar "
                        "se esse fator está elevando o risco agora.")
            return (f"A umidade relativa em {label} está em {evidence['value']} {evidence.get('unit') or ''}. "
                    "Esse valor faz parte das condições ambientais consideradas na análise atual.").replace("  ", " ")

        if any(term in normalized_question for term in ("tem incendio", "incendio perto", "foco perto", "foco de calor")):
            hotspot = detail.get("nearestHotspot") or (detail.get("hotspots") or {}).get("nearest")
            if not hotspot:
                return f"Não há foco de calor próximo disponível na análise atual de {label}."
            distance = hotspot.get("distanciaKm")
            distance_text = (f" a {distance} km da área analisada" if distance is not None
                             else " próximo da área analisada")
            source = hotspot.get("source") or "Programa Queimadas do INPE"
            return (f"Há um foco de calor{distance_text}, com registro de {source}. "
                    "Isso não confirma um incêndio em andamento na propriedade.")

        if "satelite" in normalized_question:
            hotspot_context = detail.get("hotspots") or {}
            hotspot = detail.get("nearestHotspot") or hotspot_context.get("nearest")
            satellite = self.tools._satellite_name(hotspot)
            if not satellite:
                items = hotspot_context.get("items") or []
                hotspot_id = (hotspot or {}).get("id")
                matching = next((item for item in items if hotspot_id and item.get("id") == hotspot_id),
                                items[0] if items else None)
                satellite = self.tools._satellite_name(matching)
            if satellite:
                return f"O foco próximo de {label} foi detectado pelo satélite {satellite}, via Programa Queimadas do INPE."
            return ("A fonte do foco é o Programa Queimadas do INPE, mas o satélite específico "
                    "não está disponível na análise atual.")

        if any(term in normalized_question for term in ("de onde", "fonte", "origem das informacoes", "origem dos dados")):
            sources = []
            for item in (detail.get("sources") or {}).values():
                if isinstance(item, dict) and item.get("source"):
                    sources.append(item["source"])
            sources = list(dict.fromkeys(sources))
            if not sources:
                return f"As fontes usadas para {label} não estão disponíveis na análise atual."
            return f"As informações de {label} vêm de {_join_natural(sources)}."

        if any(term in normalized_question for term in ("tendencia", "aumentando", "aumentou", "diminuiu", "mudou")):
            trend = detail.get("trend")
            if not trend:
                return (f"Ainda não há histórico suficiente para afirmar se o risco de {label} está "
                        "aumentando, diminuindo ou estável.")

        direct_terms = ("por que", "exige atencao", "em risco", "acontecendo", "regiao",
                        "mais preocupa", "merece mais atencao", "maior risco", "demo", "mock",
                        "demonstrativ", "sintetic", "dados reais", "propriedade real")
        if fallback or any(term in normalized_question for term in direct_terms):
            return self._risk_summary(detail, question)
        return None

    @staticmethod
    def _validate_grounded_answer(answer, context, question=""):
        normalized = _normalize(answer)
        if re.search(r"\b\d+(?:[,.]\d+)?\s*%\s*(?:de\s+)?(?:chance|probabilidade)\b", normalized):
            raise AgentProviderError("Resposta do provider violou a semântica do score.")
        serialized = _normalize(json.dumps(context, ensure_ascii=False))
        fire_confirmed = '"fireconfirmed": true' in serialized
        hail_confirmed = '"hailoccurrenceconfirmed": true' in serialized
        engine_temperature = '"enginetemperature": {"status": "available"' in serialized
        if not fire_confirmed and re.search(r"\b(?:incendio confirmado|ha um incendio|existe incendio)\b", normalized):
            raise AgentProviderError("Resposta do provider afirmou incêndio sem confirmação.")
        if not hail_confirmed and re.search(r"\b(?:houve|ocorreu)\s+(?:queda de\s+)?granizo\b", normalized):
            raise AgentProviderError("Resposta do provider afirmou granizo ocorrido sem confirmação.")
        if (not engine_temperature
                and re.search(r"temperatura (?:do|de) motor.{0,40}\b\d+(?:[,.]\d+)?", normalized)):
            raise AgentProviderError("Resposta do provider afirmou temperatura de motor sem sensor válido.")
        technical_request = any(term in _normalize(question) for term in (
            "json", "payload", "nome dos campos", "campos internos", "estrutura dos dados",
            "estrutura tecnica", "detalhe tecnico", "tool", "api",
        ))
        if not technical_request and re.search(
                r"\b(?:json|payload|datacoverage|sourcehealth|fazenda_id|tools_consultadas|consultedids)\b"
                r"|raiz do documento|dados estruturados|algoritmo|componentes da resposta"
                r"|pergunta nao formulada|posso consultar|essa e uma resposta|voce gostaria", normalized):
            raise AgentProviderError("Resposta do provider expôs detalhes internos dos dados.")
        disclosure_requested = any(term in _normalize(question) for term in (
            "demo", "mock", "demonstrativ", "sintetic", "dados reais", "propriedade real",
        ))
        if not disclosure_requested and re.search(
                r"\b(?:propriedade|cenario|dados?)\s+(?:demo|mock|de teste|demonstrativ\w*|sintetic\w*)",
                normalized):
            raise AgentProviderError("Resposta do provider expôs classificação interna do cenário.")

        satellites = []

        def collect_satellites(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"satellite", "satelite", "satellite_name", "satellite_id",
                               "satelliteName", "satelliteId"} and child is not None and str(child).strip():
                        satellites.append(str(child).strip())
                    collect_satellites(child)
            elif isinstance(value, list):
                for child in value:
                    collect_satellites(child)

        collect_satellites(context)
        if "satelite" in normalized:
            available = list(dict.fromkeys(satellites))
            if available and not any(_normalize(value) in normalized for value in available):
                raise AgentProviderError("Resposta do provider citou satélite diferente do contexto.")
            unavailable_disclosed = any(term in normalized for term in (
                "nao disponivel", "nao esta disponivel", "indisponivel", "nao informado",
                "nao esta informado", "sem identificacao", "nao consta",
            ))
            if not available and not unavailable_disclosed:
                raise AgentProviderError("Resposta do provider inventou identificador de satélite.")

    def analyze(self, ctx):
        analise = ctx.get("analise") or {}
        semantic_context = self.tools.format_for_llm(ctx)
        prompt = (
            "Interprete os dados oficiais abaixo como analista de risco. NÃO recalcule nem altere "
            "o nível ou score. Explique diretamente os fatores e dê recomendações preventivas.\n\n"
            "DADOS OFICIAIS PARA ANÁLISE:\n"
            + semantic_context
        )
        text = self._ollama(prompt)
        self._validate_grounded_answer(text, ctx)
        return {
            "fazenda_id": ctx.get("fazenda_id"),
            "nivel_risco_oficial": analise.get("nivel"),
            "score_oficial": analise.get("score"),
            "resposta_agente": text,
            "provider": self.provider,
            "modelo": self.model,
        }

    def answer(self, ctx, question):
        deterministic = self._deterministic_answer(ctx, question)
        if deterministic:
            self._validate_grounded_answer(deterministic, ctx, question)
            return {"pergunta": question, "resposta": deterministic,
                    "provider": self.provider, "modelo": self.model}
        semantic_context = self.tools.format_for_llm(ctx, question)
        prompt = (
            f"PERGUNTA DO USUÁRIO:\n{question}\n\n"
            "Responda como analista de risco, de forma curta e executiva. Comece pela conclusão. "
            "Use somente os dados abaixo, sem explicar sua estrutura ou seus rótulos. Não altere "
            "o resultado oficial do motor. Se não houver dado suficiente, declare-o indisponível.\n\n"
            "DADOS OFICIAIS PARA ANÁLISE:\n"
            + semantic_context
        )
        text = self._ollama(prompt)
        try:
            self._validate_grounded_answer(text, ctx, question)
        except AgentProviderError:
            fallback = self._deterministic_answer(ctx, question, fallback=True)
            if not fallback:
                raise
            text = fallback
        return {"pergunta": question, "resposta": text, "provider": self.provider, "modelo": self.model}

    def ask(self, question, context_property_id=None):
        if not isinstance(question, str) or not question.strip():
            raise AgentValidationError("Pergunta é obrigatória.")
        question = question.strip()
        if len(question) > 1000:
            raise AgentValidationError("Pergunta excede 1000 caracteres.")
        if context_property_id is not None and (
                not isinstance(context_property_id, str) or not context_property_id.strip()
                or len(context_property_id) > 100):
            raise AgentValidationError("contextPropertyId inválido.")
        if not self.configured:
            raise AgentProviderNotConfiguredError(
                "Configure LLM_PROVIDER=ollama, OLLAMA_URL e OLLAMA_MODEL.",
            )
        context = self.tools.get_agent_context(question, context_property_id)
        result = self.answer(context, question)
        return {
            "answer": result["resposta"],
            "provider": "Ollama",
            "model": self.model,
            "readOnly": True,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "contextPropertyId": context.get("fazenda_id"),
            "trace": self.tools.trace_context(context),
        }
