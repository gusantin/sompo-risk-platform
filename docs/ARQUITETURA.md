# Arquitetura da SOMPO Risk Platform

## Núcleo operacional

```text
DEVICE IDENTITY + HASHED CREDENTIAL
                 |
                 v
             TELEMETRY
                 |
                 v
MACHINE ------ PROPERTY PROFILE/CROP/CONTEXT
   |                    |
   |        CLIMATE + HOTSPOTS + GEOSPATIAL + HISTORY
   |                    |
   +--------------> RISK CONTEXT
                         |
          +--------------+--------------+
          v              v              v
  ENVIRONMENTAL      MACHINE       OPERATIONAL
      RISK             RISK        CONTEXT RISK
          +--------------+--------------+
                         |
              ANALYSIS + PROVENANCE
                         |
             EVENTS -> ALERTS -> SNAPSHOTS
                         |
                       API V1
```

Uma propriedade com latitude/longitude válidas percorre todo o núcleo sem depender de `regional_locations`. A telemetria e o hardware são opcionais para environmental risk; machine risk exige medições recentes e semanticamente configuradas.

## Aquisição e identidade

`POST /dados` é uma fronteira própria, diferente da autenticação do futuro frontend. O dispositivo envia `deviceId` e uma credencial no header. `devices` resolve a associação persistida:

```text
deviceId -> maquinaId -> fazendaId
```

IDs arbitrários do payload nunca substituem essa associação fora do bypass explícito de desenvolvimento/teste. Tokens são validados com comparação constante contra PBKDF2-SHA256 + salt, podem ser rotacionados e revogados, e não são devolvidos ou logados.

O endpoint aceita o envelope extensível `measurements`. Cada chave deve existir em `sensoresConfigurados`; valores estruturados devem usar exatamente a unidade do perfil. Não há conversão implícita. O envelope legado DHT11 é mantido com escopo `unknown`.

`readingId` oferece idempotência opcional. `observedAt`, `receivedAt`, `lastSeenAt`, `createdAt` e `updatedAt` são timestamps UTC internamente e ISO 8601 na API JSON.

## Semântica dos sensores

Um perfil inclui:

```text
sensorId + type + scope + target + unit + thresholds + metadata
```

`scope=ambient_local`, `machine_internal` e `machine_component` são domínios diferentes. Machine risk só usa os dois últimos e somente quando existem thresholds configurados. Assim, `temperature/celsius` não basta para concluir se o valor é temperatura do ar, cabine ou motor.

Thresholds são configurados por sensor e comparados na unidade daquele sensor. O backend não define threshold universal para temperatura, vibração, gás ou qualquer sensor futuro.

## Risk Context e proveniência

`RiskContextService` compõe propriedade, culturas, contexto histórico, fontes externas, hotspot, geoespacial, máquina e IoT. Para cada fonte, `provenance` mantém origem, instante observado/consultado, cache, staleness, disponibilidade e participação no score.

`dataCoverage` explicita cobertura de clima, satélite/hotspot, geoespacial, histórico, propriedade e IoT. Dado ausente permanece ausente.

Confiança significa qualidade/cobertura do conjunto de entradas. Não representa probabilidade ou certeza de sinistro.

## Domínios de risco

### Environmental risk

Motor determinístico existente para incêndio, geada, inundação, enxurrada, movimento de massa e terreno operacional. Os scores e thresholds ambientais são heurísticas acadêmicas documentadas, não probabilidades. IoT interno da máquina não entra automaticamente nesse score.

### Machine risk

Avalia somente medições recentes, finitas e vinculadas à máquina correta. Usa thresholds do perfil e tendência quando há amostras suficientes. Sem perfil/threshold/leitura válida retorna `insufficient_data`, score `null` e level `unknown`.

### Operational context risk

Matriz categórica auditável, sem média ou score decimal combinado. Exemplos:

```text
environmental critical + machine high               -> operational critical
environmental high + machine high                -> operational high
machine critical                                 -> operational high
```

Proximidade de hotspot só é afirmada se a localização da máquina for recente. Sem GPS atual, `nearestHotspotDistanceKm` não é usado como evidência de proximidade atual.

### Regional risk

Camada independente baseada em pontos representativos e snapshots persistidos. Não altera property risk, machine risk ou operational context risk.

## Eventos e alertas

Evento significa “algo aconteceu”; alerta significa “a condição exige atenção”. São documentos diferentes.

`domain_events` registra transições de environmental, machine e operational risk. Repetir o mesmo cálculo sem mudança de nível/delta relevante não gera uma nova transição.

`alerts` contém `alertId`, type, severity, status, fazenda/máquina, riskType, fatores, evidências, `sourceAnalysisId`, timestamps e chave de dedupe. A chave por condição impede uma alert storm enquanto o alerta permanece `open`/`acknowledged`; reabertura após `resolved` respeita cooldown configurável.

O ciclo permitido é:

```text
open -> acknowledged -> resolved
open -----------------> resolved
```

Não há texto de IA nem notificações externas.

## Snapshots e consultas

`analises_risco` continua sendo o histórico. Duas coleções pequenas evitam reconstruir o estado atual em cada renderização:

- `property_risk_current`: risco ambiental, explicações, cobertura, source health, tendência e análise fonte;
- `machine_state_current`: last seen, device health, últimas medições, machine risk, operational risk, localização e contexto ambiental.

`GET /fazendas/<id>/status` usa uma consulta de máquinas, uma de snapshots e uma lista limitada de alertas. `GET /.../maquinas/<id>/status` usa documentos diretos e não chama APIs externas.

`GET /dashboard` lê propriedades, `property_risk_current`, máquinas marcadas com `attention=true` e alertas ativos em consultas limitadas. Isso evita que o frontend faça uma requisição de status por fazenda.

No cálculo da fazenda, a telemetria é consultada uma vez por propriedade (limitada) e agrupada por máquina, evitando N+1. Consultas temporais utilizam Firestore StructuredQuery e índices compostos.

## Segurança HTTP

Fronteiras:

- públicas: `/`, `/health`, `/ready`;
- aplicação autenticada: propriedades, máquinas, riscos, histórico, eventos, alertas, status e regional;
- dispositivo autenticado: `POST /dados`;
- desenvolvimento: bypass/test route apenas por configuração explícita e nunca em `production`.

`ApplicationAuthService` é um provider simples de API key, isolado do domínio. Firebase Auth, JWT, sessão ou gateway podem substituí-lo sem mudar cada serviço.

Todo request recebe `X-Request-ID`. Logs técnicos estruturados registram requestId, endpoint, método, status, duração e IDs de rota; não registram payloads ou segredos. `audit_log` é uma trilha separada para mutações relevantes, não para cada leitura IoT.

Rate limits de ingestão/cálculo são configuráveis e modulares. A implementação atual é por processo e não oferece limite global multiprocesso.

## Persistência Firestore REST

O projeto não usa `firebase_admin`/gRPC. Coleções:

- `fazendas`
- `maquinas`
- `devices`
- `leituras_sensores`
- `analises_risco`
- `domain_events`
- `alerts`
- `property_risk_current`
- `machine_state_current`
- `audit_log`
- `regional_locations`
- `regional_risk_snapshots`
- `regional_risk_current`

`firestore.indexes.json` declara índices para telemetria por máquina/fazenda, análises, máquinas, devices, events, alerts, machine snapshots e regional. O deploy é sempre manual.

## Resiliência

Integrações externas rodam em paralelo com timeouts individuais e orçamento global. Uma fonte indisponível não apaga as demais. Falha ao persistir análise é informada sem apagar o risco calculado; eventos, alertas e snapshots só referenciam uma análise efetivamente persistida.

Caches e rate limits são locais ao processo.

## Regional

**Regional infrastructure ready / dataset rollout deferred.** IBGE, scripts, schemas, endpoints, snapshots e serviços permanecem no repositório, mas nenhum sync/job estadual faz parte do fluxo do núcleo ou desta etapa.

Um futuro beta regional selecionará UFs/municípios agrícolas prioritários; a seleção ainda não foi feita e não existe lista hardcoded.

## Agente contextual read-only

O endpoint `POST /agent/query` usa o `AgroRiskAgent` existente do pacote `sompo-agro-agent-v2`, com `SYSTEM_PROMPT` adaptado ao fluxo oficial atual e provider Ollama. Antes da inferência, um roteamento determinístico monta um contexto limitado pelas tools read-only de risco atual, explicações, fatores, dados ausentes, máquinas, telemetria, hotspots, tendências, eventos e alertas.

O agente não importa nem executa o `risk_engine.py`, o Firebase paralelo ou o `mock_data.py` presentes no pacote original. Os valores vêm dos snapshots e serviços do backend oficial; falhas do Ollama são explícitas e não ativam fallback mock.
