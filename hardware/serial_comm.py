#!/usr/bin/env python3
import serial
import time
import logging
import os

logger = logging.getLogger('serial_comm')

class CommunicationHandler:
    """
    Handles communication with Arduino/ESP32 via serial
    """
    
    def __init__(self, port, baudrate=115200, timeout=1):
        """
        Initialize serial communication
        
        Args:
            port: Serial port (e.g., /dev/ttyUSB0)
            baudrate: Serial baudrate
            timeout: Read timeout in seconds
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.connected = False
        
        # Try to connect to serial port
        self.connect()
    
    def connect(self):
        """Connect to the serial port"""
        try:
            # Check if port exists (for Unix-like systems)
            if os.name == 'posix' and not os.path.exists(self.port):
                logger.warning(f"Serial port {self.port} does not exist")
                self.connected = False
                return False
            
            # Create serial connection
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            
            # Wait for Arduino to reset
            time.sleep(2)
            
            # Flush input buffer
            self.ser.reset_input_buffer()
            
            self.connected = True
            logger.info(f"Connected to {self.port} at {self.baudrate} baud")
            return True
            
        except serial.SerialException as e:
            logger.error(f"Failed to connect to {self.port}: {str(e)}")
            self.connected = False
            return False
    
    def send_signal_state(self, signal_state):
        """
        Send traffic signal state to controller
        
        Args:
            signal_state: String with signal state (e.g., L1-RED-30;L2-GREEN-30)
            
        Returns:
            success: True if sent successfully, False otherwise
        """
        return self.send_message(signal_state)
    
    def send_message(self, message):
        """
        Send a message via serial
        
        Args:
            message: Message to send
            
        Returns:
            success: True if sent successfully, False otherwise
        """
        if not self.connected:
            if not self.connect():
                logger.warning("Not connected to serial port. Message not sent.")
                return False
        
        try:
            # Add newline if not present
            if not message.endswith('\n'):
                message += '\n'
            
            # Send message
            self.ser.write(message.encode('utf-8'))
            self.ser.flush()
            
            logger.debug(f"Sent message: {message.strip()}")
            return True
            
        except serial.SerialException as e:
            logger.error(f"Failed to send message: {str(e)}")
            self.connected = False
            return False
    
    def read_response(self, timeout=1.0):
        """
        Read response from controller
        
        Args:
            timeout: Read timeout in seconds
            
        Returns:
            response: Response string or None if timeout or error
        """
        if not self.connected:
            return None
        
        try:
            # Set timeout
            self.ser.timeout = timeout
            
            # Read line
            response = self.ser.readline().decode('utf-8').strip()
            
            if response:
                logger.debug(f"Received response: {response}")
                return response
            else:
                return None
                
        except serial.SerialException as e:
            logger.error(f"Failed to read response: {str(e)}")
            self.connected = False
            return None
    
    def close(self):
        """Close serial connection"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.connected = False
            logger.info("Serial connection closed")

if __name__ == "__main__":
    # Setup logging for testing
    logging.basicConfig(level=logging.DEBUG)
    
    # Test communication
    comm = CommunicationHandler("/dev/ttyUSB0")
    
    # Send test message
    comm.send_message("L1-GREEN-30;L2-RED-30")
    
    # Read response
    response = comm.read_response()
    if response:
        print(f"Arduino response: {response}")
    
    # Close connection
    comm.close() 