# Apresentação NEXT — preparação e recuperação

Este é um protótipo de apresentação, não uma declaração de prontidão produtiva. Os motores e recomendações são determinísticos; o Copilot somente interpreta dados. Após a etapa anterior, o usuário informou a comprovação da entrega real pela aplicação e da deduplicação persistida. A etapa atual aprimora dados e formatação sem repetir envios. A nova [carteira com identidades fictícias e evidência real](PRESENTATION_PORTFOLIO.md) tem captura própria e startup `-Portfolio`; os registros de validação das etapas anteriores abaixo são históricos.

## Preparação

Dependências existentes: Python com `.venv` e `requirements.txt`, Node/Next em `frontend/node_modules`, Chrome para os checks de navegador. O helper não instala pacotes, modelos, credenciais ou dados Firebase.

Na raiz, verifique sem iniciar processos:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_demo.ps1 -Offline -BackendPort 5100 -CheckOnly
```

Inicie a apresentação offline completa:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_demo.ps1 -Offline -BackendPort 5100 -Scenario combined_critical
```

O helper usa 3000 se estiver livre, depois 3100/3101/3102. Informe `-FrontendPort 3100` para preferência explícita. A porta backend ocupada causa erro; escolha outra com `-BackendPort`. Nenhum processo alheio é encerrado. Os URLs e PIDs efetivos são impressos. Abra o URL com `/?mode=demo`.

Flask e Next são iniciados em loopback, em janelas ocultas. Uma chave de aplicação efêmera é compartilhada apenas nos ambientes dos processos filhos. Não é impressa nem gravada. Bypasses de aplicação/dispositivo ficam desabilitados; Telegram fica desabilitado no modo offline. No modo real, o helper preserva a configuração do servidor/.env, mas não inicia o worker. Logs ficam em `frontend/artifacts/`, ignorado pelo Git. O ambiente da sessão chamadora é restaurado ao terminar o helper.

Para snapshots reais, configure `FIREBASE_KEY_PATH` localmente e execute sem `-Offline`. O helper não prepara análises nem popula Firebase. Use `-EnableAlertActions` apenas quando desejar explicitamente alterar alertas reais pelo ambiente local; o padrão é consulta. Essa opção é ignorada no modo offline. Produção continua bloqueando ações do navegador.

## Cinco cenários, sem Firebase

O modo offline reutiliza `scripts/seed_demo.py`, `scenario_generator`, motores de máquina/operação, regras de alerta e recomendações existentes. O arquivo exportado contém respostas dos contratos oficiais e é adaptado pelo mesmo BFF, exclusivamente no modo DEMO explícito. Não cria uma segunda API ou um novo motor.

```powershell
.venv/Scripts/python.exe -m scripts.seed_demo --export frontend/artifacts/demo-scenario.json --scenario normal
.venv/Scripts/python.exe -m scripts.seed_demo --export frontend/artifacts/demo-scenario.json --scenario machine_overheat
.venv/Scripts/python.exe -m scripts.seed_demo --export frontend/artifacts/demo-scenario.json --scenario environmental_fire_high
.venv/Scripts/python.exe -m scripts.seed_demo --export frontend/artifacts/demo-scenario.json --scenario combined_critical
.venv/Scripts/python.exe -m scripts.seed_demo --export frontend/artifacts/demo-scenario.json --scenario stale_device
```

Execute uma linha de cada vez e recarregue `/?mode=demo`. O helper configura `SOMPO_DEMO_SCENARIO_PATH` com o caminho absoluto. Inicialização manual do Next pode usar essa mesma variável. Sem ela, o DEMO ilustrativo anterior permanece disponível. Exportações só podem ser gravadas dentro de `frontend/artifacts`, e arquivos existentes sem marcador DEMO não são sobrescritos.

`normal` não deve gerar alertas; `machine_overheat` sinaliza os sensores internos; `environmental_fire_high` usa nível ambiental alto; `combined_critical` cruza riscos críticos; `stale_device` não apresenta telemetria antiga como atual. Os horários do cenário são os da exportação, explicitamente sintética. O Copilot não consulta a carteira real a partir dessa tela offline. Alertas exportados são somente leitura e não entram na fila real. A validação intencional isolada descrita abaixo tem comando próprio e exige Firebase/Telegram reais.

O seed Firebase original continua opt-in: `--dry-run` por padrão; `--write` exige `development/test`, credencial Firebase e `DEMO_DEVICE_TOKEN`. Nunca foi executado com escrita nesta etapa. Leituras de execuções distintas recebem IDs distintos para evitar conflito de idempotência por timestamp. Regras de cooldown e histórico do backend continuam vigentes; use a exportação offline para reset determinístico da apresentação.

## Smoke da apresentação

Com os processos acima iniciados e `combined_critical` exportado:

```powershell
.venv/Scripts/python.exe -m scripts.presentation_smoke --offline --backend http://127.0.0.1:5100 --frontend http://127.0.0.1:3100
```

Use as portas efetivamente impressas pelo helper. Saída esperada: `PASS` para motores/alertas/recomendações da fixture, contexto read-only, possibilidade de enqueue isolado, saúde, frontend, dados e ambos os painéis em 390/1366/1440/1920px. Um `WARNING` lembra que Firebase, APIs externas e Ollama reais dependem da configuração local. Falhas essenciais terminam com código diferente de zero.

O smoke não chama endpoints de cálculo persistente ou ingestão. O teste de outbox substitui todas as fronteiras de persistência por mocks antes de testar enqueue; o canal não é chamado e DEMO é excluído. Os testes de navegador usam o cenário exportado real através do BFF, sem interceptar seus dados.

Para executar somente o trecho visual:

```powershell
cd frontend
$env:FRONTEND_URL='http://127.0.0.1:3100'
node scripts/presentation-check.mjs
```

## Recuperação rápida

| Falha | Recuperação segura |
|---|---|
| Backend parou | Confira `backend-error.log`. Reinicie o helper após encerrar somente os PIDs que ele iniciou, ou inicie manualmente o backend mantendo a configuração da chave e URL do BFF. |
| Frontend parou | Confira `frontend-error.log`; verifique porta e dependências. Reinicie o helper com portas livres. |
| Outro serviço ocupa a porta | Escolha outra porta. Nunca mate processos desconhecidos. |
| Firebase ausente/indisponível | Use `-Offline`. O modo real informa indisponibilidade e não preenche riscos com dados sintéticos. |
| Ollama indisponível | Continue pelos fatores/recomendações determinísticos. Instale/configure o modelo separadamente se necessário; esta etapa não baixa modelos. |
| API ambiental indisponível | Consulte horário/cobertura do snapshot; não afirme atualidade. Use o DEMO explícito para a apresentação offline. |
| ESP32 offline/telemetria antiga | Confira alimentação, rede e vínculo. Conectividade e idade da medição são estados distintos; não trate leitura antiga como atual. |
| Serviço de notificação indisponível | Alertas e ações não dependem da entrega. Ausência de registro não prova recebimento. Consulte retryable e nextAttemptAt; execute o worker explicitamente após corrigir a configuração. Não reenvie unknown/attempting sem verificar a entrega no canal. |
| Cenário incorreto | Reexporte o cenário desejado e recarregue o URL DEMO; não altere dados Firebase para resetar a apresentação. |

Para encerrar processos próprios, anote os PIDs impressos. Use `Stop-Process -Id <PID-backend>` e, para a árvore do Next, `taskkill /PID <PID-frontend> /T /F`, somente após verificar que são os mesmos processos iniciados pelo helper.

## Auditoria e limites desta etapa

- Recomendações de status da máquina e Copilot agora usam a mesma função versionada, inclusive sobreaquecimento e conectividade. Listagem de alertas por fazenda também inclui recomendações.
- Freshness usa o timestamp da medição, independentemente da última comunicação; o Copilot recalcula saúde na leitura e não expõe temperatura antiga como atual. GPS vencido não retorna distância atual ao hotspot.
- Alertas usam revisão Firestore como precondição de atualização, evitando sobrescrita concorrente. Conflitos falham sem atualização otimista do navegador; o operador deve atualizar os dados.
- SOMPO Live acompanha o status confirmado; resolução atualiza contagens locais disponíveis, mantendo o histórico. A fila deduplica IDs e não inclui alertas resolvidos.
- Contagem ausente permanece `null`; coordenadas ausentes não viram zero. O BFF passou a aguardar todas as leituras iniciadas, removendo um corte oculto de 12 máquinas; permanece o limite documentado de quatro por propriedade.
- O indicador ambiental geral é separado das listas explicitamente rotuladas como risco de incêndio. A ausência de avaliação de incêndio não recebe o score ambiental geral como substituto. Focos regionais são consultados apenas para estados presentes no recorte carregado. São domínios diferentes, não um score combinado inventado.
- A seleção de máquina usa propriedade + máquina também após atualização, inclusive quando duas fazendas reutilizam o mesmo ID local de máquina.
- `frontend/AGENTS.md` e `frontend/CLAUDE.md` foram confirmados como arquivos gerados pelo Next instalado (`generate-agent-files.js`). São orientações úteis do framework, não credenciais. Foram lidos e mantidos sem alteração nesta etapa. Não existia uma convenção raiz que exigisse sua remoção.
- Capturas, exports, logs e builds permanecem ignorados. Nenhuma limpeza de dados do usuário foi realizada. A auditoria local não encontrou valores de segredo configurados para comparar; verificou também os placeholders e a separação server-only/BFF. Não equivale a auditoria completa de produção.
- Firebase configurado estava ausente e Ollama não respondeu em `/api/tags`. Logo, não houve round-trip Firestore ou resposta de modelo real. Contexto, regras, contratos e falhas foram validados com fixtures; nenhuma entrega Telegram ocorreu.

## Validação reproduzível

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -q
.venv/Scripts/python.exe -m compileall -q config.py server.py integracoes services scripts tests
cd frontend
npm run typecheck
npm run lint
node scripts/operations-check.mjs
node scripts/action-gate-check.mjs
npm run build
```

Após iniciar o build de produção em uma porta isolada, **sem** `SOMPO_DEMO_SCENARIO_PATH` para os testes herdados:

```powershell
$env:FRONTEND_URL='http://127.0.0.1:3100'
npm run product-check
npm run visual-check
```

Rode esses dois checks em sequência: product-check usa um stub em 5000 e recusa substituir um backend existente. action-gate-check usa 3001/5001, inicia e encerra seu próprio processo de desenvolvimento. O smoke offline é executado separadamente com a exportação configurada. Não execute dois processos Next de desenvolvimento no mesmo diretório simultaneamente.

Resultado desta execução: 146 testes backend, três integrações opt-in puladas; compileall, TypeScript, ESLint, build, operations-check, action-gate-check, product-check, visual-check e smoke offline passaram. Browser em 390/1366/1440/1920px, sem overflow ou erros de hidratação. O gate de produção também foi validado com a flag de ações habilitada: permaneceu bloqueado. Nenhum commit/push foi feito.

## Arquivos alterados nesta continuação

```text
README.md
docs/API.md
docs/ARQUITETURA.md
docs/PRODUCTIZATION.md
docs/PRODUCT_EXPERIENCE.md
docs/PRESENTATION_RUNBOOK.md
frontend/.env.example
frontend/src/app/page.tsx
frontend/src/components/command-center.tsx
frontend/src/components/operations-panel.tsx
frontend/src/components/risk-assistant.tsx
frontend/src/components/risk-map.tsx
frontend/src/lib/backend.ts
frontend/src/lib/operations.ts
frontend/src/lib/types.ts
frontend/scripts/operations-check.mjs
frontend/scripts/product-check.mjs
frontend/scripts/presentation-check.mjs
scripts/scenario_generator.py
scripts/seed_demo.py
scripts/start_demo.ps1
scripts/presentation_smoke.py
server.py
services/alert_service.py
services/firestore_service.py
services/recommendation_service.py
services/sompo_agro_agent/tools.py
tests/test_presentation_hardening.py
tests/test_risk_copilot_operations.py
```

As demais alterações não commitadas são anteriores e foram preservadas. O teste existente de Copilot recebeu um `lastSeenAt` de fixture coerente com a classificação stale que já verificava; suas asserções foram mantidas.

## Integração Telegram e freeze final

Configuração local necessária: `FIREBASE_KEY_PATH` aponta para a chave de serviço fora dos arquivos versionados; `.env` contém `TELEGRAM_NOTIFICATIONS_ENABLED=true`, `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`. Não copie valores para documentação, frontend ou logs. Ollama requer o serviço local e o modelo já configurado em `OLLAMA_MODEL`; o helper não instala modelos.

Comandos a partir da raiz, após configurar o ambiente:

```powershell
# Offline: nenhum envio ou seed real.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_demo.ps1 -Offline -BackendPort 5100 -Scenario combined_critical

# Integrações reais, em terminais próprios; não iniciar outro helper nas mesmas portas.
ollama serve
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_demo.ps1 -BackendPort 5100 -EnableAlertActions

# Ingestão explícita dos avisos oficiais com vínculo de propriedade demonstrável.
.venv/Scripts/python.exe -m scripts.process_weather_alerts

# Worker real: pode enviar alertas elegíveis da carteira. Não usar como teste isolado.
.venv/Scripts/python.exe -m scripts.dispatch_notifications

# Teste isolado: um alerta de incêndio do cenário suportado, sem clientes reais.
# Reutilize o mesmo run-id para dedupe; o script executa uma segunda passagem.
.venv/Scripts/python.exe -m scripts.telegram_demo --run-id freeze_v1 --action high --deliver
.venv/Scripts/python.exe -m scripts.telegram_demo --run-id freeze_v1 --action critical --deliver
.venv/Scripts/python.exe -m scripts.telegram_demo --run-id freeze_v1 --action acknowledge --deliver
.venv/Scripts/python.exe -m scripts.telegram_demo --run-id freeze_v1 --action resolve --deliver

# Smoke sem mensagens reais; inclui presentation-check em quatro larguras.
.venv/Scripts/python.exe -u -m scripts.presentation_smoke --offline --backend http://127.0.0.1:5100 --frontend http://127.0.0.1:3100
```

O script isolado usa AlertService, Firestore, outbox e o mesmo dispatcher/adapter do worker. Filtra os IDs da própria execução, sem drenar a carteira. Somente `--deliver` chama o canal. Ele registra IDs e resultado seguro, nunca credenciais. A propriedade `demo_telegram_<run-id>` fica marcada DEMO e preservada para auditoria; não substitui o cenário exportado nem aparece como cliente real. O roteiro de ações desse teste é CLI/API; a tela offline permanece somente leitura. Não repetir a criação após resolver para simular nova ocorrência: use outro run-id quando uma nova demonstração for intencional.

No teste desta sessão, o comando high/--deliver retornou `configured=false`, `firebaseCredentialPresent=false`, `delivered=false`, antes de qualquer gravação. Nenhum alertId/notificationId/message ID real foi gerado. Escalada, resolução, dedupe e entrega pelo adapter foram comprovados com persistência/transporte simulados, não com Telegram real.

Limites operacionais: a integração atual INMET retorna Tempestade; apenas localização oficial com município/UF exato permite vínculo automático. Áreas regionais sem esse vínculo ficam no dashboard, inclusive quando severas. Perigo Potencial exige também snapshot ambiental elevado e recente. A política completa, estados, backoff, reconciliação e limite de consultas estão em [PRODUCTIZATION.md](PRODUCTIZATION.md). Credenciais e confirmação do round-trip real continuam pendentes; nenhum commit/push foi realizado.

Validação de freeze: backend 160 testes, 3 skips de integração opt-in; compileall; frontend typecheck/lint/build; operations-check; action-gate-check; product-check; visual-check; smoke offline com presentation-check em 390/1366/1440/1920px. O teste de produto verifica a indicação de entrega e as ações nas perspectivas SOMPO/Cliente. O teste integrado isolado percorre emissão, persistência, outbox, adapter, acknowledgement e resolução; somente as fronteiras externas são simuladas. São 13 testes focados adicionais de política/entrega e um teste adicional de leitura de notificações pelo Copilot.

Segurança: 130 arquivos candidatos ao Git, bundle estático e logs foram examinados; nenhuma chave privada ou referência de credencial de servidor no bundle foi encontrada. Zero valores secretos reais estavam disponíveis para comparação. Testes usam credenciais fictícias para verificar a redação; `.env`, a chave Firebase e artefatos de teste continuam ignorados. Horários de tentativa/entrega são ordenados e atualizações de outbox usam revisão Firestore quando disponível. `git diff --check` passou. Os servidores temporários de validação foram encerrados; nenhum processo pré-existente foi interrompido.
