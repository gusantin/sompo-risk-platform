"""Cliente isolado para Localidades e Malhas oficiais do IBGE."""

import math
from datetime import datetime, timezone

import requests

from integracoes.cache import cache
from integracoes.geoespacial import ponto_no_geojson


LOCALIDADES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades"
MALHAS_URL = "https://servicodados.ibge.gov.br/api/v3/malhas"
TIMEOUT = 30
TTL_SECONDS = 24 * 60 * 60


class IbgeError(RuntimeError):
    pass


def _get_json(url, params=None):
    try:
        resposta = requests.get(url, params=params, timeout=TIMEOUT)
        resposta.raise_for_status()
        return resposta.json()
    except (requests.RequestException, ValueError) as erro:
        raise IbgeError("Fonte territorial IBGE indisponível ou inválida.") from erro


def listar_municipios(uf):
    uf = str(uf).upper()
    chave = f"ibge:municipios:{uf}"
    armazenado = cache.obter(chave)
    if armazenado: return armazenado
    payload = _get_json(f"{LOCALIDADES_URL}/estados/{uf}/municipios", {"orderBy": "nome"})
    if not isinstance(payload, list): raise IbgeError("Resposta de municípios do IBGE inválida.")
    resultado = []
    for item in payload:
        codigo, nome = str(item.get("id", "")), item.get("nome")
        regiao = item.get("regiao-imediata") or {}
        intermediaria = regiao.get("regiao-intermediaria") or {}
        estado = intermediaria.get("UF") or {}
        if not codigo.isdigit() or not isinstance(nome, str) or not nome.strip():
            raise IbgeError("Município inválido retornado pelo IBGE.")
        resultado.append({"ibgeCode": codigo, "municipality": nome.strip(), "state": estado.get("sigla") or uf,
            "immediateRegion": regiao.get("nome"), "intermediateRegion": intermediaria.get("nome")})
    cache.salvar(chave, resultado, TTL_SECONDS); return resultado


def obter_malhas_municipais(uf):
    uf = str(uf).upper(); chave = f"ibge:malhas:{uf}"
    armazenado = cache.obter(chave)
    if armazenado: return armazenado
    payload = _get_json(f"{MALHAS_URL}/estados/{uf}", {
        "formato": "application/vnd.geo+json", "qualidade": "minima", "intrarregiao": "municipio",
    })
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise IbgeError("Malha municipal do IBGE inválida.")
    resultado = {}
    for feature in payload["features"]:
        codigo = str((feature.get("properties") or {}).get("codarea", ""))
        geometria = feature.get("geometry")
        if codigo.isdigit() and isinstance(geometria, dict) and geometria.get("type") in ("Polygon", "MultiPolygon"):
            resultado[codigo] = geometria
    cache.salvar(chave, resultado, TTL_SECONDS); return resultado


def _area_e_centro(anel):
    soma, cx, cy = 0.0, 0.0, 0.0
    for atual, seguinte in zip(anel, anel[1:]):
        x1, y1 = atual[:2]; x2, y2 = seguinte[:2]; cruzado = x1 * y2 - x2 * y1
        soma += cruzado; cx += (x1 + x2) * cruzado; cy += (y1 + y2) * cruzado
    area = soma / 2
    if abs(area) < 1e-12: return 0, None
    return abs(area), (cy / (6 * area), cx / (6 * area))


def ponto_representativo(geometria):
    """Centróide quando interno; fallback determinístico por grade interna."""
    if not isinstance(geometria, dict) or geometria.get("type") not in ("Polygon", "MultiPolygon"):
        raise IbgeError("Geometria municipal inválida.")
    poligonos = [geometria["coordinates"]] if geometria["type"] == "Polygon" else geometria["coordinates"]
    candidatos = []
    try:
        for poligono in poligonos:
            anel = poligono[0]
            if len(anel) < 4: raise ValueError
            if any(len(p) < 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p[:2]) for p in anel):
                raise ValueError
            area, centro = _area_e_centro(anel); candidatos.append((area, centro, anel))
    except (IndexError, TypeError, ValueError) as erro:
        raise IbgeError("Coordenadas municipais inválidas.") from erro
    for _area, centro, _anel in sorted(candidatos, key=lambda item: item[0], reverse=True):
        if centro and ponto_no_geojson(centro[0], centro[1], geometria):
            return {"latitude": centro[0], "longitude": centro[1], "method": "polygon_centroid_inside"}
    for _area, _centro, anel in sorted(candidatos, key=lambda item: item[0], reverse=True):
        xs, ys = [p[0] for p in anel], [p[1] for p in anel]
        for divisao in (8, 16, 32, 64):
            for iy in range(divisao):
                latitude = min(ys) + (iy + 0.5) * (max(ys) - min(ys)) / divisao
                for ix in range(divisao):
                    longitude = min(xs) + (ix + 0.5) * (max(xs) - min(xs)) / divisao
                    if ponto_no_geojson(latitude, longitude, geometria):
                        return {"latitude": latitude, "longitude": longitude, "method": "interior_grid_point"}
    raise IbgeError("Não foi possível derivar ponto interno confiável.")


def preparar_localidades(uf):
    municipios, malhas = listar_municipios(uf), obter_malhas_municipais(uf)
    registros, pendencias = [], []
    agora = datetime.now(timezone.utc)
    for municipio in municipios:
        geometria = malhas.get(municipio["ibgeCode"])
        if geometria is None:
            pendencias.append({**municipio, "reason": "official_geometry_unavailable"}); continue
        try: ponto = ponto_representativo(geometria)
        except IbgeError:
            pendencias.append({**municipio, "reason": "representative_point_unavailable"}); continue
        registros.append({"country": "BR", **municipio, **ponto,
            "coordinateSource": "IBGE Malhas v3", "geometrySource": "IBGE simplified municipal mesh",
            "representativeness": "representative_point_only", "updatedAt": agora})
    return {"status": "partial" if pendencias else "ok", "locations": registros, "unresolved": pendencias,
            "source": "IBGE Localidades v1 + Malhas v3", "consultedAt": agora}


def preparar_localidade(ibge_code):
    """Obtém um único ponto municipal oficial sem sincronizar toda a UF."""
    codigo = str(ibge_code)
    if not codigo.isdigit():
        raise IbgeError("Código IBGE inválido.")
    chave = f"ibge:localidade:{codigo}"
    armazenado = cache.obter(chave)
    if armazenado:
        return armazenado
    municipio = _get_json(f"{LOCALIDADES_URL}/municipios/{codigo}")
    nome = municipio.get("nome")
    regiao = municipio.get("regiao-imediata") or {}
    intermediaria = regiao.get("regiao-intermediaria") or {}
    estado = intermediaria.get("UF") or {}
    malha = _get_json(f"{MALHAS_URL}/municipios/{codigo}", {
        "formato": "application/vnd.geo+json", "qualidade": "minima",
    })
    features = malha.get("features") if isinstance(malha, dict) else None
    geometria = features[0].get("geometry") if isinstance(features, list) and features else None
    if not isinstance(nome, str) or not nome.strip() or not isinstance(geometria, dict):
        raise IbgeError("Localidade individual inválida retornada pelo IBGE.")
    ponto = ponto_representativo(geometria)
    resultado = {
        "country": "BR", "ibgeCode": codigo, "municipality": nome.strip(),
        "state": estado.get("sigla"), **ponto,
        "coordinateSource": "IBGE Malhas v3", "geometrySource": "IBGE simplified municipal mesh",
        "representativeness": "municipality_representative_point_only",
        "preparedAt": datetime.now(timezone.utc).isoformat(),
    }
    cache.salvar(chave, resultado, TTL_SECONDS)
    return resultado
