#include <Arduino.h>

// -----------------------------------------------------------------------------
// Configuración del sensor y del muestreo
// -----------------------------------------------------------------------------

// GPIO al que se conecta OUT del sensor óptico.
constexpr int PIN_SENSOR = 27;

// GPIO que envía la señal de control al servo.
constexpr int PIN_SERVO = 26;

// Con RISING contamos un solo flanco por ranura. Verifiquen este valor
// contando los pulsos que genera una vuelta completa del disco.
constexpr uint32_t PULSOS_POR_VUELTA = 36;

// Intervalo mínimo entre muestras. Cada muestra usa el tiempo real
// transcurrido, aunque el loop tarde un poco más de 50 ms.
constexpr uint32_t MUESTREO_MS = 50;

// -----------------------------------------------------------------------------
// Configuración del servo
// -----------------------------------------------------------------------------

// false permite probar solo el sensor.
// Cambiar a true después de calibrar las dos posiciones del servo.
constexpr bool USAR_SERVO = false;

constexpr uint32_t SERVO_HZ = 50;
constexpr uint8_t SERVO_BITS = 14;

// Son anchos de pulso en microsegundos. El valor 0 indica que
// todavía falta completar la calibración de esa posición.
constexpr uint32_t LIBERADO_US = 0;
constexpr uint32_t APLICADO_US = 0;

// -----------------------------------------------------------------------------
// Contador del sensor y estado del ensayo
// -----------------------------------------------------------------------------

// La interrupción escribe este contador y loop() lo lee.
// El bloqueo mux protege ese acceso compartido.
portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
volatile uint32_t pulsosTotales = 0;

// Tiempos de inicio del ensayo y de la última muestra.
uint32_t inicioMs;
uint32_t ultimaMuestraMs;

// Valor del contador en la muestra anterior. Restarlo del contador
// actual da la cantidad de pulsos que ocurrieron durante el intervalo.
uint32_t pulsosAnteriores;

bool ensayoActivo = false;     // Indica si estamos enviando datos por serial.
bool escalonPendiente = false; // Se recibió 'f' y falta aplicar el cambio.
bool frenoAplicado = false;    // Indica que ya enviamos la orden al servo.

// -----------------------------------------------------------------------------
// Funciones auxiliares
// -----------------------------------------------------------------------------

// Se ejecuta automáticamente cada vez que OUT pasa de LOW a HIGH.
// Puede ejecutarse entre dos instrucciones del loop, por lo que aquí
// solo incrementamos el contador. El cálculo de RPM se hace en loop().
void ARDUINO_ISR_ATTR contarPulso() {
  portENTER_CRITICAL_ISR(&mux);
  ++pulsosTotales;
  portEXIT_CRITICAL_ISR(&mux);
}

// Toma una copia del contador total. La sección crítica evita que la
// interrupción modifique el contador mientras estamos copiando su valor.
uint32_t leerPulsos() {
  portENTER_CRITICAL(&mux);
  const uint32_t total = pulsosTotales;
  portEXIT_CRITICAL(&mux);
  return total;
}

// Convierte el ancho de pulso del servo a un valor que entiende LEDC.
// A 50 Hz, cada período dura 20 000 us. Si pulsoUs fuera 1500 us,
// la señal permanecería en alto durante el 7.5 % de cada período.
// LEDC sigue generando esa señal hasta que se escriba otro valor.
void escribirServo(uint32_t pulsoUs) {
  const uint32_t duty =
      pulsoUs * SERVO_HZ * (1UL << SERVO_BITS) / 1000000UL;
  ledcWrite(PIN_SERVO, duty);
}

// -----------------------------------------------------------------------------
// setup() se ejecuta una vez al encender o reiniciar la ESP32.
// -----------------------------------------------------------------------------

void setup() {
  // El Monitor Serie debe usar esta misma velocidad.
  Serial.begin(115200);

  // Conectamos el contador a los flancos ascendentes del sensor.
  pinMode(PIN_SENSOR, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_SENSOR), contarPulso, RISING);

  if (USAR_SERVO) {
    // La compilación falla si se habilita el servo sin configurar
    // dos anchos de pulso positivos y diferentes.
    static_assert(!USAR_SERVO ||
                  (LIBERADO_US > 0 && APLICADO_US > 0 &&
                   LIBERADO_US != APLICADO_US),
                  "Configurar las dos posiciones calibradas del servo");

    // Configuramos la salida PWM con la frecuencia y resolución elegidas.
    if (!ledcAttach(PIN_SERVO, SERVO_HZ, SERVO_BITS)) {
      Serial.println("Error al configurar el PWM del servo");
      return;
    }

    // El servo empieza en la posición calibrada de freno liberado.
    escribirServo(LIBERADO_US);
  }

  Serial.println("Enviar i para iniciar, f para aplicar freno, x para terminar.");
}

// -----------------------------------------------------------------------------
// loop() se repite continuamente. Atiende comandos, toma muestras y envía el CSV.
// -----------------------------------------------------------------------------

void loop() {
  // Revisamos si llegó un carácter desde el Monitor Serie.
  if (Serial.available()) {
    const char orden = Serial.read();

    if (orden == 'i' && !ensayoActivo) {
      // Iniciar un ensayo. Guardamos el contador actual como referencia
      // para que los pulsos previos al ensayo queden fuera del cálculo.
      inicioMs = ultimaMuestraMs = millis();
      pulsosAnteriores = leerPulsos();

      frenoAplicado = false;
      escalonPendiente = false;
      ensayoActivo = true;

      // Encabezado que MATLAB usará como nombres de columnas.
      Serial.println("t_s,u,rpm,pulsos");

    } else if (orden == 'f' && ensayoActivo && USAR_SERVO && !frenoAplicado) {
      // Programamos el escalón para la siguiente muestra. Así, el cambio
      // de orden queda registrado en la misma fila en que se envía al servo.
      escalonPendiente = true;

    } else if (orden == 'x' && ensayoActivo) {
      // Terminar el registro y devolver el servo a freno liberado.
      ensayoActivo = false;
      if (USAR_SERVO) escribirServo(LIBERADO_US);
    }
  }

  // Comprobamos si ya corresponde tomar la siguiente muestra.
  // Este return termina solo la iteración actual. Arduino llama
  // a loop() de nuevo, así que podemos seguir atendiendo comandos.
  const uint32_t ahoraMs = millis();
  const uint32_t intervaloMs = ahoraMs - ultimaMuestraMs;
  if (!ensayoActivo || intervaloMs < MUESTREO_MS) return;

  // El contador es acumulado. Su diferencia da los pulsos nuevos.
  const uint32_t total = leerPulsos();
  const uint32_t pulsos = total - pulsosAnteriores;

  // pulsos / PULSOS_POR_VUELTA da las vueltas del intervalo.
  // Dividimos por su duración en ms y multiplicamos por 60 000
  // para convertir de vueltas por milisegundo a vueltas por minuto.
  const float rpm = 60000.0f * pulsos / (PULSOS_POR_VUELTA * intervaloMs);

  // Guardamos los valores de referencia para calcular la próxima muestra.
  ultimaMuestraMs = ahoraMs;
  pulsosAnteriores = total;

  if (escalonPendiente) {
    // Una sola vez por ensayo, cambiamos a la posición de freno aplicado.
    // El PWM mantiene ese nivel. Las RPM se usan para medir la respuesta.
    escribirServo(APLICADO_US);
    frenoAplicado = true;
    escalonPendiente = false;
  }

  // Enviamos una fila del CSV.
  // t_s    = tiempo desde que se recibió 'i', en segundos
  // u      = orden al freno: 0 liberado, 1 aplicado
  // rpm    = velocidad media durante el intervalo que acaba de terminar
  // pulsos = contador acumulado desde que se encendió la ESP32
  Serial.printf("%.3f,%d,%.3f,%lu\n",
                (ahoraMs - inicioMs) / 1000.0,
                frenoAplicado ? 1 : 0,
                rpm,
                static_cast<unsigned long>(total));
}