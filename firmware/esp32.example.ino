#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>

// Copie este arquivo para esp32.ino e preencha somente no arquivo local ignorado.
const char* WIFI_SSID = "SEU_WIFI";
const char* WIFI_PASSWORD = "SUA_SENHA";
const char* SERVER_URL = "http://IP_DO_SERVIDOR:5000/dados";

#define DHT_PIN 4
#define DHT_TYPE DHT11

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long ultimoEnvio = 0;
unsigned long ultimaTentativaWiFi = 0;

const unsigned long intervaloEnvio = 5000;
const unsigned long intervaloReconexao = 15000;

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

bool conectarWiFi()
{
    Serial.println();
    Serial.println("================================");
    Serial.println("       CONECTANDO AO WIFI       ");
    Serial.println("================================");
    Serial.print("Rede: ");
    Serial.println(WIFI_SSID);

    WiFi.setAutoReconnect(false);
    WiFi.disconnect();
    delay(1000);
    WiFi.mode(WIFI_STA);
    delay(500);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("Conectando");
    unsigned long inicio = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - inicio < 20000)
    {
        Serial.print(".");
        delay(500);
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED)
    {
        Serial.println("WIFI CONECTADO!");
        Serial.print("IP do ESP32: ");
        Serial.println(WiFi.localIP());
        Serial.print("Servidor: ");
        Serial.println(SERVER_URL);
        Serial.print("Sinal WiFi: ");
        Serial.print(WiFi.RSSI());
        Serial.println(" dBm");
        WiFi.setAutoReconnect(true);
        return true;
    }

    Serial.println("FALHA AO CONECTAR NO WIFI!");
    mostrarStatusWiFi();
    return false;
}

void enviarDados(float temperatura, float umidade)
{
    if (WiFi.status() != WL_CONNECTED)
    {
        Serial.println("Sem WiFi. Dados nao enviados.");
        return;
    }

    HTTPClient http;
    Serial.println("Conectando ao webserver...");
    http.setTimeout(5000);
    http.begin(SERVER_URL);
    http.addHeader("Content-Type", "application/json");

    String json = "{";
    json += "\"temperatura\":";
    json += String(temperatura, 2);
    json += ",";
    json += "\"umidade\":";
    json += String(umidade, 2);
    json += "}";

    Serial.println("JSON enviado:");
    Serial.println(json);

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
}

void setup()
{
    Serial.begin(115200);
    delay(2000);
    Serial.println("ESP32 + DHT11 + WEBSERVER");
    dht.begin();
    conectarWiFi();
    ultimaTentativaWiFi = millis();
}

void loop()
{
    if (WiFi.status() != WL_CONNECTED &&
        millis() - ultimaTentativaWiFi >= intervaloReconexao)
    {
        ultimaTentativaWiFi = millis();
        conectarWiFi();
    }

    if (millis() - ultimoEnvio >= intervaloEnvio)
    {
        ultimoEnvio = millis();
        float temperatura = dht.readTemperature();
        float umidade = dht.readHumidity();

        if (isnan(temperatura) || isnan(umidade))
        {
            Serial.println("ERRO AO LER DHT11!");
            return;
        }

        Serial.print("Temperatura: ");
        Serial.print(temperatura, 2);
        Serial.println(" C");
        Serial.print("Umidade: ");
        Serial.print(umidade, 2);
        Serial.println(" %");

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
