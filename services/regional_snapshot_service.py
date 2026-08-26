"""Persistência e leitura barata dos snapshots regionais usados pelo frontend."""

from datetime import datetime, timezone

from services.firestore_service import consultar_documentos, obter_documento, salvar_documento, upsert_documento
from services.telemetria_service import parse_timestamp
from services.tendencia_service import metricas_tendencia


CURRENT_COLLECTION = "regional_risk_current"
HISTORY_COLLECTION = "regional_risk_snapshots"


def hotspot_summary(dados):
    por_raio = dados.get("quantidadePorRaioKm", {}) if isinstance(dados, dict) else {}
    def total(raio, janela): return (por_raio.get(str(raio)) or {}).get(janela)
    foco = dados.get("focoMaisProximo") if isinstance(dados, dict) else None
    return {"nearestDistanceKm": foco.get("distanciaKm") if foco else None,
        "nearestHotspot": foco, "count5km": total(5, "ultimas48h"), "count10km": total(10, "ultimas48h"),
        "count25km": total(25, "ultimas48h"), "count50km": total(50, "ultimas48h"),
        "last24h": dados.get("quantidadeFocos24hAte50Km") if isinstance(dados, dict) else None,
        "last48h": dados.get("quantidadeFocos48hAte50Km") if isinstance(dados, dict) else None,
        "last7d": dados.get("quantidadeFocos7dAte50Km") if isinstance(dados, dict) else None}


class RegionalSnapshotService:
    def __init__(self, firebase, max_limit=200): self.firebase, self.max_limit = firebase, max_limit

    def _args(self): self.firebase.initialize(); return self.firebase.firestore_url, self.firebase.obter_token

    @staticmethod
    def _id(ibge_code, risk_type): return f"{ibge_code}__{risk_type}"

    def persistir(self, item):
        atual = dict(item); atual["updatedAt"] = datetime.now(timezone.utc)
        upsert_documento(*self._args(), CURRENT_COLLECTION,
                         self._id(item["territory"]["ibgeCode"], item["riskType"]), atual)
        return salvar_documento(*self._args(), HISTORY_COLLECTION, atual)

    def listar(self, state, risk_type, limit=20, level=None, municipality=None):
        limite = int(limit)
        if not 1 <= limite <= self.max_limit: raise ValueError(f"limit deve estar entre 1 e {self.max_limit}.")
        # Uma única query traz no máximo uma linha corrente por município; filtros textuais são locais.
        itens = consultar_documentos(*self._args(), CURRENT_COLLECTION,
            {"territory.state": state, "riskType": risk_type}, "riskScore", "DESCENDING", self.max_limit)
        if level: itens = [x for x in itens if x.get("riskLevel") == level]
        if municipality:
            alvo = municipality.casefold(); itens = [x for x in itens if alvo in (x.get("territory", {}).get("municipality") or "").casefold()]
        validos = [x for x in itens if isinstance(x.get("riskScore"), (int, float))]
        insuficientes = [x for x in itens if not isinstance(x.get("riskScore"), (int, float))]
        return (validos + insuficientes)[:limite]

    def detalhe(self, ibge_code, risk_type):
        return obter_documento(*self._args(), CURRENT_COLLECTION, self._id(str(ibge_code), risk_type))

    def historico(self, ibge_code, risk_type, limit=50, start_time=None, end_time=None):
        limite = int(limit)
        if not 1 <= limite <= self.max_limit: raise ValueError(f"limit deve estar entre 1 e {self.max_limit}.")
        inicio, fim = parse_timestamp(start_time, "startTime"), parse_timestamp(end_time, "endTime")
        if inicio and fim and inicio > fim: raise ValueError("startTime deve ser anterior a endTime.")
        return consultar_documentos(*self._args(), HISTORY_COLLECTION,
            {"territory.ibgeCode": str(ibge_code), "riskType": risk_type}, "calculatedAt", "DESCENDING",
            limite, inicio, fim)

    def tendencia(self, historico):
        valores = [x.get("riskScore") for x in reversed(historico)]
        return metricas_tendencia(valores)
