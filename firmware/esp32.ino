#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>

// =====================================================
// CONFIGURAÇÃO DO WIFI
// =====================================================

// ATENÇÃO: o nome precisa ser EXATAMENTE igual ao hotspot
const char* WIFI_SSID = "iPhone de Gustavo";
const char* WIFI_PASSWORD = "gustavo97";

// IP do computador rodando o Flask
const char* SERVER_URL = "http://172.20.10.6:5000/dados";

// =====================================================
// CONFIGURAÇÃO DO DHT11
// =====================================================

#define DHT_PIN 4
#define DHT_TYPE DHT11

DHT dht(DHT_PIN, DHT_TYPE);

// =====================================================
// INTERVALOS
// =====================================================

unsigned long ultimoEnvio = 0;
unsigned long ultimaTentativaWiFi = 0;

const unsigned long intervaloEnvio = 5000;
const unsigned long intervaloReconexao = 15000;

// =====================================================
// MOSTRAR STATUS WIFI
// =====================================================

void mostrarStatusWiFi()
{
    Serial.print("Status WiFi: ");

    switch (WiFi.status())
    {
        case WL_CONNECTED:
            Serial.println("CONECTADO");
            break;

        case WL_NO_SSID_AVAIL:
            Serial.println("REDE NAO ENCONTRADA");
            break;

        case WL_CONNECT_FAILED:
            Serial.println("FALHA NA CONEXAO / SENHA INCORRETA");
            break;

        case WL_CONNECTION_LOST:
            Serial.println("CONEXAO PERDIDA");
            break;

        case WL_DISCONNECTED:
            Serial.println("DESCONECTADO");
            break;

        default:
            Serial.print("CODIGO ");
            Serial.println(WiFi.status());
            break;
    }
}

// =====================================================
// CONECTAR AO WIFI
// =====================================================

bool conectarWiFi()
{
    Serial.println();
    Serial.println("================================");
    Serial.println("       CONECTANDO AO WIFI       ");
    Serial.println("================================");

    Serial.print("Rede: ");
    Serial.println(WIFI_SSID);

    // Evita conflito de tentativas anteriores
    WiFi.setAutoReconnect(false);

    WiFi.disconnect();

    delay(1000);

    WiFi.mode(WIFI_STA);

    delay(500);

    // Uma única tentativa limpa
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("Conectando");

    // Aguarda até 20 segundos
    unsigned long inicio = millis();

    while (WiFi.status() != WL_CONNECTED &&
           millis() - inicio < 20000)
    {
        Serial.print(".");
        delay(500);
    }

    Serial.println();

    if (WiFi.status() == WL_CONNECTED)
    {
        Serial.println();
        Serial.println("================================");
        Serial.println("        WIFI CONECTADO!         ");
        Serial.println("================================");

        Serial.print("IP do ESP32: ");
        Serial.println(WiFi.localIP());

        Serial.print("IP do servidor: ");
        Serial.println("172.20.10.6");

        Serial.print("Sinal WiFi: ");
        Serial.print(WiFi.RSSI());
        Serial.println(" dBm");

        Serial.println();

        WiFi.setAutoReconnect(true);

        return true;
    }

    Serial.println();
    Serial.println("FALHA AO CONECTAR NO WIFI!");

    mostrarStatusWiFi();

    Serial.println();

    return false;
}

// =====================================================
// ENVIAR TEMPERATURA E UMIDADE
// =====================================================

void enviarDados(float temperatura, float umidade)
{
    if (WiFi.status() != WL_CONNECTED)
    {
        Serial.println("Sem WiFi. Dados nao enviados.");
        return;
    }

    HTTPClient http;

    Serial.println();
    Serial.println("Conectando ao webserver...");

    http.setTimeout(5000);

    http.begin(SERVER_URL);

    http.addHeader("Content-Type", "application/json");

    // =================================================
    // MONTA JSON
    // =================================================

    String json = "{";

    json += "\"temperatura\":";
    json += String(temperatura, 2);

    json += ",";

    json += "\"umidade\":";
    json += String(umidade, 2);

    json += "}";

    Serial.println("JSON enviado:");
    Serial.println(json);

    // =================================================
    // HTTP POST
    // =================================================

    int codigoHTTP = http.POST(json);

    if (codigoHTTP > 0)
    {
        Serial.print("HTTP Status: ");
        Serial.println(codigoHTTP);

        String resposta = http.getString();

        Serial.print("Resposta do servidor: ");
        Serial.println(resposta);

        if (codigoHTTP == 200)
        {
            Serial.println("DADOS ARMAZENADOS COM SUCESSO!");
        }
    }
    else
    {
        Serial.print("ERRO HTTP: ");
        Serial.println(codigoHTTP);

        Serial.println("Nao foi possivel acessar o servidor.");
    }

    http.end();

    Serial.println();
}

// =====================================================
// SETUP
// =====================================================

void setup()
{
    Serial.begin(115200);

    delay(2000);

    Serial.println();
    Serial.println("======================================");
    Serial.println("      ESP32 + DHT11 + WEBSERVER       ");
    Serial.println("======================================");
    Serial.println();

    // Inicia sensor
    dht.begin();

    // Conecta apenas UMA vez inicialmente
    conectarWiFi();

    ultimaTentativaWiFi = millis();
}

// =====================================================
// LOOP
// =====================================================

void loop()
{
    // =================================================
    // RECONECTAR WIFI
    // =================================================

    if (WiFi.status() != WL_CONNECTED)
    {
        if (millis() - ultimaTentativaWiFi >= intervaloReconexao)
        {
            ultimaTentativaWiFi = millis();

            conectarWiFi();
        }
    }

    // =================================================
    // LEITURA A CADA 5 SEGUNDOS
    // =================================================

    if (millis() - ultimoEnvio >= intervaloEnvio)
    {
        ultimoEnvio = millis();

        float temperatura = dht.readTemperature();
        float umidade = dht.readHumidity();

        Serial.println();
        Serial.println("----------- LEITURA -----------");

        // =================================================
        // VERIFICAR DHT
        // =================================================

        if (isnan(temperatura) || isnan(umidade))
        {
            Serial.println("ERRO AO LER DHT11!");
            Serial.println("-------------------------------");

            return;
        }

        // =================================================
        // MOSTRAR NO SERIAL MONITOR
        // =================================================

        Serial.print("Temperatura: ");
        Serial.print(temperatura, 2);
        Serial.println(" C");

        Serial.print("Umidade: ");
        Serial.print(umidade, 2);
        Serial.println(" %");

        Serial.println("-------------------------------");

        // =================================================
        // ENVIAR AO SERVIDOR
        // =================================================

        if (WiFi.status() == WL_CONNECTED)
        {
            enviarDados(temperatura, umidade);
        }
        else
        {
            Serial.println("WiFi ainda nao conectado.");
            Serial.println("Leitura realizada, mas nao enviada.");
        }
    }
}