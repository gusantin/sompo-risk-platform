"""Focos de calor recentes publicados pelo Programa Queimadas do INPE."""

import csv
import io
import logging
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


def _agora():
    return datetime.now(timezone.utc)


def _baixar_dia(dia):
    nome = f"focos_diario_br_{dia:%Y%m%d}.csv"
    resposta = requests.get(f"{BASE_URL}/{nome}", timeout=TIMEOUT)
    resposta.raise_for_status()
    texto = resposta.content.decode("utf-8-sig", errors="replace")
    return csv.DictReader(io.StringIO(texto))


def _data_utc(valor):
    return datetime.strptime(valor.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


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
                        "idadeHoras": round(idade_horas, 2),
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

