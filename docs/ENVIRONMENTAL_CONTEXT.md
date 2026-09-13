# Contexto ambiental compartilhado

`services/environmental_context.py` agrega e apresenta fatos; não calcula score, não classifica risco e não cria alertas. `environmental_context_v1` é usado pela carteira, cartões SOMPO/Cliente, detalhes, mapa, Copilot somente leitura e Telegram de apresentação. Snapshots operacionais novos também armazenam o contexto, sem migração de documentos antigos.

## Fontes auditadas

- [Open-Meteo Forecast](https://open-meteo.com/en/docs): o adapter existente solicita adicionalmente weather_code, relative_humidity_2m, rain e showers. Os campos legados consumidos pelo motor permanecem intactos. A nova agregação usa horários explícitos, iniciando na próxima hora completa depois da leitura do modelo. A leitura `current` é informação modelada, não medição de uma estação física.
- INPE Queimadas: preservados arquivos diários, observação, distância e limites de 50 km/48h existentes. [Produtos oficiais de risco e meteorologia](https://dataserver-coids.inpe.br/queimadas/queimadas/riscofogo_meteorologia/observado/risco_fogo/) exigem amostragem espacial de rasters NetCDF. O limite de integração `produtos_secundarios` retorna indisponibilidade explícita para risco observado/previsto, precipitação, temperatura, umidade e dias sem chuva. Nenhum índice INPE é inferido do score SOMPO ou da existência de focos.
- INMET WIS2: preservado o adapter de observações de estação, com disponibilidade independente.
- INMET: o RSS existente de Tempestade permanece na ingestão de alertas. O mesmo adapter agora lê também os CAP oficiais vinculados pelo RSS para **contexto**, com limite de documentos, cache, host permitido e falhas independentes. Polígono CAP ou código IBGE exato fundamentam aplicabilidade; o texto regional não é suficiente. Eventos futuros e vigentes na consulta são distintos. Cobertura parcial nunca permite afirmar ausência de avisos. CAP não altera a classificação de risco nem a política de notificação.

## Contrato e apresentação

Cada fato contém value, unit, kind, source, observedAt, forecastFor, fetchedAt, freshness e provenance, conforme o tipo. Hora de consulta não substitui hora de observação ausente. Identidade fictícia permanece separada da evidência real.

- Última leitura: temperatura, umidade, precipitação, vento, rajada e condição WMO conhecida.
- Janelas completas de 6/12/24/72h: precipitação acumulada, probabilidade máxima, chuva, pancadas, temperatura máxima/mínima, umidade mínima, vento e rajada máximos, códigos e condições WMO. Falta de qualquer hora de uma variável torna sua agregação indisponível; não há soma parcial apresentada como total.
- 72h: ausência de precipitação prevista somente quando a soma completa é zero; diferenças de limites de temperatura/umidade entre janelas, sem alegar uma nova classificação ou tendência observada. Não se calcula duração histórica de estiagem.
- Fogo: foco mais próximo e contagem retornados pelo INPE, com horário da detecção e ressalva de que não confirmam incêndio.
- CAP: fenômeno, severidade original, descrição, início, fim e evidência geográfica. Possibilidade de granizo continua possibilidade.

As previsões ficam separadas dos fatores oficiais do motor, como condição adicional. As janelas exibem suas datas originais; reabrir o snapshot não desloca a previsão para agora. Leituras em cache não são live. Após seis horas, leituras antigas são desatualizadas; previsões expiradas e observações antigas também recebem marcação própria. O Copilot seleciona deterministicamente os trechos pertinentes à pergunta, sem inventar previsões. Os textos usados nas superfícies vêm das mesmas seções canônicas.

## Captura e limitações verificadas

Captura de 12/09/2026 23:48 UTC: incêndio moderado 43 em Poconé, alto 65 em Confresa e baixo 14 em Dourados, calculados pelo motor existente. As tentativas recentes de Open-Meteo tiveram timeout/503; Poconé e Dourados conservaram as respostas reais de 23:44 UTC já contendo previsão nova. Confresa conservou a resposta real anterior de 22:06 UTC, sem os novos campos de previsão; sua previsão de 24h está indisponível. INMET WIS2 permaneceu indisponível. CAP teve cobertura parcial, com avisos aplicáveis preservados.

O risco de incêndio baixo em Dourados e um aviso CAP de tempestade Perigo são informações de domínios diferentes, exibidas separadamente. Nenhuma regra foi alterada para converter automaticamente esse contexto em alerta ou Telegram. A ausência de previsão meteorológica em Confresa e a indisponibilidade dos rasters INPE são limites de cobertura explícitos, não condições normais.

Nenhum Telegram real foi enviado nesta etapa. A captura local continua ignorada pelo Git.

## Validação e arquivos desta etapa

196 testes backend, 3 skips opt-in, nenhuma falha. Oito testes novos de contexto; 25 testes direcionados de contexto/Copilot/Telegram passaram. Compileall, typecheck, lint, build, portfolio-check, product-check, operations-check, visual-check, presentation smoke e git diff --check passaram. Carteira e Copilot verificados em 390/1440/1920px; smoke em 390/1366/1440/1920px; visual sem erros ou overflow em 1366/1920px.

```text
integracoes/open_meteo.py
integracoes/inmet.py
integracoes/inpe_queimadas.py
services/environmental_context.py
services/presentation_portfolio_service.py
services/risk_context_service.py
services/live_case_service.py
services/sompo_agro_agent/presentation.py
services/sompo_agro_agent/agent.py
services/sompo_agro_agent/tools.py
services/notification_messages.py
scripts/telegram_demo.py
server.py
frontend/src/lib/backend.ts
frontend/src/lib/types.ts
frontend/src/components/environmental-conditions.tsx
frontend/src/components/exposure-summary.tsx
frontend/src/components/command-center.tsx
frontend/src/components/risk-map.tsx
frontend/scripts/portfolio-check.mjs
tests/test_environmental_context.py
docs/ENVIRONMENTAL_CONTEXT.md
docs/PRESENTATION_PORTFOLIO.md
```
