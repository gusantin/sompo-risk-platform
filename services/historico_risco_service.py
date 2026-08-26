"""Histórico e tendências das análises de risco persistidas."""

from services.firestore_service import consultar_documentos
from services.telemetria_service import parse_timestamp
from services.tendencia_service import metricas_tendencia
from services.propriedade_service import validar_id


class HistoricoRiscoService:
    def __init__(self, firebase, default_limit=20, max_limit=100):
        self.firebase, self.default_limit, self.max_limit = firebase, default_limit, max_limit

    def _args(self):
        self.firebase.initialize(); return self.firebase.firestore_url, self.firebase.obter_token

    def listar(self, fazenda_id, limit=None, start_time=None, end_time=None):
        validar_id(fazenda_id); limite = self.default_limit if limit is None else int(limit)
        if not 1 <= limite <= self.max_limit: raise ValueError(f"limit deve estar entre 1 e {self.max_limit}.")
        inicio, fim = parse_timestamp(start_time, "startTime"), parse_timestamp(end_time, "endTime")
        if inicio and fim and inicio > fim: raise ValueError("startTime deve ser anterior a endTime.")
        return consultar_documentos(*self._args(), "analises_risco", {"fazendaId": fazenda_id},
                                    "timestamp", "DESCENDING", limite, inicio, fim)

    def tendencias(self, fazenda_id, limit=None, start_time=None, end_time=None):
        analises = list(reversed(self.listar(fazenda_id, limit, start_time, end_time)))
        nomes = set()
        for analise in analises: nomes.update((analise.get("riscos") or {}).keys())
        tendencias = {}
        for nome in nomes:
            valores = [(a.get("riscos") or {}).get(nome, {}).get("score") for a in analises]
            tendencias[nome] = metricas_tendencia(valores)
        return {"fazendaId": fazenda_id, "samples": len(analises), "risks": tendencias,
                "period": {"start": analises[0].get("timestamp") if analises else None,
                           "end": analises[-1].get("timestamp") if analises else None}}

