/*
 * rescue_boat_firmware.ino
 * ─────────────────────────────────────────────────────────────────────────
 * Arduino UNO Q — STM32 MCU side
 *
 * Motor driver : HL-51 V1.0 Relay Module (ON/OFF — fixed RPM)
 * Power source : Arduino UNO Q board 5V pin
 *
 * ── Modulino Modules (all via I2C / Qwiic) ───────────────────────────────
 *   ModulinoMovement  (0x6A) — gyroscope/accel → tilt detection
 *   ModulinoButtons   (0x7C) — 3 buttons → mode control
 *   ModulinoDistance  (0x29) — ToF sensor  → obstacle / person detection
 *   ModulinoPixels    (0x6C) — 8 RGB LEDs  → emergency light
 *   ModulinoBuzzer    (0x3C) — piezo buzzer → emergency sound
 *
 * ── Other pins ───────────────────────────────────────────────────────────
 *   D4  — HL-51 Relay In1  (LOW = motor ON)
 *   D9  — Steering Servo   (50°=left | 90°=center | 130°=right)
 *   D10 — Supply Drop Servo(0°=closed | 90°=open)
 *
 * ── HL-51 Wiring ──────────────────────────────────────────────────────────
 *   Arduino 5V  ──► Relay Vcc
 *   Arduino GND ──► Relay Gnd
 *   Arduino D4  ──► Relay In1
 *   Arduino 5V  ──► Relay COM
 *   Relay NO    ──► DC Motor (+)
 *   DC Motor (-)──► Arduino GND
 *   NC terminal — leave unconnected
 *
 * ── Button functions ─────────────────────────────────────────────────────
 *   Button A (index 0) — Toggle EMERGENCY mode (alarm + red lights)
 *   Button B (index 1) — Stop motor immediately
 *   Button C (index 2) — Resume / clear emergency
 *
 * ── Distance behaviour ───────────────────────────────────────────────────
 *   Object < STOP_DISTANCE_MM  → auto-stop motor + trigger emergency
 *   Object >= STOP_DISTANCE_MM → normal operation
 *
 * ── Serial commands from Linux MPU (newline-terminated JSON) ─────────────
 *   {"cmd":"drive","steering":90}
 *   {"cmd":"stop"}
 *   {"cmd":"drop_supply"}
 *   {"cmd":"emergency_on"}
 *   {"cmd":"emergency_off"}
 *
 * ── Telemetry to Linux MPU every 500 ms ──────────────────────────────────
 *   {"motor":true,"steer":90,"dist":450,"gyro_x":0.1,"gyro_y":-0.2,
 *    "gyro_z":0.0,"emergency":false,"btn_a":false,"btn_b":false,"btn_c":false}
 *
 * ── Required libraries (install via Arduino IDE Library Manager) ──────────
 *   - Modulino         (search "Modulino" by Arduino)
 *   - ArduinoJson      (search "ArduinoJson" by Benoit Blanchon v7+)
 *   - Servo            (built-in)
 * ─────────────────────────────────────────────────────────────────────────
 */

#include <Modulino.h>
#include <Servo.h>
#include <ArduinoJson.h>

// ── Modulino objects ──────────────────────────────────────────────────────
ModulinoMovement movement;
ModulinoButtons  buttons;
ModulinoDistance distSensor;
ModulinoPixels   pixels;
ModulinoBuzzer   buzzer;

// ── Servo objects ─────────────────────────────────────────────────────────
Servo steerServo;
Servo supplyServo;

// ── Pin definitions ───────────────────────────────────────────────────────
const int PIN_RELAY        = 4;
const int PIN_STEER_SERVO  = 9;
const int PIN_SUPPLY_SERVO = 10;

// ── Relay logic (HL-51 is active-LOW) ────────────────────────────────────
const int RELAY_ON  = LOW;
const int RELAY_OFF = HIGH;

// ── Steering limits ───────────────────────────────────────────────────────
const int STEER_LEFT   = 50;
const int STEER_CENTER = 90;
const int STEER_RIGHT  = 130;

// ── Supply drop config ────────────────────────────────────────────────────
const int SUPPLY_CLOSED  = 0;
const int SUPPLY_OPEN    = 90;
const int SUPPLY_HOLD_MS = 2000;

// ── Distance threshold ────────────────────────────────────────────────────
const int STOP_DISTANCE_MM = 300;   // stop if object closer than 30 cm

// ── Emergency light colours (RGB) ────────────────────────────────────────
// Alternates between RED and BLUE every BLINK_INTERVAL_MS
const int BLINK_INTERVAL_MS = 250;

// ── State ─────────────────────────────────────────────────────────────────
bool   motorRunning    = false;
int    currentSteering = STEER_CENTER;
String currentCmd      = "stop";
bool   emergencyActive = false;
bool   distBlocked     = false;

// ── Timing ────────────────────────────────────────────────────────────────
unsigned long lastTelemetry  = 0;
unsigned long lastBlink      = 0;
unsigned long lastBuzzer     = 0;
bool          blinkState     = false;     // alternates for emergency light
bool          buzzerState    = false;

const unsigned long TELEMETRY_MS   = 500;
const unsigned long BUZZER_ON_MS   = 300;
const unsigned long BUZZER_OFF_MS  = 300;

// ── Serial buffer ─────────────────────────────────────────────────────────
String serialBuffer = "";

// ─────────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);

  // Relay — motor OFF on boot
  pinMode(PIN_RELAY, OUTPUT);
  digitalWrite(PIN_RELAY, RELAY_OFF);

  // Servos
  steerServo.attach(PIN_STEER_SERVO);
  supplyServo.attach(PIN_SUPPLY_SERVO);
  steerServo.write(STEER_CENTER);
  supplyServo.write(SUPPLY_CLOSED);

  // Modulino init (must call Modulino.begin() first)
  Modulino.begin();
  movement.begin();
  buttons.begin();
  distSensor.begin();
  pixels.begin();
  buzzer.begin();

  // Boot indicator — brief green sweep on pixels
  bootLightShow();

  Serial.println("{\"status\":\"ready\",\"msg\":\"Rescue Boat MCU online\"}");
}

// ─────────────────────────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // ── 1. Read serial commands from Linux MPU ────────────────────────────
  readSerial();

  // ── 2. Read Modulino Buttons ──────────────────────────────────────────
  handleButtons();

  // ── 3. Read Modulino Distance sensor ─────────────────────────────────
  handleDistance();

  // ── 4. Update emergency light & buzzer ───────────────────────────────
  if (emergencyActive) {
    handleEmergencyLight(now);
    handleEmergencyBuzzer(now);
  }

  // ── 5. Send telemetry ─────────────────────────────────────────────────
  if (now - lastTelemetry >= TELEMETRY_MS) {
    sendTelemetry();
    lastTelemetry = now;
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Serial command reader
// ─────────────────────────────────────────────────────────────────────────
void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (serialBuffer.length() > 0) {
        processCommand(serialBuffer);
        serialBuffer = "";
      }
    } else {
      serialBuffer += c;
      if (serialBuffer.length() > 256) serialBuffer = "";
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────
// JSON command processor
// ─────────────────────────────────────────────────────────────────────────
void processCommand(const String& json) {
  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, json)) return;

  const char* cmd = doc["cmd"] | "unknown";
  currentCmd = String(cmd);

  if      (strcmp(cmd, "drive")        == 0) cmdDrive(doc["steering"] | STEER_CENTER);
  else if (strcmp(cmd, "stop")         == 0) cmdStop();
  else if (strcmp(cmd, "drop_supply")  == 0) cmdDropSupply();
  else if (strcmp(cmd, "emergency_on") == 0) setEmergency(true);
  else if (strcmp(cmd, "emergency_off")== 0) setEmergency(false);
}

// ─────────────────────────────────────────────────────────────────────────
// Motor / servo commands
// ─────────────────────────────────────────────────────────────────────────
void cmdDrive(int steering) {
  if (distBlocked || emergencyActive) return;   // safety gate
  currentSteering = constrain(steering, STEER_LEFT, STEER_RIGHT);
  steerServo.write(currentSteering);
  digitalWrite(PIN_RELAY, RELAY_ON);
  motorRunning = true;
}

void cmdStop() {
  digitalWrite(PIN_RELAY, RELAY_OFF);
  steerServo.write(STEER_CENTER);
  currentSteering = STEER_CENTER;
  motorRunning = false;
}

void cmdDropSupply() {
  cmdStop();
  delay(300);
  supplyServo.write(SUPPLY_OPEN);
  Serial.println("{\"event\":\"supply_drop\",\"state\":\"open\"}");
  delay(SUPPLY_HOLD_MS);
  supplyServo.write(SUPPLY_CLOSED);
  Serial.println("{\"event\":\"supply_drop\",\"state\":\"closed\"}");
}

// ─────────────────────────────────────────────────────────────────────────
// Modulino Buttons handler
//   A → toggle emergency
//   B → stop motor
//   C → clear emergency
// ─────────────────────────────────────────────────────────────────────────
void handleButtons() {
  // isPressed() returns true while button is held
  if (buttons.isPressed(0)) {           // Button A — toggle emergency
    delay(50);                           // simple debounce
    if (buttons.isPressed(0)) {
      setEmergency(!emergencyActive);
      while (buttons.isPressed(0));      // wait for release
    }
  }
  if (buttons.isPressed(1)) {           // Button B — stop
    cmdStop();
    delay(50);
    while (buttons.isPressed(1));
  }
  if (buttons.isPressed(2)) {           // Button C — clear emergency
    delay(50);
    if (buttons.isPressed(2)) {
      setEmergency(false);
      while (buttons.isPressed(2));
    }
  }

  // Mirror button LEDs to show current emergency state
  buttons.setLeds(emergencyActive, !motorRunning && !emergencyActive, false);
}

// ─────────────────────────────────────────────────────────────────────────
// Modulino Distance handler
//   Auto-stops motor and triggers emergency if object is too close
// ─────────────────────────────────────────────────────────────────────────
void handleDistance() {
  if (!distSensor.available()) return;

  int mm = (int)distSensor.get();

  if (mm < STOP_DISTANCE_MM) {
    if (!distBlocked) {
      distBlocked = true;
      cmdStop();
      setEmergency(true);
      Serial.print("{\"event\":\"obstacle\",\"dist_mm\":");
      Serial.print(mm);
      Serial.println("}");
    }
  } else {
    if (distBlocked) {
      distBlocked = false;
      setEmergency(false);
      Serial.println("{\"event\":\"obstacle_cleared\"}");
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Emergency state setter
// ─────────────────────────────────────────────────────────────────────────
void setEmergency(bool active) {
  emergencyActive = active;
  if (active) {
    cmdStop();
    Serial.println("{\"event\":\"emergency_on\"}");
  } else {
    // Clear pixels and silence buzzer
    for (int i = 0; i < 8; i++) pixels.set(i, 0, 0, 0);
    pixels.show();
    buzzer.tone(0, 1);   // stop buzzer (frequency 0)
    Serial.println("{\"event\":\"emergency_off\"}");
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Modulino Pixels — emergency strobe (RED / BLUE alternating)
// ─────────────────────────────────────────────────────────────────────────
void handleEmergencyLight(unsigned long now) {
  if (now - lastBlink < BLINK_INTERVAL_MS) return;
  lastBlink  = now;
  blinkState = !blinkState;

  for (int i = 0; i < 8; i++) {
    if (blinkState) {
      // Even LEDs RED, odd LEDs off
      if (i % 2 == 0) pixels.set(i, 255, 0, 0);
      else             pixels.set(i, 0,   0, 0);
    } else {
      // Even LEDs off, odd LEDs BLUE
      if (i % 2 == 0) pixels.set(i, 0, 0,   0);
      else             pixels.set(i, 0, 0, 255);
    }
  }
  pixels.show();
}

// ─────────────────────────────────────────────────────────────────────────
// Modulino Buzzer — emergency beep (on/off pattern)
// ─────────────────────────────────────────────────────────────────────────
void handleEmergencyBuzzer(unsigned long now) {
  unsigned long interval = buzzerState ? BUZZER_ON_MS : BUZZER_OFF_MS;
  if (now - lastBuzzer < interval) return;
  lastBuzzer  = now;
  buzzerState = !buzzerState;

  if (buzzerState) buzzer.tone(880, BUZZER_ON_MS);   // 880 Hz beep
  else             buzzer.tone(0,   1);               // silence
}

// ─────────────────────────────────────────────────────────────────────────
// Boot light show — brief green sweep across all 8 LEDs
// ─────────────────────────────────────────────────────────────────────────
void bootLightShow() {
  for (int i = 0; i < 8; i++) {
    for (int j = 0; j < 8; j++) pixels.set(j, 0, 0, 0);
    pixels.set(i, 0, 200, 0);   // green dot sweeps right
    pixels.show();
    delay(60);
  }
  for (int i = 0; i < 8; i++) pixels.set(i, 0, 0, 0);
  pixels.show();
}

// ─────────────────────────────────────────────────────────────────────────
// Telemetry — sent to Linux MPU every 500 ms
// ─────────────────────────────────────────────────────────────────────────
void sendTelemetry() {
  // Read gyroscope from Modulino Movement
  float gx = 0, gy = 0, gz = 0;
  if (movement.update()) {
    gx = movement.getX();
    gy = movement.getY();
    gz = movement.getZ();
  }

  // Read distance
  int dist_mm = -1;
  if (distSensor.available()) dist_mm = (int)distSensor.get();

  // Button states
  bool bA = buttons.isPressed(0);
  bool bB = buttons.isPressed(1);
  bool bC = buttons.isPressed(2);

  // Compose telemetry JSON manually (saves memory vs ArduinoJson)
  Serial.print("{\"motor\":");      Serial.print(motorRunning ? "true" : "false");
  Serial.print(",\"steer\":");      Serial.print(currentSteering);
  Serial.print(",\"dist_mm\":");    Serial.print(dist_mm);
  Serial.print(",\"gyro_x\":");     Serial.print(gx, 2);
  Serial.print(",\"gyro_y\":");     Serial.print(gy, 2);
  Serial.print(",\"gyro_z\":");     Serial.print(gz, 2);
  Serial.print(",\"emergency\":");  Serial.print(emergencyActive ? "true" : "false");
  Serial.print(",\"dist_blocked\":");Serial.print(distBlocked ? "true" : "false");
  Serial.print(",\"btn_a\":");      Serial.print(bA ? "true" : "false");
  Serial.print(",\"btn_b\":");      Serial.print(bB ? "true" : "false");
  Serial.print(",\"btn_c\":");      Serial.print(bC ? "true" : "false");
  Serial.println("}");
}
