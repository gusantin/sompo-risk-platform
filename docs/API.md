# Contrato da API V1

`apiContractVersion = "1"` foi preservado. Todas as respostas incluem `X-API-Contract-Version` e `X-Request-ID`. Timestamps JSON usam ISO 8601; documentos Firestore usam `timestampValue`.

Erros seguem o contrato:

```json
{
  "status": "erro",
  "requestId": "...",
  "error": {"code": "DEVICE_UNAUTHORIZED", "message": "Dispositivo não autorizado."}
}
```

`status`, `codigo` e `mensagem` legados continuam presentes nos erros para compatibilidade. Stack traces e mensagens internas não são enviados em produção.

## Auth

| Fronteira | Autenticação |
|---|---|
| `/`, `/health`, `/ready` | pública |
| endpoints da aplicação | `Authorization: Bearer <APP_API_KEY>` |
| `POST /dados` | `deviceId` + `X-Device-Token` |
| desenvolvimento/teste | bypass apenas por configuração explícita fora de production |

O provider de aplicação V1 usa API key, mas está isolado para futura substituição por Firebase Auth/JWT/sessão/gateway.

## Device

Provisionamento:

```http
POST /devices
```

```json
{
  "deviceId": "device_01",
  "fazendaId": "fazenda_01",
  "maquinaId": "trator_01",
  "token": "credencial-fornecida-por-canal-seguro",
  "metadata": {"model": "esp32"}
}
```

O token é write-only. A resposta e listagens removem hash, salt e parâmetros do hash. `PATCH /devices/<id>` revoga; um dispositivo revogado só volta a `active` por `/rotate`, que troca a credencial e incrementa `tokenVersion` atomicamente.

`lastSeenAt` é atualizado após ingestão autenticada. Device health derivado:

- `online`: idade menor/igual a `DEVICE_STALE_AFTER_SECONDS`;
- `stale`: acima do limite online e até `DEVICE_OFFLINE_AFTER_SECONDS`;
- `offline`: acima do limite offline;
- `unknown`: nenhuma comunicação conhecida.

## Telemetria

### ESP32 DHT (pré-flight físico)

O firmware físico deve fazer `POST` para `http://<IP-LAN-DO-SERVIDOR>:5000/dados` com os headers:

```http
Content-Type: application/json
X-Device-Token: <TOKEN_PROVISIONADO>
```

Payload exato usado pelo firmware atual:

```json
{
  "deviceId": "esp32_real_01",
  "readingId": "esp32_1a2b3c4d_1",
  "temperatura": 25.4,
  "umidade": 61.2
}
```

`deviceId`, `temperatura` e `umidade` são obrigatórios. `readingId` é fortemente recomendado e o firmware sempre o envia para que uma reconexão possa repetir a mesma leitura sem duplicá-la. Temperatura e umidade são números JSON (não texto e não `null`); temperatura aceita a faixa configurada em `TEMPERATURA_MIN_C..TEMPERATURA_MAX_C` (`-40..85 °C` por padrão) e umidade aceita `0..100%`. O backend atribui `observedAt` em UTC quando o DHT não possui relógio confiável. Fazenda e máquina não são enviadas: a identidade persistida do dispositivo resolve e valida ambas.

Resposta de sucesso (`200`), inclusive em reenvio idempotente:

```json
{
  "status": "ok",
  "mensagem": "Telemetria recebida",
  "documentoId": "reading_...",
  "deviceId": "esp32_real_01",
  "fazendaId": "fazenda_real_01",
  "maquinaId": "maquina_real_01",
  "observedAt": "2026-08-25T18:00:00+00:00",
  "receivedAt": "2026-08-25T18:00:00+00:00",
  "deduplicated": false,
  "apiContractVersion": "1"
}
```

Códigos de ingestão: `200` aceita/deduplica; `400` rejeita JSON inválido, incompleto, tipo ou faixa inválida; `401` rejeita identidade/token; `409` rejeita `readingId` reutilizado com conteúdo diferente; `413` rejeita corpo grande; `415` exige JSON; `429` aplica o limite e retorna `Retry-After`; `503` indica persistência temporariamente indisponível. Falha de rede/timeout não produz resposta HTTP e o firmware mantém a leitura pendente para nova tentativa.

Teste manual PowerShell, sem gravar token no repositório:

```powershell
$env:SOMPO_DEVICE_TOKEN = "TOKEN_PROVISIONADO"
$headers = @{ "X-Device-Token" = $env:SOMPO_DEVICE_TOKEN }
$body = @{
  deviceId = "esp32_real_01"
  readingId = "manual_$([guid]::NewGuid().ToString('N'))"
  temperatura = 25.4
  umidade = 61.2
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://IP_LAN:5000/dados" -Headers $headers -ContentType "application/json" -Body $body
```

Teste equivalente por Python:

```powershell
$env:SOMPO_DEVICE_TOKEN = "TOKEN_PROVISIONADO"
python -m scripts.smoke_test_api --base-url http://IP_LAN:5000 --send-telemetry --device esp32_real_01 --temperatura 25.4 --umidade 61.2
```

Envelope recomendado:

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

O backend resolve fazenda/máquina pela identidade. `fazendaId`/`maquinaId`, se enviados, precisam coincidir. `readingId` é idempotente por dispositivo.

Cada measurement deve corresponder a `sensoresConfigurados` da máquina. O valor pode ser numérico (unidade implícita do perfil) ou `{value, unit}`. A unidade explícita deve coincidir exatamente; não existe conversão silenciosa entre Celsius/Fahrenheit/Kelvin ou m/s/km/h.

O payload legado `{temperatura, umidade}` permanece aceito para firmware DHT11, com `measurementScope=unknown`. Ele não é interpretado como temperatura ambiente ou do motor.

Limites: JSON configurável (16 KiB por padrão), até 50 measurements, metadata limitada e IDs/strings limitados. Rate limit V1 é local ao processo.

## Property e contexto temporal

Property inclui identidade, município/UF, coordenadas, área, atividade, solo, evidências, culturas e timestamps. `culturas` aceita `safra`, `estagioSafra`, `vigenteDesde`, `vigenteAte` e `atual`, permitindo evolução temporal sem introduzir um modelo agronômico completo.

Property risk é independente do catálogo regional.

## Machine e sensor profile

```json
{
  "sensorId": "temp_motor",
  "type": "temperature",
  "scope": "machine_component",
  "target": "engine",
  "unit": "celsius",
  "thresholds": {"warning": 70, "high": 85, "critical": 95},
  "metadata": {}
}
```

`sensorId`, `type`, `scope`, `target` e `unit` preservam o significado. Thresholds são por sensor e crescentes; não há threshold universal. Quando o hardware possui faixa física conhecida, `metadata.validRange={min,max}` rejeita valores fora dessa faixa antes da persistência e do motor.

## Risk Context, coverage e provenance

Risk Context inclui `property`, `weather`, `geospatial`, `satellite`, `history`, `iot`, `machineContext`, `provenance`, `sourceHealth`, `dataCoverage`, `cropProfile`, `riskDomains` e versões.

Para cada fonte, provenance indica origem, horário observado/consultado, cache, stale, disponibilidade e participação no score. Coverage não preenche lacunas de clima, hotspot, geoespacial, histórico ou IoT.

## Risk outputs

- **EnvironmentalRisk:** scores determinísticos por perigo, fatores, cobertura e confiança. Terreno operacional não determina o risco ambiental geral.
- **MachineRisk:** categorias dirigidas por thresholds e tendência; sem dados válidos retorna `insufficient_data`, `score=null`.
- **OperationalContextRisk:** matriz de estados, GPS e hotspot, com `score=null` e método explícito.
- **riskExplanations:** por risco, `level`, `score`, `mainFactors`, `evidence`, `missingData`, `confidence` e `confidenceMeaning=quality_and_coverage_of_input_data`.

Confiança não significa certeza de ocorrência.

## Events

`domain_events` registra transições como:

```text
environmental_risk_changed
machine_risk_changed
operational_risk_changed
hotspot_detected
telemetry_stale
device_offline
source_unavailable
```

V1 gera automaticamente as três transições de risco. O modelo aceita os demais tipos para evolução. Nível igual sem delta configurado não produz evento repetido; IDs são determinísticos para a mesma transição/análise.

## Alerts

Alertas internos V1 são gerados para environmental fire high/critical, hotspot recente próximo à propriedade, machine high/critical, combinação operacional elevada e máquina marcada em operação com GPS recente próxima a hotspot em ambiente elevado.

```json
{
  "alertId": "alert_...",
  "type": "machine_risk",
  "severity": "high",
  "status": "open",
  "fazendaId": "fazenda_01",
  "maquinaId": "trator_01",
  "riskType": "machine",
  "createdAt": "...",
  "updatedAt": "...",
  "factors": [],
  "evidence": [],
  "sourceAnalysisId": "..."
}
```

Não existe texto de IA. A dedupe key é estável por condição/fazenda/máquina. Enquanto o alerta está open/acknowledged, novos cálculos não criam outro. Reabertura após resolved respeita `ALERT_COOLDOWN_SECONDS`.

Transições aceitas: `open -> acknowledged -> resolved` ou `open -> resolved`.

## Status snapshots

`GET /fazendas/<id>/status` agrega propriedade, risco atual, explicações, tendência, source health, coverage, máquinas e alertas ativos. `GET /fazendas/<id>/maquinas/<id>/status` agrega identidade, device health, últimas medições, machine/environmental/operational risk, localização e alertas.

Essas rotas só leem Firestore; não chamam clima, INPE, SGB ou outras fontes.

## Endpoints

### Públicos

- `GET /`
- `GET /health`
- `GET /ready`

### Devices e ingestão

- `POST|GET /devices`
- `GET|PATCH /devices/<deviceId>`
- `POST /devices/<deviceId>/rotate`
- `POST /dados`

### Aplicação

- `GET /risco?lat=&lon=`
- `GET /dashboard` — agregado persistido; não chama fontes externas
- `POST|GET /fazendas`
- `GET|PATCH /fazendas/<fazendaId>`
- `GET /fazendas/<fazendaId>/risco`
- `GET /fazendas/<fazendaId>/analises`
- `GET /fazendas/<fazendaId>/risco/tendencia`
- `GET /fazendas/<fazendaId>/status`
- `POST|GET /fazendas/<fazendaId>/maquinas`
- `GET|PATCH /fazendas/<fazendaId>/maquinas/<maquinaId>`
- `GET /fazendas/<fazendaId>/maquinas/<maquinaId>/telemetria`
- `GET /fazendas/<fazendaId>/maquinas/<maquinaId>/risco`
- `GET /fazendas/<fazendaId>/maquinas/<maquinaId>/status`
- `GET /eventos?fazendaId=...`
- `GET /alertas`
- `GET /fazendas/<fazendaId>/alertas`
- `GET|PATCH /alertas/<alertId>`

### Regional preservado

- `GET /regional/risco`
- `GET /regional/risco/<ibgeCode>`
- `GET /regional/risco/<ibgeCode>/historico`
- `GET /regional/map`
- `GET /regional/hotspots`

**Regional infrastructure ready / dataset rollout deferred.** Os endpoints só leem snapshots existentes e podem retornar coleção vazia/indisponível enquanto o dataset não estiver carregado. Os scripts foram preservados, mas não devem ser usados como pré-requisito do núcleo.

## Firestore e índices

Novas coleções: `devices`, `domain_events`, `alerts`, `property_risk_current`, `machine_state_current`, `audit_log`.

`firestore.indexes.json` cobre telemetria por fazenda/máquina, análises, devices, events, alerts e machine snapshots. Deploy não é automático.

## Desenvolvimento

Seed seguro:

```powershell
python -m scripts.seed_demo --dry-run --scenario normal
```

Smoke do núcleo (pode persistir análise):

```powershell
python -m scripts.smoke_test_api --core-flow --fazenda demo_fazenda_01 --maquina demo_trator_01
```

Integrações reais permanecem opt-in e somente leitura. Não há mocks/hardcodes de demo nas rotas de produção.

O teste Firestore de escrita é ainda mais restrito: requer `RUN_FIREBASE_INTEGRATION_TESTS=1`,
`ENVIRONMENT=development|test` e `FIREBASE_TEST_PROJECT_ACK` igual ao project ID. Ele usa
`test_sompo_core/test_core_*` e limpa exclusivamente o documento que criou.
