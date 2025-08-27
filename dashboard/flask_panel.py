#!/usr/bin/env python3
import os
import sys
import json
import time
import threading
import logging
from datetime import datetime
from flask import Flask, render_template, jsonify, request
import paho.mqtt.client as mqtt

# Add parent directory to path for importing
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('traffic_dashboard')

# Flask application
app = Flask(__name__)

# Data storage
traffic_data = {
    "lanes": {
        "L1": {"state": "RED", "time_left": 30, "count": 0, "emergency": False},
        "L2": {"state": "RED", "time_left": 30, "count": 0, "emergency": False}
    },
    "last_update": time.time(),
    "system_status": "Operational",
    "log_messages": []
}

# Configuration
MAX_LOG_MESSAGES = 100
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPICS = ["traffic/signals", "traffic/status", "traffic/detection"]
MQTT_CLIENT_ID = f"traffic-dashboard-{time.time()}"

# Initialize MQTT client
mqtt_client = None
mqtt_connected = False

# Routes
@app.route('/')
def index():
    """Render dashboard"""
    # Check for active emergency alerts
    emergency_alerts = {}
    current_time = time.time()
    
    for lane_id, lane_info in traffic_data["lanes"].items():
        if lane_info.get("emergency", False):
            emergency_type = lane_info.get("emergency_type", "unknown")
            emergency_alerts[lane_id] = emergency_type
    
    return render_template('index.html', traffic_data=traffic_data, emergency_alerts=emergency_alerts)

@app.route('/api/traffic-data')
def get_traffic_data():
    """API endpoint to get current traffic data"""
    return jsonify(traffic_data)

@app.route('/api/system-control', methods=['POST'])
def system_control():
    """API endpoint for system control commands"""
    command = request.json.get('command')
    params = request.json.get('params', {})
    
    if command == 'emergency_override':
        lane_id = params.get('lane_id')
        if lane_id and lane_id in traffic_data['lanes']:
            message = f"EMERGENCY_OVERRIDE:{lane_id}"
            if mqtt_client and mqtt_connected:
                mqtt_client.publish("traffic/control", message)
                add_log_message(f"Emergency override triggered for lane {lane_id}")
                return jsonify({"status": "success", "message": f"Emergency override sent for lane {lane_id}"})
    
    elif command == 'reset_system':
        if mqtt_client and mqtt_connected:
            mqtt_client.publish("traffic/control", "RESET_SYSTEM")
            add_log_message("System reset command sent")
            return jsonify({"status": "success", "message": "System reset command sent"})
    
    return jsonify({"status": "error", "message": "Invalid command or parameters"})

@app.route('/api/log')
def get_log():
    """API endpoint to get log messages"""
    return jsonify({"logs": traffic_data["log_messages"]})

def add_log_message(message):
    """Add a message to the log"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {"timestamp": timestamp, "message": message}
    
    # Add to beginning of list and maintain max size
    traffic_data["log_messages"].insert(0, log_entry)
    if len(traffic_data["log_messages"]) > MAX_LOG_MESSAGES:
        traffic_data["log_messages"] = traffic_data["log_messages"][:MAX_LOG_MESSAGES]
    
    logger.info(message)

# MQTT Functions
def on_mqtt_connect(client, userdata, flags, rc):
    """Callback when connected to MQTT broker"""
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        logger.info("Connected to MQTT broker")
        
        # Subscribe to topics
        for topic in MQTT_TOPICS:
            client.subscribe(topic)
            logger.info(f"Subscribed to {topic}")
        
        add_log_message("Dashboard connected to MQTT broker")
    else:
        mqtt_connected = False
        logger.error(f"Failed to connect to MQTT broker with code {rc}")

def on_mqtt_disconnect(client, userdata, rc):
    """Callback when disconnected from MQTT broker"""
    global mqtt_connected
    mqtt_connected = False
    logger.warning("Disconnected from MQTT broker")
    add_log_message("Dashboard disconnected from MQTT broker")

def on_mqtt_message(client, userdata, msg):
    """Callback when message received from MQTT broker"""
    try:
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        logger.debug(f"MQTT message received: {topic}: {payload}")
        
        if topic == "traffic/signals":
            process_signal_message(payload)
        elif topic == "traffic/status":
            process_status_message(payload)
        elif topic == "traffic/detection":
            process_detection_message(payload)
    except Exception as e:
        logger.error(f"Error processing MQTT message: {str(e)}")

def process_signal_message(message):
    """Process signal state message from main controller"""
    try:
        # Format: L1-GREEN-30;L2-RED-30
        lane_states = message.split(';')
        
        for lane_state in lane_states:
            if not lane_state:
                continue
                
            parts = lane_state.split('-')
            if len(parts) >= 3:
                lane_id = parts[0]
                state = parts[1]
                time_left = int(parts[2])
                
                if lane_id in traffic_data["lanes"]:
                    # Update lane state
                    old_state = traffic_data["lanes"][lane_id]["state"]
                    traffic_data["lanes"][lane_id]["state"] = state
                    traffic_data["lanes"][lane_id]["time_left"] = time_left
                    
                    # Log state changes
                    if old_state != state:
                        add_log_message(f"Lane {lane_id} changed from {old_state} to {state}")
        
        # Update timestamp
        traffic_data["last_update"] = time.time()
    except Exception as e:
        logger.error(f"Error processing signal message: {str(e)}")

def process_status_message(message):
    """Process status message from controller"""
    try:
        if message.startswith("STATUS:"):
            # Remove STATUS: prefix
            status_data = message[7:]
            
            # Process each lane status
            lane_statuses = status_data.split(';')
            
            for lane_status in lane_statuses:
                if not lane_status:
                    continue
                    
                # Check if emergency flag is present
                emergency = "-EMER" in lane_status
                if emergency:
                    lane_status = lane_status.replace("-EMER", "")
                
                parts = lane_status.split('-')
                if len(parts) >= 3:
                    lane_id = parts[0]
                    state = parts[1]
                    time_left = int(parts[2])
                    
                    if lane_id in traffic_data["lanes"]:
                        traffic_data["lanes"][lane_id]["state"] = state
                        traffic_data["lanes"][lane_id]["time_left"] = time_left
                        traffic_data["lanes"][lane_id]["emergency"] = emergency
            
            # Update timestamp
            traffic_data["last_update"] = time.time()
    except Exception as e:
        logger.error(f"Error processing status message: {str(e)}")

def process_detection_message(message):
    """Process vehicle detection message"""
    try:
        detection_data = json.loads(message)
        
        if "lanes" in detection_data:
            for lane_id, lane_info in detection_data["lanes"].items():
                if lane_id in traffic_data["lanes"]:
                    traffic_data["lanes"][lane_id]["count"] = lane_info.get("count", 0)
                    
                    # Check if emergency vehicle was detected
                    if lane_info.get("emergency", False):
                        emergency_type = lane_info.get("emergency_type", "unknown")
                        emergency_confidence = lane_info.get("emergency_confidence", 0.0)
                        
                        traffic_data["lanes"][lane_id]["emergency"] = True
                        traffic_data["lanes"][lane_id]["emergency_type"] = emergency_type
                        traffic_data["lanes"][lane_id]["emergency_confidence"] = emergency_confidence
                        
                        # Determine detection source based on confidence and type
                        detection_source = "YOLO"
                        if emergency_type in ["ambulance", "fire_truck", "police_car"]:
                            detection_source = "YOLO"
                        elif emergency_confidence < 0.7:  # Lower confidence typically means OCR detection
                            detection_source = "OCR"
                        
                        # Add formatted emergency message with vehicle type and confidence
                        message = f"⚠️ EMERGENCY: {emergency_type.upper()} detected in lane {lane_id} " \
                                 f"(confidence: {emergency_confidence:.2f}, source: {detection_source}) ⚠️"
                        add_log_message(message)
                        
                        # Flash UI notification - this will be picked up by JS
                        traffic_data["emergency_alert"] = {
                            "lane": lane_id,
                            "type": emergency_type,
                            "confidence": emergency_confidence,
                            "source": detection_source,
                            "time": time.time()
                        }
                    elif traffic_data["lanes"][lane_id]["emergency"]:
                        # Emergency vehicle is no longer detected
                        traffic_data["lanes"][lane_id]["emergency"] = False
                        traffic_data["lanes"][lane_id]["emergency_type"] = None
                        traffic_data["lanes"][lane_id]["emergency_confidence"] = 0.0
                        add_log_message(f"Emergency vehicle has passed lane {lane_id}")
        
        # Update timestamp
        traffic_data["last_update"] = time.time()
    except json.JSONDecodeError:
        logger.error("Invalid JSON in detection message")
    except Exception as e:
        logger.error(f"Error processing detection message: {str(e)}")

def setup_mqtt_client():
    """Set up MQTT client and connect to broker"""
    global mqtt_client
    
    try:
        mqtt_client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_disconnect = on_mqtt_disconnect
        mqtt_client.on_message = on_mqtt_message
        
        # Connect to broker
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        
        # Start MQTT loop in a separate thread
        mqtt_client.loop_start()
        
        logger.info(f"MQTT client initialized, connecting to {MQTT_BROKER}:{MQTT_PORT}")
    except Exception as e:
        logger.error(f"Failed to set up MQTT client: {str(e)}")
        logger.info("Continuing without MQTT connection")

def create_html_templates():
    """Create HTML templates directory and files if they don't exist"""
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    # Create index.html template with only 2 lanes
    index_path = os.path.join(templates_dir, 'index.html')
    try:
        os.remove(index_path)  # Remove existing template to force update
        logger.info(f"Removed existing template: {index_path}")
    except FileNotFoundError:
        pass
        
    with open(index_path, 'w') as f:
        f.write('''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Traffic Control System</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        .header {
            background-color: #333;
            color: white;
            padding: 15px 20px;
            text-align: center;
            border-radius: 5px 5px 0 0;
        }
        .status-panel {
            background-color: white;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            overflow: hidden;
        }
        .traffic-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-bottom: 20px;
        }
        .lane-card {
            background-color: white;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            padding: 15px;
            position: relative;
        }
        .lane-card h3 {
            margin-top: 0;
            border-bottom: 1px solid #eee;
            padding-bottom: 10px;
        }
        .lane-card.emergency {
            border: 2px solid red;
            animation: emergency-pulse 1s infinite;
        }
        .traffic-light {
            display: flex;
            justify-content: space-around;
            margin: 15px 0;
        }
        .light {
            width: 50px;
            height: 50px;
            border-radius: 50%;
            background-color: #ccc;
            border: 2px solid #999;
        }
        .red { background-color: #ffcccc; }
        .yellow { background-color: #ffffcc; }
        .green { background-color: #ccffcc; }
        .active-red { background-color: #ff0000; box-shadow: 0 0 10px #ff0000; }
        .active-yellow { background-color: #ffff00; box-shadow: 0 0 10px #ffff00; }
        .active-green { background-color: #00ff00; box-shadow: 0 0 10px #00ff00; }
        .lane-details {
            margin-top: 15px;
        }
        .lane-details p {
            margin: 5px 0;
        }
        .log-panel {
            background-color: white;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            padding: 15px;
            height: 300px;
            overflow-y: auto;
        }
        .log-item {
            padding: 5px 0;
            border-bottom: 1px solid #eee;
        }
        .log-timestamp {
            color: #666;
            font-size: 0.8em;
        }
        .controls {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        .control-group {
            flex: 1;
            margin-right: 10px;
        }
        button {
            background-color: #4CAF50;
            color: white;
            border: none;
            padding: 10px 15px;
            text-align: center;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
            margin: 4px 2px;
            cursor: pointer;
            border-radius: 4px;
        }
        button.emergency-btn {
            background-color: #f44336;
        }
        button:hover {
            opacity: 0.8;
        }
        select {
            padding: 9px 15px;
        }
        @keyframes emergency-pulse {
            0% { box-shadow: 0 0 0 0 rgba(255,0,0,0.7); }
            70% { box-shadow: 0 0 0 10px rgba(255,0,0,0); }
            100% { box-shadow: 0 0 0 0 rgba(255,0,0,0); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>AI Traffic Control System</h1>
            <p>Real-time traffic monitoring and signal control</p>
        </div>
        
        <div class="status-panel">
            <div class="header" style="background-color: #4CAF50;">
                <h2>System Status: <span id="system-status">Operational</span></h2>
                <p>Last Update: <span id="last-update">N/A</span></p>
            </div>
            
            <div class="controls">
                <div class="control-group">
                    <select id="lane-select">
                        <option value="L1">Lane 1</option>
                        <option value="L2">Lane 2</option>
                    </select>
                    <button class="emergency-btn" onclick="triggerEmergency()">Emergency Override</button>
                </div>
                <div class="control-group" style="text-align: right;">
                    <button onclick="resetSystem()">Reset System</button>
                </div>
            </div>
        </div>
        
        <div class="traffic-grid" id="traffic-grid">
            <!-- Lane cards will be inserted here -->
        </div>
        
        <div class="log-panel">
            <h2>System Log</h2>
            <div id="log-content">
                <!-- Log entries will be inserted here -->
            </div>
        </div>
    </div>
    
    <script>
        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            // Start data polling
            fetchTrafficData();
            setInterval(fetchTrafficData, 1000);
            
            // Start log polling
            fetchLogData();
            setInterval(fetchLogData, 5000);
        });
        
        // Fetch traffic data
        function fetchTrafficData() {
            fetch('/api/traffic-data')
                .then(response => response.json())
                .then(data => {
                    updateTrafficDisplay(data);
                })
                .catch(error => console.error('Error fetching traffic data:', error));
        }
        
        // Fetch log data
        function fetchLogData() {
            fetch('/api/log')
                .then(response => response.json())
                .then(data => {
                    updateLogDisplay(data.logs);
                })
                .catch(error => console.error('Error fetching log data:', error));
        }
        
        // Update traffic display
        function updateTrafficDisplay(data) {
            // Update system status
            document.getElementById('system-status').textContent = data.system_status;
            
            // Update last update time
            const lastUpdate = new Date(data.last_update * 1000).toLocaleTimeString();
            document.getElementById('last-update').textContent = lastUpdate;
            
            // Create or update lane cards
            const trafficGrid = document.getElementById('traffic-grid');
            trafficGrid.innerHTML = '';
            
            // Only display L1 and L2
            const laneOrder = ["L1", "L2"];
            
            for (const laneId of laneOrder) {
                const laneData = data.lanes[laneId];
                if (!laneData) continue;
                
                const card = document.createElement('div');
                card.className = 'lane-card' + (laneData.emergency ? ' emergency' : '');
                
                // Create card content
                card.innerHTML = `
                    <h3>${laneId}</h3>
                    <div class="traffic-light">
                        <div class="light red ${laneData.state === 'RED' ? 'active-red' : ''}"></div>
                        <div class="light yellow ${laneData.state === 'YELLOW' ? 'active-yellow' : ''}"></div>
                        <div class="light green ${laneData.state === 'GREEN' ? 'active-green' : ''}"></div>
                    </div>
                    <div class="lane-details">
                        <p>Current State: <strong>${laneData.state}</strong></p>
                        <p>Time Left: <strong>${laneData.time_left} seconds</strong></p>
                        <p>Vehicle Count: <strong>${laneData.count}</strong></p>
                        <p>Emergency Vehicle: <strong>${laneData.emergency ? 'YES' : 'No'}</strong></p>
                    </div>
                `;
                
                trafficGrid.appendChild(card);
            }
        }
        
        // Update log display
        function updateLogDisplay(logs) {
            const logContent = document.getElementById('log-content');
            logContent.innerHTML = '';
            
            logs.forEach(log => {
                const logItem = document.createElement('div');
                logItem.className = 'log-item';
                logItem.innerHTML = `
                    <span class="log-timestamp">${log.timestamp}</span>
                    <span class="log-message">${log.message}</span>
                `;
                logContent.appendChild(logItem);
            });
        }
        
        // Trigger emergency override
        function triggerEmergency() {
            const laneId = document.getElementById('lane-select').value;
            
            fetch('/api/system-control', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    command: 'emergency_override',
                    params: {
                        lane_id: laneId
                    }
                })
            })
            .then(response => response.json())
            .then(data => {
                console.log('Emergency response:', data);
                // Refresh immediately
                fetchTrafficData();
                fetchLogData();
            })
            .catch(error => console.error('Error triggering emergency:', error));
        }
        
        // Reset system
        function resetSystem() {
            if (confirm('Are you sure you want to reset the system?')) {
                fetch('/api/system-control', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        command: 'reset_system'
                    })
                })
                .then(response => response.json())
                .then(data => {
                    console.log('Reset response:', data);
                    // Refresh immediately
                    fetchTrafficData();
                    fetchLogData();
                })
                .catch(error => console.error('Error resetting system:', error));
            }
        }
    </script>
</body>
</html>''')
        logger.info(f"Created template file: {index_path}")

if __name__ == "__main__":
    try:
        # Create templates
        create_html_templates()
        
        # Set up MQTT client (commented out to avoid connection issues)
        try:
            setup_mqtt_client()
        except Exception as e:
            logger.warning(f"MQTT setup failed: {str(e)}. Continuing without MQTT.")
        
        # Add initial log message
        add_log_message("Traffic monitoring dashboard started")
        
        # Start Flask app with port 8080 instead of 5000
        app.run(host='0.0.0.0', port=8080, debug=True)
    except KeyboardInterrupt:
        logger.info("Dashboard stopped by user")
    except Exception as e:
        logger.error(f"Error starting dashboard: {str(e)}")
    finally:
        # Clean up MQTT client
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect() 