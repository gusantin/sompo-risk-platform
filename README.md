# SOMPO Risk Platform

Backend Flask para análise determinística e explicável de riscos em propriedades e máquinas agrícolas. O núcleo combina cadastro da fazenda, contexto produtivo, máquinas, telemetria IoT opcional, clima, hotspots, geoespacial e histórico.

Os resultados são índices experimentais: não são probabilidades, laudos técnicos, previsões garantidas de sinistro ou decisões atuariais.

## Fluxo principal

```text
device -> telemetry -> machine -> property -> Risk Context
       -> environmental risk + machine risk -> operational context risk
       -> history -> events -> alerts -> current snapshots -> API V1
```

O fluxo da propriedade depende de latitude/longitude válidas, não de `regional_locations`. Hardware físico também não é obrigatório: testes, seed e cenários sintéticos exercitam a mesma persistência e os mesmos serviços.

## Domínios

- **Environmental risk:** incêndio, geada, inundação, enxurrada, movimento de massa e terreno. Usa fontes externas e contexto da propriedade.
- **Machine risk:** estado interno da máquina. Só avalia sensores internos/de componente com thresholds configurados; sem dados válidos retorna `insufficient_data`.
- **Operational context risk:** cruza estados ambientais, da máquina, GPS atual e hotspot por regras categóricas explícitas. Não fabrica score decimal combinado.
- **Regional risk:** agregação independente baseada em snapshots municipais. A infraestrutura está preservada; o carregamento do dataset foi adiado.
- **Event:** registro de que uma transição relevante ocorreu.
- **Alert:** condição persistida que exige atenção (risco elevado ou hotspot recente próximo), com dedupe e ciclo `open -> acknowledged -> resolved`.

`confidence` descreve a qualidade/cobertura das informações usadas no cálculo. Não significa certeza de que um sinistro ocorrerá. Ausência de clima, hotspot, geoespacial, histórico ou IoT permanece explícita; o backend não inventa dados.

## Instalação e startup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python server.py
```

Configure `FIREBASE_KEY_PATH` para uma conta de serviço local. `firebase-key.json`, `.env`, `firmware/secrets.h` e `firmware/esp32.ino` são ignorados e não devem ser versionados.

```powershell
$env:FIREBASE_KEY_PATH = "C:\caminho\seguro\firebase-key.json"
$env:ENVIRONMENT = "development"
```

Em produção, configure ao menos uma chave de aplicação:

```powershell
$env:ENVIRONMENT = "production"
$env:APP_API_KEYS = "SUA_CHAVE_DE_API_LOCAL"
```

O painel compacto usa o `AgroRiskAgent` do pacote `sompo-agro-agent-v2` com Ollama local. O agente recebe apenas o contexto read-only montado pelos serviços oficiais; ele não importa o motor de risco nem os dados mock do pacote original.

```powershell
$env:LLM_PROVIDER = "ollama"
$env:OLLAMA_URL = "http://localhost:11434"
$env:OLLAMA_MODEL = "llama3.2:3b"
```

Se o Ollama ou o modelo configurado não estiver disponível, `POST /agent/query` retorna indisponibilidade explícita. Não existe fallback mock ou dependência de chave OpenAI.

Não há bypass implícito em produção. `ALLOW_DEV_AUTH_BYPASS=true` e `ALLOW_DEV_DEVICE_BYPASS=true` só funcionam em `development`/`test` e devem ser habilitados conscientemente. O bypass automático usado pela suíte depende de `TESTING=True` do Flask.

## Autenticação

- `GET /`, `/health` e `/ready`: públicos.
- Endpoints da aplicação: `Authorization: Bearer <APP_API_KEY>` quando o bypass de desenvolvimento não está ativo.
- `POST /dados`: `deviceId` no corpo e `X-Device-Token` (ou `Authorization: Device ...`). A identidade persistida resolve `deviceId -> maquinaId -> fazendaId`.
- `/teste-firebase`: só existe quando explicitamente habilitado e continua sujeito à autenticação da aplicação.

Tokens IoT são armazenados como PBKDF2-SHA256 com salt, podem ser rotacionados/revogados e nunca aparecem nas respostas. Logs não incluem headers de autenticação nem payloads.

## Telemetria e semântica

Cada sensor configurado contém `sensorId`, `type`, `scope`, `target`, `unit`, `thresholds` e `metadata`. Isso impede interpretar temperatura do motor como temperatura do ar. Uma faixa física opcional pode ser configurada em `metadata.validRange` sem inventar limites universais.

```json
{
  "deviceId": "device_01",
  "readingId": "reading_0001",
  "observedAt": "2026-08-25T18:00:00Z",
  "measurements": {
    "temp_motor": {"value": 82.5, "unit": "celsius"},
    "vibracao_motor": 2.7
  }
}
```

Valores numéricos simples usam a unidade do perfil. Valores estruturados devem informar exatamente a mesma unidade configurada. Celsius, Fahrenheit, Kelvin, m/s e km/h não são tratados como equivalentes; nenhuma conversão é realizada. Unidade desconhecida não é convertida.

O contrato legado `temperatura`/`umidade` permanece aceito, mas é persistido com escopo `unknown` e não entra automaticamente em machine risk ou environmental risk.

`readingId` é opcional e idempotente por dispositivo. Reenvio idêntico é deduplicado; reutilização com outro payload retorna conflito.

### Preparação do ESP32 físico

O servidor usa `HOST=0.0.0.0` e `PORT=5000` por padrão, portanto aceita conexões na rede local. Antes do upload, copie `firmware/secrets.example.h` para `firmware/secrets.h` e preencha localmente Wi-Fi, URL LAN, `deviceId` provisionado e token; nenhuma credencial deve ir para o Git. O computador precisa manter o mesmo IP (reserva DHCP recomendada) e permitir TCP/5000 no perfil de rede privada do firewall.

O DHT envia somente a identidade/idempotência exigidas pelo backend e as duas medições:

```json
{"deviceId":"esp32_real_01","readingId":"esp32_1a2b3c4d_1","temperatura":25.4,"umidade":61.2}
```

O firmware mantém uma leitura pendente em memória durante falha de rede, timeout, `429` ou erro `5xx`, reconecta ao Wi-Fi e repete o mesmo `readingId`. Reiniciar/desenergizar o ESP32 pode perder apenas essa leitura ainda não confirmada. O contrato completo, teste PowerShell e smoke Python estão em [docs/API.md](docs/API.md).

## Endpoints principais

```text
GET  /health
GET  /ready
GET  /dashboard

POST /devices
GET  /devices
GET  /devices/<deviceId>
PATCH /devices/<deviceId>
POST /devices/<deviceId>/rotate
POST /dados

POST /fazendas
GET  /fazendas
GET|PATCH /fazendas/<fazendaId>
GET  /fazendas/<fazendaId>/risco
GET  /fazendas/<fazendaId>/analises
GET  /fazendas/<fazendaId>/risco/tendencia
GET  /fazendas/<fazendaId>/status

POST|GET /fazendas/<fazendaId>/maquinas
GET|PATCH /fazendas/<fazendaId>/maquinas/<maquinaId>
GET  /fazendas/<fazendaId>/maquinas/<maquinaId>/telemetria
GET  /fazendas/<fazendaId>/maquinas/<maquinaId>/risco
GET  /fazendas/<fazendaId>/maquinas/<maquinaId>/status

GET  /eventos?fazendaId=...
GET  /alertas
GET  /fazendas/<fazendaId>/alertas
GET|PATCH /alertas/<alertId>
```

O contrato detalhado está em [docs/API.md](docs/API.md) e [openapi.yaml](openapi.yaml). `apiContractVersion = "1"` e os headers `X-API-Contract-Version` e `X-Request-ID` são retornados em toda resposta.

## Testes

Comando principal:

```powershell
python -m unittest discover -s tests -v
```

Validação de sintaxe:

```powershell
python -m compileall -q config.py server.py integracoes services scripts tests
```

Integrações públicas reais são somente leitura e opt-in:

```powershell
$env:RUN_INTEGRATION_TESTS = "1"
python -m unittest tests.test_integration_optin -v
```

Elas não são necessárias para validar o núcleo e não executam rollout regional.

O round-trip Firebase com escrita/limpeza é um opt-in separado. Ele só opera em
`development`/`test`, exige `RUN_FIREBASE_INTEGRATION_TESTS=1` e confirmação exata do
project ID em `FIREBASE_TEST_PROJECT_ACK`; remove somente o documento `test_core_*`
criado pelo próprio teste.

## Frontend MVP

O **SOMPO Rural Risk Command Center** fica em `frontend/` e concentra a apresentação em uma única tela responsiva. O Next.js acessa o Flask exclusivamente no servidor; a chave administrativa não usa prefixo `NEXT_PUBLIC_` e não é enviada ao navegador.

```powershell
cd frontend
Copy-Item .env.example .env.local
# Preencha SOMPO_BACKEND_API_KEY em .env.local quando o bypass local estiver desabilitado.
npm install
npm run dev
```

O dashboard tenta primeiro o snapshot de condições ambientais reais. Se o backend ou o snapshot estiver indisponível, a interface não preenche a tela silenciosamente: mostra `Dados reais indisponíveis` e oferece o cenário `DEMO` somente por ação explícita do usuário.

Prepare ou atualize o snapshot leve antes da apresentação. A rotina consulta um conjunto limitado de focos do INPE e três pontos municipais oficiais do IBGE, usa cache e preserva os scores do motor atual:

```powershell
python scripts/find_live_demo_cases.py --write
```

As propriedades do showcase são fictícias e aparecem como `Propriedade demonstrativa — condições ambientais reais`. Coordenadas, clima, focos, horários e fontes vêm das integrações consultadas. O endpoint de leitura é `GET /showcase/live-cases`; `LIVE_CASE_MAX_AGE_SECONDS` controla quando a interface passa a marcar o snapshot como desatualizado.

## Demo e smoke test

O seed é dry-run por padrão, usa apenas IDs `demo_` e nunca roda no startup:

```powershell
python -m scripts.seed_demo --dry-run --scenario combined_critical
```

Para gravar explicitamente em um Firebase de desenvolvimento, configure `DEMO_DEVICE_TOKEN` fora do Git e use `--write`. Propriedade, máquina, telemetria, análise/snapshots e alertas sintéticos usam IDs `demo_`, marcador `demoData` ou origem `DEMO_SEED` e ficam restritos à fazenda `demo_fazenda_01`; não são misturados às fazendas reais.

```powershell
$env:DEMO_DEVICE_TOKEN = "credencial-local-nao-versionada"
python -m scripts.seed_demo --write --scenario normal
```

Cenários disponíveis: `normal`, `machine_overheat`, `environmental_fire_high`, `combined_critical` e `stale_device`.

Smoke somente de saúde/listagem:

```powershell
python -m scripts.smoke_test_api
```

Use `SOMPO_API_KEY`/`--api-key` quando o bypass de desenvolvimento não estiver ativo.

Fluxo completo opt-in, que pode persistir uma análise:

```powershell
python -m scripts.smoke_test_api --core-flow --fazenda demo_fazenda_01 --maquina demo_trator_01
```

## Firestore

Coleções do núcleo: `fazendas`, `maquinas`, `devices`, `leituras_sensores`, `analises_risco`, `domain_events`, `alerts`, `property_risk_current`, `machine_state_current` e `audit_log`.

As consultas temporais e agregadas usam StructuredQuery com limites; os índices necessários estão em [firestore.indexes.json](firestore.indexes.json). Nenhum deploy é automático.

O rate limit V1 é modular, mas mantido em memória por processo. Em uma implantação multiprocesso, os limites não são globais; um store compartilhado poderá substituir essa implementação.

## Regional

**Regional infrastructure ready / dataset rollout deferred.** Integração IBGE, schemas, serviços, scripts, endpoints e snapshots foram preservados. Esta etapa não sincroniza municípios, não corrige coordenadas, não popula coleções regionais e não executa jobs estaduais.

Property risk é independente do rollout regional. No futuro haverá um beta com subconjunto ainda não definido de UFs/municípios agrícolas prioritários; nenhuma lista foi hardcoded agora.

## Limitações

- Pesos e limiares ambientais continuam heurísticos/experimentais e precisam de calibração antes de uso produtivo.
- O DHT11 legado não informa por si só se mede ar, cabine ou motor.
- O rate limit e o cache são locais ao processo.
- O protótipo usa API keys estáticas para a aplicação; a interface de auth foi separada para futura adoção de Firebase Auth/JWT/gateway.
- Eventos/alertas são internos; não há envio de e-mail, WhatsApp, push ou webhook.
- APIs externas podem apresentar atraso, indisponibilidade e cobertura parcial.
- O frontend é um MVP de apresentação; não inclui autenticação de usuário final, RBAC, notificações ou atualização em tempo real.
- O `AgroRiskAgent` é read-only e depende do Ollama/modelo configurados; indisponibilidade é explícita e não há mock silencioso.

## Roadmap

**DONE:** backend foundation; Firebase; property domain; machine domain; sensor semantics; telemetry; Risk Context; environmental risk; machine risk; operational risk; history; trend; hotspots; regional infrastructure.

**DONE:** frontend MVP; Command Center; integração BFF; modo demo explícito.

**CURRENT:** preparação e validação do MVP de apresentação; agente contextual read-only conectado aos contratos existentes.

**NEXT:** autenticação de usuários e evolução controlada do dashboard após o MVP.

**DEFERRED:** regional dataset rollout.

**LATER:** advanced notifications; calibrated predictive models.

## Licença e uso

Projeto acadêmico. Antes de uso produtivo, valide licenças das fontes, atribuição, segurança, calibração e governança.
