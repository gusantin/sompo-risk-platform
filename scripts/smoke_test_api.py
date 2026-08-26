"""Smoke test do núcleo; cálculos e ingestão são sempre opt-in."""

import argparse
import json
import os
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def consultar(base_url, caminho, api_key=None, method="GET", body=None, device_token=None):
    try:
        headers = {"Accept": "application/json"}
        if api_key: headers["Authorization"] = f"Bearer {api_key}"
        if device_token: headers["X-Device-Token"] = device_token
        encoded = json.dumps(body).encode("utf-8") if body is not None else None
        if encoded is not None: headers["Content-Type"] = "application/json"
        request = Request(f"{base_url.rstrip('/')}{caminho}", data=encoded, headers=headers, method=method)
        with urlopen(request, timeout=30) as resposta:
            payload = json.loads(resposta.read().decode("utf-8"))
            result = {"path": caminho, "http": resposta.status, "status": payload.get("status")}
            for key in ("documentoId", "deviceId", "fazendaId", "maquinaId", "observedAt",
                        "receivedAt", "deduplicated"):
                if key in payload:
                    result[key] = payload[key]
            return result
    except HTTPError as erro:
        try:
            payload = json.loads(erro.read().decode("utf-8"))
            code = (payload.get("error") or {}).get("code")
        except (ValueError, AttributeError):
            code = None
        return {"path": caminho, "http": erro.code, "status": "http_error", "errorCode": code}
    except (URLError, ValueError) as erro: return {"path": caminho, "http": None, "status": "unavailable", "errorType": type(erro).__name__}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--api-key", default=os.getenv("SOMPO_API_KEY"))
    parser.add_argument("--fazenda")
    parser.add_argument("--maquina")
    parser.add_argument("--core-flow", action="store_true", help="Inclui risco, histórico, tendência, alertas e status; pode persistir análise.")
    parser.add_argument("--device")
    parser.add_argument("--device-token", default=os.getenv("SOMPO_DEVICE_TOKEN"))
    parser.add_argument("--send-telemetry", action="store_true")
    parser.add_argument("--temperatura", type=float, default=25.4)
    parser.add_argument("--umidade", type=float, default=61.2)
    args = parser.parse_args()
    caminhos = ["/health", "/ready", "/fazendas", "/dashboard"]
    if args.core_flow:
        if not args.fazenda or not args.maquina:
            parser.error("--core-flow exige --fazenda e --maquina")
        prefix = f"/fazendas/{args.fazenda}"
        caminhos.extend([prefix, f"{prefix}/maquinas", f"{prefix}/maquinas/{args.maquina}",
            f"{prefix}/maquinas/{args.maquina}/telemetria", f"{prefix}/risco",
            f"{prefix}/analises", f"{prefix}/risco/tendencia", f"{prefix}/alertas",
            f"{prefix}/status", f"{prefix}/maquinas/{args.maquina}/status"])
    results = [consultar(args.base_url, path, args.api_key) for path in caminhos]
    if args.send_telemetry:
        if not args.device or not args.device_token:
            parser.error("--send-telemetry exige --device e --device-token/SOMPO_DEVICE_TOKEN")
        results.append(consultar(args.base_url, "/dados", method="POST", device_token=args.device_token, body={
            "deviceId": args.device, "readingId": f"preflight_{uuid.uuid4().hex}",
            "temperatura": args.temperatura, "umidade": args.umidade,
        }))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
