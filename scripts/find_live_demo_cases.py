"""Busca poucos casos reais e opcionalmente persiste o snapshot usado pelo frontend."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Config
from integracoes.ibge import preparar_localidade
from integracoes.inmet import consultar_inmet
from integracoes.inpe_queimadas import contextualizar_focos, listar_focos_recentes
from integracoes.open_meteo import consultar_clima
from services.live_case_service import LiveCaseService
from services.risco_service import calcular_riscos


def executar(write=False, output=None):
    service = LiveCaseService(
        listar_focos_recentes, contextualizar_focos, preparar_localidade,
        consultar_clima, consultar_inmet, calcular_riscos,
        Config.LIVE_CASE_MONITORED_STATES, Config.LIVE_CASE_MAX_WORKERS,
    )
    payload = service.discover()
    if write and payload.get("cases"):
        service.save_snapshot(payload, output or Config.LIVE_CASE_SNAPSHOT_PATH)
    return payload


def resumo(payload):
    resultado = {"generatedAt": payload.get("generatedAt"), "sourcesResponded": payload.get("sourcesResponded"), "cases": []}
    for caso in payload.get("cases", []):
        risco, propriedade = caso.get("risk", {}), caso.get("property", {})
        evidencia = {item.get("label"): f"{item.get('value')} {item.get('unit')}" for item in caso.get("environmentalEvidence", [])}
        resultado["cases"].append({
            "riskType": caso.get("riskType"), "local": f"{propriedade.get('municipio')}/{propriedade.get('estado')}",
            "score": risco.get("score"), "level": risco.get("nivel"),
            "factors": [item.get("fator") for item in risco.get("fatores", [])], "evidence": evidencia,
            "lastHotspot": ((caso.get("hotspots") or {}).get("nearest") or {}).get("detectedAt"),
        })
    return resultado


def main():
    parser = argparse.ArgumentParser(description="Encontra casos ambientais reais com chamadas limitadas e cache.")
    parser.add_argument("--write", action="store_true", help="Persiste o snapshot somente quando existirem casos reais.")
    parser.add_argument("--output", help="Caminho alternativo do snapshot.")
    args = parser.parse_args()
    payload = executar(args.write, args.output)
    print(json.dumps(resumo(payload), ensure_ascii=False, indent=2))
    if not payload.get("cases"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
