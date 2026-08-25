# Sompo Risk Platform

Protótipo acadêmico de análise preventiva de riscos geoespaciais associados a máquinas agrícolas seguradas. A plataforma cruza localização, previsão meteorológica, observações oficiais, relevo, hidrologia, cartografia de suscetibilidade e focos de calor para produzir scores determinísticos e explicáveis.

Os resultados são experimentais: não constituem laudo técnico, previsão garantida de sinistro ou decisão atuarial.

## Funcionamento

Sem dispositivo embarcado:

```text
latitude/longitude
        ↓
fontes climáticas e geoespaciais
        ↓
motor determinístico de risco
```

Evolução prevista com dispositivo embarcado:

```text
latitude/longitude + telemetria ESP32 + fontes externas
                           ↓
                 motor de risco da máquina
```

O backend já recebe temperatura e umidade de um ESP32 com DHT11, mas o cálculo geoespacial funciona sem o dispositivo físico.

## Riscos analisados

- Potencial climático e evidências próximas relacionadas a incêndio
- Geada
- Inundação
- Enxurrada
- Movimento de massa
- Risco operacional associado ao terreno
- Risco geral, definido pelo maior score disponível

Os scores variam de 0 a 100: baixo (0–29), moderado (30–59), alto (60–79) e crítico (80–100). Dados ausentes não são transformados automaticamente em zero.

## Fontes atuais

- **Open-Meteo Forecast:** previsão/modelagem de temperatura, umidade, precipitação, vento, rajadas e condições do solo.
- **Open-Meteo Flood / GloFAS:** indicador hidrológico regional de vazão e tendência.
- **Open-Meteo Elevation / Copernicus DEM:** elevação e métricas aproximadas de uma grade 3×3.
- **SGB OGC API:** cartografia de suscetibilidade a inundação, enxurrada e movimentos de massa.
- **INPE Programa Queimadas:** detecções orbitais recentes de focos de calor próximos.
- **INMET WIS2:** observações meteorológicas oficiais de uma estação próxima com dados recentes.

Detalhes e limitações estão em [Fontes de dados](docs/FONTES_DE_DADOS.md).

## Arquitetura

```text
                 LOCALIZAÇÃO
                lat + longitude
                       │
          ┌────────────┼────────────┐
          │            │            │
       CLIMA        TERRENO     HIDROLOGIA
          │            │            │
          └────────────┼────────────┘
                       │
              INPE / INMET / SGB
                       │
                       ▼
                MOTOR DE RISCO
                       │
             scores determinísticos
                       │
                       ▼
                   FIRESTORE
                       │
                       ▼
                  AGENTE/IA
                    (futuro)
```

O ESP32 ocupa a camada de aquisição local e futuramente complementará o risco da localidade com telemetria específica da máquina. Consulte a [documentação de arquitetura](docs/ARQUITETURA.md).

## Endpoints

### Health check

```http
GET /
```

### Risco por localização

```http
GET /risco?lat=-17.79&lon=-50.92
```

Latitude é obrigatória entre -90 e 90; longitude é obrigatória entre -180 e 180.

### Dados do dispositivo

```http
POST /dados
Content-Type: application/json
```

```json
{
  "temperatura": 27.5,
  "umidade": 63,
  "fazendaId": "fazenda_01",
  "maquinaId": "trator_01"
}
```

## Instalação no Windows

Requer Python 3 e uma credencial de conta de serviço do Firebase com acesso ao Firestore.

```powershell
git clone <URL_DO_REPOSITORIO>
cd sompo-risk-platform
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Coloque `firebase-key.json` na raiz apenas no ambiente local. Esse arquivo está ignorado e nunca deve ser enviado ao Git. Como alternativa, defina o caminho:

```powershell
$env:FIREBASE_KEY_PATH = "C:\caminho\seguro\firebase-key.json"
```

O firmware real também contém configuração local e é ignorado. Copie [esp32.example.ino](firmware/esp32.example.ino) para `firmware/esp32.ino` e preencha as configurações somente na cópia local.

## Continuar o projeto em outro computador

No Windows PowerShell, execute os comandos abaixo em ordem:

```powershell
git clone https://github.com/gusantin/sompo-risk-platform.git
cd sompo-risk-platform
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

O arquivo `firebase-key.json` não está no GitHub por segurança. Obtenha novamente a credencial da conta de serviço por um canal seguro e escolha uma das opções:

1. Coloque `firebase-key.json` na raiz do projeto; ou
2. mantenha a chave em outro diretório e configure o caminho na sessão do PowerShell:

```powershell
$env:FIREBASE_KEY_PATH = "C:\caminho\seguro\firebase-key.json"
```

Não copie uma chave real para `.env.example`, documentação, testes ou commits. Em seguida, valide e execute o projeto:

```powershell
python -m compileall -q server.py integracoes services tests
python -m unittest discover -s tests -v
python server.py
```

Com o servidor iniciado, abra:

```text
http://127.0.0.1:5000/
http://127.0.0.1:5000/risco?lat=-17.79&lon=-50.92
```

Para testar o ESP32 no novo computador, copie `firmware/esp32.example.ino` para o arquivo local ignorado `firmware/esp32.ino`, configure Wi-Fi e endereço do servidor e use o ambiente Arduino habitual. Não é necessário configurar PlatformIO para executar o backend.

## Execução

```powershell
.\.venv\Scripts\Activate.ps1
python server.py
```

Servidor local: `http://127.0.0.1:5000`.

## Testes

```powershell
python -m compileall -q server.py integracoes services tests
python -m unittest discover -s tests -v
```

Os testes cobrem validação das rotas, resiliência das integrações, cálculos de risco e terreno e persistência REST simulada.

## Arquivos auxiliares e legados

- `dados_sensores.csv`: pequena amostra histórica útil para demonstração; não participa atualmente do fluxo Flask nem do motor de risco.
- `teste_firebase.py`: diagnóstico manual legado da conexão REST com o Firestore. Ele escreve um documento de teste e não faz parte da suíte automatizada.

Esses arquivos foram mantidos para referência e não são necessários para iniciar `server.py`.

## Segurança

- Firestore é acessado por REST; o projeto não usa `firebase_admin` ou gRPC.
- `firebase-key.json`, `.env`, `.venv/` e o firmware configurado localmente são ignorados.
- A versão de firmware disponível no Git contém somente placeholders.
- Não grave tokens, senhas ou respostas contendo credenciais em logs e exemplos.

## Limitações

- Pesos e limiares dos scores são experimentais e acadêmicos.
- A plataforma não substitui laudos geológicos, meteorológicos, agronômicos ou atuariais.
- O DEM não identifica barrancos, valas ou obstáculos pontuais.
- GloFAS é um indicador regional e não uma medição exata de um rio específico.
- Foco de calor do INPE não confirma incêndio na propriedade.
- Disponibilidade e variáveis publicadas pelas estações INMET variam.
- APIs externas podem apresentar atraso, indisponibilidade ou cobertura incompleta.
- O cache é local ao processo e se perde quando o servidor reinicia.

## Roadmap

- ANA e CEMADEN
- MapBiomas e Copernicus Sentinel
- Testes com ESP32 físico
- Cadastro de fazendas e máquinas
- Calibração do motor de risco
- Agente de IA para explicações, sem substituir o motor determinístico
- Dashboard e mapas de risco
- Alertas preventivos

## Licença e uso

Projeto acadêmico. Antes de qualquer uso produtivo, valide licenças das fontes, requisitos de atribuição, segurança, calibração e governança dos dados.
