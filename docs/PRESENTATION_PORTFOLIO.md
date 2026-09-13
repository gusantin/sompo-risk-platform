# Carteira de apresentação e procedência

O [contexto ambiental compartilhado](ENVIRONMENTAL_CONTEXT.md) descreve as novas previsões, os CAP oficiais, a cobertura atual e a separação entre condições adicionais e classificação do motor.

Cliente A / Fazenda Araguaia / Confresa–MT e Fazenda Horizonte / Sorriso–MT; Cliente B / Fazenda Pantanal Norte / Poconé–MT; Cliente C / Fazenda Campo Sul / Dourados–MS são identidades fictícias. Não representam segurados SOMPO. Os pontos são obtidos pelas malhas municipais IBGE, nunca por reposicionamento próximo de um evento. Um ponto municipal não representa os limites de uma fazenda real. Veja as rotas `/seguradora` e `/segurado`, cadastro e limites de autorização em [PRODUCT_PERSPECTIVES.md](PRODUCT_PERSPECTIVES.md).

## Modos e comandos

```powershell
# Consulta real e captura local, sem Firebase ou Telegram.
.venv/Scripts/python.exe -m scripts.capture_presentation_portfolio --write

# Última captura real; Atualizar consulta as fontes.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_demo.ps1 -Portfolio -BackendPort 5100
# URL: http://127.0.0.1:3100/?mode=portfolio quando 3000 estiver ocupada.

# Cenário sintético separado, sem fallback automático.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_demo.ps1 -Offline -BackendPort 5100 -Scenario combined_critical
```

Não execute dois helpers nas mesmas portas. `-Portfolio` desabilita envios e ações de escrita, permite consulta mesmo sem Firebase e não cria registros de clientes/alertas. O worker global não deve ser usado para testar formatação. A entrega real pela pipeline existente foi informada como comprovada pelo usuário; esta etapa não envia novas mensagens.

`data/presentation_portfolio.json` é a captura canônica local ignorada pelo Git. O frontend em produção usa um backend explicitamente configurado ou a projeção publicável em `frontend/src/data/presentation-portfolio.json`, incluída no build. `PRESENTATION_PORTFOLIO_PATH` só configura uma leitura alternativa no frontend em desenvolvimento local; não é usado em produção. Veja [exportação, configuração e validação Vercel](VERCEL_PRESENTATION.md).

## Dados reais e fallback

Fontes utilizadas: IBGE Malhas v3, Open-Meteo Forecast API, INPE Programa Queimadas, observações INMET WIS2 e INMET Avisos Meteorológicos RSS. O motor existente calcula as mesmas categorias ambientais. A carteira seleciona a categoria ambiental de maior score e compara, por severidade, avisos meteorológicos oficialmente vinculados. Avisos não recebem um score numérico inventado.

O vínculo meteorológico reutiliza a regra conservadora de município/UF exato e validade temporal do AlertService. O adapter atual retorna Tempestade. Uma descrição regional sem vínculo demonstrável não é atribuída à fazenda, e a ausência de aviso vinculado não comprova ausência de qualquer fenômeno meteorológico.

Cada propriedade mantém `provenance.identity=demo` independente de `provenance.environmental.origin/state/acquiredAt`. Estados: `real_live`, `real_cached`, `stale`, `insufficient_data`, `unavailable`; os cenários offline continuam sintéticos. A aquisição original das respostas e a hora de cálculo são campos diferentes. Depois de seis horas, a captura é desatualizada; ela nunca vira live por abrir/recarregar a página.

Falha de provider reaproveita somente resposta real anterior com origem, status e timestamp válidos. Sem essa resposta, a fonte fica indisponível. Nenhuma temperatura, quantidade, distância ou score sintético é inserido. Falha do IBGE só reutiliza coordenadas já capturadas do mesmo município; caso contrário não cria um marcador nem consulta um ponto arbitrário.

## Apresentação e mensagens

SOMPO e Cliente mostram identidade, localização, risco, fatores com contribuição positiva, medidas disponíveis, recomendações determinísticas, fontes, última atualização e procedência. A ordenação usa severidade antes de score; avisos críticos sem score continuam prioritários. Detalhes e mapa usam o mesmo objeto de propriedade. Contagens de focos distinguem total informado e amostra exibida. Contagens estaduais de propriedades com foco no entorno não são contagens de focos distintos.

Estados operacionais são lidos do Firestore quando disponível, limitados a 20 alertas recentes por propriedade. Sem consulta válida, não é inferido zero ou entrega. As identidades locais não são automaticamente gravadas como clientes/alertas. O Copilot consulta o mesmo arquivo de captura em modo somente leitura, com `mode=portfolio` e `snapshotGeneratedAt` da tela. Se a captura mudar, retorna 409 e pede atualização da carteira. As respostas determinísticas preservam os níveis oficiais, identificam clientes fictícios, cache, dados desatualizados/insuficientes/indisponíveis e não confirmam incêndio a partir de foco de calor. A visão Cliente restringe a consulta à propriedade selecionada. Esta consulta não acessa provedores, calcula risco, envia Telegram ou deduz estados operacionais ausentes; não depende do Ollama. Mesmo após uma captura live, sua leitura pelo Copilot é identificada como cache.

`notification_messages.py` formata mensagens sem enviar ou calcular risco. O dispatcher preserva elegibilidade, IDs de dedupe, claims, retries e estados. Nomes são enriquecidos por leituras opcionais da identidade persistida. Sensores internos exigem scope compatível; temperatura ambiente não vira temperatura de componente. A escalada pode exibir mudança de medição persistida. Encerramento humano usa “ALERTA ENCERRADO”, sem afirmar normalização física não comprovada. Foco de calor não vira incêndio confirmado; “possibilidade de granizo” permanece possibilidade.

Exemplos de mensagens são gerados de fixtures locais nos testes, sem Telegram. Nunca apresente seus números como uma leitura real.

### Telegram com a captura da carteira

`scripts.telegram_demo --run-id presentation_final --portfolio-client A --preview` renderiza a captura local sem Firebase ou envio. Trocar `--preview` por `--deliver` executa intencionalmente o fluxo persistido e isolado existente. Requer a configuração Telegram/Firebase do servidor em development/test. Não aceita `--action` nesse modo: usa a classificação armazenada e bloqueia níveis não elegíveis, dados sintéticos, indisponíveis ou insuficientes. Não consulta provedores nem recalcula risco.

A propriedade isolada mantém somente a referência da identidade canônica e os metadados necessários à notificação. O mesmo run-id fica vinculado à captura selecionada; repetir não duplica entrega, e trocar a captura exige outro run-id intencional. A mensagem mostra a fazenda, não o rótulo Cliente A nem o identificador técnico. Leituras do arquivo são cache ou desatualizadas. Datas são formatadas em America/Sao_Paulo, o fuso de apresentação, salvo `property.timezone` explícito; timestamps UTC originais são preservados. `tzdata` fornece a base de fusos também no Windows.

## Validação

Suite backend, compileall, typecheck, lint, build, product-check, visual-check, operations-check, action-gate-check e smoke offline. `node scripts/portfolio-check.mjs`, em frontend, verifica a captura real existente, identidade separada, ausência de fatores com contribuição zero, escopo do cliente e layouts em 390/1440/1920px. Screenshots e logs ficam em `frontend/artifacts`, ignorados.

Resultado desta etapa: 171 testes backend, com 3 skips de integração opt-in. Na captura iniciada em 12/09/2026 22:06 UTC, o motor retornou incêndio moderado (48) em Poconé, alto (65) em Confresa e baixo (16) em Dourados. Esses são resultados da captura, não condições fixas do produto. Open-Meteo, INPE e avisos INMET responderam; observações de estação INMET ficaram indisponíveis. Nenhum aviso severo foi forçado sobre Dourados. O arquivo preserva os horários individuais de aquisição das fontes.

## Files changed in this pass

27 files; previous uncommitted work preserved.

```text
.env.example
.gitignore
README.md
config.py
docs/API.md
docs/PRESENTATION_PORTFOLIO.md
docs/PRESENTATION_RUNBOOK.md
frontend/.env.example
frontend/scripts/portfolio-check.mjs
frontend/src/app/page.tsx
frontend/src/components/command-center.tsx
frontend/src/components/exposure-summary.tsx
frontend/src/components/operations-panel.tsx
frontend/src/components/risk-map.tsx
frontend/src/lib/backend.ts
frontend/src/lib/operations.ts
frontend/src/lib/provenance.ts
frontend/src/lib/types.ts
openapi.yaml
scripts/capture_presentation_portfolio.py
scripts/start_demo.ps1
services/alert_service.py
services/notification_service.py
services/notification_messages.py
services/presentation_portfolio_service.py
tests/test_notification_policy.py
tests/test_presentation_portfolio.py
```
