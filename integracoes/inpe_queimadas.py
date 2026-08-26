"""Focos de calor recentes publicados pelo Programa Queimadas do INPE."""

import csv
import io
import logging
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

from integracoes.cache import cache, chave_coordenada
from integracoes.geoespacial import distancia_km


LOGGER = logging.getLogger(__name__)
TIMEOUT = 20
BASE_URL = (
    "https://dataserver-coids.inpe.br/queimadas/queimadas/"
    "focos/csv/diario/Brasil"
)
RAIOS_KM = (5, 10, 25, 50)
ESTADO_PARA_UF = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM", "BAHIA": "BA",
    "CEARA": "CE", "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO",
    "MARANHAO": "MA", "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS",
    "MINAS GERAIS": "MG", "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR",
    "PERNAMBUCO": "PE", "PIAUI": "PI", "RIO DE JANEIRO": "RJ",
    "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO",
    "RORAIMA": "RR", "SANTA CATARINA": "SC", "SAO PAULO": "SP", "SERGIPE": "SE",
    "TOCANTINS": "TO",
}


def _agora():
    return datetime.now(timezone.utc)


def _baixar_dia(dia):
    nome = f"focos_diario_br_{dia:%Y%m%d}.csv"
    resposta = requests.get(f"{BASE_URL}/{nome}", timeout=TIMEOUT)
    resposta.raise_for_status()
    try:
        texto = resposta.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = resposta.content.decode("latin-1")
    return csv.DictReader(io.StringIO(texto))


def _data_utc(valor):
    return datetime.strptime(valor.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _normalizar_estado(valor):
    texto = unicodedata.normalize("NFD", str(valor or "").strip().upper())
    return "".join(caractere for caractere in texto if unicodedata.category(caractere) != "Mn")


def listar_focos_recentes(ufs, limite=200):
    """Lista limitada de focos reais das últimas 48 h para UFs informadas."""
    ufs = tuple(sorted({str(uf).upper() for uf in ufs if str(uf).upper() in ESTADO_PARA_UF.values()}))
    if not ufs:
        return {"status": "invalid", "dados": {"items": [], "lookbackHours": 48}}
    limite = max(1, min(int(limite), 1000))
    chave = f"queimadas:listagem:{','.join(ufs)}:{limite}"
    armazenado = cache.obter(chave)
    if armazenado:
        armazenado["cache"] = True
        return armazenado

    agora, focos, erros = _agora(), [], []
    for dia in (agora.date(), (agora - timedelta(days=1)).date()):
        try:
            for linha in _baixar_dia(dia):
                uf = ESTADO_PARA_UF.get(_normalizar_estado(linha.get("estado")))
                if uf not in ufs:
                    continue
                instante = _data_utc(linha["data_hora_gmt"])
                idade_horas = (agora - instante).total_seconds() / 3600
                if not 0 <= idade_horas <= 48:
                    continue
                focos.append({
                    "id": linha.get("id") or None,
                    "latitude": float(linha["lat"]), "longitude": float(linha["lon"]),
                    "dataHoraUtc": instante.isoformat(), "detectedAt": instante.isoformat(),
                    "idadeHoras": round(idade_horas, 2), "ageHours": round(idade_horas, 2),
                    "source": "INPE Programa Queimadas", "satelite": linha.get("satelite") or None,
                    "municipio": (linha.get("municipio") or "").strip() or None, "uf": uf,
                })
        except (requests.RequestException, ValueError, KeyError) as erro:
            LOGGER.warning("Falha ao consultar listagem diária do INPE (%s): %s", dia, erro)
            erros.append(f"{dia}: {erro}")

    unicos = {}
    for foco in focos:
        chave_foco = (foco["latitude"], foco["longitude"], foco["detectedAt"])
        unicos.setdefault(chave_foco, foco)
    focos = sorted(unicos.values(), key=lambda item: item["detectedAt"], reverse=True)
    resultado = {
        "status": "erro_api" if len(erros) == 2 else "parcial" if erros else "ok",
        "mensagem": "; ".join(erros) if erros else None,
        "consultadoEm": agora.isoformat(), "cache": False,
        "dados": {"items": focos[:limite], "lookbackHours": 48},
        "atribuicao": "INPE Programa Queimadas",
    }
    if resultado["status"] != "erro_api":
        cache.salvar(chave, resultado, 10 * 60)
    return resultado


def contextualizar_focos(latitude, longitude, focos, consultado_em=None):
    """Converte uma listagem INPE já obtida no contrato geoespacial usado pelo motor."""
    agora = _agora()
    proximos = []
    for item in focos:
        distancia = distancia_km(latitude, longitude, item["latitude"], item["longitude"])
        if distancia <= 50:
            proximos.append({**item, "distanciaKm": round(distancia, 2)})
    proximos.sort(key=lambda item: item["distanciaKm"])
    por_raio = {
        str(raio): {
            "ultimas24h": sum(1 for foco in proximos if foco["distanciaKm"] <= raio and foco["idadeHoras"] <= 24),
            "ultimas48h": sum(1 for foco in proximos if foco["distanciaKm"] <= raio),
        }
        for raio in RAIOS_KM
    }
    return {
        "status": "ok", "mensagem": None, "consultadoEm": consultado_em or agora.isoformat(),
        "cache": False, "atribuicao": "INPE Programa Queimadas",
        "dados": {
            "quantidadeFocos24hAte50Km": por_raio["50"]["ultimas24h"],
            "quantidadeFocos48hAte50Km": por_raio["50"]["ultimas48h"],
            "quantidadeFocos7dAte50Km": None, "lookbackHours": 48,
            "quantidadePorRaioKm": por_raio, "focoMaisProximo": proximos[0] if proximos else None,
            "focosRecentes": sorted(proximos, key=lambda item: item["detectedAt"], reverse=True)[:20],
            "observacao": "Foco de calor por satélite não confirma incêndio atingindo a propriedade.",
        },
    }


def consultar_queimadas(latitude, longitude):
    chave = chave_coordenada("queimadas", latitude, longitude)
    armazenado = cache.obter(chave)
    if armazenado:
        armazenado["cache"] = True
        return armazenado

    agora = _agora()
    focos = []
    erros = []
    arquivos_consultados = 0
    for dia in (agora.date(), (agora - timedelta(days=1)).date()):
        try:
            arquivos_consultados += 1
            for linha in _baixar_dia(dia):
                instante = _data_utc(linha["data_hora_gmt"])
                idade_horas = (agora - instante).total_seconds() / 3600
                if idade_horas < 0 or idade_horas > 48:
                    continue
                lat_foco = float(linha["lat"])
                lon_foco = float(linha["lon"])
                distancia = distancia_km(latitude, longitude, lat_foco, lon_foco)
                if distancia <= 50:
                    focos.append({
                        "distanciaKm": round(distancia, 2),
                        "dataHoraUtc": instante.isoformat(),
                        "detectedAt": instante.isoformat(),
                        "idadeHoras": round(idade_horas, 2),
                        "ageHours": round(idade_horas, 2),
                        "source": "INPE Programa Queimadas",
                        "satelite": linha.get("satelite") or None,
                        "latitude": lat_foco,
                        "longitude": lon_foco,
                    })
        except (requests.RequestException, ValueError, KeyError) as erro:
            LOGGER.warning("Falha ao consultar arquivo diário do INPE (%s): %s", dia, erro)
            erros.append(f"{dia}: {erro}")

    if len(erros) == arquivos_consultados:
        return {
            "status": "erro_api", "mensagem": "; ".join(erros),
            "consultadoEm": agora.isoformat(), "cache": False, "dados": {},
            "atribuicao": "INPE Programa Queimadas",
        }

    focos.sort(key=lambda item: item["distanciaKm"])
    por_raio = {}
    for raio in RAIOS_KM:
        por_raio[str(raio)] = {
            "ultimas24h": sum(1 for foco in focos if foco["distanciaKm"] <= raio and foco["idadeHoras"] <= 24),
            "ultimas48h": sum(1 for foco in focos if foco["distanciaKm"] <= raio),
        }
    dados = {
        "quantidadeFocos24hAte50Km": por_raio["50"]["ultimas24h"],
        "quantidadeFocos48hAte50Km": por_raio["50"]["ultimas48h"],
        "quantidadeFocos7dAte50Km": None,
        "lookbackHours": 48,
        "quantidadePorRaioKm": por_raio,
        "focoMaisProximo": focos[0] if focos else None,
        "observacao": "Foco de calor por satélite não confirma incêndio atingindo a propriedade.",
    }
    resultado = {
        "status": "parcial" if erros else "ok",
        "mensagem": "; ".join(erros) if erros else None,
        "consultadoEm": agora.isoformat(), "cache": False, "dados": dados,
        "atribuicao": "INPE Programa Queimadas",
    }
    cache.salvar(chave, resultado, 10 * 60)
    return resultado

