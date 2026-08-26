#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>

// Mantém firmware/esp32.ino como fonte única do firmware existente.
// Os includes acima permitem ao PlatformIO descobrir as bibliotecas internas do framework.
// Este wrapper fornece o ponto de entrada esperado sem duplicar o código do firmware.
#include "../esp32.ino"
