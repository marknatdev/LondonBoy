/*
 * rescue_boat_firmware.ino
 * ─────────────────────────────────────────────────────────────────────────
 * Arduino UNO Q — STM32 MCU side (Zephyr OS / Arduino environment)
 *
 * Receives JSON commands from the Linux MPU over UART (Serial).
 * Controls:
 *   D9  — Steering Servo (0°=full left, 90°=straight, 130°=full right)
 *   D5  — DC Motor PWM (speed 0–255)
 *   D4  — DC Motor direction (HIGH=forward, LOW=brake)
 *   D10 — Supply Drop Servo (0°=closed, 90°=open/drop)
 *
 * Expected command format (newline-terminated JSON):
 *   {"cmd":"drive","speed":150,"steering":90}
 *   {"cmd":"stop"}
 *   {"cmd":"drop_supply"}
 *
 * Telemetry sent back every 500ms:
 *   {"steer":<degrees>,"speed":<pwm>,"mode":<cmd>}
 * ─────────────────────────────────────────────────────────────────────────
 */

#include <Servo.h>
#include <ArduinoJson.h>   // Install: ArduinoJson by Benoit Blanchon v7+

// ── Pin definitions ────────────────────────────────────────────────────────
const int PIN_STEER_SERVO  = 9;
const int PIN_SUPPLY_SERVO = 10;
const int PIN_MOTOR_PWM    = 5;
const int PIN_MOTOR_DIR    = 4;

// ── Servo objects ──────────────────────────────────────────────────────────
Servo steerServo;
Servo supplyServo;

// ── State ──────────────────────────────────────────────────────────────────
int  currentSpeed   = 0;
int  currentSteering = 90;   // neutral
bool motorRunning   = false;
String currentCmd   = "stop";

// ── Supply drop config ─────────────────────────────────────────────────────
const int SUPPLY_CLOSED_ANGLE = 0;
const int SUPPLY_OPEN_ANGLE   = 90;
const int SUPPLY_HOLD_MS      = 2000;   // hold open for 2 seconds

// ── Serial buffer ──────────────────────────────────────────────────────────
String serialBuffer = "";

// ── Telemetry interval ─────────────────────────────────────────────────────
unsigned long lastTelemetry = 0;
const unsigned long TELEMETRY_INTERVAL_MS = 500;

// ─────────────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);

  steerServo.attach(PIN_STEER_SERVO);
  supplyServo.attach(PIN_SUPPLY_SERVO);

  pinMode(PIN_MOTOR_PWM, OUTPUT);
  pinMode(PIN_MOTOR_DIR, OUTPUT);

  // Safe initial state
  steerServo.write(90);          // straight
  supplyServo.write(SUPPLY_CLOSED_ANGLE);
  analogWrite(PIN_MOTOR_PWM, 0);
  digitalWrite(PIN_MOTOR_DIR, HIGH);

  Serial.println("{\"status\":\"ready\",\"msg\":\"Rescue Boat MCU online\"}");
}

// ─────────────────────────────────────────────────────────────────────────────
void loop() {
  // ── Read incoming serial characters ───────────────────────────────────
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

  // ── Periodic telemetry ─────────────────────────────────────────────────
  if (millis() - lastTelemetry >= TELEMETRY_INTERVAL_MS) {
    sendTelemetry();
    lastTelemetry = millis();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
void processCommand(const String& json) {
  StaticJsonDocument<256> doc;
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
    int speed    = doc["speed"]    | 0;
    int steering = doc["steering"] | 90;
    cmdDrive(speed, steering);

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

// ── Drive command ──────────────────────────────────────────────────────────
void cmdDrive(int speed, int steering) {
  currentSpeed    = constrain(speed, 0, 255);
  currentSteering = constrain(steering, 50, 130);

  steerServo.write(currentSteering);
  digitalWrite(PIN_MOTOR_DIR, HIGH);   // forward
  analogWrite(PIN_MOTOR_PWM, currentSpeed);
  motorRunning = true;
}

// ── Stop command ───────────────────────────────────────────────────────────
void cmdStop() {
  currentSpeed = 0;
  analogWrite(PIN_MOTOR_PWM, 0);
  digitalWrite(PIN_MOTOR_DIR, LOW);
  steerServo.write(90);         // return to straight
  currentSteering = 90;
  motorRunning = false;
}

// ── Supply drop command ────────────────────────────────────────────────────
void cmdDropSupply() {
  cmdStop();                                      // stop motors first
  delay(300);
  supplyServo.write(SUPPLY_OPEN_ANGLE);           // open hatch
  Serial.println("{\"event\":\"supply_drop\",\"state\":\"open\"}");
  delay(SUPPLY_HOLD_MS);
  supplyServo.write(SUPPLY_CLOSED_ANGLE);         // close hatch
  Serial.println("{\"event\":\"supply_drop\",\"state\":\"closed\"}");
}

// ── Telemetry ──────────────────────────────────────────────────────────────
void sendTelemetry() {
  Serial.print("{\"steer\":");
  Serial.print(currentSteering);
  Serial.print(",\"speed\":");
  Serial.print(currentSpeed);
  Serial.print(",\"motor\":");
  Serial.print(motorRunning ? "true" : "false");
  Serial.print(",\"cmd\":\"");
  Serial.print(currentCmd);
  Serial.println("\"}");
}
