"""Orquestração e ranking de risco representativo regional."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from integracoes.cache import cache
from services.risk_context_service import MOTOR_VERSION
from services.regional_snapshot_service import hotspot_summary


REGIONAL_RISK_VERSION = "1.0.0"


class RegionalRiskService:
    def __init__(self, analisar_coordenada, max_concurrency=4, cache_ttl=1800):
        self.analisar_coordenada = analisar_coordenada
        self.max_concurrency, self.cache_ttl = max_concurrency, cache_ttl

    def analisar_localidades(self, localidades, risk_type="incendio", force_refresh=False):
        chave = ("regional", risk_type, tuple((x.get("ibgeCode"), x.get("latitude"), x.get("longitude")) for x in localidades))
        armazenado = None if force_refresh else cache.obter(chave)
        if armazenado: return {**armazenado, "cache": True}
        itens = []
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
            futuros = {executor.submit(self.analisar_coordenada, l["latitude"], l["longitude"]): l for l in localidades
                       if l.get("latitude") is not None and l.get("longitude") is not None}
            for futuro in as_completed(futuros):
                local = futuros[futuro]
                try:
                    resultado = futuro.result(); risco = resultado["riscos"].get(risk_type, {})
                    calculado_em = datetime.now(timezone.utc)
                    itens.append({"territory": {"country": "BR", "state": local.get("state"),
                        "municipality": local.get("municipality"), "ibgeCode": local.get("ibgeCode")},
                        "coordinates": {"latitude": local.get("latitude"), "longitude": local.get("longitude"),
                            "source": local.get("coordinateSource"), "method": local.get("method")},
                        "riskType": risk_type, "riskScore": risco.get("score"), "riskLevel": risco.get("nivel"),
                        "confidence": risco.get("confianca"), "topFactors": risco.get("fatores", [])[:5],
                        "coverage": resultado.get("dataCoverage"), "hotspotSummary": hotspot_summary(resultado.get("hotspotInfo") or {}),
                        "weatherSummary": resultado.get("weatherSummary"), "sourceHealth": resultado.get("sourceHealth"),
                        "calculatedAt": calculado_em, "representativeness": "representative_point_only",
                        "stale": False, "dataAgeSeconds": 0,
                        "engineVersion": MOTOR_VERSION, "regionalRiskVersion": REGIONAL_RISK_VERSION})
                except Exception:
                    itens.append({"territory": {"country": "BR", "state": local.get("state"),
                        "municipality": local.get("municipality"), "ibgeCode": local.get("ibgeCode")},
                        "coordinates": {"latitude": local.get("latitude"), "longitude": local.get("longitude"),
                            "source": local.get("coordinateSource"), "method": local.get("method")},
                        "riskType": risk_type, "riskScore": None, "riskLevel": "dados_insuficientes",
                        "confidence": "insuficiente", "coverage": {}, "topFactors": [], "hotspotSummary": {},
                        "sourceHealth": {}, "calculatedAt": datetime.now(timezone.utc),
                        "representativeness": "representative_point_only", "stale": False,
                        "engineVersion": MOTOR_VERSION, "regionalRiskVersion": REGIONAL_RISK_VERSION})
        itens.sort(key=lambda x: (x.get("riskScore") is not None, x.get("riskScore") or -1), reverse=True)
        resultado = {"status": "ok", "riskType": risk_type, "items": itens,
                     "updatedAt": datetime.now(timezone.utc), "cache": False,
                     "limitation": "Cada resultado representa somente a coordenada de referência informada."}
        cache.salvar(chave, resultado, self.cache_ttl); return resultado

    @staticmethod
    def ranking(snapshots, limit=20):
        validos = [s for s in snapshots if isinstance(s.get("riskScore"), (int, float))]
        return sorted(validos, key=lambda s: s["riskScore"], reverse=True)[:limit]
