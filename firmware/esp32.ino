#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <esp_system.h>
#include "secrets.h"

// Copie secrets.example.h para secrets.h e mantenha credenciais fora do Git.
const char* WIFI_SSID = WIFI_SSID_VALUE;
const char* WIFI_PASSWORD = WIFI_PASSWORD_VALUE;
const char* SERVER_URL = SERVER_URL_VALUE;

#define DHT_PIN 4
#define DHT_TYPE DHT11

DHT dht(DHT_PIN, DHT_TYPE);

const unsigned long INTERVALO_LEITURA_MS = 5000;
const unsigned long INTERVALO_RECONEXAO_MS = 15000;
const unsigned long INTERVALO_RETRY_HTTP_MS = 5000;
const uint16_t TIMEOUT_HTTP_MS = 5000;

unsigned long ultimaLeitura = 0;
unsigned long ultimaTentativaWiFi = 0;
unsigned long ultimaTentativaHTTP = 0;
uint32_t bootId = 0;
uint32_t sequenciaLeitura = 0;

struct LeituraPendente
{
    bool ativa = false;
    float temperatura = 0;
    float umidade = 0;
    String readingId;
};

LeituraPendente pendente;

enum ResultadoEnvio
{
    ENVIO_SUCESSO,
    ENVIO_REJEITADO,
    ENVIO_TENTAR_NOVAMENTE
};

bool conectarWiFi()
{
    Serial.println("Conectando ao Wi-Fi...");
    WiFi.setAutoReconnect(false);
    WiFi.disconnect();
    delay(500);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long inicio = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - inicio < 20000)
    {
        delay(500);
        Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() != WL_CONNECTED)
    {
        Serial.print("Falha no Wi-Fi. Status: ");
        Serial.println(WiFi.status());
        return false;
    }

    WiFi.setAutoReconnect(true);
    Serial.print("Wi-Fi conectado. IP do ESP32: ");
    Serial.println(WiFi.localIP());
    Serial.print("Endpoint: ");
    Serial.println(SERVER_URL);
    return true;
}

String novoReadingId()
{
    char buffer[64];
    snprintf(
        buffer,
        sizeof(buffer),
        "esp32_%08lx_%lu",
        static_cast<unsigned long>(bootId),
        static_cast<unsigned long>(sequenciaLeitura++)
    );
    return String(buffer);
}

ResultadoEnvio enviarDados(const LeituraPendente& leitura)
{
    if (WiFi.status() != WL_CONNECTED)
    {
        Serial.println("Sem Wi-Fi; leitura mantida para nova tentativa.");
        return ENVIO_TENTAR_NOVAMENTE;
    }

    HTTPClient http;
    http.setTimeout(TIMEOUT_HTTP_MS);
    if (!http.begin(SERVER_URL))
    {
        Serial.println("Nao foi possivel inicializar a conexao HTTP.");
        return ENVIO_TENTAR_NOVAMENTE;
    }

    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Device-Token", DEVICE_TOKEN_VALUE);

    String json;
    json.reserve(220);
    json += "{\"deviceId\":\"";
    json += DEVICE_ID_VALUE;
    json += "\",\"readingId\":\"";
    json += leitura.readingId;
    json += "\",\"temperatura\":";
    json += String(leitura.temperatura, 2);
    json += ",\"umidade\":";
    json += String(leitura.umidade, 2);
    json += "}";

    Serial.print("Enviando leitura ");
    Serial.print(leitura.readingId);
    Serial.print(": temperatura=");
    Serial.print(leitura.temperatura, 2);
    Serial.print(" C, umidade=");
    Serial.print(leitura.umidade, 2);
    Serial.println(" %");

    int codigoHTTP = http.POST(json);
    String resposta = codigoHTTP > 0 ? http.getString() : "";
    http.end();

    if (codigoHTTP == 200)
    {
        Serial.println("Leitura aceita pelo servidor.");
        return ENVIO_SUCESSO;
    }

    Serial.print("Falha HTTP: ");
    Serial.println(codigoHTTP);
    if (resposta.length() > 0)
    {
        Serial.print("Resposta: ");
        Serial.println(resposta);
    }

    if (codigoHTTP <= 0 || codigoHTTP == 408 || codigoHTTP == 429 || codigoHTTP >= 500)
    {
        Serial.println("Falha temporaria; a mesma readingId sera reenviada.");
        return ENVIO_TENTAR_NOVAMENTE;
    }

    Serial.println("Leitura rejeitada de forma permanente; verifique contrato e credencial.");
    return ENVIO_REJEITADO;
}

void tentarEnviarPendente()
{
    if (!pendente.ativa || WiFi.status() != WL_CONNECTED)
    {
        return;
    }
    if (ultimaTentativaHTTP != 0 && millis() - ultimaTentativaHTTP < INTERVALO_RETRY_HTTP_MS)
    {
        return;
    }

    ultimaTentativaHTTP = millis();
    ResultadoEnvio resultado = enviarDados(pendente);
    if (resultado != ENVIO_TENTAR_NOVAMENTE)
    {
        pendente.ativa = false;
    }
}

void setup()
{
    Serial.begin(115200);
    delay(1500);
    Serial.println("ESP32 + DHT11 -> SOMPO Risk Platform");

    bootId = esp_random();
    dht.begin();
    delay(2000);
    conectarWiFi();
    ultimaTentativaWiFi = millis();
}

void loop()
{
    if (WiFi.status() != WL_CONNECTED &&
        millis() - ultimaTentativaWiFi >= INTERVALO_RECONEXAO_MS)
    {
        ultimaTentativaWiFi = millis();
        conectarWiFi();
    }

    tentarEnviarPendente();

    if (millis() - ultimaLeitura < INTERVALO_LEITURA_MS)
    {
        return;
    }
    ultimaLeitura = millis();

    float temperatura = dht.readTemperature();
    float umidade = dht.readHumidity();
    if (isnan(temperatura) || isnan(umidade))
    {
        Serial.println("Falha ao ler o DHT11; nenhuma requisicao enviada.");
        return;
    }

    if (pendente.ativa)
    {
        Serial.println("Servidor indisponivel; aguardando envio da leitura pendente.");
        return;
    }

    pendente.ativa = true;
    pendente.temperatura = temperatura;
    pendente.umidade = umidade;
    pendente.readingId = novoReadingId();
    ultimaTentativaHTTP = 0;
    tentarEnviarPendente();
}
