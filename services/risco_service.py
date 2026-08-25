"""Motor determinístico de riscos com pesos experimentais.

Os limiares e pesos abaixo são heurísticas para um protótipo acadêmico. Eles não
constituem previsão de desastre, laudo técnico ou recomendação operacional.
"""


def _limitar(valor, minimo=0, maximo=100):
    return max(minimo, min(maximo, valor))


def _crescente(valor, inicio, fim):
    return _limitar((valor - inicio) * 100 / (fim - inicio))


def _decrescente(valor, inicio, fim):
    return 100 - _crescente(valor, inicio, fim)


def _nivel(score):
    if score >= 80:
        return "critico"
    if score >= 60:
        return "alto"
    if score >= 30:
        return "moderado"
    return "baixo"


def _montar(componentes, minimo_componentes=1):
    validos = [(nome, valor, peso, descricao) for nome, valor, peso, descricao in componentes if valor is not None]
    if len(validos) < minimo_componentes:
        return {"score": None, "nivel": "dados_insuficientes", "confianca": "insuficiente", "fatores": []}
    peso_disponivel = sum(item[2] for item in validos)
    peso_total = sum(item[2] for item in componentes)
    score = round(sum(valor * peso for _, valor, peso, _ in validos) / peso_disponivel)
    cobertura = peso_disponivel / peso_total
    confianca = "alta" if cobertura >= 0.8 else "media" if cobertura >= 0.5 else "baixa"
    fatores = [{"fator": nome, "contribuicao": round(valor), "descricao": descricao} for nome, valor, _, descricao in validos]
    return {
        "score": score, "nivel": _nivel(score), "confianca": confianca,
        "coberturaDadosPct": round(cobertura * 100), "fatores": fatores,
    }


def _elevar_confianca(risco, motivo):
    ordem = ("insuficiente", "baixa", "media", "alta")
    atual = risco.get("confianca", "insuficiente")
    if atual in ordem and risco.get("score") is not None:
        risco["confianca"] = ordem[min(ordem.index(atual) + 1, len(ordem) - 1)]
        risco.setdefault("fontesConfianca", []).append(motivo)


def _risco_foco(queimadas):
    if queimadas.get("status") not in ("ok", "parcial"):
        return None
    dados = queimadas.get("dados", {})
    foco = dados.get("focoMaisProximo")
    if not foco:
        return 0
    distancia = foco.get("distanciaKm")
    quantidade = dados.get("quantidadeFocos24hAte50Km")
    por_distancia = _decrescente(distancia, 0, 50) if distancia is not None else 0
    por_quantidade = _crescente(quantidade, 0, 5) if quantidade is not None else 0
    return max(por_distancia, por_quantidade)


def _divergencias(clima, inmet):
    dados_inmet = inmet.get("dados", {})
    if inmet.get("status") != "ok" or not dados_inmet.get("observacaoRecente"):
        return []
    comparacoes = (
        ("temperatura", clima.get("temperaturaAtualC"), dados_inmet.get("temperaturaObservadaC"), 5, "C"),
        ("umidade_relativa", clima.get("umidadeRelativaAtualPct"), dados_inmet.get("umidadeObservadaPct"), 20, "%"),
    )
    resultado = []
    for variavel, modelo, observado, limite, unidade in comparacoes:
        if modelo is not None and observado is not None and abs(modelo - observado) >= limite:
            resultado.append({
                "variavel": variavel, "openMeteo": modelo, "inmet": observado,
                "diferencaAbsoluta": round(abs(modelo - observado), 2), "unidade": unidade,
            })
    return resultado


def _sgb(sgb, processo):
    item = sgb.get("dados", {}).get(processo, {})
    classe = item.get("classe")
    return {"baixa": 15, "media": 50, "alta": 80, "muito_alta": 100}.get(classe)


def calcular_riscos(fontes):
    clima = fontes.get("clima", {}).get("dados", {})
    hidro = fontes.get("hidrologia", {}).get("dados", {})
    sgb = fontes.get("sgb", {})
    terreno = fontes.get("terreno", {}).get("dados", {})
    queimadas = fontes.get("queimadas", {})
    inmet = fontes.get("inmet", {})

    temperatura = clima.get("temperaturaAtualC")
    umidade = clima.get("umidadeRelativaAtualPct")
    rajada = clima.get("rajadaMax72hKmh")
    chuva72 = clima.get("chuvaAcumulada72hMm")
    solo = clima.get("umidadeSoloMin72hM3M3")
    componentes_climaticos_incendio = [
        ("temperatura_alta", _crescente(temperatura, 25, 40) if temperatura is not None else None, 0.20, "Temperatura atual elevada favorece ressecamento."),
        ("umidade_relativa_baixa", _decrescente(umidade, 20, 70) if umidade is not None else None, 0.20, "Umidade relativa baixa eleva o potencial climático."),
        ("rajadas", _crescente(rajada, 15, 70) if rajada is not None else None, 0.15, "Rajadas podem favorecer propagação."),
        ("ausencia_chuva", _decrescente(chuva72, 0, 40) if chuva72 is not None else None, 0.125, "Pouca chuva prevista mantém condições secas."),
        ("umidade_solo_baixa", _decrescente(solo, 0.08, 0.35) if solo is not None else None, 0.125, "Baixa umidade superficial do solo indica secura."),
    ]
    potencial_climatico = _montar(componentes_climaticos_incendio, 2)
    risco_foco = _risco_foco(queimadas)
    incendio = _montar(componentes_climaticos_incendio + [
        ("foco_calor_proximo", risco_foco, 0.20, "Foco de calor observado pelo INPE em até 50 km; não confirma incêndio na propriedade."),
    ], 2)
    incendio["potencialClimatico"] = {
        "score": potencial_climatico["score"], "nivel": potencial_climatico["nivel"],
    }
    incendio["focoCalorObservadoProximo"] = (
        None if risco_foco is None else queimadas.get("dados", {}).get("focoMaisProximo") is not None
    )

    minima = clima.get("temperaturaMinima72hC")
    geada = _montar([
        ("temperatura_minima", _decrescente(minima, -2, 6) if minima is not None else None, 0.85, "Temperatura mínima prevista nas próximas 72 h."),
        ("temperatura_atual", _decrescente(temperatura, 0, 12) if temperatura is not None else None, 0.15, "Temperatura atual como indicador complementar."),
    ])

    vazao_atual = hidro.get("vazaoAtualEstimadaM3s")
    vazao_max = hidro.get("vazaoMaximaPrevista7dM3s")
    tendencia = hidro.get("tendenciaAumentoPct")
    aumento_relativo = None
    if vazao_atual not in (None, 0) and vazao_max is not None:
        aumento_relativo = (vazao_max - vazao_atual) / abs(vazao_atual) * 100
    inundacao = _montar([
        ("chuva_72h", _crescente(chuva72, 20, 120) if chuva72 is not None else None, 0.30, "Chuva acumulada prevista em 72 h."),
        ("aumento_vazao", _crescente(aumento_relativo, 5, 100) if aumento_relativo is not None else None, 0.25, "Aumento relativo da vazão regional prevista."),
        ("tendencia_vazao", _crescente(tendencia, 0, 50) if tendencia is not None else None, 0.10, "Tendência percentual da vazão regional."),
        ("suscetibilidade_sgb", _sgb(sgb, "inundacao"), 0.35, "Classe de suscetibilidade no ponto segundo o SGB."),
    ], 2)
    enxurrada = _montar([
        ("chuva_72h", _crescente(chuva72, 20, 100) if chuva72 is not None else None, 0.55, "Chuva acumulada prevista em 72 h."),
        ("suscetibilidade_sgb", _sgb(sgb, "enxurrada"), 0.45, "Classe de suscetibilidade no ponto segundo o SGB."),
    ])
    movimento = _montar([
        ("chuva_72h", _crescente(chuva72, 30, 150) if chuva72 is not None else None, 0.45, "Chuva acumulada prevista em 72 h."),
        ("suscetibilidade_sgb", _sgb(sgb, "movimentoMassa"), 0.55, "Classe de suscetibilidade no ponto segundo o SGB."),
    ])
    declividade = terreno.get("declividadePct")
    variacao = terreno.get("variacaoAltitudeMetros")
    rugosidade = terreno.get("rugosidade")
    terreno_operacional = _montar([
        ("declividade_aproximada", _crescente(declividade, 5, 35) if declividade is not None else None, 0.50, "Declividade aproximada calculada na grade de elevação."),
        ("variacao_altitude", _crescente(variacao, 10, 100) if variacao is not None else None, 0.30, "Variação de altitude no entorno amostrado."),
        ("rugosidade", _crescente(rugosidade, 3, 35) if rugosidade is not None else None, 0.20, "Desvio-padrão das nove elevações como rugosidade simples."),
    ], 2)
    terreno_operacional["interpretacao"] = "Potencial de risco operacional associado ao relevo; não identifica barrancos ou obstáculos pontuais."

    divergencias = _divergencias(clima, inmet)
    inmet_recente = inmet.get("status") == "ok" and inmet.get("dados", {}).get("observacaoRecente")
    if inmet_recente and not divergencias:
        for risco in (incendio, geada, inundacao, enxurrada, movimento):
            _elevar_confianca(risco, "Observação recente do INMET sem divergência relevante nas variáveis comparáveis.")
    if queimadas.get("status") in ("ok", "parcial"):
        _elevar_confianca(incendio, "Consulta recente ao Programa Queimadas do INPE.")
    riscos = {
        "incendio": incendio, "geada": geada, "inundacao": inundacao,
        "enxurrada": enxurrada, "movimentoMassa": movimento,
        "terrenoOperacional": terreno_operacional,
    }
    disponiveis = [item for item in riscos.values() if item["score"] is not None]
    if disponiveis:
        pior = max(disponiveis, key=lambda item: item["score"])
        riscos["geral"] = {"score": pior["score"], "nivel": pior["nivel"], "criterio": "maior_score_disponivel"}
    else:
        riscos["geral"] = {"score": None, "nivel": "dados_insuficientes", "criterio": "sem_scores_disponiveis"}
    riscos["aviso"] = "Scores experimentais; não representam previsão de ocorrência nem laudo técnico."
    riscos["divergenciasMeteorologicas"] = divergencias
    return riscos
