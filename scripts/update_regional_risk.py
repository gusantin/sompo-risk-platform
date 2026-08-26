"""Atualização regional controlada. Não executa lote nacional implicitamente."""

import argparse
import json

import server
from services.firestore_service import consultar_documentos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uf", required=True)
    parser.add_argument("--risk", default="incendio")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--municipality")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Ignora apenas o cache regional em uma evolução futura; fontes mantêm cache seguro.")
    args = parser.parse_args()
    uf = args.uf.upper()
    if len(uf) != 2 or not 1 <= args.limit <= server.app.config["REGIONAL_JOB_MAX_LOCATIONS"]:
        parser.error("UF ou limit inválido")
    localidades = consultar_documentos(*server._firebase_args(), "regional_locations", {"state": uf},
                                        "municipality", "ASCENDING", args.limit)
    if args.municipality:
        alvo = args.municipality.casefold()
        localidades = [x for x in localidades if alvo in x.get("municipality", "").casefold()]
    resultado = server.regional_risk.analisar_localidades(localidades, args.risk, args.force_refresh)
    falhas = 0
    if not args.dry_run:
        for item in resultado["items"]:
            try: server.regional_snapshots.persistir(item)
            except Exception: falhas += 1
    print(json.dumps({"status": resultado["status"], "items": len(resultado["items"]),
                      "persisted": 0 if args.dry_run else len(resultado["items"]) - falhas,
                      "failures": falhas, "dryRun": args.dry_run}, ensure_ascii=False))


if __name__ == "__main__":
    main()
