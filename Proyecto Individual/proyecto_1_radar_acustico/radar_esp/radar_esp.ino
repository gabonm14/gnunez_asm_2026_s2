#include <Arduino.h>
#include <math.h>
#include "esp_timer.h"

// ============================================================
// PINES
// ============================================================

const uint8_t MIC_PIN     = 1;    // Salida AUD del micrófono
const uint8_t SPEAKER_PIN = 17;   // Hacia filtro RC -> PAM8403

// ============================================================
// MUESTREO
// ============================================================

const uint32_t SAMPLE_RATE = 16000;   // Hz

// Captura total
const int CAPTURE_N = 4096;

// ============================================================
// CHIRP
// ============================================================

// 25 ms
const int CHIRP_MS = 25;

const int CHIRP_N =
    (SAMPLE_RATE * CHIRP_MS) / 1000;  // 400 muestras

const float F_START = 2000.0f;
const float F_END   = 6000.0f;

// ============================================================
// PWM PARA GENERAR AUDIO
// ============================================================

// PWM ultrasónico/inaudible que posteriormente se filtra
const uint32_t PWM_CARRIER = 125000;   // 125 kHz
const uint8_t PWM_BITS = 8;

// 8 bits -> 0 ... 255
const int PWM_CENTER = 128;

// Amplitud de modulación.
// 90 mantiene margen sin llegar a 0 ni 255.
const int PWM_AMPLITUDE = 90;

// ============================================================
// FFT
// ============================================================

const int FFT_N = 1024;

// ============================================================
// DETECCIÓN
// ============================================================

// Velocidad aproximada del sonido a ~20 °C
const float SOUND_SPEED = 343.0f;

// Rango que a buscar.
// Se puede modificar posteriormente.
const float MIN_DISTANCE_M = 0.20f;
const float MAX_DISTANCE_M = 3.00f;

// Umbral mínimo de correlación
const float MIN_ECHO_SCORE = 0.08f;

// Para reconocer la señal directa
const float MIN_DIRECT_SCORE = 0.08f;

// Corrección experimental.
// Inicialmente 0.
// Después calibra con una distancia conocida.
const float DISTANCE_OFFSET_M = 0.0f;

// ============================================================
// BUFFERS
// ============================================================

float chirpRef[CHIRP_N];

uint16_t adcBuffer[CAPTURE_N];

float fftReal[FFT_N];
float fftImag[FFT_N];

// ============================================================
// VARIABLES GLOBALES
// ============================================================

float adcMean = 0.0f;
float chirpEnergy = 0.0f;

// ============================================================
// ESTRUCTURA PARA PICOS DE CORRELACIÓN
// ============================================================

struct Peak {
  int lag;
  float score;
};


// ============================================================
// GENERAR CHIRP DE REFERENCIA
// ============================================================

void generateReferenceChirp() {

  float T =
      (float)(CHIRP_N - 1) / (float)SAMPLE_RATE;

  // Pendiente frecuencia / tiempo
  float k =
      (F_END - F_START) / T;

  chirpEnergy = 0.0f;

  for (int n = 0; n < CHIRP_N; n++) {

    float t =
        (float)n / (float)SAMPLE_RATE;

    // Fase de chirp lineal:
    //
    // phi(t) =
    // 2*pi*(f0*t + 0.5*k*t^2)

    float phase =
        TWO_PI *
        (F_START * t +
         0.5f * k * t * t);

    // Ventana Hann.
    //
    // Reduce clicks al iniciar/finalizar
    // y reduce lóbulos laterales de correlación.

    float window =
        0.5f -
        0.5f *
        cosf(
          TWO_PI *
          (float)n /
          (float)(CHIRP_N - 1)
        );

    chirpRef[n] =
        sinf(phase) * window;

    chirpEnergy +=
        chirpRef[n] *
        chirpRef[n];
  }
}


// ============================================================
// CAPTURA + TRANSMISIÓN SIMULTÁNEA
// ============================================================

void transmitAndCapture(
    uint32_t &lateSamples,
    uint64_t &elapsedUs) {

  lateSamples = 0;

  ledcWrite(
      SPEAKER_PIN,
      PWM_CENTER
  );

  delay(20);

  uint64_t startUs =
      esp_timer_get_time();

  for (int i = 0; i < CAPTURE_N; i++) {

    uint64_t targetUs =
        startUs +
        ((uint64_t)i * 1000000ULL)
        / SAMPLE_RATE;

    uint64_t now =
        esp_timer_get_time();

    // Espera hasta el instante de muestreo

    if (now < targetUs) {

      while (
          esp_timer_get_time()
          < targetUs
      ) {
        // espera activa
      }

    } else {


      if ((now - targetUs) > 10) {
        lateSamples++;
      }
    }

    // --------------------------------------------------------
    // GENERACIÓN DEL CHIRP
    // --------------------------------------------------------

    if (i < CHIRP_N) {

      int duty =
          PWM_CENTER +
          (int)(
            PWM_AMPLITUDE *
            chirpRef[i]
          );

      // Seguridad

      if (duty < 1)
        duty = 1;

      if (duty > 254)
        duty = 254;

      ledcWrite(
          SPEAKER_PIN,
          duty
      );

    } else if (i == CHIRP_N) {

      // Termina el chirp.
      ledcWrite(
          SPEAKER_PIN,
          PWM_CENTER
      );
    }

    // --------------------------------------------------------
    // ADC
    // --------------------------------------------------------

    adcBuffer[i] =
        analogRead(MIC_PIN);
  }

  ledcWrite(
      SPEAKER_PIN,
      PWM_CENTER
  );

  elapsedUs =
      esp_timer_get_time()
      - startUs;
}


// ============================================================
// ESTADÍSTICAS ADC
// ============================================================

void calculateADCStatistics(
    uint16_t &minimum,
    uint16_t &maximum) {

  minimum = 4095;
  maximum = 0;

  uint64_t sum = 0;

  for (int i = 0; i < CAPTURE_N; i++) {

    uint16_t x =
        adcBuffer[i];

    sum += x;

    if (x < minimum)
      minimum = x;

    if (x > maximum)
      maximum = x;
  }

  adcMean =
      (float)sum /
      (float)CAPTURE_N;
}


// ============================================================
// CORRELACIÓN NORMALIZADA
// ============================================================
//
// Compara:
//
// señal recibida:
//
//     x[lag+n]
//
// contra:
//
//     chirp[n]
//
// Resultado ideal:
//     cercano a 1
//
// Ruido:
//     cercano a 0
//
// ============================================================

float correlationScore(int lag) {

  double corr = 0.0;
  double signalEnergy = 0.0;

  for (int n = 0; n < CHIRP_N; n++) {

    float x =
        (float)adcBuffer[lag + n]
        - adcMean;

    float r =
        chirpRef[n];

    corr +=
        (double)x *
        (double)r;

    signalEnergy +=
        (double)x *
        (double)x;
  }

  if (signalEnergy < 1.0)
    return 0.0f;

  double denominator =
      sqrt(
        signalEnergy *
        chirpEnergy
      );

  float score =
      fabs(
        corr /
        denominator
      );

  return score;
}


// ============================================================
// BUSCAR MAYOR PICO
// ============================================================

Peak findPeak(
    int startLag,
    int endLag) {

  Peak result;

  result.lag = startLag;
  result.score = 0.0f;

  for (
      int lag = startLag;
      lag <= endLag;
      lag++
  ) {

    float score =
        correlationScore(lag);

    if (score > result.score) {

      result.score = score;
      result.lag = lag;
    }
  }

  return result;
}


float refinePeak(int lag) {

  int maxLag =
      CAPTURE_N -
      CHIRP_N -
      1;

  if (
      lag <= 0 ||
      lag >= maxLag
  ) {
    return (float)lag;
  }

  float ym =
      correlationScore(lag - 1);

  float y0 =
      correlationScore(lag);

  float yp =
      correlationScore(lag + 1);

  float denominator =
      ym -
      2.0f * y0 +
      yp;

  if (
      fabsf(denominator)
      < 0.000001f
  ) {
    return (float)lag;
  }

  float delta =
      0.5f *
      (ym - yp) /
      denominator;

  

  if (delta > 0.5f)
    delta = 0.5f;

  if (delta < -0.5f)
    delta = -0.5f;

  return
      (float)lag +
      delta;
}


// ============================================================
// FFT RADIX-2
// ============================================================

void fft(
    float *real,
    float *imag,
    int N) {

  // ----------------------------------------------------------
  // BIT REVERSAL
  // ----------------------------------------------------------

  int j = 0;

  for (int i = 1; i < N; i++) {

    int bit = N >> 1;

    while (j & bit) {

      j ^= bit;
      bit >>= 1;
    }

    j ^= bit;

    if (i < j) {

      float temp;

      temp = real[i];
      real[i] = real[j];
      real[j] = temp;

      temp = imag[i];
      imag[i] = imag[j];
      imag[j] = temp;
    }
  }

  // ----------------------------------------------------------
  // BUTTERFLIES
  // ----------------------------------------------------------


  for (
      int length = 2;
      length <= N;
      length <<= 1
  ) {

    float angle =
        -TWO_PI /
        (float)length;

    float wLenReal =
        cosf(angle);

    float wLenImag =
        sinf(angle);

    for (
        int i = 0;
        i < N;
        i += length
    ) {

      float wReal = 1.0f;
      float wImag = 0.0f;

      int half =
          length >> 1;

      for (
          int k = 0;
          k < half;
          k++
      ) {

        int even =
            i + k;

        int odd =
            i + k + half;

        float oddReal =
            real[odd] *
            wReal -
            imag[odd] *
            wImag;

        float oddImag =
            real[odd] *
            wImag +
            imag[odd] *
            wReal;

        float evenReal =
            real[even];

        float evenImag =
            imag[even];

        real[even] =
            evenReal +
            oddReal;

        imag[even] =
            evenImag +
            oddImag;

        real[odd] =
            evenReal -
            oddReal;

        imag[odd] =
            evenImag -
            oddImag;

        float nextWReal =
            wReal *
            wLenReal -
            wImag *
            wLenImag;

        float nextWImag =
            wReal *
            wLenImag +
            wImag *
            wLenReal;

        wReal = nextWReal;
        wImag = nextWImag;
      }
    }
  }
}


// ============================================================
// ANALISIS ESPECTRAL
// ============================================================

void analyzeFFT(
    float &peakFrequency,
    float &bandPercentage) {

  // primeras 1024 muestras.

  for (int i = 0; i < FFT_N; i++) {

    float sample =
        (float)adcBuffer[i]
        - adcMean;

    // Ventana Hann

    float window =
        0.5f -
        0.5f *
        cosf(
          TWO_PI *
          (float)i /
          (float)(FFT_N - 1)
        );

    fftReal[i] =
        sample *
        window;

    fftImag[i] =
        0.0f;
  }

  fft(
      fftReal,
      fftImag,
      FFT_N
  );

  float totalEnergy = 0.0f;
  float chirpBandEnergy = 0.0f;

  float largestMagnitude = 0.0f;

  peakFrequency = 0.0f;



  for (
      int bin = 1;
      bin < FFT_N / 2;
      bin++
  ) {

    float frequency =
        (float)bin *
        SAMPLE_RATE /
        FFT_N;

    float magnitudeSquared =
        fftReal[bin] *
        fftReal[bin] +
        fftImag[bin] *
        fftImag[bin];

    totalEnergy +=
        magnitudeSquared;

    if (
        frequency >= F_START &&
        frequency <= F_END
    ) {

      chirpBandEnergy +=
          magnitudeSquared;

      if (
          magnitudeSquared >
          largestMagnitude
      ) {

        largestMagnitude =
            magnitudeSquared;

        peakFrequency =
            frequency;
      }
    }
  }

  if (totalEnergy > 0.0f) {

    bandPercentage =
        100.0f *
        chirpBandEnergy /
        totalEnergy;

  } else {

    bandPercentage = 0.0f;
  }
}


// ============================================================
// ESTIMAR PISO DE CORRELACIÓN
// ============================================================

void correlationStatistics(
    int startLag,
    int endLag,
    float &mean,
    float &stdDev) {

  double sum = 0.0;
  double sumSquared = 0.0;

  int count = 0;

  for (
      int lag = startLag;
      lag <= endLag;
      lag++
  ) {

    float value =
        correlationScore(lag);

    sum += value;

    sumSquared +=
        value * value;

    count++;
  }

  if (count == 0) {

    mean = 0.0f;
    stdDev = 0.0f;

    return;
  }

  mean =
      sum /
      count;

  float variance =
      (sumSquared / count) -
      mean * mean;

  if (variance < 0)
    variance = 0;

  stdDev =
      sqrtf(variance);
}


// ============================================================
// MEDICIÓN COMPLETA
// ============================================================

void measureDistance() {

  Serial0.println();
  Serial0.println(
      "========================================"
  );

  Serial0.println(
      "NUEVA MEDICION"
  );

  Serial0.println(
      "========================================"
  );

  // ----------------------------------------------------------
  // 1. TRANSMITIR + CAPTURAR
  // ----------------------------------------------------------

  uint32_t lateSamples;
  uint64_t elapsedUs;

  transmitAndCapture(
      lateSamples,
      elapsedUs
  );

  // ----------------------------------------------------------
  // 2. ADC
  // ----------------------------------------------------------

  uint16_t adcMin;
  uint16_t adcMax;

  calculateADCStatistics(
      adcMin,
      adcMax
  );

  Serial0.print("ADC medio: ");
  Serial0.println(adcMean, 1);

  Serial0.print("ADC min: ");
  Serial0.println(adcMin);

  Serial0.print("ADC max: ");
  Serial0.println(adcMax);

  Serial0.print("ADC P-P: ");
  Serial0.println(
      adcMax - adcMin
  );

  Serial0.print(
      "Muestras retrasadas: "
  );

  Serial0.print(lateSamples);

  Serial0.print(" / ");

  Serial0.println(CAPTURE_N);

  float effectiveSampleRate =
      ((float)CAPTURE_N *
       1000000.0f) /
      (float)elapsedUs;

  Serial0.print(
      "Fs efectiva aprox: "
  );

  Serial0.print(
      effectiveSampleRate,
      1
  );

  Serial0.println(" Hz");

  // ----------------------------------------------------------
  // 3. FFT
  // ----------------------------------------------------------

  float peakFrequency;
  float bandPercentage;

  analyzeFFT(
      peakFrequency,
      bandPercentage
  );

  Serial0.println();
  Serial0.println(
      "--- FFT ---"
  );

  Serial0.print(
      "Pico dentro de 2-6 kHz: "
  );

  Serial0.print(
      peakFrequency,
      1
  );

  Serial0.println(" Hz");

  Serial0.print(
      "Energia dentro de banda chirp: "
  );

  Serial0.print(
      bandPercentage,
      1
  );

  Serial0.println(" %");

  // ----------------------------------------------------------
  // 4. CORRELACIÓN
  // ----------------------------------------------------------

  int maxCorrelationLag =
      CAPTURE_N -
      CHIRP_N -
      1;

  // La señal directa debería aparecer
  // durante los primeros ~10 ms.

  int directSearchEnd =
      (int)(
        0.010f *
        SAMPLE_RATE
      );

  if (
      directSearchEnd >
      maxCorrelationLag
  ) {
    directSearchEnd =
        maxCorrelationLag;
  }

  Peak directPeak =
      findPeak(
        0,
        directSearchEnd
      );

  Serial0.println();
  Serial0.println(
      "--- CORRELACION ---"
  );

  Serial0.print(
      "Pico directo lag: "
  );

  Serial0.print(
      directPeak.lag
  );

  Serial0.print(
      " muestras, score: "
  );

  Serial0.println(
      directPeak.score,
      4
  );

  if (
      directPeak.score <
      MIN_DIRECT_SCORE
  ) {

    Serial0.println();
    Serial0.println(
      "ADVERTENCIA:"
    );

    Serial0.println(
      "No se detecto claramente el chirp directo."
    );

    Serial0.println(
      "Revise volumen, microfono o saturacion."
    );

    return;
  }

  // ----------------------------------------------------------
  // 5. RANGO DE BÚSQUEDA DEL ECO
  // ----------------------------------------------------------

  int minimumDelaySamples =
      (int)ceilf(
        (
          2.0f *
          MIN_DISTANCE_M /
          SOUND_SPEED
        ) *
        SAMPLE_RATE
      );

  int maximumDelaySamples =
      (int)floorf(
        (
          2.0f *
          MAX_DISTANCE_M /
          SOUND_SPEED
        ) *
        SAMPLE_RATE
      );

  int echoStart =
      directPeak.lag +
      minimumDelaySamples;

  int echoEnd =
      directPeak.lag +
      maximumDelaySamples;

  if (echoStart < 0)
    echoStart = 0;

  if (
      echoEnd >
      maxCorrelationLag
  ) {
    echoEnd =
        maxCorrelationLag;
  }

  if (
      echoStart >= echoEnd
  ) {

    Serial0.println(
      "ERROR: ventana de eco invalida."
    );

    return;
  }

  // ----------------------------------------------------------
  // 6. PISO DE RUIDO DE CORRELACIÓN
  // ----------------------------------------------------------

  float corrMean;
  float corrStd;

  correlationStatistics(
      echoStart,
      echoEnd,
      corrMean,
      corrStd
  );

  // Umbral adaptativo

  float adaptiveThreshold =
      corrMean +
      3.0f *
      corrStd;

  if (
      adaptiveThreshold <
      MIN_ECHO_SCORE
  ) {

    adaptiveThreshold =
        MIN_ECHO_SCORE;
  }

  // ----------------------------------------------------------
  // 7. ECO
  // ----------------------------------------------------------

  Peak echoPeak =
      findPeak(
        echoStart,
        echoEnd
      );

  Serial0.print(
      "Pico eco lag: "
  );

  Serial0.print(
      echoPeak.lag
  );

  Serial0.print(
      " muestras, score: "
  );

  Serial0.println(
      echoPeak.score,
      4
  );

  Serial0.print(
      "Umbral adaptativo: "
  );

  Serial0.println(
      adaptiveThreshold,
      4
  );

  if (
      echoPeak.score <
      adaptiveThreshold
  ) {

    Serial0.println();
    Serial0.println(
      "No se detecto un eco suficientemente confiable."
    );

    return;
  }

  // ----------------------------------------------------------
  // 8. INTERPOLACIÓN SUB-MUESTRA
  // ----------------------------------------------------------

  float directLag =
      refinePeak(
        directPeak.lag
      );

  float echoLag =
      refinePeak(
        echoPeak.lag
      );

  float delaySamples =
      echoLag -
      directLag;

  // ----------------------------------------------------------
  // 9. TIEMPO DE VUELO
  // ----------------------------------------------------------

  float timeOfFlight =
      delaySamples /
      SAMPLE_RATE;

  // ----------------------------------------------------------
  // 10. DISTANCIA
  // ----------------------------------------------------------

  float distance =
      (
        SOUND_SPEED *
        timeOfFlight
      ) /
      2.0f;

  distance +=
      DISTANCE_OFFSET_M;

  // ----------------------------------------------------------
  // RESULTADO
  // ----------------------------------------------------------

  Serial0.println();

  Serial0.println(
      "========== RESULTADO =========="
  );

  Serial0.print(
      "Retardo: "
  );

  Serial0.print(
      delaySamples,
      3
  );

  Serial0.println(
      " muestras"
  );

  Serial0.print(
      "Tiempo de vuelo: "
  );

  Serial0.print(
      timeOfFlight *
      1000.0f,
      3
  );

  Serial0.println(
      " ms"
  );

  Serial0.print(
      "DISTANCIA: "
  );

  Serial0.print(
      distance *
      100.0f,
      1
  );

  Serial0.println(
      " cm"
  );

  Serial0.println(
      "==============================="
  );
}


// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial0.begin(115200);

  delay(1500);

  Serial0.println();
  Serial0.println(
      "Radar acustico ESP32-S3"
  );

  // ----------------------------------------------------------
  // ADC
  // ----------------------------------------------------------

  analogReadResolution(12);

  // Permite medir prácticamente
  // todo el rango de 3.3 V.

  analogSetPinAttenuation(
      MIC_PIN,
      ADC_11db
  );

  // ----------------------------------------------------------
  // PWM
  // ----------------------------------------------------------

  bool pwmOK =
      ledcAttach(
        SPEAKER_PIN,
        PWM_CARRIER,
        PWM_BITS
      );

  if (!pwmOK) {

    Serial0.println(
      "ERROR configurando LEDC."
    );

    while (true) {
      delay(1000);
    }
  }

  ledcWrite(
      SPEAKER_PIN,
      PWM_CENTER
  );

  // ----------------------------------------------------------
  // CHIRP
  // ----------------------------------------------------------

  generateReferenceChirp();

  Serial0.println(
      "Configuracion:"
  );

  Serial0.print(
      "Fs = "
  );

  Serial0.print(
      SAMPLE_RATE
  );

  Serial0.println(
      " Hz"
  );

  Serial0.print(
      "Chirp = "
  );

  Serial0.print(
      F_START,
      0
  );

  Serial0.print(
      " -> "
  );

  Serial0.print(
      F_END,
      0
  );

  Serial0.println(
      " Hz"
  );

  Serial0.print(
      "Duracion chirp = "
  );

  Serial0.print(
      CHIRP_MS
  );

  Serial0.println(
      " ms"
  );

  Serial0.print(
      "Muestras chirp = "
  );

  Serial0.println(
      CHIRP_N
  );

  Serial0.println();
  Serial0.println(
      "Sistema listo."
  );
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  measureDistance();

  // Una nueva medición cada 1.5 segundos.

  delay(1500);
}