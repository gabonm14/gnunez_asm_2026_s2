#include <Arduino.h>

// Pines del montaje actual.
const int SERVO_PIN = 18;
const int MOTOR_PWM = 17;
const int MOTOR_IN1 = 16;
const int MOTOR_IN2 = 15;
const int SENSOR_PIN = 4;

// Configuración del disco y del motor.
const int RANURAS = 36;
const int VELOCIDAD_PWM = 160;  // Escala de 0 a 255.

// Posiciones calibradas del servo y sus límites de pulso.
const int SERVO_ABIERTO = 180;
const int SERVO_CERRADO = 0;
const int PULSO_MIN = 700;
const int PULSO_MAX = 2300;

// Todos los tiempos están en milisegundos.
const unsigned long TIEMPO_APERTURA = 1000;
const unsigned long TIEMPO_MOTOR = 8000;
const unsigned long TIEMPO_REGISTRO_FINAL = 8000;
const unsigned long TIEMPO_SERVO_CERRADO = 1000;
const unsigned long INTERVALO_RPM = 500;

enum Prueba {
  NINGUNA,
  MOTOR_CON_FRENO,
  MOTOR_SIN_FRENO,
  SOLO_FRENO
};

enum Estado {
  ESPERANDO,
  ABRIENDO,
  MOTOR_ACTIVO,
  FRENANDO,
  GIRO_LIBRE,
  FRENO_CERRADO
};

Prueba pruebaActual = NINGUNA;
Estado estado = ESPERANDO;
bool pwmListo = false;

volatile uint32_t pulsos = 0;
portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;

unsigned long inicioPrueba = 0;
unsigned long tiempoEstado = 0;
unsigned long ultimaMedicion = 0;

// La interrupción cuenta un flanco descendente por cada pulso del H206.
void IRAM_ATTR contarPulso() {
  portENTER_CRITICAL_ISR(&mux);
  ++pulsos;
  portEXIT_CRITICAL_ISR(&mux);
}

// Lee y reinicia el contador en una sola sección crítica. Así, cada
// muestra de RPM usa únicamente los pulsos del intervalo que acaba de pasar.
uint32_t tomarPulsos() {
  portENTER_CRITICAL(&mux);
  const uint32_t cantidad = pulsos;
  pulsos = 0;
  portEXIT_CRITICAL(&mux);
  return cantidad;
}

// Convierte el ángulo en ancho de pulso y luego en duty del PWM.
// A 50 Hz, cada período del servo dura 20 000 microsegundos.
void moverServo(int angulo) {
  angulo = constrain(angulo, 0, 180);
  const int pulso = map(angulo, 0, 180, PULSO_MIN, PULSO_MAX);
  const uint32_t duty = (pulso * 16384UL) / 20000UL;
  ledcWrite(SERVO_PIN, duty);
}

// Conserva el sentido de giro y el PWM del código original.
void encenderMotor() {
  digitalWrite(MOTOR_IN1, HIGH);
  digitalWrite(MOTOR_IN2, LOW);
  ledcWrite(MOTOR_PWM, VELOCIDAD_PWM);
}

// Quita el PWM y deja ambas entradas del driver en LOW.
void apagarMotor() {
  ledcWrite(MOTOR_PWM, 0);
  digitalWrite(MOTOR_IN1, LOW);
  digitalWrite(MOTOR_IN2, LOW);
}

// Devuelve el nombre que se imprime junto con cada medición.
const char* nombreEstado() {
  switch (estado) {
    case ABRIENDO:       return "ABRIENDO";
    case MOTOR_ACTIVO:   return "MOTOR ON";
    case FRENANDO:       return "MOTOR OFF / FRENO";
    case GIRO_LIBRE:     return "MOTOR OFF / FRENO ABIERTO";
    case FRENO_CERRADO:  return "FRENO CERRADO";
    case ESPERANDO:      return "ESPERANDO";
  }
  return "DESCONOCIDO";
}

// Registra un evento con su tiempo relativo al inicio de la prueba.
// Estas líneas marcan las órdenes al motor y al servo.
void registrarEvento(unsigned long ahora, const char* mensaje) {
  Serial.printf("%.3f s | EVENTO | %s\n",
                (ahora - inicioPrueba) / 1000.0,
                mensaje);
}

// Calcula la velocidad media usando el tiempo real de la ventana.
void medirRPM(unsigned long ahora) {
  const unsigned long dt = ahora - ultimaMedicion;
  if (dt < INTERVALO_RPM) return;

  const uint32_t cantidad = tomarPulsos();
  ultimaMedicion = ahora;

  const float rpm = (cantidad * 60000.0f) / (RANURAS * dt);

  Serial.printf("Tiempo: %.3f s | Pulsos: %lu | RPM: %.1f | Estado: %s\n",
                (ahora - inicioPrueba) / 1000.0,
                static_cast<unsigned long>(cantidad),
                rpm,
                nombreEstado());
}

void mostrarMenu() {
  Serial.println("Enviar b: motor con freno");
  Serial.println("Enviar m: motor sin freno");
  Serial.println("Enviar f: solo abrir y cerrar el freno");
}

// Cada ensayo comienza con el motor apagado y el freno abierto.
// También reinicia el reloj y descarta los pulsos de la prueba anterior.
void iniciarPrueba(Prueba prueba, unsigned long ahora) {
  apagarMotor();
  moverServo(SERVO_ABIERTO);
  tomarPulsos();

  pruebaActual = prueba;
  estado = ABRIENDO;
  inicioPrueba = ahora;
  tiempoEstado = ahora;
  ultimaMedicion = ahora;

  registrarEvento(ahora, "INICIO / FRENO ABIERTO");
}

// Termina el registro y espera otro comando. El servo conserva
// la última posición de la prueba hasta el próximo comando.
void terminarPrueba(unsigned long ahora) {
  apagarMotor();
  registrarEvento(ahora, "FIN DE PRUEBA");
  pruebaActual = NINGUNA;
  estado = ESPERANDO;
  mostrarMenu();
}

void setup() {
  Serial.begin(115200);

  pinMode(MOTOR_IN1, OUTPUT);
  pinMode(MOTOR_IN2, OUTPUT);
  digitalWrite(MOTOR_IN1, LOW);
  digitalWrite(MOTOR_IN2, LOW);

  // Configura el PWM del motor antes de permitir cualquier prueba.
  if (!ledcAttach(MOTOR_PWM, 20000, 8)) {
    Serial.println("Error al configurar el PWM del motor.");
    return;
  }
  apagarMotor();

  if (!ledcAttach(SERVO_PIN, 50, 14)) {
    Serial.println("Error al configurar el PWM del servo.");
    return;
  }

  pinMode(SENSOR_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(SENSOR_PIN), contarPulso, FALLING);

  moverServo(SERVO_ABIERTO);
  pwmListo = true;
  mostrarMenu();
}

void loop() {
  if (!pwmListo) return;

  // Los comandos se aceptan cuando la ESP32 está esperando.
  // Los saltos de línea del Monitor Serie se ignoran.
  while (Serial.available() > 0) {
    const char comando = Serial.read();
    if (estado != ESPERANDO) continue;

    switch (comando) {
      case 'b':
        iniciarPrueba(MOTOR_CON_FRENO, millis());
        break;
      case 'm':
        iniciarPrueba(MOTOR_SIN_FRENO, millis());
        break;
      case 'f':
        iniciarPrueba(SOLO_FRENO, millis());
        break;
    }
  }

  if (estado == ESPERANDO) return;

  const unsigned long ahora = millis();
  const unsigned long transcurrido = ahora - tiempoEstado;

  // Registramos la velocidad antes de cambiar las órdenes si justo
  // vence el intervalo de medición. El evento marca la transición.
  medirRPM(ahora);

  switch (estado) {
    case ABRIENDO:
      if (transcurrido < TIEMPO_APERTURA) break;

      tiempoEstado = ahora;
      if (pruebaActual == SOLO_FRENO) {
        moverServo(SERVO_CERRADO);
        estado = FRENO_CERRADO;
        registrarEvento(ahora, "FRENO CERRADO");
      } else {
        encenderMotor();
        estado = MOTOR_ACTIVO;
        registrarEvento(ahora, "MOTOR ENCENDIDO");
      }
      break;

    case MOTOR_ACTIVO:
      if (transcurrido < TIEMPO_MOTOR) break;

      apagarMotor();
      tiempoEstado = ahora;

      if (pruebaActual == MOTOR_CON_FRENO) {
        moverServo(SERVO_CERRADO);
        estado = FRENANDO;
        registrarEvento(ahora, "MOTOR APAGADO / FRENO CERRADO");
      } else {
        estado = GIRO_LIBRE;
        registrarEvento(ahora, "MOTOR APAGADO / FRENO ABIERTO");
      }
      break;

    case FRENANDO:
    case GIRO_LIBRE:
      if (transcurrido >= TIEMPO_REGISTRO_FINAL) {
        terminarPrueba(ahora);
      }
      break;

    case FRENO_CERRADO:
      if (transcurrido >= TIEMPO_SERVO_CERRADO) {
        terminarPrueba(ahora);
      }
      break;

    case ESPERANDO:
      break;
  }
}