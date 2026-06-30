/*
 * motor_test.ino
 * ─────────────────────────────────────────────────────────────────────────
 * Simple DC Motor test using HL-51 V1.0 Relay Module
 *
 * Wiring:
 *   Arduino 5V  ──► Relay Vcc
 *   Arduino GND ──► Relay Gnd
 *   Arduino D4  ──► Relay In1
 *   Arduino 5V  ──► Relay COM
 *   Relay NO    ──► DC Motor (+)
 *   DC Motor (-)──► Arduino GND
 *
 * Behaviour:
 *   Motor ON  for 3 seconds
 *   Motor OFF for 2 seconds
 *   Repeat forever
 * ─────────────────────────────────────────────────────────────────────────
 */

const int RELAY_PIN = 4;      // D4 → Relay In1
const int RELAY_ON  = LOW;    // HL-51 is active-LOW
const int RELAY_OFF = HIGH;

void setup() {
  Serial.begin(9600);
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, RELAY_OFF);   // motor OFF on boot
  Serial.println("Motor test ready.");
}

void loop() {
  // Motor ON
  Serial.println("Motor ON");
  digitalWrite(RELAY_PIN, RELAY_ON);
  delay(3000);

  // Motor OFF
  Serial.println("Motor OFF");
  digitalWrite(RELAY_PIN, RELAY_OFF);
  delay(2000);
}
