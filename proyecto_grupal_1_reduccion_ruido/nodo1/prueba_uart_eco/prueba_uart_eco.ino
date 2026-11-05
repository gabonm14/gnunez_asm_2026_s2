/* Prueba mínima de la UART, lado receptor. Se carga en el ESP32 de los nodos 2/3.
 * Muestra en su monitor serie (115200) todo lo que llega por GPIO16 (UART2 RX).
 * Conexión: GPIO17 del nodo 1 ──► GPIO16 de este ESP32, y GND común.
 * Debe aparecer "Llego: HOLA <n>" dos veces por segundo, con n creciendo de uno en uno.
 */
#include <Arduino.h>

constexpr int PIN_RX = 16, PIN_TX = 17;

void setup() {
  Serial.begin(115200);
  Serial2.begin(115200, SERIAL_8N1, PIN_RX, PIN_TX);
  delay(300);
  Serial.println("Esperando datos del nodo 1 en GPIO16...");
}

void loop() {
  static String linea;
  static uint32_t ultimo = millis();
  while (Serial2.available()) {
    const char c = Serial2.read();
    ultimo = millis();
    if (c == '\n') { Serial.printf("Llego: %s\n", linea.c_str()); linea = ""; }
    else if (c != '\r') linea += c;
  }
  static uint32_t aviso = 0;
  if (millis() - ultimo > 2000 && millis() - aviso > 2000) {
    aviso = millis();
    Serial.println("(nada en los ultimos 2 s: revise GPIO17 -> GPIO16 y GND)");
  }
}
