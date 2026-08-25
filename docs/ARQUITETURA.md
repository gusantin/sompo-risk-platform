# Arquitetura da Sompo Risk Platform

## Visão geral

A plataforma separa aquisição, integrações, domínio, persistência e exposição HTTP. Essa divisão permite acrescentar fontes futuras sem concentrar regras no `server.py`.

```text
ESP32 e coordenadas
        │
        ▼
integrações externas ──► cache em memória
        │
        ▼
motor determinístico de risco
        │
        ├──► resposta da API Flask
        └──► Firestore REST
```

## Camada de aquisição

### Localização

O endpoint `GET /risco` recebe latitude e longitude. A análise geoespacial funciona sem hardware conectado.

### ESP32

O firmware de referência utiliza ESP32 e DHT11. O dispositivo envia temperatura e umidade para `POST /dados`, juntamente com identificadores opcionais de fazenda e máquina. A versão real configurada é local e ignorada pelo Git; `firmware/esp32.example.ino` é o modelo seguro.

No futuro, a telemetria deverá complementar — não substituir — o risco da localidade.

## Camada de integração

O pacote `integracoes/` encapsula os contratos externos:

- `open_meteo.py`: clima, hidrologia e terreno;
- `sgb.py`: coleções OGC de suscetibilidade;
- `inpe_queimadas.py`: CSVs diários de focos de calor;
- `inmet.py`: estações e observações WIS2/OGC;
- `geoespacial.py`: cálculo de distância sem dependências adicionais;
- `cache.py`: cache em memória por coordenada arredondada.

Cada integração define timeout, captura falhas, informa status, mensagem, horário da consulta e dados disponíveis. Uma fonte indisponível não impede o uso das demais.

## Camada de domínio

`services/risco_service.py` contém o motor determinístico. Os pesos e limiares são heurísticas documentadas para o protótipo acadêmico.

O serviço:

- calcula scores apenas com componentes disponíveis;
- não transforma ausência de dados em zero;
- informa fatores e cobertura dos dados;
- ajusta confiança conforme fontes observacionais disponíveis;
- registra divergências relevantes entre Open-Meteo e INMET;
- mantém separado o potencial climático de incêndio da detecção de foco de calor.

## Persistência

`services/firestore_service.py` converte tipos Python para o formato de documentos do Firestore e escreve pela API REST HTTP.

Coleções atuais:

- `leituras_sensores`: telemetria recebida pelo endpoint `/dados`;
- `analises_risco`: localização, scores, fatores e resumo das fontes utilizadas.

O projeto não usa `firebase_admin` nem o transporte gRPC. Uma falha de persistência é informada na resposta sem apagar o resultado calculado.

## API Flask

`server.py` realiza composição e configuração:

- valida parâmetros HTTP;
- chama as integrações;
- entrega as fontes ao motor de risco;
- tenta persistir o resultado;
- preserva o contrato do ESP32.

Rotas atuais:

- `GET /` — estado da aplicação;
- `GET /risco` — análise por coordenada;
- `POST /dados` — telemetria do ESP32;
- `GET /teste-firebase` — diagnóstico manual de persistência.

## Cache e resiliência

O cache é mantido em memória e usa coordenadas arredondadas. Clima possui validade curta; hidrologia, INMET e INPE usam intervalos intermediários; terreno e SGB têm validade maior. Cada processo Flask possui seu próprio cache.

Não existe retentativa agressiva. Respostas incompletas conservam `None` e estados como `erro_api`, `parcial`, `fonte_sem_cobertura` e `sem_evidencia_na_fonte`.

## Futuro agente de IA

A IA poderá:

- interpretar scores já calculados;
- produzir explicações e relatórios;
- resumir fatores e limitações;
- sugerir ações preventivas para avaliação humana.

A IA não deverá:

- inventar observações ou completar dados ausentes;
- substituir as fontes oficiais;
- calcular unilateralmente os scores determinísticos;
- afirmar que um sinistro ocorrerá;
- executar decisões de seguro automaticamente.

