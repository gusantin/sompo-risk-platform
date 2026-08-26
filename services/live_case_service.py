"""Seleção limitada de casos ambientais reais para a apresentação do MVP."""

import json
import os
import re
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from services.risk_explanation_service import explain_risks


SOURCE_OK = {"ok", "parcial", "sem_evidencia_na_fonte", "sem_observacao_recente"}
FROST_CANDIDATE_CODES = ("4108502", "4117602", "3139904")


def _agora_iso():
    return datetime.now(timezone.utc).isoformat()


def _slug(valor):
    texto = unicodedata.normalize("NFD", str(valor or ""))
    texto = "".join(caractere for caractere in texto if unicodedata.category(caractere) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_") or "local"


def _score(caso):
    valor = (caso.get("risk") or {}).get("score")
    return valor if isinstance(valor, (int, float)) else -1


class LiveCaseService:
    def __init__(self, listar_focos, contextualizar_focos, preparar_localidade,
                 consultar_clima, consultar_inmet, calcular_riscos,
                 monitored_states=("MT", "MS", "GO", "MG", "PR"), max_workers=3):
        self.listar_focos = listar_focos
        self.contextualizar_focos = contextualizar_focos
        self.preparar_localidade = preparar_localidade
        self.consultar_clima = consultar_clima
        self.consultar_inmet = consultar_inmet
        self.calcular_riscos = calcular_riscos
        self.monitored_states = tuple(monitored_states)
        self.max_workers = max(1, min(int(max_workers), 4))

    @staticmethod
    def _source_health(fontes):
        return {
            nome: {
                "status": fonte.get("status"), "cacheHit": fonte.get("cache", False),
                "consultedAt": fonte.get("consultadoEm"), "attribution": fonte.get("atribuicao", nome),
                "observedAt": (fonte.get("dados") or {}).get("dataHoraObservacaoUtc"),
            }
            for nome, fonte in fontes.items()
        }

    @staticmethod
    def _evidence(fontes, risk_type):
        clima, queimadas = (fontes.get("clima") or {}).get("dados", {}), (fontes.get("queimadas") or {}).get("dados", {})
        consultado_clima = (fontes.get("clima") or {}).get("consultadoEm")
        itens = []

        def adicionar(label, value, unit, source="Open-Meteo Forecast API", observed_at=consultado_clima):
            if isinstance(value, (int, float)):
                itens.append({"label": label, "value": value, "unit": unit, "source": source, "observedAt": observed_at})

        if risk_type == "incendio":
            adicionar("Temperatura atual", clima.get("temperaturaAtualC"), "°C")
            adicionar("Umidade relativa atual", clima.get("umidadeRelativaAtualPct"), "%")
            adicionar("Precipitação atual", clima.get("precipitacaoAtualMm"), "mm")
            adicionar("Chuva acumulada prevista em 72 h", clima.get("chuvaAcumulada72hMm"), "mm")
            adicionar("Vento atual", clima.get("velocidadeVentoAtualKmh"), "km/h")
            adicionar("Rajada máxima prevista em 72 h", clima.get("rajadaMax72hKmh"), "km/h")
            adicionar("Umidade mínima do solo prevista em 72 h", clima.get("umidadeSoloMin72hM3M3"), "m³/m³")
            foco = queimadas.get("focoMaisProximo")
            if foco:
                adicionar("Distância do foco mais próximo", foco.get("distanciaKm"), "km",
                          "INPE Programa Queimadas", foco.get("detectedAt") or foco.get("dataHoraUtc"))
        else:
            adicionar("Temperatura mínima prevista em 72 h", clima.get("temperaturaMinima72hC"), "°C")
            adicionar("Temperatura atual", clima.get("temperaturaAtualC"), "°C")
        return itens

    def _analisar(self, local, risk_type, focos, inpe_consulted_at):
        latitude, longitude = local["latitude"], local["longitude"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            clima_future = executor.submit(self.consultar_clima, latitude, longitude)
            inmet_future = executor.submit(self.consultar_inmet, latitude, longitude)
            clima, inmet = clima_future.result(), inmet_future.result()
        queimadas = self.contextualizar_focos(latitude, longitude, focos, inpe_consulted_at)
        fontes = {"clima": clima, "inmet": inmet}
        if risk_type == "incendio":
            fontes["queimadas"] = queimadas
        riscos = self.calcular_riscos(fontes)
        cobertura = {
            "weatherAvailable": clima.get("status") in {"ok", "parcial"},
            "satelliteAvailable": queimadas.get("status") in {"ok", "parcial"},
            "geospatialAvailable": False, "historyAvailable": False,
            "propertyContextAvailable": False, "iotAvailable": False,
        }
        risco = riscos.get(risk_type, {})
        municipio = local.get("municipio") or local.get("municipality")
        uf = local.get("uf") or local.get("state")
        recentes = (queimadas.get("dados") or {}).get("focosRecentes", []) if risk_type == "incendio" else []
        caso = {
            "id": f"live_{risk_type}_{_slug(uf)}_{_slug(municipio)}",
            "riskType": risk_type, "risk": risco,
            "riskExplanation": explain_risks(riscos, cobertura).get(risk_type, {}),
            "property": {
                "fazendaId": f"live_{risk_type}_{_slug(uf)}_{_slug(municipio)}",
                "nome": f"Fazenda Demo — {(municipio or uf or 'local monitorado').title()}",
                "municipio": municipio, "estado": uf, "latitude": latitude, "longitude": longitude,
                "demoData": True, "environmentalDataReal": True,
                "coordinateSource": local.get("coordinateSource", "INPE Programa Queimadas"),
                "coordinateMethod": local.get("method", "observed_hotspot_coordinate"),
                "ibgeCode": local.get("ibgeCode"), "culturas": [],
            },
            "environmentalDataReal": True, "analysisAt": _agora_iso(),
            "environmentalEvidence": self._evidence(fontes, risk_type),
            "dataCoverage": cobertura, "sourceHealth": self._source_health(fontes),
            "provenance": {
                nome: {"source": fonte.get("atribuicao", nome), "consultedAt": fonte.get("consultadoEm"),
                       "status": fonte.get("status"), "cache": fonte.get("cache", False)}
                for nome, fonte in fontes.items()
            },
            "hotspots": {"lookbackHours": 48, "items": recentes[:8],
                         "nearest": (queimadas.get("dados") or {}).get("focoMaisProximo")},
            "relevant": risco.get("nivel") in {"moderado", "alto", "critico"},
        }
        return caso

    @staticmethod
    def _fire_candidates(focos, limit=5):
        selecionados, chaves, estados = [], set(), set()
        for foco in focos:
            uf = foco.get("uf")
            if uf in estados:
                continue
            estados.add(uf)
            chave = (uf, foco.get("municipio"))
            chaves.add(chave)
            selecionados.append({**foco, "coordinateSource": "INPE Programa Queimadas",
                                 "method": "observed_hotspot_coordinate"})
            if len(selecionados) >= limit:
                return selecionados
        for foco in focos:
            chave = (foco.get("uf"), foco.get("municipio"))
            if chave in chaves:
                continue
            chaves.add(chave)
            selecionados.append({**foco, "coordinateSource": "INPE Programa Queimadas",
                                 "method": "observed_hotspot_coordinate"})
            if len(selecionados) >= limit:
                break
        return selecionados

    def discover(self, fire_candidate_limit=5, frost_codes=FROST_CANDIDATE_CODES):
        inicio = _agora_iso()
        inpe = self.listar_focos(self.monitored_states, 300)
        focos = (inpe.get("dados") or {}).get("items", [])
        casos, erros = [], []

        candidatos_fogo = self._fire_candidates(focos, fire_candidate_limit)
        avaliados_fogo = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futuros = {executor.submit(self._analisar, local, "incendio", focos, inpe.get("consultadoEm")): local
                       for local in candidatos_fogo}
            for futuro in as_completed(futuros):
                try:
                    avaliados_fogo.append(futuro.result())
                except Exception as erro:
                    erros.append({"riskType": "incendio", "location": futuros[futuro], "error": type(erro).__name__})
        if avaliados_fogo:
            casos.append(max(avaliados_fogo, key=_score))

        candidatos_geada = []
        for codigo in frost_codes:
            try:
                candidatos_geada.append(self.preparar_localidade(codigo))
            except Exception as erro:
                erros.append({"riskType": "geada", "ibgeCode": codigo, "error": type(erro).__name__})
        avaliados_geada = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futuros = {executor.submit(self._analisar, local, "geada", focos, inpe.get("consultadoEm")): local
                       for local in candidatos_geada}
            for futuro in as_completed(futuros):
                try:
                    avaliados_geada.append(futuro.result())
                except Exception as erro:
                    erros.append({"riskType": "geada", "location": futuros[futuro], "error": type(erro).__name__})
        if avaliados_geada:
            casos.append(max(avaliados_geada, key=_score))

        fontes = sorted({meta.get("source") for caso in casos for meta in caso["provenance"].values()
                         if meta.get("status") in SOURCE_OK and meta.get("source")})
        return {
            "status": "ok" if casos else "unavailable", "generatedAt": _agora_iso(), "startedAt": inicio,
            "environmentalDataReal": bool(casos), "lookbackHours": 48,
            "monitoredStates": list(self.monitored_states), "sourcesResponded": fontes,
            "cases": casos, "errors": erros,
            "limitations": [
                "Propriedades são demonstrativas; coordenadas e condições ambientais são reais.",
                "Focos representam detecções por satélite nas últimas 48 horas e não confirmam incêndio na propriedade.",
                "Previsão de geada usa o motor determinístico atual e não confirma dano ocorrido.",
            ],
        }

    @staticmethod
    def save_snapshot(payload, path):
        destino = Path(path).resolve()
        destino.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destino.parent, delete=False,
                                         prefix=f".{destino.name}.", suffix=".tmp") as arquivo:
            json.dump(payload, arquivo, ensure_ascii=False, indent=2)
            temporario = arquivo.name
        os.replace(temporario, destino)
        return destino

    @staticmethod
    def load_snapshot(path):
        with Path(path).open("r", encoding="utf-8") as arquivo:
            payload = json.load(arquivo)
        if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
            raise ValueError("Snapshot de casos reais inválido.")
        return payload
