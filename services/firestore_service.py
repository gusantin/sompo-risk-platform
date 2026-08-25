"""Persistência no Firestore exclusivamente pela API REST."""

from datetime import datetime, timezone

import requests


def _valor_firestore(valor):
    if valor is None:
        return {"nullValue": None}
    if isinstance(valor, bool):
        return {"booleanValue": valor}
    if isinstance(valor, int):
        return {"integerValue": str(valor)}
    if isinstance(valor, float):
        return {"doubleValue": valor}
    if isinstance(valor, datetime):
        return {"timestampValue": valor.astimezone(timezone.utc).isoformat()}
    if isinstance(valor, dict):
        return {"mapValue": {"fields": {chave: _valor_firestore(item) for chave, item in valor.items()}}}
    if isinstance(valor, (list, tuple)):
        return {"arrayValue": {"values": [_valor_firestore(item) for item in valor]}}
    return {"stringValue": str(valor)}


def salvar_documento(firestore_url, obter_token, colecao, dados, timeout=20):
    payload = {"fields": {chave: _valor_firestore(valor) for chave, valor in dados.items()}}
    resposta = requests.post(
        f"{firestore_url}/{colecao}",
        headers={"Authorization": f"Bearer {obter_token()}", "Content-Type": "application/json"},
        json=payload, timeout=timeout,
    )
    if resposta.status_code not in (200, 201):
        raise RuntimeError(f"Firebase HTTP {resposta.status_code}: {resposta.text}")
    return resposta.json()


def montar_analise(latitude, longitude, riscos, fontes):
    fontes_resumidas = {
        nome: {
            "status": fonte.get("status"), "consultadoEm": fonte.get("consultadoEm"),
            "cache": fonte.get("cache", False), "dados": fonte.get("dados", {}),
        }
        for nome, fonte in fontes.items()
    }
    return {
        "latitude": latitude, "longitude": longitude,
        "timestamp": datetime.now(timezone.utc),
        "scores": {nome: item.get("score") for nome, item in riscos.items() if isinstance(item, dict) and "score" in item},
        "fatores": {nome: item.get("fatores", []) for nome, item in riscos.items() if isinstance(item, dict)},
        "fontes": fontes_resumidas,
    }
