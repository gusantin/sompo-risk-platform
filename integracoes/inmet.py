"""Observações oficiais do INMET publicadas pela OGC API do WIS2 Brasil."""

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import quote
from xml.etree import ElementTree

import requests

from integracoes.cache import cache, chave_coordenada
from integracoes.geoespacial import distancia_km


LOGGER = logging.getLogger(__name__)
TIMEOUT = 20
BASE_URL = "https://wis2bra.inmet.gov.br/oapi"
COLECAO = quote("urn:wmo:md:br-inmet:synop", safe="")
ALERTAS_RSS_URL = "https://apiprevmet3.inmet.gov.br/avisos/rss"
ALERTAS_TIMEOUT = 3
_CAP_LOCK = Lock()


def parse_cap(content):
    ns = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
    root = ElementTree.fromstring(content)
    if root.tag != "{urn:oasis:names:tc:emergency:cap:1.2}alert":
        raise ValueError("Not an official CAP document")
    if root.findtext("cap:status", namespaces=ns) != "Actual" or root.findtext("cap:msgType", namespaces=ns) not in {"Alert", "Update"}:
        return []
    items = []
    for info in root.findall("cap:info", ns):
        if info.findtext("cap:language", default="pt-BR", namespaces=ns) not in {"pt-BR", "pt"}:
            continue
        params = {p.findtext("cap:valueName", namespaces=ns): p.findtext("cap:value", namespaces=ns) for p in info.findall("cap:parameter", ns)}
        polygons = []
        for polygon in info.findall("cap:area/cap:polygon", ns):
            points = [[float(v) for v in pair.split(",")][::-1] for pair in (polygon.text or "").split()]
            if len(points) >= 3 and all(len(p) == 2 and -180 <= p[0] <= 180 and -90 <= p[1] <= 90 for p in points):
                polygons.append(points)
        items.append({"id": root.findtext("cap:identifier", namespaces=ns), "source": "INMET CAP",
            "eventType": info.findtext("cap:event", namespaces=ns), "severity": info.findtext("cap:severity", namespaces=ns),
            "description": info.findtext("cap:description", default="", namespaces=ns),
            "startsAt": info.findtext("cap:onset", namespaces=ns) or info.findtext("cap:effective", namespaces=ns),
            "endsAt": info.findtext("cap:expires", namespaces=ns), "publishedAt": root.findtext("cap:sent", namespaces=ns),
            "municipalityCodes": re.findall(r"\((\d{7})\)", params.get("Municipios") or ""), "polygons": polygons})
    return items


def avisos_aplicaveis(items, property_data, now):
    from integracoes.geoespacial import ponto_no_poligono
    from services.environmental_context import instant
    result = []
    for item in items:
        start, end = instant(item.get("startsAt")), instant(item.get("endsAt"))
        if not start or not end or end <= now or end <= start:
            continue
        evidence = None
        lat, lon = property_data.get("latitude"), property_data.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and any(ponto_no_poligono(lon, lat, p) for p in item.get("polygons", [])):
            evidence = "ponto monitorado dentro do polígono CAP"
        elif str(property_data.get("ibgeCode")) in item.get("municipalityCodes", []):
            evidence = "código IBGE do município listado no CAP"
        if evidence:
            result.append({**{key: item.get(key) for key in ("id", "source", "eventType", "severity", "description", "startsAt", "endsAt", "publishedAt")},
                           "geographicEvidence": evidence, "temporalState": "active" if start <= now else "upcoming"})
    return result


def consultar_contexto_avisos_inmet():
    """All official CAP phenomena for context only; does not change alert ingestion policy."""
    with _CAP_LOCK:
        stored = cache.obter("inmet:cap_context")
        if stored:
            return {**stored, "cache": True}
        try:
            response = requests.get(ALERTAS_RSS_URL, timeout=ALERTAS_TIMEOUT)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            links = list(dict.fromkeys(i.findtext("link") or "" for i in root.findall(".//item")))
            valid_links = [link for link in links if re.fullmatch(r"https://apiprevmet3\.inmet\.gov\.br/avisos/rss/\d+", link)]
            def fetch(link):
                try:
                    response = requests.get(link, timeout=ALERTAS_TIMEOUT, allow_redirects=False)
                    response.raise_for_status()
                    return parse_cap(response.content), True
                except (requests.RequestException, ValueError, ElementTree.ParseError):
                    return [], False
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(fetch, valid_links[:60]))
            complete = len(links) == len(valid_links) and len(valid_links) <= 60 and all(ok for _, ok in results)
            result = {"status": "ok" if complete else "parcial", "atribuicao": "INMET CAP", "consultadoEm": _agora().isoformat(),
                      "cache": False, "dados": {"items": [item for batch, _ in results for item in batch], "complete": complete}}
            cache.salvar("inmet:cap_context", result, 300)
            return result
        except (requests.RequestException, ValueError, ElementTree.ParseError):
            return {"status": "unavailable", "atribuicao": "INMET CAP", "dados": {}, "consultadoEm": None}


class _TabelaAvisoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.celulas = []
        self._celula = None

    def handle_starttag(self, tag, _attrs):
        if tag in {"th", "td"}:
            self._celula = []

    def handle_data(self, data):
        if self._celula is not None:
            self._celula.append(data)

    def handle_endtag(self, tag):
        if tag in {"th", "td"} and self._celula is not None:
            self.celulas.append(" ".join("".join(self._celula).split()))
            self._celula = None


def _normalizar_texto(valor):
    texto = unicodedata.normalize("NFD", str(valor or ""))
    return "".join(caractere for caractere in texto if unicodedata.category(caractere) != "Mn").lower()


def _campos_aviso(descricao_html):
    parser = _TabelaAvisoParser()
    parser.feed(descricao_html or "")
    return {
        _normalizar_texto(chave): valor
        for chave, valor in zip(parser.celulas[::2], parser.celulas[1::2])
    }


def _horario_inmet(valor):
    correspondencia = re.match(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", str(valor or ""))
    if not correspondencia:
        return valor or None
    ano, mes, dia, hora, minuto = correspondencia.groups()
    return f"{dia}/{mes}/{ano} {hora}:{minuto}"


def _agora():
    return datetime.now(timezone.utc)


def _json(url, parametros):
    resposta = requests.get(url, params=parametros, timeout=TIMEOUT)
    resposta.raise_for_status()
    return resposta.json()


def _estacoes_proximas(latitude, longitude):
    for amplitude in (3, 8):
        bbox = f"{longitude-amplitude},{latitude-amplitude},{longitude+amplitude},{latitude+amplitude}"
        bruto = _json(
            f"{BASE_URL}/collections/stations/items",
            {"f": "json", "bbox": bbox, "limit": 1000},
        )
        candidatas = []
        for feature in bruto.get("features", []):
            coordenadas = feature.get("geometry", {}).get("coordinates", [])
            if len(coordenadas) < 2:
                continue
            distancia = distancia_km(latitude, longitude, coordenadas[1], coordenadas[0])
            candidatas.append((distancia, feature))
        if candidatas:
            return sorted(candidatas, key=lambda item: item[0])
    return []


def _campo_por_alias(campos, aliases):
    for alias in aliases:
        if alias in campos:
            return campos[alias]
    return None


def consultar_inmet(latitude, longitude):
    chave = chave_coordenada("inmet", latitude, longitude)
    armazenado = cache.obter(chave)
    if armazenado:
        armazenado["cache"] = True
        return armazenado

    agora = _agora()
    try:
        candidatas = _estacoes_proximas(latitude, longitude)
        if not candidatas:
            resultado = {
                "status": "fonte_sem_cobertura", "mensagem": "Nenhuma estação encontrada no entorno.",
                "consultadoEm": agora.isoformat(), "cache": False, "dados": {},
                "atribuicao": "INMET WIS2 / OGC API",
            }
            cache.salvar(chave, resultado, 60 * 60)
            return resultado

        inicio = (agora - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fim = agora.strftime("%Y-%m-%dT%H:%M:%SZ")
        distancia = None
        feature = None
        features = []
        # Algumas estações cadastradas estão temporariamente sem publicar dados.
        # Limitar a busca evita uma sequência exagerada de chamadas ao WIS2.
        for distancia_candidata, feature_candidata in candidatas[:8]:
            propriedades_candidata = feature_candidata.get("properties", {})
            id_candidato = propriedades_candidata.get("wigos_station_identifier") or feature_candidata.get("id")
            bruto = _json(
                f"{BASE_URL}/collections/{COLECAO}/items",
                {
                    "f": "json", "wigos_station_identifier": id_candidato,
                    "datetime": f"{inicio}/{fim}", "limit": 1000,
                },
            )
            features = bruto.get("features", [])
            if features:
                distancia, feature = distancia_candidata, feature_candidata
                break
        if feature is None:
            distancia, feature = candidatas[0]
        propriedades = feature.get("properties", {})
        identificador = propriedades.get("wigos_station_identifier") or feature.get("id")
        if not features:
            status = "sem_observacao_recente"
            campos = {}
            horario = None
        else:
            horarios = [item.get("properties", {}).get("reportTime") for item in features]
            horario = max(item for item in horarios if item)
            campos = {
                item.get("properties", {}).get("name"): item.get("properties", {}).get("value")
                for item in features
                if item.get("properties", {}).get("reportTime") == horario
            }
            status = "ok"
        idade = None
        if horario:
            instante = datetime.fromisoformat(horario.replace("Z", "+00:00"))
            idade = round((agora - instante).total_seconds() / 3600, 2)
        dados = {
            "estacao": propriedades.get("name"),
            "codigoWigos": identificador,
            "codigoTradicional": propriedades.get("traditional_station_identifier"),
            "distanciaEstacaoKm": round(distancia, 2),
            "dataHoraObservacaoUtc": horario,
            "idadeObservacaoHoras": idade,
            "observacaoRecente": idade is not None and idade <= 6,
            "temperaturaObservadaC": _campo_por_alias(campos, ("air_temperature",)),
            "umidadeObservadaPct": _campo_por_alias(campos, ("relative_humidity",)),
            "precipitacaoObservadaMm": _campo_por_alias(campos, (
                "total_precipitation_or_total_water_equivalent",
                "total_precipitation_past_1_hour",
            )),
            "velocidadeVentoObservadaMs": _campo_por_alias(campos, ("wind_speed",)),
        }
        resultado = {
            "status": status,
            "mensagem": None if status == "ok" else "Estação encontrada sem observação nas últimas 48 h.",
            "consultadoEm": agora.isoformat(), "cache": False, "dados": dados,
            "atribuicao": "INMET WIS2 / OGC API",
        }
        cache.salvar(chave, resultado, 30 * 60)
        return resultado
    except (requests.RequestException, ValueError) as erro:
        LOGGER.warning("Falha ao consultar INMET WIS2: %s", erro)
        return {
            "status": "erro_api", "mensagem": str(erro),
            "consultadoEm": agora.isoformat(), "cache": False, "dados": {},
            "atribuicao": "INMET WIS2 / OGC API",
        }


def consultar_avisos_inmet():
    """Retorna somente avisos cujo tipo oficial seja Tempestade, sem inferir fenômenos."""
    chave = "inmet:avisos_meteorologicos"
    armazenado = cache.obter(chave)
    if armazenado:
        armazenado["cache"] = True
        return armazenado

    agora = _agora()
    try:
        resposta = requests.get(ALERTAS_RSS_URL, timeout=ALERTAS_TIMEOUT)
        resposta.raise_for_status()
        raiz = ElementTree.fromstring(resposta.content)
        avisos = []
        for item in raiz.findall(".//item"):
            titulo = item.findtext("title") or ""
            link = item.findtext("link") or ""
            campos = _campos_aviso(item.findtext("description"))
            evento = campos.get("evento")
            if _normalizar_texto(evento) != "tempestade":
                continue
            descricao = campos.get("descricao") or ""
            texto_explicito = _normalizar_texto(f"{titulo} {descricao}")
            avisos.append({
                "id": link.rstrip("/").rsplit("/", 1)[-1] or titulo,
                "eventType": evento,
                "severity": campos.get("severidade"),
                "status": campos.get("status"),
                "startsAt": _horario_inmet(campos.get("inicio")),
                "endsAt": _horario_inmet(campos.get("fim")),
                "publishedAt": item.findtext("pubDate"),
                "description": descricao,
                "location": campos.get("area"),
                "hailExplicit": "granizo" in texto_explicito,
                "source": "INMET Avisos Meteorológicos",
                "sourceUrl": link,
            })
        resultado = {
            "status": "ok", "mensagem": None, "consultadoEm": agora.isoformat(),
            "cache": False, "dados": {"items": avisos},
            "atribuicao": "INMET Avisos Meteorológicos (RSS)",
        }
        cache.salvar(chave, resultado, 5 * 60)
        return resultado
    except (requests.RequestException, ElementTree.ParseError, ValueError) as erro:
        LOGGER.warning("Falha ao consultar avisos meteorológicos do INMET: %s", erro)
        return {
            "status": "erro_api", "mensagem": str(erro),
            "consultadoEm": agora.isoformat(), "cache": False, "dados": {"items": []},
            "atribuicao": "INMET Avisos Meteorológicos (RSS)",
        }
