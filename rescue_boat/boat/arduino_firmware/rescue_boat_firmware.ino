#include <Servo.h>
#include <Arduino_Modulino.h>
#include <ArduinoJson.h>

// ── Pins & Constants ─────────────────────────────────────────────────────────
const int STEERING_PIN = 9;
const int DROP_PIN = 10;
const int RELAY_PIN = 4;

const int DISTANCE_THRESHOLD_MM = 200; // 20 cm
const unsigned long SERIAL_TIMEOUT = 2000; // ms

// ── Hardware Objects ─────────────────────────────────────────────────────────
Servo steeringServo;
Servo dropServo;

ModulinoPixels pixels;
ModulinoDistance distance;
ModulinoMovement movement;
ModulinoButtons buttons;

// ── Global State ─────────────────────────────────────────────────────────────
int currentSteering = 90;
int currentDrop = 0;
int motorReq = 0;

bool manualOverride = false;
unsigned long lastSerialTime = 0;

void setup() {
  Serial.begin(9600);
  
  // Initialize Relays and Servos
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW); // Active-High: start OFF
  
  steeringServo.attach(STEERING_PIN);
  dropServo.attach(DROP_PIN);
  
  steeringServo.write(90); // Center
  dropServo.write(0);      // Retracted
  
  // Initialize Modulino
  Modulino.begin();
  pixels.begin();
  distance.begin();
  movement.begin();
  buttons.begin();
  
  // Initial Pixels setup (White = Standby)
  setAllPixels(255, 255, 255);
}

void loop() {
  unsigned long now = millis();
  
  // 1. Check Modulino Sensors
  buttons.update();
  if (buttons.isPressed(0)) {
    manualOverride = !manualOverride; // Toggle override with Button 0
    delay(200); // Debounce
  }
  
  bool obstacleDetected = false;
  if (distance.available()) {
    int dist = distance.get(); // in mm
    if (dist > 0 && dist < DISTANCE_THRESHOLD_MM) {
      obstacleDetected = true;
    }
  }

  // Optional: Read Movement for logging
  if (movement.available()) {
    movement.update();
    // float ax = movement.getAccelerationX();
    // Could implement stabilization later
  }

  // 2. Read Serial Commands (JSON)
  if (Serial.available() > 0) {
    StaticJsonDocument<200> doc;
    DeserializationError error = deserializeJson(doc, Serial);
    
    if (!error) {
      if (doc.containsKey("steering")) currentSteering = doc["steering"];
      if (doc.containsKey("drop")) currentDrop = doc["drop"];
      if (doc.containsKey("motor")) motorReq = doc["motor"];
      
      lastSerialTime = now;
    }
  }
  
  // Failsafe: if no serial data for 2 seconds, stop motor and center steering
  if (now - lastSerialTime > SERIAL_TIMEOUT) {
    currentSteering = 90;
    motorReq = 0;
  }

  // 3. Actuate Servos
  steeringServo.write(currentSteering);
  dropServo.write(currentDrop == 1 ? 180 : 0);
  
  // 4. Actuate Relay (DC Motor) with safety checks
  bool canRunMotor = (motorReq == 1) && !obstacleDetected && !manualOverride;
  if (canRunMotor) {
    digitalWrite(RELAY_PIN, HIGH); // Active-High to turn ON
  } else {
    digitalWrite(RELAY_PIN, LOW);  // Turn OFF
  }

  // 5. Update Modulino Pixels Status
  if (manualOverride) {
    setAllPixels(255, 100, 0); // Orange = Manual Override / Stopped
  } else if (obstacleDetected) {
    setAllPixels(255, 0, 0);   // Red = Obstacle Detected
  } else if (currentDrop == 1) {
    setAllPixels(0, 0, 255);   // Blue = Dropping Supply
  } else if (canRunMotor) {
    setAllPixels(0, 255, 0);   // Green = Tracking and Moving
  } else {
    setAllPixels(255, 255, 255); // White = Idle
  }
}

// Helper to set all 8 pixels
void setAllPixels(int r, int g, int b) {
  for (int i = 0; i < 8; i++) {
    pixels.set(i, r, g, b);
  }
  pixels.show();
}
