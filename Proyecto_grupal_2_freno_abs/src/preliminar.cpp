const int SERVO_PIN = 18;
const int MOTOR_PWM = 17;
const int MOTOR_IN1 = 16;
const int MOTOR_IN2 = 15;
const int SENSOR_PIN = 4;

// Configuracion del disco
const int RANURAS = 36;

// Configuracion del motor
const int VELOCIDAD_PWM = 160; // 0 a 255
const unsigned long TIEMPO_MOTOR = 8000;

// Configuracion del servo
const int SERVO_ABIERTO = 180;
const int SERVO_CERRADO = 0;
const int PULSO_MIN = 700;
const int PULSO_MAX = 2300;

// Medicion RPM
const unsigned long INTERVALO_RPM = 500;

volatile uint32_t pulsos = 0;
portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;

unsigned long tiempoEstado = 0;
unsigned long ultimaMedicion = 0;

// Estados de la prueba
enum Estado {
  ABRIENDO,
  MOTOR_ACTIVO,
  FRENANDO
};

Estado estado = ABRIENDO;

// Interrupcion del H206
void IRAM_ATTR contarPulso() {
  portENTER_CRITICAL_ISR(&mux);
  pulsos++;
  portEXIT_CRITICAL_ISR(&mux);
}

// Control del servo
void moverServo(int angulo) {
  angulo = constrain(angulo, 0, 180);

  int pulso = map(angulo, 0, 180,
                  PULSO_MIN, PULSO_MAX);

  uint32_t duty = (pulso * 16384UL) / 20000UL;
  ledcWrite(SERVO_PIN, duty);
}

// Medir RPM
void medirRPM(unsigned long ahora) {
  unsigned long dt = ahora - ultimaMedicion;

  if (dt < INTERVALO_RPM) return;

  uint32_t cantidad;

  portENTER_CRITICAL(&mux);
  cantidad = pulsos;
  pulsos = 0;
  portEXIT_CRITICAL(&mux);

  ultimaMedicion = ahora;

  float rpm = (cantidad * 60000.0f) /
              (RANURAS * dt);

  Serial.print("Tiempo: ");
  Serial.print(ahora / 1000.0f, 2);

  Serial.print(" s | Pulsos: ");
  Serial.print(cantidad);

  Serial.print(" | RPM: ");
  Serial.print(rpm, 1);

  Serial.print(" | Estado: ");

  switch (estado) {
    case ABRIENDO:
      Serial.println("ABRIENDO");
      break;

    case MOTOR_ACTIVO:
      Serial.println("MOTOR ON");
      break;

    case FRENANDO:
      Serial.println("MOTOR OFF / FRENO");
      break;
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(MOTOR_IN1, OUTPUT);
  pinMode(MOTOR_IN2, OUTPUT);

  digitalWrite(MOTOR_IN1, LOW);
  digitalWrite(MOTOR_IN2, LOW);

  // PWM del motor: 20 kHz, 8 bits
  ledcAttach(MOTOR_PWM, 20000, 8);
  ledcWrite(MOTOR_PWM, 0);

  // PWM del servo: 50 Hz, 14 bits
  ledcAttach(SERVO_PIN, 50, 14);

  // Sensor H206
  pinMode(SENSOR_PIN, INPUT);
  attachInterrupt(
    digitalPinToInterrupt(SENSOR_PIN),
    contarPulso,
    FALLING
  );

  // Abrir el freno
  moverServo(SERVO_ABIERTO);

  Serial.println("=== PRUEBA DE DISCO ===");
  Serial.println("Abriendo servo...");

  tiempoEstado = millis();
  ultimaMedicion = millis();
}

void loop() {
  unsigned long ahora = millis();

  // Esperar 1 segundo para abrir el servo
  if (estado == ABRIENDO &&
      ahora - tiempoEstado >= 1000) {

    digitalWrite(MOTOR_IN1, HIGH);
    digitalWrite(MOTOR_IN2, LOW);

    ledcWrite(MOTOR_PWM, VELOCIDAD_PWM);

    estado = MOTOR_ACTIVO;
    tiempoEstado = ahora;

    Serial.println("MOTOR ENCENDIDO");
  }

  // Apagar motor despues de 8 segundos
  if (estado == MOTOR_ACTIVO &&
      ahora - tiempoEstado >= TIEMPO_MOTOR) {

    ledcWrite(MOTOR_PWM, 0);

    digitalWrite(MOTOR_IN1, LOW);
    digitalWrite(MOTOR_IN2, LOW);

    // Cerrar el freno inmediatamente
    moverServo(SERVO_CERRADO);

    estado = FRENANDO;

    Serial.println("MOTOR APAGADO");
    Serial.println("SERVO CERRADO");
  }

  // Medir RPM permanentemente
  medirRPM(ahora);
}