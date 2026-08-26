"""Sincroniza municípios e pontos representativos oficiais do IBGE sem apagar registros."""

import argparse
import json
import logging

from integracoes.ibge import IbgeError, preparar_localidades
from services.firestore_service import consultar_documentos, upsert_documento
import server


LOGGER = logging.getLogger("regional_sync")


def executar(uf, dry_run=False, only_missing=False):
    resultado = preparar_localidades(uf)
    existentes = []
    if only_missing:
        existentes = consultar_documentos(*server._firebase_args(), "regional_locations", {"state": uf},
                                           "municipality", "ASCENDING", 300)
    codigos_existentes = {str(item.get("ibgeCode")) for item in existentes}
    gravados, ignorados = 0, 0
    for local in resultado["locations"]:
        if only_missing and local["ibgeCode"] in codigos_existentes:
            ignorados += 1; continue
        if not dry_run:
            upsert_documento(*server._firebase_args(), "regional_locations", local["ibgeCode"], local)
        gravados += 1
    resumo = {"status": resultado["status"], "state": uf, "resolved": len(resultado["locations"]),
              "unresolved": resultado["unresolved"], "written": 0 if dry_run else gravados,
              "prepared": gravados, "skippedExisting": ignorados, "dryRun": dry_run,
              "source": resultado["source"]}
    LOGGER.info("service=regional_sync state=%s resolved=%d unresolved=%d dry_run=%s",
                uf, len(resultado["locations"]), len(resultado["unresolved"]), dry_run)
    return resumo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uf", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-missing", action="store_true")
    args = parser.parse_args(); uf = args.uf.upper()
    if uf not in server.ESTADOS: parser.error("UF inválida")
    try: resultado = executar(uf, args.dry_run, args.only_missing)
    except IbgeError as erro:
        LOGGER.warning("service=regional_sync source=ibge error_type=%s", type(erro).__name__)
        resultado = {"status": "error", "state": uf, "error": {"code": "IBGE_UNAVAILABLE", "message": str(erro)}}
    print(json.dumps(resultado, ensure_ascii=False, default=str))


if __name__ == "__main__": main()
