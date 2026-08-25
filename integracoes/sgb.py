"""Consulta conservadora às coleções de suscetibilidade da OGC API do SGB."""

import logging
import unicodedata
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from integracoes.cache import cache, chave_coordenada


LOGGER = logging.getLogger(__name__)
BASE_URL = "https://geoservicos.sgb.gov.br/ogcapi"
TIMEOUT = 12
COLECOES = {
    "inundacao": "gestao-territorial/suscetibilidade/inundacao",
    "enxurrada": "gestao-territorial/suscetibilidade/enxurrada",
    "movimentoMassa": "gestao-territorial/suscetibilidade/movimento-de-massa",
    "corridaMassa": "gestao-territorial/suscetibilidade/corrida-de-massa",
}


def _agora():
    return datetime.now(timezone.utc).isoformat()


def _normalizar(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def _classe(properties):
    for chave, valor in properties.items():
        if "class" in _normalizar(chave) or "susc" in _normalizar(chave):
            texto = _normalizar(valor)
            if "muito alto" in texto or "muito alta" in texto:
                return "muito_alta"
            if "alto" in texto or "alta" in texto:
                return "alta"
            if "medio" in texto or "media" in texto:
                return "media"
            if "baixo" in texto or "baixa" in texto:
                return "baixa"
    return None


def _dentro_extensao(latitude, longitude, metadados):
    caixas = metadados.get("extent", {}).get("spatial", {}).get("bbox", [])
    if not caixas:
        return None
    for caixa in caixas:
        if len(caixa) >= 4 and caixa[0] <= longitude <= caixa[2] and caixa[1] <= latitude <= caixa[3]:
            return True
    return False


def _consultar_colecao(nome, colecao, latitude, longitude):
    caminho = quote(colecao, safe="/")
    metadados_resp = requests.get(f"{BASE_URL}/collections/{caminho}", params={"f": "json"}, timeout=TIMEOUT)
    metadados_resp.raise_for_status()
    metadados = metadados_resp.json()
    dentro = _dentro_extensao(latitude, longitude, metadados)
    if dentro is False:
        return {"status": "fonte_sem_cobertura", "classe": None, "featuresEncontradas": 0}

    # Uma caixa mínima efetua a consulta pontual sem depender de extensões CQL.
    delta = 0.00001
    bbox = f"{longitude-delta},{latitude-delta},{longitude+delta},{latitude+delta}"
    itens_resp = requests.get(
        f"{BASE_URL}/collections/{caminho}/items",
        params={"f": "json", "bbox": bbox, "limit": 10}, timeout=TIMEOUT,
    )
    itens_resp.raise_for_status()
    features = itens_resp.json().get("features", [])
    if not features:
        return {"status": "sem_evidencia_na_fonte", "classe": None, "featuresEncontradas": 0}
    classes = [_classe(feature.get("properties", {})) for feature in features]
    ordem = {"baixa": 1, "media": 2, "alta": 3, "muito_alta": 4}
    classes_validas = [item for item in classes if item in ordem]
    classe = max(classes_validas, key=ordem.get) if classes_validas else None
    return {
        "status": "risco_classificado" if classe else "evidencia_sem_classe",
        "classe": classe,
        "featuresEncontradas": len(features),
    }


def consultar_suscetibilidade(latitude, longitude):
    chave = chave_coordenada("sgb", latitude, longitude)
    armazenado = cache.obter(chave)
    if armazenado:
        armazenado["cache"] = True
        return armazenado

    resultados = {}
    for nome, colecao in COLECOES.items():
        try:
            resultados[nome] = _consultar_colecao(nome, colecao, latitude, longitude)
        except (requests.RequestException, ValueError) as erro:
            LOGGER.warning("Falha na coleção SGB %s: %s", nome, erro)
            resultados[nome] = {"status": "erro_api", "classe": None, "mensagem": str(erro)}

    estados = {item["status"] for item in resultados.values()}
    status = "erro_api" if estados == {"erro_api"} else "parcial" if "erro_api" in estados else "ok"
    resultado = {
        "status": status,
        "mensagem": "Uma ou mais coleções falharam." if status == "parcial" else None,
        "consultadoEm": _agora(), "cache": False, "dados": resultados,
        "atribuicao": "Serviço Geológico do Brasil (SGB) - OGC API, CC-BY 4.0",
    }
    cache.salvar(chave, resultado, 6 * 60 * 60)
    return resultado

