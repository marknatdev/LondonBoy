# Rescue Boat Wiring Schematic

This document outlines the hardware connections for the Arduino UNO R4 WiFi (or compatible board with Qwiic I2C).

## 1. Modulino Ecosystem (I2C)
The Modulino modules are designed to be daisy-chained using standard Qwiic cables.

| Arduino Board | Modulino Distance | Modulino Pixels | Modulino Buttons | Modulino Movement |
| :--- | :--- | :--- | :--- | :--- |
| **Qwiic Port** | Qwiic IN | Qwiic IN | Qwiic IN | Qwiic IN |
| | Qwiic OUT | Qwiic OUT | Qwiic OUT | Qwiic OUT |

*Note: Daisy-chain them in any order. The `Arduino_Modulino` library will automatically detect them on the I2C bus.*

## 2. Servos
Servos require a stable 5V power supply. If your servos draw significant current, power them from an external 5V UBEC or battery, ensuring the grounds are tied together.

| Component | Pin on Component | Pin on Arduino |
| :--- | :--- | :--- |
| **Steering Servo** | Signal (Orange/Yellow) | **D9** |
| | VCC (Red) | 5V (External) |
| | GND (Brown/Black) | GND |
| **Supply Drop Servo**| Signal (Orange/Yellow) | **D10** |
| | VCC (Red) | 5V (External) |
| | GND (Brown/Black) | GND |

## 3. HL-51 Relay & DC Motor
The HL-51 is configured as an **Active-High** relay (setting the pin HIGH will engage the COM and NO terminals). 

| HL-51 Pin | Connection |
| :--- | :--- |
| **VCC** | 5V (Arduino) |
| **GND** | GND (Arduino) |
| **IN1** | **D4** (Arduino Digital Pin) |

**High-Power Side (Motor Circuit):**
| Relay Terminal | Connection |
| :--- | :--- |
| **COM** (Common) | Positive Terminal (+) of Battery |
| **NO** (Normally Open) | Positive Terminal (+) of DC Motor |

*Note: Connect the Negative Terminal (-) of the Battery directly to the Negative Terminal (-) of the DC Motor.*

## 4. Serial Communication (to Linux Vision System)
If the vision pipeline is running on a companion Linux board (e.g., Raspberry Pi or the MPU side of the UNO Q), connect it via USB.
| Linux Board | Arduino Board |
| :--- | :--- |
| **USB Port** | **USB-C Port** |

*(This will appear as `/dev/ttyACM0` or `/dev/ttyUSB0` on the Linux side, facilitating `ArduinoJson` communication at 9600 baud).*
