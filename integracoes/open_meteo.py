"""Integrações com Forecast, Flood e Elevation da Open-Meteo."""

import logging
from math import atan, cos, degrees, radians, sqrt
from statistics import pstdev
from datetime import datetime, timezone

import requests

from integracoes.cache import cache, chave_coordenada


LOGGER = logging.getLogger(__name__)
TIMEOUT = 12
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
ESPACAMENTO_TERRENO_METROS = 200


def _agora():
    return datetime.now(timezone.utc).isoformat()


def _numeros(valores):
    return [valor for valor in (valores or []) if isinstance(valor, (int, float))]


def _resumo_erro(nome, erro):
    LOGGER.warning("Falha ao consultar %s: %s", nome, erro)
    return {
        "status": "erro_api",
        "mensagem": str(erro),
        "consultadoEm": _agora(),
        "dados": {},
    }


def _get_json(url, parametros):
    resposta = requests.get(url, params=parametros, timeout=TIMEOUT)
    resposta.raise_for_status()
    dados = resposta.json()
    if dados.get("error"):
        raise RuntimeError(dados.get("reason", "Erro informado pela API"))
    return dados


def consultar_clima(latitude, longitude):
    chave = chave_coordenada("clima", latitude, longitude)
    armazenado = cache.obter(chave)
    if armazenado:
        armazenado["cache"] = True
        return armazenado

    try:
        bruto = _get_json(FORECAST_URL, {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "auto",
            "forecast_days": 4,
            "current": ",".join([
                "temperature_2m", "relative_humidity_2m", "precipitation",
                "wind_speed_10m", "wind_gusts_10m", "soil_temperature_0cm",
                "soil_moisture_0_to_1cm",
            ]),
            "hourly": ",".join([
                "temperature_2m", "precipitation", "precipitation_probability",
                "wind_speed_10m", "wind_gusts_10m", "soil_moisture_0_to_1cm",
            ]),
        })
        atual = bruto.get("current", {})
        horario = bruto.get("hourly", {})

        horarios = horario.get("time", [])
        inicio = 0
        if atual.get("time") in horarios:
            inicio = horarios.index(atual["time"])

        def janela(campo, horas):
            return _numeros(horario.get(campo, [])[inicio:inicio + horas])

        chuva_24 = janela("precipitation", 24)
        chuva_72 = janela("precipitation", 72)
        temperaturas_72 = janela("temperature_2m", 72)
        probabilidades_72 = janela("precipitation_probability", 72)
        ventos_72 = janela("wind_speed_10m", 72)
        rajadas_72 = janela("wind_gusts_10m", 72)
        solos_72 = janela("soil_moisture_0_to_1cm", 72)
        dados = {
            "temperaturaAtualC": atual.get("temperature_2m"),
            "umidadeRelativaAtualPct": atual.get("relative_humidity_2m"),
            "precipitacaoAtualMm": atual.get("precipitation"),
            "velocidadeVentoAtualKmh": atual.get("wind_speed_10m"),
            "rajadaAtualKmh": atual.get("wind_gusts_10m"),
            "temperaturaSoloAtualC": atual.get("soil_temperature_0cm"),
            "umidadeSoloAtualM3M3": atual.get("soil_moisture_0_to_1cm"),
            "temperaturaMinima72hC": min(temperaturas_72) if temperaturas_72 else None,
            "temperaturaMaxima72hC": max(temperaturas_72) if temperaturas_72 else None,
            "chuvaAcumulada24hMm": round(sum(chuva_24), 2) if chuva_24 else None,
            "chuvaAcumulada72hMm": round(sum(chuva_72), 2) if chuva_72 else None,
            "probabilidadePrecipitacaoMax72hPct": max(probabilidades_72) if probabilidades_72 else None,
            "ventoMax72hKmh": max(ventos_72) if ventos_72 else None,
            "rajadaMax72hKmh": max(rajadas_72) if rajadas_72 else None,
            "umidadeSoloMin72hM3M3": min(solos_72) if solos_72 else None,
        }
        resultado = {
            "status": "ok", "mensagem": None, "consultadoEm": _agora(),
            "cache": False, "dados": dados,
            "atribuicao": "Open-Meteo Forecast API",
        }
        cache.salvar(chave, resultado, 10 * 60)
        return resultado
    except (requests.RequestException, ValueError, RuntimeError) as erro:
        return _resumo_erro("Open-Meteo Forecast", erro)


def consultar_hidrologia(latitude, longitude):
    chave = chave_coordenada("hidrologia", latitude, longitude)
    armazenado = cache.obter(chave)
    if armazenado:
        armazenado["cache"] = True
        return armazenado

    try:
        bruto = _get_json(FLOOD_URL, {
            "latitude": latitude, "longitude": longitude,
            "daily": "river_discharge,river_discharge_max", "forecast_days": 7,
        })
        diario = bruto.get("daily", {})
        vazoes = _numeros(diario.get("river_discharge"))
        maximas = _numeros(diario.get("river_discharge_max"))
        atual = vazoes[0] if vazoes else None
        prevista = vazoes[1] if len(vazoes) > 1 else None
        tendencia = None
        tendencia_percentual = None
        if atual is not None and prevista is not None:
            tendencia = round(prevista - atual, 2)
            if atual != 0:
                tendencia_percentual = round((prevista - atual) / abs(atual) * 100, 2)
        dados = {
            "vazaoAtualEstimadaM3s": atual,
            "vazaoPrevistaM3s": prevista,
            "vazaoMaximaPrevista7dM3s": max(maximas or vazoes) if (maximas or vazoes) else None,
            "tendenciaAumentoM3s": tendencia,
            "tendenciaAumentoPct": tendencia_percentual,
            "tendencia": "aumento" if tendencia and tendencia > 0 else "queda_ou_estavel" if tendencia is not None else None,
            "observacao": "Indicador regional do maior rio em uma célula de aproximadamente 5 km.",
        }
        resultado = {
            "status": "ok", "mensagem": None, "consultadoEm": _agora(),
            "cache": False, "dados": dados,
            "atribuicao": "Open-Meteo Flood API / GloFAS",
        }
        cache.salvar(chave, resultado, 30 * 60)
        return resultado
    except (requests.RequestException, ValueError, RuntimeError) as erro:
        return _resumo_erro("Open-Meteo Flood", erro)


def calcular_metricas_terreno(elevacoes, espacamento_metros=ESPACAMENTO_TERRENO_METROS):
    """Calcula métricas aproximadas para uma grade 3x3 ordenada por linhas."""
    if len(elevacoes) != 9 or any(not isinstance(valor, (int, float)) for valor in elevacoes):
        raise ValueError("São necessárias nove elevações numéricas para calcular o terreno.")
    gradiente_leste_oeste = (elevacoes[5] - elevacoes[3]) / (2 * espacamento_metros)
    gradiente_norte_sul = (elevacoes[7] - elevacoes[1]) / (2 * espacamento_metros)
    inclinacao = sqrt(gradiente_leste_oeste ** 2 + gradiente_norte_sul ** 2)
    declividade_pct = inclinacao * 100
    return {
        "altitudeMetros": elevacoes[4],
        "altitudeMinimaMetros": min(elevacoes),
        "altitudeMaximaMetros": max(elevacoes),
        "variacaoAltitudeMetros": round(max(elevacoes) - min(elevacoes), 2),
        "declividadePct": round(declividade_pct, 2),
        "declividadeGraus": round(degrees(atan(inclinacao)), 2),
        "rugosidade": round(pstdev(elevacoes), 2),
        "espacamentoGradeMetros": espacamento_metros,
        "quantidadePontos": 9,
        "observacao": "Métricas aproximadas de uma grade 3x3; não identificam obstáculos pontuais.",
    }


def _grade_terreno(latitude, longitude, espacamento_metros=ESPACAMENTO_TERRENO_METROS):
    delta_latitude = espacamento_metros / 111_320
    fator_longitude = max(cos(radians(latitude)), 0.01)
    delta_longitude = espacamento_metros / (111_320 * fator_longitude)
    pontos = []
    for deslocamento_lat in (-delta_latitude, 0, delta_latitude):
        for deslocamento_lon in (-delta_longitude, 0, delta_longitude):
            pontos.append((latitude + deslocamento_lat, longitude + deslocamento_lon))
    return pontos


def consultar_terreno(latitude, longitude):
    chave = chave_coordenada("terreno", latitude, longitude)
    armazenado = cache.obter(chave)
    if armazenado:
        armazenado["cache"] = True
        return armazenado

    try:
        pontos = _grade_terreno(latitude, longitude)
        bruto = _get_json(ELEVATION_URL, {
            "latitude": ",".join(str(ponto[0]) for ponto in pontos),
            "longitude": ",".join(str(ponto[1]) for ponto in pontos),
        })
        elevacoes = bruto.get("elevation") or []
        dados = calcular_metricas_terreno(elevacoes)
        resultado = {
            "status": "ok", "mensagem": None, "consultadoEm": _agora(),
            "cache": False, "dados": dados,
            "atribuicao": "Open-Meteo Elevation API / Copernicus DEM GLO-90",
        }
        cache.salvar(chave, resultado, 12 * 60 * 60)
        return resultado
    except (requests.RequestException, ValueError, RuntimeError) as erro:
        return _resumo_erro("Open-Meteo Elevation", erro)
