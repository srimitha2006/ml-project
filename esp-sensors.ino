#include "DHTesp.h"
#define BUZZER_PIN    25
#define LED_PIN       26
#define DHT_PIN       27

#define TEMP_LIMIT    35.0   // °C: siren starts at or above this
#define TEMP_RESET    34.0   // °C: siren stops below this

#define PERSON_HZ     2700   // steady buzz for person
#define SIREN_HIGH_HZ 3200   // two-tone siren for high temperature
#define SIREN_LOW_HZ  2200
#define SIREN_STEP_MS 300
#define DHT_READ_MS   2000

DHTesp dht;

String command = "";
bool personAlarm = false;
bool tempAlarm = false;
int currentHz = 0;
bool sirenHigh = false;
unsigned long lastSirenStep = 0;
unsigned long lastDhtRead = 0;

void setTone(int hz) {
  if (hz == currentHz) return;
  currentHz = hz;
  if (hz == 0) {
    noTone(BUZZER_PIN);
    digitalWrite(BUZZER_PIN, LOW);
  } else {
    tone(BUZZER_PIN, hz);
  }
}

void readCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      command.trim();
      if (command == "ALERT") {
        personAlarm = true;
        Serial.println("PERSON ON");
      } else if (command == "CLEAR") {
        personAlarm = false;
        Serial.println("PERSON OFF");
      }
      command = "";
    } else {
      command += c;
      if (command.length() > 32) command = "";
    }
  }
}

void readDht() {
  if (millis() - lastDhtRead < DHT_READ_MS) return;
  lastDhtRead = millis();

  TempAndHumidity v = dht.getTempAndHumidity();
  float t = v.temperature;
  float h = v.humidity;

  // DHT11 range is 0-50 °C, 20-90 %RH; anything else is a bad read
  if (dht.getStatus() != DHTesp::ERROR_NONE || isnan(t) || isnan(h) ||
      t < 1 || t > 55 || h < 20 || h > 95) {
    Serial.printf("DHT ERROR %s (t=%.1f h=%.1f model=%d)\n",
                  dht.getStatusString(), t, h, dht.getModel());
    return;
  }

  if (!tempAlarm && t >= TEMP_LIMIT) tempAlarm = true;
  else if (tempAlarm && t < TEMP_RESET) tempAlarm = false;

  Serial.printf("TEMP %.1f HUM %.0f ALARM %d\n", t, h, tempAlarm ? 1 : 0);
}


void updateOutputs() {
  if (tempAlarm) {
    // High temperature: two-tone siren + LED blinking in step
    if (millis() - lastSirenStep >= SIREN_STEP_MS) {
      lastSirenStep = millis();
      sirenHigh = !sirenHigh;
    }
    setTone(sirenHigh ? SIREN_HIGH_HZ : SIREN_LOW_HZ);
    digitalWrite(LED_PIN, sirenHigh ? HIGH : LOW);
  } else if (personAlarm) {
    // Person: steady buzz + LED solid ON
    setTone(PERSON_HZ);
    digitalWrite(LED_PIN, HIGH);
  } else {
    setTone(0);
    digitalWrite(LED_PIN, LOW);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(LED_PIN, LOW);
  dht.setup(DHT_PIN, DHTesp::DHT11);   // AUTO_DETECT misreads DHT11 as DHT22
  Serial.println("SentinelX ESP32 Ready");
}

void loop() {
  readCommands();
  readDht();
  updateOutputs();
}
