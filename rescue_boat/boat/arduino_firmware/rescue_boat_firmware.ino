/*
 * rescue_boat_firmware.ino
 * ─────────────────────────────────────────────────────────────────────────
 * Arduino UNO Q — STM32 MCU side
 *
 * Motor driver : HL-51 V1.0 Relay Module (ON/OFF only — fixed RPM)
 * Power source : Arduino UNO Q board 5V pin (no external battery)
 *
 * Pin layout:
 *   D4  — HL-51 In1  (LOW = relay ON = motor runs)
 *   D9  — Steering Servo  (50°=left | 90°=straight | 130°=right)
 *   D10 — Supply Drop Servo (0°=closed | 90°=open/drop)
 *
 * HL-51 V1.0 wiring:
 *
 *   [ Control side ]
 *   Arduino 5V  ──► Relay Vcc
 *   Arduino GND ──► Relay Gnd
 *   Arduino D4  ──► Relay In1   (LOW = relay ON, HIGH = relay OFF)
 *
 *   [ Load side — use NO so motor is OFF by default ]
 *   Arduino 5V  ──► Relay COM
 *   Relay NO    ──► DC Motor (+)   ← circuit closes when relay fires
 *   DC Motor (-)──► Arduino GND
 *   (NC terminal — leave unconnected)
 *
 * NOTE: Arduino 5V pin supplies ~400 mA max.
 *       Use a small DC motor that draws < 300 mA to stay safe.
 *       If the board resets under load, use the VIN pin instead
 *       (requires a 7–12 V power adapter plugged into the barrel jack).
 *
 * Commands received from Linux MPU (newline-terminated JSON):
 *   {"cmd":"drive","steering":90}   ← motor ON, set steering angle
 *   {"cmd":"stop"}                  ← motor OFF, servo to center
 *   {"cmd":"drop_supply"}           ← stop motor, open supply hatch
 *
 * Telemetry sent back every 500 ms:
 *   {"motor":true,"steer":90,"cmd":"drive"}
 * ─────────────────────────────────────────────────────────────────────────
 */

#include <Servo.h>
#include <ArduinoJson.h>   // ArduinoJson by Benoit Blanchon v7+

// ── Pin definitions ────────────────────────────────────────────────────────
const int PIN_RELAY        = 4;    // HL-51 relay IN pin
const int PIN_STEER_SERVO  = 9;    // Steering servo signal
const int PIN_SUPPLY_SERVO = 10;   // Supply drop servo signal

// ── HL-51 relay logic (active-LOW: LOW = relay energised = motor ON) ───────
const int RELAY_ON  = LOW;
const int RELAY_OFF = HIGH;

// ── Servo objects ──────────────────────────────────────────────────────────
Servo steerServo;
Servo supplyServo;

// ── Steering angle limits ──────────────────────────────────────────────────
const int STEER_LEFT    = 50;
const int STEER_CENTER  = 90;
const int STEER_RIGHT   = 130;

// ── Supply drop config ─────────────────────────────────────────────────────
const int SUPPLY_CLOSED = 0;
const int SUPPLY_OPEN   = 90;
const int SUPPLY_HOLD_MS = 2000;   // hold open 2 s then close

// ── State ──────────────────────────────────────────────────────────────────
bool   motorRunning   = false;
int    currentSteering = STEER_CENTER;
String currentCmd      = "stop";

// ── Serial receive buffer ──────────────────────────────────────────────────
String serialBuffer = "";

// ── Telemetry timer ────────────────────────────────────────────────────────
unsigned long lastTelemetry      = 0;
const unsigned long TELEMETRY_MS = 500;

// ─────────────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);

  // Relay pin — HIGH by default so motor starts OFF
  pinMode(PIN_RELAY, OUTPUT);
  digitalWrite(PIN_RELAY, RELAY_OFF);

  // Servos
  steerServo.attach(PIN_STEER_SERVO);
  supplyServo.attach(PIN_SUPPLY_SERVO);
  steerServo.write(STEER_CENTER);
  supplyServo.write(SUPPLY_CLOSED);

  Serial.println("{\"status\":\"ready\",\"msg\":\"Rescue Boat MCU online — HL-51 relay mode\"}");
}

// ─────────────────────────────────────────────────────────────────────────────
void loop() {
  // ── Read serial line from Linux MPU ───────────────────────────────────
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (serialBuffer.length() > 0) {
        processCommand(serialBuffer);
        serialBuffer = "";
      }
    } else {
      serialBuffer += c;
      if (serialBuffer.length() > 256) serialBuffer = "";  // overflow guard
    }
  }

  // ── Send telemetry periodically ────────────────────────────────────────
  if (millis() - lastTelemetry >= TELEMETRY_MS) {
    sendTelemetry();
    lastTelemetry = millis();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
void processCommand(const String& json) {
  StaticJsonDocument<128> doc;
  DeserializationError err = deserializeJson(doc, json);
  if (err) {
    Serial.print("{\"error\":\"json_parse\",\"detail\":\"");
    Serial.print(err.c_str());
    Serial.println("\"}");
    return;
  }

  const char* cmd = doc["cmd"] | "unknown";
  currentCmd = String(cmd);

  if (strcmp(cmd, "drive") == 0) {
    int steering = doc["steering"] | STEER_CENTER;
    cmdDrive(steering);

  } else if (strcmp(cmd, "stop") == 0) {
    cmdStop();

  } else if (strcmp(cmd, "drop_supply") == 0) {
    cmdDropSupply();

  } else {
    Serial.print("{\"warn\":\"unknown_cmd\",\"cmd\":\"");
    Serial.print(cmd);
    Serial.println("\"}");
  }
}

// ── Drive — relay ON at fixed RPM, set steering angle ─────────────────────
void cmdDrive(int steering) {
  currentSteering = constrain(steering, STEER_LEFT, STEER_RIGHT);
  steerServo.write(currentSteering);
  digitalWrite(PIN_RELAY, RELAY_ON);   // motor ON (full speed from battery)
  motorRunning = true;
}

// ── Stop — relay OFF, servo back to center ─────────────────────────────────
void cmdStop() {
  digitalWrite(PIN_RELAY, RELAY_OFF);  // motor OFF
  steerServo.write(STEER_CENTER);
  currentSteering = STEER_CENTER;
  motorRunning = false;
}

// ── Supply drop — stop first, open hatch, wait, close hatch ───────────────
void cmdDropSupply() {
  cmdStop();
  delay(300);

  supplyServo.write(SUPPLY_OPEN);
  Serial.println("{\"event\":\"supply_drop\",\"state\":\"open\"}");
  delay(SUPPLY_HOLD_MS);

  supplyServo.write(SUPPLY_CLOSED);
  Serial.println("{\"event\":\"supply_drop\",\"state\":\"closed\"}");
}

// ── Telemetry ──────────────────────────────────────────────────────────────
void sendTelemetry() {
  Serial.print("{\"motor\":");
  Serial.print(motorRunning ? "true" : "false");
  Serial.print(",\"steer\":");
  Serial.print(currentSteering);
  Serial.print(",\"cmd\":\"");
  Serial.print(currentCmd);
  Serial.println("\"}");
}
