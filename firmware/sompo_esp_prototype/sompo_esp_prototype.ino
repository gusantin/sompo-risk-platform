#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>

#define DHT_PIN4
#define DHT_TYPE DHT22

#define POT_PIN35
#define LDR_PIN19

#define BUZZER_PIN15

#define I2C_SDA_PIN21
#define I2C_SCL_PIN22

#define LCD_I2C_ADDRESS 0x27
#define LCD_COLUMNS16
#define LCD_ROWS2

constfloat TEMP_MIN_NORMAL = 15.0;
constfloat TEMP_MAX_NORMAL = 30.0;
constfloat TEMP_MAX_ATENCAO = 35.0;
constfloat TEMP_LIMITE_RISCO = 35.0;

constfloat UMD_MIN_NORMAL = 40.0;
constfloat UMD_MAX_NORMAL = 80.0;
constfloat UMD_MIN_RISCO = 20.0;
constfloat UMD_MAX_RISCO = 95.0;

constfloat VENTO_NORMAL_MAX = 30.0;
constfloat VENTO_ATENCAO_MAX = 50.0;
constfloat VENTO_RISCO = 50.0;

constunsignedlong BUZZER_INTERVAL_MS = 500;

constunsignedlong TELA_INTERVAL_MS = 3000;

DHT dht(DHT_PIN, DHT_TYPE);
LiquidCrystal_I2C lcd(LCD_I2C_ADDRESS, LCD_COLUMNS, LCD_ROWS);

unsignedlong ultimaTrocaTela = 0;
unsignedlong ultimoToggleBuzzer = 0;
bool telaAtual = false;
bool buzzerLigado = false;

float temperatura = 0.0;
float umidade = 0.0;
bool dhtComErro = false;

float ventoKmh = 0.0;
int leituraLdrDigital = 0;

unsignedlong ultimaLeituraSensores = 0;
constunsignedlong INTERVALO_LEITURA_SENSORES = 2000;

String statusGeral = "NORMAL";

voidsetup() {
Serial.begin(115200);

Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);

lcd.init();
lcd.backlight();
lcd.setCursor(0, 0);
lcd.print("AgroRisk SOMPO");
lcd.setCursor(0, 1);
lcd.print("Iniciando...");

dht.begin();

pinMode(LDR_PIN, INPUT);
pinMode(BUZZER_PIN, OUTPUT);
digitalWrite(BUZZER_PIN, LOW);

delay(1500);
lcd.clear();
}

voidloop() {
unsignedlong agora = millis();

 if (agora - ultimaLeituraSensores >= INTERVALO_LEITURA_SENSORES) {
 ultimaLeituraSensores = agora;
lerSensores();
calcularStatusGeral();
 }

controlarBuzzer(agora);

 if (agora - ultimaTrocaTela >= TELA_INTERVAL_MS) {
 ultimaTrocaTela = agora;
 telaAtual = !telaAtual;
atualizarLCD();
 }
}

voidlerSensores() {
float t = dht.readTemperature();
float h = dht.readHumidity();

 if (isnan(t) || isnan(h)) {
 dhtComErro = true;
Serial.println("Erro na leitura do sensor DHT!");
 } else {
 dhtComErro = false;
 temperatura = t;
 umidade = h;
 }

int leituraPot = analogRead(POT_PIN);
 ventoKmh = mapFloat(leituraPot, 0, 4095, 0.0, 100.0);

 leituraLdrDigital = digitalRead(LDR_PIN);
}

floatmapFloat(float x, float inMin, float inMax, float outMin, float outMax) {
 return (x - inMin) * (outMax - outMin) / (inMax - inMin) + outMin;
}

String classificarTemperatura() {
 if (dhtComErro) return "ERRO";
 if (temperatura > TEMP_LIMITE_RISCO) return "RISCO";
 if (temperatura < TEMP_MIN_NORMAL || temperatura > TEMP_MAX_NORMAL) return "ATENCAO";
 return "NORMAL";
}

String classificarUmidade() {
 if (dhtComErro) return "ERRO";
 if (umidade < UMD_MIN_RISCO || umidade > UMD_MAX_RISCO) return "RISCO";
 if (umidade < UMD_MIN_NORMAL || umidade > UMD_MAX_NORMAL) return "ATENCAO";
 return "NORMAL";
}

String classificarVento() {
 if (ventoKmh > VENTO_RISCO) return "RISCO";
 if (ventoKmh > VENTO_NORMAL_MAX) return "ATENCAO";
 return "NORMAL";
}

voidcalcularStatusGeral() {
 String statusTemp = classificarTemperatura();
 String statusUmd = classificarUmidade();
 String statusVento = classificarVento();

 if (statusTemp == "RISCO" || statusUmd == "RISCO" || statusVento == "RISCO") {
 statusGeral = "RISCO";
 } else if (statusTemp == "ATENCAO" || statusUmd == "ATENCAO" || statusVento == "ATENCAO") {
 statusGeral = "ATENCAO";
 } else {
 statusGeral = "NORMAL";
 }
}

voidcontrolarBuzzer(unsignedlong agora) {
bool emRisco = (statusGeral == "RISCO");

 if (emRisco) {
 if (agora - ultimoToggleBuzzer >= BUZZER_INTERVAL_MS) {
 ultimoToggleBuzzer = agora;
 buzzerLigado = !buzzerLigado;
digitalWrite(BUZZER_PIN, buzzerLigado ? HIGH : LOW);
 }
 } else {
 if (buzzerLigado) {
 buzzerLigado = false;
digitalWrite(BUZZER_PIN, LOW);
 }
 }
}

voidatualizarLCD() {
lcd.clear();

 if (!telaAtual) {
lcd.setCursor(0, 0);
 if (dhtComErro) {
lcd.print("TEMP: ERRO DHT");
 } else {
lcd.print("TEMP: ");
lcd.print(temperatura, 1);
lcd.print(" C");
 }

lcd.setCursor(0, 1);
 if (dhtComErro) {
lcd.print("UMD: ERRO DHT");
 } else {
lcd.print("UMD: ");
lcd.print(umidade, 0);
lcd.print(" %");
 }
 } else {
lcd.setCursor(0, 0);
lcd.print("VST: ");
lcd.print(ventoKmh, 0);
lcd.print(" km/h");

lcd.setCursor(0, 1);
 if (statusGeral == "RISCO") {
lcd.print("STATUS:RISCO!");
 } else if (statusGeral == "ATENCAO") {
lcd.print("STATUS:ATENCAO");
 } else {
lcd.print("STATUS:NORMAL");
 }
 }
}
