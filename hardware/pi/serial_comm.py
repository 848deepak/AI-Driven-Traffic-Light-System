#!/usr/bin/env python3
import time
import serial
import logging
import threading
import paho.mqtt.client as mqtt

logger = logging.getLogger('serial_comm')

class CommunicationHandler:
    """
    Communication handler for traffic light controller.
    Supports both Serial and MQTT communication methods.
    """
    def __init__(self, comm_port, baud_rate=115200, use_mqtt=False, mqtt_broker="localhost"):
        """
        Initialize communication handler
        
        Args:
            comm_port: Serial port name (e.g., /dev/ttyUSB0) or MQTT topic or "None" to disable
            baud_rate: Serial baud rate (only for serial mode)
            use_mqtt: If True, use MQTT instead of serial
            mqtt_broker: MQTT broker address (only for MQTT mode)
        """
        self.comm_port = comm_port
        self.baud_rate = baud_rate
        self.use_mqtt = use_mqtt
        self.mqtt_broker = mqtt_broker
        self.mqtt_topic = "traffic/signals"
        
        self.serial_conn = None
        self.mqtt_client = None
        
        # Cache for last sent signal state
        self.last_signal_state = ""
        
        # Disable flag - allows running without actual communication
        self.disabled = comm_port == "None" or comm_port is None
        
        if not self.disabled:
            # Open connection
            self._open_connection()
            logger.info(f"Communication handler initialized using {'MQTT' if use_mqtt else 'Serial'}")
        else:
            logger.info("Communication handler initialized in disabled mode")
    
    def _open_connection(self):
        """Open communication connection (either Serial or MQTT)"""
        if self.disabled:
            return
            
        try:
            if self.use_mqtt:
                # Set up MQTT client
                self.mqtt_client = mqtt.Client()
                self.mqtt_client.on_connect = self._on_mqtt_connect
                self.mqtt_client.connect(self.mqtt_broker, 1883, 60)
                self.mqtt_client.loop_start()
                logger.info(f"MQTT client connected to {self.mqtt_broker}")
            else:
                # Check if port exists for Raspberry Pi
                import glob
                available_ports = glob.glob('/dev/tty*')
                if self.comm_port not in available_ports:
                    logger.warning(f"Serial port {self.comm_port} not found. Available ports: {available_ports}")
                    # Try to find an alternative port
                    for port in available_ports:
                        if 'USB' in port or 'ACM' in port:
                            logger.info(f"Trying alternative port: {port}")
                            self.comm_port = port
                            break
                
                # Set up Serial connection
                try:
                    self.serial_conn = serial.Serial(
                        port=self.comm_port,
                        baudrate=self.baud_rate,
                        timeout=1
                    )
                    # Wait for Arduino to reset after serial connection
                    time.sleep(2)
                    logger.info(f"Serial connection established on {self.comm_port}")
                except serial.SerialException as e:
                    logger.error(f"Failed to open serial port {self.comm_port}: {str(e)}")
                    self.disabled = True
        except Exception as e:
            logger.error(f"Failed to open communication: {str(e)}")
            if not self.use_mqtt:
                logger.warning("Trying MQTT as fallback...")
                self.use_mqtt = True
                self.mqtt_broker = "localhost"
                self._open_connection()
    
    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """Callback when MQTT client connects"""
        if rc == 0:
            logger.info("Connected to MQTT broker")
        else:
            logger.error(f"Failed to connect to MQTT broker with code {rc}")
    
    def send_signal_state(self, signal_state):
        """
        Send signal state to the controller
        
        Args:
            signal_state: Formatted signal state string (e.g., "L1-GREEN-30;L2-RED-30")
            
        Returns:
            success: True if message was sent successfully
        """
        if self.disabled:
            # Just log the state in disabled mode
            logger.debug(f"Signal state (disabled mode): {signal_state}")
            return True
            
        # Skip sending if state hasn't changed
        if signal_state == self.last_signal_state:
            return True
        
        self.last_signal_state = signal_state
        
        try:
            if self.use_mqtt:
                # Send via MQTT
                result = self.mqtt_client.publish(self.mqtt_topic, signal_state)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.error(f"Failed to publish MQTT message: {result.rc}")
                    return False
                logger.debug(f"MQTT message sent: {signal_state}")
            else:
                # Send via Serial
                if self.serial_conn is None or not self.serial_conn.is_open:
                    logger.error("Serial connection is not open")
                    # Try to reopen
                    self._open_connection()
                    if self.serial_conn is None or not self.serial_conn.is_open:
                        return False
                
                # Add newline for Arduino parsing
                message = signal_state + "\n"
                self.serial_conn.write(message.encode())
                self.serial_conn.flush()
                logger.debug(f"Serial message sent: {signal_state}")
            
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {str(e)}")
            # Try to reopen the connection
            self._open_connection()
            return False
    
    def send_message(self, message):
        """
        Send a general message (helper method)
        
        Args:
            message: Message to send
            
        Returns:
            success: True if message was sent successfully
        """
        if self.disabled:
            logger.debug(f"Message (disabled mode): {message}")
            return True
            
        try:
            if self.use_mqtt:
                # Send via MQTT
                result = self.mqtt_client.publish(f"{self.mqtt_topic}/message", message)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.error(f"Failed to publish MQTT message: {result.rc}")
                    return False
                logger.debug(f"MQTT message sent: {message}")
            else:
                # Send via Serial
                if self.serial_conn is None or not self.serial_conn.is_open:
                    logger.error("Serial connection is not open")
                    return False
                
                # Add newline for Arduino parsing
                message = message + "\n"
                self.serial_conn.write(message.encode())
                self.serial_conn.flush()
                logger.debug(f"Serial message sent: {message}")
            
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {str(e)}")
            return False
    
    def receive_message(self, timeout=1.0):
        """
        Receive message from controller
        
        Args:
            timeout: Timeout in seconds
            
        Returns:
            message: Received message string or None
        """
        if self.disabled:
            return None
            
        try:
            if self.use_mqtt:
                # Not implemented for MQTT - would need a subscription
                logger.warning("receive_message not implemented for MQTT mode")
                return None
            else:
                # Serial read
                if self.serial_conn is None or not self.serial_conn.is_open:
                    logger.error("Serial connection is not open")
                    return None
                
                # Check if data is available
                if self.serial_conn.in_waiting > 0:
                    response = self.serial_conn.readline().decode('utf-8').strip()
                    logger.debug(f"Serial message received: {response}")
                    return response
                
                return None
        except Exception as e:
            logger.error(f"Failed to receive message: {str(e)}")
            return None
    
    def close(self):
        """Close communication connection"""
        if self.disabled:
            return
            
        try:
            if self.use_mqtt and self.mqtt_client is not None:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
                logger.info("MQTT client disconnected")
            elif not self.use_mqtt and self.serial_conn is not None:
                self.serial_conn.close()
                logger.info("Serial connection closed")
        except Exception as e:
            logger.error(f"Error closing communication: {str(e)}")

# For testing
if __name__ == "__main__":
    # Enable console logging
    logging.basicConfig(level=logging.DEBUG)
    
    # Simple test for serial communication
    try:
        # For testing, you might need to change the port
        comm = CommunicationHandler("/dev/ttyUSB0", use_mqtt=False)
        
        # Test sending a few signal states
        test_states = [
            "L1-GREEN-30;L2-RED-30;L3-RED-30;L4-RED-30",
            "L1-YELLOW-5;L2-RED-25;L3-RED-25;L4-RED-25",
            "L1-RED-30;L2-GREEN-30;L3-RED-30;L4-RED-30"
        ]
        
        for state in test_states:
            print(f"Sending: {state}")
            comm.send_signal_state(state)
            
            # Wait for response
            time.sleep(1)
            response = comm.receive_message()
            if response:
                print(f"Received: {response}")
            
            time.sleep(3)
        
        comm.close()
        
    except KeyboardInterrupt:
        print("Test stopped by user")
    except Exception as e:
        print(f"Test error: {str(e)}") 