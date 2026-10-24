/*
  Solar Monitor - ESP32 sender
  Device: __DEVICE_NAME__

  Reads panel voltage and current and posts them to your Solar Monitor server
  every few seconds. The server address and API key below were filled in for
  you when you downloaded this sketch from the Devices page.

  Before you upload, in order:
    1. Enter your Wi-Fi name and password (section 1).
    2. Check the sensor section (section 3) against YOUR wiring.
    3. Open the Serial Monitor at 115200 baud to watch it work.

  Needs the "esp32" board package (Arduino IDE > Boards Manager).
  No extra libraries are required.

  IMPORTANT - NOT TESTED ON YOUR HARDWARE. This was written without access to
  your sensors. Verify the numbers it prints against a multimeter before you
  trust them, and adjust the calibration values in section 3.
*/

#include <WiFi.h>
#include <HTTPClient.h>

// ===== 1. Wi-Fi (edit these two lines) =======================================
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// ===== 2. Filled in by the Solar Monitor app (leave as is) ===================
const char* SERVER_URL = "__SERVER_URL__/api/ingest";
const char* API_KEY    = "__API_KEY__";
const char* FIRMWARE   = "1.0.0";
// Starting interval. The server can change it from the Devices page and the
// ESP32 picks the new value up automatically after its next reading.
unsigned long sendIntervalMs = __INTERVAL__ * 1000UL;

// ===== 3. Sensors - CHECK EVERY LINE AGAINST YOUR WIRING =====================
//
// Use ADC1 pins only: 32, 33, 34, 35, 36 or 39. The other ADC (ADC2) stops
// working while Wi-Fi is on.
const int VOLTAGE_PIN = 34;
const int CURRENT_PIN = 35;

// --- Voltage: a resistor divider ---
//      panel +  --- R1 ---+--- R2 --- GND
//                         |
//                    VOLTAGE_PIN
//
// !! An ESP32 pin must NEVER see more than 3.3 V or it can be damaged. !!
// Divider ratio = (R1 + R2) / R2. Choose it so your panel's HIGHEST voltage
// (open-circuit, in full sun) divided by the ratio is below about 3.0 V.
//   Example: an "18 V" panel can reach ~22 V, so the ratio must be at least
//   22 / 3.0 = 7.3. R1 = 100k and R2 = 15k gives 7.67 -> 22 V becomes 2.9 V.
const float R1_OHMS = 100000.0;
const float R2_OHMS = 15000.0;

// --- Current: ACS712 5 A module powered from 5 V ---
// Its output is 2.5 V at 0 A and changes 0.185 V per amp (use 0.100 for the
// 20 A version, 0.066 for the 30 A version). That output can reach 5 V, which
// is too much for the ESP32, so divide it down first and tell the sketch the
// ratio: 10k on top and 20k to ground divides by 1.5.
const float CURRENT_ZERO_V  = 2.5;
const float CURRENT_V_PER_A = 0.185;
const float CURRENT_DIVIDER = 1.5;

// --- Calibration: compare with a multimeter, then adjust ---
const float VOLTAGE_SCALE    = 1.00;   // multiply voltage by this
const float CURRENT_OFFSET_A = 0.00;   // subtract this at 0 A (sensor offset)

// ===== Code ==================================================================

float readPinVolts(int pin) {
  // Average many samples: the ESP32's ADC is noisy.
  const int SAMPLES = 32;
  unsigned long total = 0;
  for (int i = 0; i < SAMPLES; i++) {
    total += analogReadMilliVolts(pin);
    delayMicroseconds(200);
  }
  return (total / (float)SAMPLES) / 1000.0;
}

float readVoltage() {
  float pinVolts = readPinVolts(VOLTAGE_PIN);
  return pinVolts * ((R1_OHMS + R2_OHMS) / R2_OHMS) * VOLTAGE_SCALE;
}

float readCurrent() {
  float sensorVolts = readPinVolts(CURRENT_PIN) * CURRENT_DIVIDER;
  float amps = (sensorVolts - CURRENT_ZERO_V) / CURRENT_V_PER_A - CURRENT_OFFSET_A;
  return amps < 0 ? 0 : amps;           // tiny negative values are just noise
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("Connecting to Wi-Fi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 20000) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(" connected, IP ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println(" failed, will retry");
  }
}

// Returns true if the server accepted the reading.
bool sendReading(float voltage, float current) {
  if (WiFi.status() != WL_CONNECTED) return false;

  char body[200];
  snprintf(body, sizeof(body),
           "{\"voltage\":%.3f,\"current\":%.3f,\"firmware\":\"%s\",\"rssi\":%d,\"uptime_s\":%lu}",
           voltage, current, FIRMWARE, WiFi.RSSI(), millis() / 1000UL);

  HTTPClient http;
  http.setTimeout(5000);
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  int code = http.POST(String(body));

  if (code == 200) {
    // The reply includes {"config": {"sample_interval_s": N}}. Find the number
    // after the key, whether or not the server added spaces.
    String reply = http.getString();
    int key = reply.indexOf("\"sample_interval_s\"");
    if (key >= 0) {
      int colon = reply.indexOf(':', key);
      long seconds = reply.substring(colon + 1).toInt();
      if (seconds >= 1 && seconds <= 300) sendIntervalMs = (unsigned long)seconds * 1000UL;
    }
  } else if (code == 401) {
    Serial.println("The server rejected the API key. Download a fresh sketch from the Devices page.");
  } else if (code == 403) {
    Serial.println("The server says this device is disabled. Enable it on the Devices page.");
  } else if (code == 400) {
    Serial.println("The server rejected the numbers: " + http.getString());
  } else {
    Serial.printf("Could not reach the server (code %d). Is the address right and the server running?\n", code);
  }
  http.end();
  return code == 200;
}

unsigned long lastSend = 0;
bool firstSend = true;

void setup() {
  Serial.begin(115200);
  delay(500);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);       // lets the pin read up to ~3.1 V
  Serial.println("\nSolar Monitor sender starting");
  connectWiFi();
}

void loop() {
  connectWiFi();                        // does nothing if already connected

  if (firstSend || millis() - lastSend >= sendIntervalMs) {
    firstSend = false;
    lastSend = millis();

    float voltage = readVoltage();
    float current = readCurrent();
    bool ok = sendReading(voltage, current);
    Serial.printf("%.2f V  %.3f A  %.2f W  -> %s\n", voltage, current, voltage * current,
                  ok ? "sent" : "NOT sent");
  }
  delay(50);
}
