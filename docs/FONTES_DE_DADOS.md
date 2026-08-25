# Fontes de dados

## Categorias

As fontes possuem naturezas diferentes e não devem ser tratadas como medições equivalentes:

- **Observação:** medição realizada por estação, como INMET.
- **Previsão/modelagem:** estimativa produzida por modelos, como Open-Meteo.
- **Satélite/detecção:** evento observado remotamente, como focos do INPE.
- **Geologia/cartografia:** mapeamento territorial, como SGB.
- **Modelo hidrológico:** estimativa regional de vazão, como GloFAS.

## Open-Meteo Forecast

- **Fornecedor:** Open-Meteo, agregando modelos meteorológicos.
- **Finalidade:** condições atuais modeladas e previsão de curto prazo.
- **Dados utilizados:** temperatura, umidade relativa, precipitação, probabilidade de chuva, vento, rajadas, temperatura e umidade do solo; agregados de 24 e 72 horas.
- **Natureza:** previsão/modelagem meteorológica.
- **Limitações:** resolução e disponibilidade variam conforme modelo e região. Não é uma estação instalada na propriedade.

## Open-Meteo Flood / GloFAS

- **Fornecedor:** Open-Meteo com dados do Global Flood Awareness System.
- **Finalidade:** contexto hidrológico regional.
- **Dados utilizados:** vazão estimada, previsão, máxima prevista e tendência percentual.
- **Natureza:** modelo hidrológico.
- **Limitações:** representa o maior rio na célula regional de aproximadamente 5 km; não mede um curso d'água específico nem substitui uma estação fluviométrica.

## Open-Meteo Elevation / Copernicus DEM

- **Fornecedor:** Open-Meteo e Copernicus DEM GLO-90.
- **Finalidade:** caracterização aproximada do relevo.
- **Dados utilizados:** nove elevações em grade 3×3, altitude central, extremos, variação, declividade e rugosidade simples.
- **Natureza:** modelo digital de elevação.
- **Limitações:** resolução aproximada de 90 m. Não detecta barrancos, valas, erosões ou obstáculos pontuais; declividade e rugosidade são aproximações do entorno.

## Serviço Geológico do Brasil — SGB

- **Fornecedor:** Serviço Geológico do Brasil, via OGC API.
- **Finalidade:** consultar cartografia de suscetibilidade no ponto.
- **Dados utilizados:** classes de inundação, enxurrada, movimento de massa e corrida de massa.
- **Natureza:** geologia/cartografia temática.
- **Limitações:** cobertura não é universal. Ausência de feição significa `sem_evidencia_na_fonte`, não risco baixo. Ponto fora da extensão declarada significa `fonte_sem_cobertura`.

## INPE Programa Queimadas

- **Fornecedor:** Instituto Nacional de Pesquisas Espaciais.
- **Finalidade:** identificar focos de calor recentes no entorno.
- **Dados utilizados:** contagens em 24/48 horas para 5, 10, 25 e 50 km; foco mais próximo, distância, horário, coordenadas e satélite.
- **Natureza:** satélite/detecção remota.
- **Limitações:** um foco é uma detecção orbital e não comprova incêndio na propriedade. Cobertura de nuvens, passagem dos satélites, resolução, atraso e falsos positivos ou negativos afetam os dados.

## INMET WIS2

- **Fornecedor:** Instituto Nacional de Meteorologia.
- **Finalidade:** adicionar observação meteorológica oficial brasileira.
- **Dados utilizados:** estação, distância, horário, temperatura, umidade, precipitação e vento quando publicados.
- **Natureza:** observação em estação meteorológica.
- **Limitações:** estações podem ficar indisponíveis ou publicar apenas algumas variáveis. A estação escolhida é a mais próxima entre um conjunto limitado de candidatas com observações nas últimas 48 horas; ainda pode estar distante da propriedade.

## Uso conjunto e divergências

Open-Meteo continua sendo a fonte de previsão/modelagem; INMET adiciona observação. Uma divergência relevante é registrada na análise e não resolvida silenciosamente em favor de uma das fontes.

Todas as fontes externas podem sofrer mudanças de contrato, atraso ou indisponibilidade. O status e o horário de cada consulta devem ser considerados junto aos scores e à confiança.
