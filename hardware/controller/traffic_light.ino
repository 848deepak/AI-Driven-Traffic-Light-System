/*
 * AI Traffic Light System - LED Controller
 * 
 * This sketch controls traffic light LEDs based on commands received from
 * the Raspberry Pi via Serial or MQTT.
 * 
 * Hardware setup:
 * - LEDs for 2 lanes (RED, YELLOW, GREEN for each)
 * - Optional: Piezo buzzer for emergency vehicle alerts
 * 
 * Communication protocol:
 * - Serial input format: 
 *   - Signal state: L1-RED-30;L2-GREEN-30
 *   - Detection data: DETECTION:{"lanes":{"L1":{"count":5,"emergency":false},"L2":{"count":3,"emergency":true}}}
 * 
 * Created for AI Traffic Light System
 */

#include <Arduino.h>
#include <ArduinoJson.h>  // For parsing JSON detection data

// Uncomment for ESP32 with MQTT support
// #define USE_ESP32_MQTT

#ifdef USE_ESP32_MQTT
  #include <WiFi.h>
  #include <PubSubClient.h>
#endif

// Pin definitions
// Each lane has 3 LEDs: RED, YELLOW, GREEN
// Lane 1 pins
const int L1_RED = 2;
const int L1_YELLOW = 3;
const int L1_GREEN = 4;

// Lane 2 pins
const int L2_RED = 5;
const int L2_YELLOW = 6;
const int L2_GREEN = 7;

// Emergency alert buzzer (optional)
#define BUZZER_PIN A0
#define USE_BUZZER true  // Set to false if no buzzer connected

// Signal states
enum SignalState {
  RED,
  YELLOW,
  GREEN
};

// Lane information
struct LaneInfo {
  SignalState state;
  int timeLeft;
  boolean emergency;
  int vehicleCount;  // Current vehicle count from camera
};

// Lane array (2 lanes)
LaneInfo lanes[2];

// LED pins organized by lane
const int lanePins[2][3] = {
  {L1_RED, L1_YELLOW, L1_GREEN},
  {L2_RED, L2_YELLOW, L2_GREEN}
};

// WiFi and MQTT settings (for ESP32)
#ifdef USE_ESP32_MQTT
  const char* ssid = "YourWiFiSSID";
  const char* password = "YourWiFiPassword";
  const char* mqtt_server = "192.168.1.100";  // MQTT broker IP
  const int mqtt_port = 1883;
  const char* mqtt_topic = "traffic/signals";
  
  WiFiClient espClient;
  PubSubClient mqttClient(espClient);
#endif

// Timing variables
unsigned long lastUpdateTime = 0;
const int countdownInterval = 1000; // 1 second interval for countdown

// Serial buffer
const int MAX_BUFFER_SIZE = 256;  // Increased for JSON messages
char serialBuffer[MAX_BUFFER_SIZE];
int bufferIndex = 0;

// JSON document for parsing detection data
StaticJsonDocument<512> jsonDoc;

void setup() {
  // Initialize Serial communication
  Serial.begin(115200);
  Serial.println("AI Traffic Light Controller Starting...");
  
  // Initialize all pins as outputs
  for (int lane = 0; lane < 2; lane++) {
    for (int signal = 0; signal < 3; signal++) {
      pinMode(lanePins[lane][signal], OUTPUT);
      // Initially all lights off
      digitalWrite(lanePins[lane][signal], LOW);
    }
  }
  
  // Initialize buzzer if enabled
  if (USE_BUZZER) {
    pinMode(BUZZER_PIN, OUTPUT);
    digitalWrite(BUZZER_PIN, LOW);
  }
  
  // Initialize lane states (all default to RED)
  for (int i = 0; i < 2; i++) {
    lanes[i].state = RED;
    lanes[i].timeLeft = 30;
    lanes[i].emergency = false;
    lanes[i].vehicleCount = 0;
  }
  
  // Initial startup sequence - test all lights
  testLEDs();
  
  #ifdef USE_ESP32_MQTT
    // Setup WiFi
    setupWiFi();
    
    // Setup MQTT
    mqttClient.setServer(mqtt_server, mqtt_port);
    mqttClient.setCallback(mqttCallback);
  #endif
  
  // Set initial state - Lane 1 GREEN, Lane 2 RED
  updateSignals("L1-GREEN-30;L2-RED-30");
  
  Serial.println("Controller ready");
}

void loop() {
  // Handle serial input
  if (Serial.available() > 0) {
    char c = Serial.read();
    
    // Process complete messages ending with newline
    if (c == '\n') {
      serialBuffer[bufferIndex] = '\0'; // Null terminate
      
      // Process the command
      if (bufferIndex > 0) {
        processSerialCommand(serialBuffer);
      }
      
      // Reset buffer
      bufferIndex = 0;
    } 
    else if (bufferIndex < MAX_BUFFER_SIZE - 1) {
      // Add character to buffer
      serialBuffer[bufferIndex++] = c;
    }
  }
  
  #ifdef USE_ESP32_MQTT
    // Handle MQTT connection and messages
    if (!mqttClient.connected()) {
      reconnectMQTT();
    }
    mqttClient.loop();
  #endif
  
  // Update countdown timers every second
  unsigned long currentTime = millis();
  if (currentTime - lastUpdateTime >= countdownInterval) {
    lastUpdateTime = currentTime;
    updateCountdowns();
  }
  
  // Check if any lane has emergency vehicle and operate buzzer
  if (USE_BUZZER) {
    handleEmergencyAlert();
  }
}

// Process incoming serial commands
void processSerialCommand(const char* command) {
  // Check if it's a detection data message
  if (strncmp(command, "DETECTION:", 10) == 0) {
    // Process detection data
    processDetectionData(command + 10);  // Skip "DETECTION:" prefix
  } else {
    // Process regular signal state command
    updateSignals(command);
  }
}

// Process detection data from camera
void processDetectionData(const char* jsonData) {
  // Clear previous data
  jsonDoc.clear();
  
  // Parse JSON
  DeserializationError error = deserializeJson(jsonDoc, jsonData);
  
  if (error) {
    Serial.print("JSON parse error: ");
    Serial.println(error.c_str());
    return;
  }
  
  // Extract lane data
  JsonObject lanesObj = jsonDoc["lanes"];
  
  if (!lanesObj.isNull()) {
    // Process each lane
    for (int i = 0; i < 2; i++) {
      char laneId[3];
      sprintf(laneId, "L%d", i+1);
      
      if (lanesObj.containsKey(laneId)) {
        // Update vehicle count
        lanes[i].vehicleCount = lanesObj[laneId]["count"];
        
        // Check for emergency vehicles detected by camera
        boolean cameraDetectedEmergency = lanesObj[laneId]["emergency"];
        if (cameraDetectedEmergency && !lanes[i].emergency) {
          lanes[i].emergency = true;
          Serial.print("Emergency vehicle detected in lane ");
          Serial.println(i+1);
        }
      }
    }
    
    // Print vehicle counts
    Serial.print("Vehicle counts - L1: ");
    Serial.print(lanes[0].vehicleCount);
    Serial.print(", L2: ");
    Serial.println(lanes[1].vehicleCount);
  }
}

// Update countdown timers
void updateCountdowns() {
  boolean stateChanged = false;
  
  for (int lane = 0; lane < 2; lane++) {
    if (lanes[lane].timeLeft > 0) {
      lanes[lane].timeLeft--;
      
      // For debug, print remaining time for GREEN signals
      if (lanes[lane].state == GREEN) {
        Serial.print("Lane ");
        Serial.print(lane + 1);
        Serial.print(" GREEN: ");
        Serial.print(lanes[lane].timeLeft);
        Serial.println("s remaining");
      }
    }
  }
  
  // Send status update back to Pi every 5 seconds
  static int statusCounter = 0;
  if (++statusCounter >= 5) {
    statusCounter = 0;
    sendStatusUpdate();
  }
}

// Parse and update signal states
void updateSignals(const char* signalState) {
  Serial.print("Received signal update: ");
  Serial.println(signalState);
  
  // Make a copy of the signal state string to tokenize
  char buffer[MAX_BUFFER_SIZE];
  strncpy(buffer, signalState, MAX_BUFFER_SIZE);
  
  // Process each lane state
  char* laneTok = strtok(buffer, ";");
  while (laneTok != NULL) {
    // Parse lane format: "L1-RED-30"
    char laneId[3] = {0};
    char stateStr[7] = {0};
    int timeLeft = 0;
    
    // Extract lane ID, state, and time
    if (sscanf(laneTok, "%2s-%6[^-]-%d", laneId, stateStr, &timeLeft) == 3) {
      // Convert lane ID to index (L1 -> 0, L2 -> 1)
      int laneIndex = laneId[1] - '1';
      
      if (laneIndex >= 0 && laneIndex < 2) {
        // Convert state string to enum
        SignalState newState;
        if (strcmp(stateStr, "RED") == 0) {
          newState = RED;
        } else if (strcmp(stateStr, "YELLOW") == 0) {
          newState = YELLOW;
        } else if (strcmp(stateStr, "GREEN") == 0) {
          newState = GREEN;
        } else {
          // Invalid state, skip this lane
          laneTok = strtok(NULL, ";");
          continue;
        }
        
        // Check for emergency state (time over 100 indicates emergency)
        boolean isEmergency = false;
        if (timeLeft > 100) {
          timeLeft = timeLeft - 100;
          isEmergency = true;
        }
        
        // Update lane state
        lanes[laneIndex].state = newState;
        lanes[laneIndex].timeLeft = timeLeft;
        lanes[laneIndex].emergency = isEmergency;
        
        // Apply the light state to the LEDs
        updateLaneLEDs(laneIndex);
      }
    }
    
    // Get next lane token
    laneTok = strtok(NULL, ";");
  }
  
  // Send confirmation
  Serial.println("States updated");
}

// Update LEDs for a specific lane
void updateLaneLEDs(int lane) {
  // Turn off all LEDs for this lane
  for (int i = 0; i < 3; i++) {
    digitalWrite(lanePins[lane][i], LOW);
  }
  
  // Turn on the appropriate LED based on state
  switch (lanes[lane].state) {
    case RED:
      digitalWrite(lanePins[lane][0], HIGH);
      break;
    case YELLOW:
      digitalWrite(lanePins[lane][1], HIGH);
      break;
    case GREEN:
      digitalWrite(lanePins[lane][2], HIGH);
      break;
  }
}

// Send status update back to Pi
void sendStatusUpdate() {
  char statusMessage[MAX_BUFFER_SIZE];
  int offset = 0;
  
  // Format status update
  offset += snprintf(statusMessage + offset, MAX_BUFFER_SIZE - offset, "STATUS:");
  
  for (int lane = 0; lane < 2; lane++) {
    const char* stateStr;
    switch (lanes[lane].state) {
      case RED:
        stateStr = "RED";
        break;
      case YELLOW:
        stateStr = "YELLOW";
        break;
      case GREEN:
        stateStr = "GREEN";
        break;
    }
    
    offset += snprintf(statusMessage + offset, MAX_BUFFER_SIZE - offset, 
                       "L%d-%s-%d%s;", lane + 1, stateStr, lanes[lane].timeLeft,
                       lanes[lane].emergency ? "-EMER" : "");
  }
  
  // Add vehicle counts
  offset += snprintf(statusMessage + offset, MAX_BUFFER_SIZE - offset, 
                    "COUNTS:L1-%d;L2-%d", 
                    lanes[0].vehicleCount, lanes[1].vehicleCount);
  
  // Send status
  Serial.println(statusMessage);
  
  #ifdef USE_ESP32_MQTT
    mqttClient.publish("traffic/status", statusMessage);
  #endif
}

// Test sequence - cycle through all LEDs
void testLEDs() {
  Serial.println("Running LED test sequence...");
  
  // Turn on all RED LEDs
  for (int lane = 0; lane < 2; lane++) {
    digitalWrite(lanePins[lane][0], HIGH); // RED
  }
  delay(1000);
  
  // Turn on all YELLOW LEDs
  for (int lane = 0; lane < 2; lane++) {
    digitalWrite(lanePins[lane][0], LOW); // RED off
    digitalWrite(lanePins[lane][1], HIGH); // YELLOW on
  }
  delay(1000);
  
  // Turn on all GREEN LEDs
  for (int lane = 0; lane < 2; lane++) {
    digitalWrite(lanePins[lane][1], LOW); // YELLOW off
    digitalWrite(lanePins[lane][2], HIGH); // GREEN on
  }
  delay(1000);
  
  // Turn all LEDs off
  for (int lane = 0; lane < 2; lane++) {
    digitalWrite(lanePins[lane][2], LOW); // GREEN off
  }
  delay(500);
  
  Serial.println("LED test completed");
}

// Handle emergency vehicle alert with buzzer
void handleEmergencyAlert() {
  static boolean buzzerState = false;
  static unsigned long lastBuzzerTime = 0;
  
  // Check if any lane has emergency vehicle
  boolean anyEmergency = false;
  for (int lane = 0; lane < 2; lane++) {
    if (lanes[lane].emergency) {
      anyEmergency = true;
      break;
    }
  }
  
  // Control buzzer
  if (anyEmergency) {
    // Fast beeping for emergency (200ms on/off)
    unsigned long currentTime = millis();
    if (currentTime - lastBuzzerTime >= 200) {
      lastBuzzerTime = currentTime;
      buzzerState = !buzzerState;
      digitalWrite(BUZZER_PIN, buzzerState ? HIGH : LOW);
    }
  } else {
    // No emergency, buzzer off
    if (buzzerState) {
      buzzerState = false;
      digitalWrite(BUZZER_PIN, LOW);
    }
  }
}

#ifdef USE_ESP32_MQTT
  // WiFi setup
  void setupWiFi() {
    delay(10);
    Serial.println();
    Serial.print("Connecting to WiFi: ");
    Serial.println(ssid);
    
    WiFi.begin(ssid, password);
    
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
    }
    
    Serial.println("");
    Serial.println("WiFi connected");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
  }
  
  // Reconnect to MQTT broker
  void reconnectMQTT() {
    // Loop until we're reconnected
    while (!mqttClient.connected()) {
      Serial.print("Attempting MQTT connection...");
      // Create a client ID
      String clientId = "TrafficLightController-";
      clientId += String(random(0xffff), HEX);
      
      // Attempt to connect
      if (mqttClient.connect(clientId.c_str())) {
        Serial.println("connected");
        // Subscribe to topic
        mqttClient.subscribe(mqtt_topic);
      } else {
        Serial.print("failed, rc=");
        Serial.print(mqttClient.state());
        Serial.println(" try again in 5 seconds");
        // Wait 5 seconds before retrying
        delay(5000);
      }
    }
  }
  
  // MQTT message callback
  void mqttCallback(char* topic, byte* payload, unsigned int length) {
    Serial.print("Message arrived [");
    Serial.print(topic);
    Serial.print("] ");
    
    // Copy payload to buffer
    if (length < MAX_BUFFER_SIZE) {
      memcpy(serialBuffer, payload, length);
      serialBuffer[length] = '\0';
      Serial.println(serialBuffer);
      
      // Process the message
      processSerialCommand(serialBuffer);
    }
  }
#endif 