"""Persistência no Firestore exclusivamente pela API REST."""

from datetime import datetime, timezone
from urllib.parse import quote

import requests


def _python_firestore(valor):
    if "nullValue" in valor:
        return None
    if "booleanValue" in valor:
        return valor["booleanValue"]
    if "integerValue" in valor:
        return int(valor["integerValue"])
    if "doubleValue" in valor:
        return valor["doubleValue"]
    if "timestampValue" in valor:
        return datetime.fromisoformat(valor["timestampValue"].replace("Z", "+00:00"))
    if "stringValue" in valor:
        return valor["stringValue"]
    if "arrayValue" in valor:
        return [_python_firestore(item) for item in valor["arrayValue"].get("values", [])]
    if "mapValue" in valor:
        return {
            chave: _python_firestore(item)
            for chave, item in valor["mapValue"].get("fields", {}).items()
        }
    return None


def _documento_python(documento):
    dados = {
        chave: _python_firestore(valor)
        for chave, valor in documento.get("fields", {}).items()
    }
    dados["id"] = documento.get("name", "").split("/")[-1]
    return dados


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


def criar_documento(firestore_url, obter_token, colecao, documento_id, dados, timeout=20):
    resposta = requests.post(
        f"{firestore_url}/{quote(colecao, safe='/')}",
        params={"documentId": documento_id},
        headers={"Authorization": f"Bearer {obter_token()}", "Content-Type": "application/json"},
        json={"fields": {chave: _valor_firestore(valor) for chave, valor in dados.items()}},
        timeout=timeout,
    )
    if resposta.status_code not in (200, 201):
        raise RuntimeError(f"Firebase HTTP {resposta.status_code}: {resposta.text}")
    return _documento_python(resposta.json())


def obter_documento(firestore_url, obter_token, colecao, documento_id, timeout=20):
    resposta = requests.get(
        f"{firestore_url}/{quote(colecao, safe='/')}/{quote(documento_id, safe='')}",
        headers={"Authorization": f"Bearer {obter_token()}"}, timeout=timeout,
    )
    if resposta.status_code == 404:
        return None
    if resposta.status_code != 200:
        raise RuntimeError(f"Firebase HTTP {resposta.status_code}: {resposta.text}")
    return _documento_python(resposta.json())


def deletar_documento(firestore_url, obter_token, colecao, documento_id, timeout=20):
    resposta = requests.delete(
        f"{firestore_url}/{quote(colecao, safe='/')}/{quote(documento_id, safe='')}",
        headers={"Authorization": f"Bearer {obter_token()}"}, timeout=timeout,
    )
    if resposta.status_code == 404:
        return False
    if resposta.status_code not in (200, 204):
        raise RuntimeError(f"Firebase HTTP {resposta.status_code}: {resposta.text}")
    return True


def atualizar_documento(firestore_url, obter_token, colecao, documento_id, dados, timeout=20):
    resposta = requests.patch(
        f"{firestore_url}/{quote(colecao, safe='/')}/{quote(documento_id, safe='')}",
        headers={"Authorization": f"Bearer {obter_token()}", "Content-Type": "application/json"},
        json={"fields": {chave: _valor_firestore(valor) for chave, valor in dados.items()}},
        timeout=timeout,
    )
    if resposta.status_code == 404:
        return None
    if resposta.status_code != 200:
        raise RuntimeError(f"Firebase HTTP {resposta.status_code}: {resposta.text}")
    return _documento_python(resposta.json())


def atualizar_campos_documento(firestore_url, obter_token, colecao, documento_id, dados, timeout=20):
    """Atualiza somente os campos informados, preservando credenciais e demais dados."""
    params = [("updateMask.fieldPaths", chave) for chave in dados]
    resposta = requests.patch(
        f"{firestore_url}/{quote(colecao, safe='/')}/{quote(documento_id, safe='')}",
        params=params,
        headers={"Authorization": f"Bearer {obter_token()}", "Content-Type": "application/json"},
        json={"fields": {chave: _valor_firestore(valor) for chave, valor in dados.items()}},
        timeout=timeout,
    )
    if resposta.status_code == 404:
        return None
    if resposta.status_code != 200:
        raise RuntimeError(f"Firebase HTTP {resposta.status_code}: {resposta.text}")
    return _documento_python(resposta.json())


def upsert_documento(firestore_url, obter_token, colecao, documento_id, dados, timeout=20):
    atualizado = atualizar_documento(firestore_url, obter_token, colecao, documento_id, dados, timeout)
    if atualizado is not None: return atualizado
    return criar_documento(firestore_url, obter_token, colecao, documento_id, dados, timeout)


def listar_documentos(firestore_url, obter_token, colecao, limite=100, timeout=20):
    resposta = requests.get(
        f"{firestore_url}/{quote(colecao, safe='/')}", params={"pageSize": limite},
        headers={"Authorization": f"Bearer {obter_token()}"}, timeout=timeout,
    )
    if resposta.status_code == 404:
        return []
    if resposta.status_code != 200:
        raise RuntimeError(f"Firebase HTTP {resposta.status_code}: {resposta.text}")
    return [_documento_python(item) for item in resposta.json().get("documents", [])]


def consultar_documentos(
    firestore_url, obter_token, colecao, filtros=None, ordem_campo=None,
    direcao="DESCENDING", limite=20, start_time=None, end_time=None, timeout=20,
):
    """Executa StructuredQuery REST, sem carregar a coleção inteira em memória."""
    filtros_query = []
    for campo, valor in (filtros or {}).items():
        filtros_query.append({"fieldFilter": {
            "field": {"fieldPath": campo}, "op": "EQUAL", "value": _valor_firestore(valor),
        }})
    if start_time is not None:
        filtros_query.append({"fieldFilter": {
            "field": {"fieldPath": ordem_campo}, "op": "GREATER_THAN_OR_EQUAL",
            "value": _valor_firestore(start_time),
        }})
    if end_time is not None:
        filtros_query.append({"fieldFilter": {
            "field": {"fieldPath": ordem_campo}, "op": "LESS_THAN_OR_EQUAL",
            "value": _valor_firestore(end_time),
        }})
    consulta = {"from": [{"collectionId": colecao}], "limit": limite}
    if filtros_query:
        consulta["where"] = filtros_query[0] if len(filtros_query) == 1 else {
            "compositeFilter": {"op": "AND", "filters": filtros_query}
        }
    if ordem_campo:
        consulta["orderBy"] = [{"field": {"fieldPath": ordem_campo}, "direction": direcao}]
    raiz = firestore_url.rsplit("/documents", 1)[0]
    resposta = requests.post(
        f"{raiz}/documents:runQuery",
        headers={"Authorization": f"Bearer {obter_token()}", "Content-Type": "application/json"},
        json={"structuredQuery": consulta}, timeout=timeout,
    )
    if resposta.status_code != 200:
        raise RuntimeError(f"Firebase HTTP {resposta.status_code}: {resposta.text}")
    return [_documento_python(item["document"]) for item in resposta.json() if item.get("document")]


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
