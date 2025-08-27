#!/usr/bin/env python3
import cv2
import numpy as np
import time
import os
import threading
import logging
import json
import re
import sys
import argparse

from ultralytics import YOLO

# Local imports
from traffic_logic import TrafficController
from serial_comm import CommunicationHandler

# OCR imports
try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False
    logging.warning("pytesseract not available, falling back to YOLO-only detection")

try:
    import easyocr
    EASYOCR_AVAILABLE = True
    # Initialize EasyOCR reader (only once to save resources)
    reader = easyocr.Reader(['en'], gpu=False)  # Use GPU if available
except ImportError:
    EASYOCR_AVAILABLE = False
    logging.warning("easyocr not available, falling back to YOLO-only detection")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='traffic_system.log'
)
logger = logging.getLogger('traffic_main')

# Vehicle classes from COCO dataset used by YOLOv8
VEHICLE_CLASSES = [2, 3, 5, 7]  # car, motorcycle, bus, truck

# Emergency vehicle classes - different options:
# 1. Using standard COCO classes that might be emergency: person(0) potentially (which could be a manual override)
# 2. If you have a custom model, change these to match your custom class IDs
# 3. If your model can distinguish ambulance/firetruck directly, add their class IDs
EMERGENCY_CLASSES = {
    "ambulance": 8,      # Custom class ID for ambulance (if available in your model)
    "fire_truck": 9,     # Custom class ID for fire truck (if available in your model)
    "police_car": 10,    # Custom class ID for police car (if available in your model)
    "standard_coco": [0] # Person class as fallback (emergency personnel might be visible)
}

# OCR keywords for emergency vehicle detection
EMERGENCY_KEYWORDS = [
    "ambulance", "emergency", "police", "rescue", "fire", "paramedic", 
    "emt", "911", "999", "112", "medic", "urgent", "sheriff", "trooper",
    "highway patrol", "state police"
]

# Confidence thresholds
YOLO_CONFIDENCE_THRESHOLD = 0.5
EMERGENCY_CONFIDENCE_THRESHOLD = 0.6  # Higher threshold for emergency vehicles
OCR_CONFIDENCE_THRESHOLD = 0.4  # Threshold for OCR text detection

# Flag to enable emergency vehicle detection simulation for testing
SIMULATE_EMERGENCY = False
EMERGENCY_SIMULATION_INTERVAL = 60  # seconds between simulated emergency vehicles

def test_cameras():
    # Try different camera indices
    for camera_idx in range(3):  # Try cameras 0, 1, 2
        print(f"Trying camera index {camera_idx}")
        cap = cv2.VideoCapture(camera_idx)
        
        if not cap.isOpened():
            print(f"Camera {camera_idx} not available")
            continue
        
        print(f"Camera {camera_idx} opened successfully")
        
        # Try to read 10 frames
        for i in range(10):
            ret, frame = cap.read()
            if ret:
                print(f"Frame {i} read successfully")
                # Show frame
                cv2.imshow(f"Camera {camera_idx}", frame)
                cv2.waitKey(100)
            else:
                print(f"Frame {i} read failed")
        
        cap.release()
        cv2.destroyAllWindows()

class TrafficDetectionSystem:
    def __init__(self, model_path="model/yolov8n.pt", camera_source=0, comm_port="/dev/ttyUSB0"):
        """
        Initialize the traffic detection system
        
        Args:
            model_path: Path to YOLOv8 model
            camera_source: Camera ID or video file path
            comm_port: Serial port for communication with Arduino/ESP32
        """
        self.model = None
        self.model_path = model_path
        self.camera_source = camera_source
        self.comm_port = comm_port
        
        # Traffic lanes configuration - MODIFIED FOR 2 LANES
        self.lanes = {
            "L1": {"bounds": (0, 0.5), "count": 0, "emergency": False, "emergency_type": None, "emergency_confidence": 0.0},
            "L2": {"bounds": (0.5, 1.0), "count": 0, "emergency": False, "emergency_type": None, "emergency_confidence": 0.0}
        }
        
        # Initialize components
        self.load_model()
        self.cap = None
        self.setup_camera()
        self.traffic_controller = TrafficController(self.lanes.keys())
        self.comm_handler = CommunicationHandler(self.comm_port)
        
        # Status flags
        self.running = False
        
        # Last time detection data was sent to dashboard
        self.last_detection_update = 0
        
        # For emergency vehicle simulation
        self.last_emergency_time = 0
        
        # Preprocess OCR keywords for more efficient matching
        self.emergency_keywords_pattern = re.compile(r'\b(' + '|'.join(EMERGENCY_KEYWORDS) + r')\b', re.IGNORECASE)
        
    def load_model(self):
        """Load YOLOv8 model"""
        try:
            logger.info(f"Loading YOLOv8 model from {self.model_path}")
            self.model = YOLO(self.model_path)
            logger.info("Model loaded successfully")
            
            # Log available classes in the model
            logger.info(f"Model classes: {self.model.names}")
        except Exception as e:
            logger.error(f"Error loading model: {str(e)}")
            raise
    
    def setup_camera(self):
        """Set up camera or video source with robust error handling for Raspberry Pi 5"""
        max_retries = 5
        retry_count = 0
        
        # Check if source is a video file
        is_video_file = isinstance(self.camera_source, str) and (
            self.camera_source.endswith('.mp4') or 
            self.camera_source.endswith('.avi') or
            self.camera_source.endswith('.mov')
        )
        
        while retry_count < max_retries:
            try:
                if is_video_file:
                    logger.info(f"Opening video file: {self.camera_source}")
                else:
                    logger.info(f"Setting up camera source: {self.camera_source} (attempt {retry_count+1})")
                
                self.cap = cv2.VideoCapture(self.camera_source)
                
                if not self.cap.isOpened():
                    retry_count += 1
                    logger.warning(f"Failed to open camera, retrying ({retry_count}/{max_retries})...")
                    
                    # Try alternate camera index if numeric source
                    if isinstance(self.camera_source, int) and retry_count == 2:
                        alt_source = 0 if self.camera_source > 0 else 1
                        logger.info(f"Trying alternate camera index: {alt_source}")
                        self.camera_source = alt_source
                    
                    time.sleep(2)  # Wait before retry
                    continue
                
                # Camera opened successfully
                logger.info("Camera connected successfully")
                
                # Only set properties for actual cameras (not video files)
                if not is_video_file:
                    # Try different formats for Raspberry Pi camera compatibility
                    # MJPG format usually works well with Pi cameras
                    self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
                    
                    # Set resolution - lower for Pi Camera to ensure performance
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    
                    # Reduce buffer size to minimize latency
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    
                    # Get actual camera properties after setting
                    actual_width = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                    actual_height = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
                    
                    logger.info(f"Camera properties: {actual_width}x{actual_height} @ {actual_fps}fps")
                
                # Read a test frame to validate camera
                ret, test_frame = self.cap.read()
                if not ret or test_frame is None:
                    logger.warning("Test frame read failed, retrying...")
                    retry_count += 1
                    self.cap.release()
                    time.sleep(1)
                    continue
                    
                logger.info(f"Camera setup successful: {'Video file' if is_video_file else 'Camera'}")
                return
                
            except Exception as e:
                retry_count += 1
                logger.error(f"Camera setup error: {str(e)}, retrying ({retry_count}/{max_retries})...")
                time.sleep(2)  # Wait before retry
        
        # If we get here, all retries failed
        logger.error(f"Failed to set up camera after {max_retries} attempts")
        
        # Fallback to test mode with static image if camera setup fails
        logger.warning("Falling back to test mode with static image")
        self.cap = None  # We'll handle this in the run() method
    
    def determine_lane(self, x_center, img_width):
        """
        Determine which lane a detected object belongs to based on its position
        
        Args:
            x_center: x-coordinate of object center
            img_width: width of the image
            
        Returns:
            lane_id: ID of the lane (L1, L2)
        """
        x_ratio = x_center / img_width
        
        for lane_id, lane_info in self.lanes.items():
            min_bound, max_bound = lane_info["bounds"]
            if min_bound <= x_ratio < max_bound:
                return lane_id
        
        return None
    
    def is_emergency_vehicle(self, class_id, confidence):
        """
        Check if the detected class is an emergency vehicle
        
        Args:
            class_id: Class ID of the detected object
            confidence: Detection confidence score
            
        Returns:
            (is_emergency, emergency_type, confidence): Tuple with boolean flag, type of emergency vehicle, and confidence score
        """
        # Check if confidence exceeds emergency threshold
        if confidence < EMERGENCY_CONFIDENCE_THRESHOLD:
            return False, None, 0.0
            
        # Check for specific emergency vehicle classes
        if class_id == EMERGENCY_CLASSES["ambulance"]:
            return True, "ambulance", confidence
        elif class_id == EMERGENCY_CLASSES["fire_truck"]:
            return True, "fire_truck", confidence
        elif class_id == EMERGENCY_CLASSES["police_car"]:
            return True, "police_car", confidence
        # Check standard COCO classes that might indicate emergency
        elif class_id in EMERGENCY_CLASSES["standard_coco"]:
            return True, "emergency_personnel", confidence
        
        return False, None, 0.0
    
    def check_ocr_for_emergency(self, image, bbox):
        """
        Run OCR on a vehicle bounding box to check for emergency text
        
        Args:
            image: Source image
            bbox: Bounding box (x1, y1, x2, y2)
            
        Returns:
            (is_emergency, emergency_type, confidence): Tuple with boolean flag, detected text, and confidence
        """
        x1, y1, x2, y2 = map(int, bbox[:4])
        
        # Ensure bbox is within image boundaries
        h, w = image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        # Extract vehicle ROI
        try:
            roi = image[y1:y2, x1:x2]
            # Skip if ROI is empty
            if roi.size == 0 or roi.shape[0] == 0 or roi.shape[1] == 0:
                return False, None, 0.0
                
            # Preprocess image for better OCR results
            # Convert to grayscale
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            # Apply slight blur to reduce noise
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            # Apply adaptive thresholding
            thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
            
            text = ""
            confidence = 0.0
            
            # Use pytesseract if available
            if PYTESSERACT_AVAILABLE:
                try:
                    text = pytesseract.image_to_string(thresh).lower()
                    # Simple confidence estimate based on text length
                    confidence = min(0.5 + len(text) / 100, 0.9) if text else 0.0
                except Exception as e:
                    logger.warning(f"Pytesseract OCR failed: {str(e)}")
            
            # Use EasyOCR if available (more accurate but slower)
            if not text and EASYOCR_AVAILABLE:
                try:
                    results = reader.readtext(thresh)
                    if results:
                        # Combine all text with confidence > threshold
                        texts = []
                        conf_sum = 0
                        for (_, detected_text, conf) in results:
                            if conf > OCR_CONFIDENCE_THRESHOLD:
                                texts.append(detected_text.lower())
                                conf_sum += conf
                        text = " ".join(texts)
                        confidence = conf_sum / len(results) if results else 0.0
                except Exception as e:
                    logger.warning(f"EasyOCR failed: {str(e)}")
            
            # Check for emergency keywords in the detected text
            if text:
                matches = self.emergency_keywords_pattern.findall(text)
                if matches:
                    # Use first keyword found as the emergency type
                    emergency_type = matches[0]
                    logger.info(f"OCR detected emergency text: '{emergency_type}' with confidence {confidence:.2f}")
                    return True, emergency_type, confidence
            
            return False, None, 0.0
            
        except Exception as e:
            logger.error(f"Error in OCR processing: {str(e)}")
            return False, None, 0.0
    
    def process_frame(self, frame):
        """
        Process a single frame with YOLOv8 and OCR
        
        Args:
            frame: Image frame from camera
            
        Returns:
            processed_frame: Frame with detections drawn
        """
        # Reset counts
        for lane_id in self.lanes:
            self.lanes[lane_id]["count"] = 0
            self.lanes[lane_id]["emergency"] = False
            self.lanes[lane_id]["emergency_type"] = None
            self.lanes[lane_id]["emergency_confidence"] = 0.0
        
        # Create a copy for drawing
        processed_frame = frame.copy()
        
        # Draw lane boundaries
        h, w = frame.shape[:2]
        # Draw vertical line at middle (0.5)
        mid_x = int(w * 0.5)
        cv2.line(processed_frame, (mid_x, 0), (mid_x, h), (0, 255, 255), 2)
        cv2.putText(processed_frame, "L1 | L2", (mid_x - 50, 50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        
        # Run object detection
        try:
            # Skip if no model loaded
            if self.model is None:
                return processed_frame
            
            # Optimize for Raspberry Pi - resize input to smaller size if needed
            # Note: Only resize if frame is large, as YOLOv8 already has internal resizing
            if w > 640 or h > 640:
                inference_frame = cv2.resize(frame, (640, 480))
            else:
                inference_frame = frame
            
            # Run inference with YOLOv8
            results = self.model.predict(source=inference_frame, 
                                        conf=YOLO_CONFIDENCE_THRESHOLD, 
                                        iou=0.45,
                                        verbose=False)
            
            # No detections
            if len(results) == 0 or len(results[0].boxes) == 0:
                return processed_frame
            
            # Process detections
            for det in results[0].boxes.data.cpu().numpy():
                x1, y1, x2, y2, conf, cls = det
                
                if conf < YOLO_CONFIDENCE_THRESHOLD:  # Confidence threshold
                    continue
                    
                # Get class name and ID
                class_id = int(cls)
                class_name = self.model.names[class_id]
                
                # Calculate center
                x_center = (x1 + x2) / 2
                
                # Determine lane
                lane_id = self.determine_lane(x_center, w)
                if not lane_id:
                    continue
                    
                # Check if it's a vehicle
                is_vehicle = class_id in VEHICLE_CLASSES
                is_emergency, emergency_type, emergency_conf = self.is_emergency_vehicle(class_id, conf)
                
                # Process vehicle count 
                if is_vehicle:
                    self.lanes[lane_id]["count"] += 1
                    
                    # For vehicles, run OCR to detect emergency text if not already detected
                    # Limit OCR processing to every 5th frame to improve performance
                    if not is_emergency and (PYTESSERACT_AVAILABLE or EASYOCR_AVAILABLE) and self.lanes[lane_id]["count"] % 5 == 0:
                        ocr_is_emergency, ocr_emergency_type, ocr_conf = self.check_ocr_for_emergency(frame, (x1, y1, x2, y2))
                        
                        if ocr_is_emergency:
                            is_emergency = True
                            emergency_type = ocr_emergency_type
                            emergency_conf = ocr_conf
                            logger.info(f"OCR detected {emergency_type} on {class_name} in lane {lane_id} (conf: {emergency_conf:.2f})")
                
                # Update lane emergency status if confidence is higher than current
                if is_emergency and emergency_conf > self.lanes[lane_id]["emergency_confidence"]:
                    self.lanes[lane_id]["emergency"] = True
                    self.lanes[lane_id]["emergency_type"] = emergency_type
                    self.lanes[lane_id]["emergency_confidence"] = emergency_conf
                    logger.info(f"{emergency_type.capitalize()} detected in lane {lane_id} (conf: {emergency_conf:.2f})")
                
                # Draw bounding box
                # Color scheme: Red for emergency, Green for normal vehicles
                color = (0, 255, 0)  # Default: green (BGR) for normal vehicles
                if is_emergency:
                    # Use different colors based on detection method
                    if emergency_type == "ambulance":
                        color = (0, 0, 255)  # Red
                    elif emergency_type == "fire_truck":
                        color = (0, 0, 255)  # Red
                    elif emergency_type == "police_car":
                        color = (0, 0, 255)  # Red
                    else:
                        color = (0, 0, 255)  # Red for OCR detected emergency
                
                # Draw the bounding box
                cv2.rectangle(processed_frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                
                # Prepare the label text
                if is_emergency:
                    label = f"⚠️ {emergency_type.upper()} ({emergency_conf:.2f}) ⚠️"
                else:
                    label = f"{class_name} ({conf:.2f})"
                
                # Add lane information to label
                label += f" {lane_id}"
                
                # Draw the label with a background
                label_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                label_ymin = max(y1, label_size[1] + 10)
                cv2.rectangle(processed_frame, (int(x1), int(label_ymin - label_size[1] - 10)),
                            (int(x1 + label_size[0]), int(label_ymin)), color, -1)
                cv2.putText(processed_frame, label, (int(x1), int(label_ymin - 7)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        
        except Exception as e:
            logger.error(f"Error processing frame: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        
        # Add lane count information
        lane1_count = self.lanes["L1"]["count"]
        lane2_count = self.lanes["L2"]["count"]
        
        cv2.putText(processed_frame, f"Lane 1: {lane1_count} vehicles", (20, h - 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(processed_frame, f"Lane 2: {lane2_count} vehicles", (w - 250, h - 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        # Highlight emergency vehicle lanes
        for lane_id, lane_info in self.lanes.items():
            if lane_info["emergency"]:
                emergency_text = f"⚠️ EMERGENCY: {lane_info['emergency_type']} ⚠️"
                text_pos_x = 20 if lane_id == "L1" else w - 400
                cv2.putText(processed_frame, emergency_text, (text_pos_x, h - 20), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        # Send detection data to dashboard
        current_time = time.time()
        if current_time - self.last_detection_update >= 1:  # Send detection data every second
            self.send_detection_data()
            self.last_detection_update = current_time
        
        return processed_frame
    
    def send_detection_data(self):
        """Send vehicle detection data to dashboard via serial and MQTT"""
        # Create detection data object
        detection_data = {
            "lanes": {}
        }
        
        # Add lane data
        for lane_id, lane_info in self.lanes.items():
            detection_data["lanes"][lane_id] = {
                "count": lane_info["count"],
                "emergency": lane_info["emergency"],
                "emergency_type": lane_info["emergency_type"],
                "emergency_confidence": float(f"{lane_info['emergency_confidence']:.2f}")
            }
        
        # Serialize to JSON
        detection_json = json.dumps(detection_data)
        
        # Send via serial to Arduino
        self.comm_handler.send_message(f"DETECTION:{detection_json}")
        
        # Send via serial for dashboard to pick up
        print(f"DETECTION_DATA:{detection_json}")
        
        # Alternatively, if MQTT is available:
        try:
            import paho.mqtt.client as mqtt
            import paho.mqtt.publish as publish
            
            try:
                # Send detection data via MQTT for dashboard
                publish.single("traffic/detection", detection_json, hostname="localhost")
                logger.debug("Detection data sent via MQTT")
            except Exception as e:
                logger.error(f"Failed to publish MQTT message: {str(e)}")
        except ImportError:
            # MQTT not available, skip
            pass
    
    def run(self):
        """Main loop for traffic detection system with robust error handling"""
        self.running = True
        frame_count = 0
        last_signal_time = time.time()
        last_frame = None  # Store last successful frame
        fps_counter = 0
        fps_timer = time.time()
        fps = 0
        
        # Create a test image if we don't have a camera
        if self.cap is None:
            test_image = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(test_image, "Camera Not Available", (50, 240), 
                      cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            cv2.putText(test_image, "Test Mode Active", (50, 280), 
                      cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            last_frame = test_image
        
        while self.running:
            try:
                # Get frame
                if self.cap is not None:
                    ret, frame = self.cap.read()
                else:
                    # Use test image or generate simulated traffic
                    ret = True
                    if last_frame is not None:
                        frame = last_frame.copy()
                    else:
                        # Create a blank frame with message
                        frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(frame, "Test Mode - No Camera", (50, 240), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                
                # If frame reading failed but we have a previous frame, use it
                if not ret or frame is None:
                    logger.warning("Failed to read frame, attempting to reconnect camera...")
                    
                    # Try to reconnect camera
                    if self.cap is not None:
                        self.cap.release()
                    time.sleep(1)
                    self.setup_camera()
                    
                    # If we have a previous frame, use it
                    if last_frame is not None:
                        frame = last_frame.copy()
                    else:
                        # Create a blank frame with text
                        frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(frame, "Camera disconnected...", (50, 240), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                else:
                    # Store last successful frame
                    last_frame = frame.copy()
                
                # Process frame with detection model
                processed_frame = self.process_frame(frame)
                
                # Calculate FPS
                fps_counter += 1
                if time.time() - fps_timer >= 1.0:
                    fps = fps_counter
                    fps_counter = 0
                    fps_timer = time.time()
                
                # Add FPS to the frame
                cv2.putText(processed_frame, f"FPS: {fps}", (20, 30), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                # Show frame - only if running on a desktop environment
                try:
                    cv2.imshow("AI Traffic Control", processed_frame)
                except Exception as e:
                    # Headless environment might not support imshow
                    logger.warning(f"Could not display frame (headless mode?): {str(e)}")
                
                # Update traffic controller with new lane data
                signal_state = self.traffic_controller.update(self.lanes)
                
                # Send signal state to Arduino/ESP32 controller
                if time.time() - last_signal_time >= 1:  # Send updates every second
                    self.comm_handler.send_signal_state(signal_state)
                    last_signal_time = time.time()
                
                # Handle emergency vehicle simulation if enabled
                if SIMULATE_EMERGENCY and time.time() - self.last_emergency_time > EMERGENCY_SIMULATION_INTERVAL:
                    self.simulate_emergency()
                    self.last_emergency_time = time.time()
                
                # Handle keyboard interrupt
                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC key
                    break
                elif key == ord('e'):  # Press 'e' to simulate emergency
                    emergency_lane = "L1" if np.random.random() < 0.5 else "L2"
                    emergency_type = np.random.choice(["ambulance", "fire_truck", "police_car"])
                    self.lanes[emergency_lane]["emergency"] = True
                    self.lanes[emergency_lane]["emergency_type"] = emergency_type
                    self.lanes[emergency_lane]["emergency_confidence"] = 0.9  # High confidence for manual trigger
                    logger.info(f"MANUAL emergency trigger: {emergency_type} in lane {emergency_lane}")
                elif key == ord('o'):  # Press 'o' to simulate OCR-detected emergency
                    emergency_lane = "L1" if np.random.random() < 0.5 else "L2"
                    emergency_type = np.random.choice(EMERGENCY_KEYWORDS)
                    self.lanes[emergency_lane]["emergency"] = True
                    self.lanes[emergency_lane]["emergency_type"] = emergency_type
                    self.lanes[emergency_lane]["emergency_confidence"] = 0.65  # Medium confidence for OCR
                    logger.info(f"MANUAL OCR emergency trigger: {emergency_type} in lane {emergency_lane}")
                
                frame_count += 1
                
            except Exception as e:
                logger.error(f"Error in main loop: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(1)  # Avoid tight loop in case of error
        
        self.cleanup()
    
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources")
        self.running = False
        if self.cap is not None:
            self.cap.release()
        cv2.destroyAllWindows()
        self.comm_handler.close()

    def simulate_traffic(self, frame):
        """Generate simulated traffic for testing when camera is not available"""
        h, w = frame.shape[:2]
        
        # Define lane boundaries
        lane1_center = int(w * 0.25)  # 25% from left
        lane2_center = int(w * 0.75)  # 75% from left
        
        # Clear previous lanes
        for lane_id in self.lanes:
            self.lanes[lane_id]["count"] = 0
            self.lanes[lane_id]["emergency"] = False
            self.lanes[lane_id]["emergency_type"] = None
            self.lanes[lane_id]["emergency_confidence"] = 0.0
        
        # Randomly generate traffic for each lane
        # Lane 1 (left)
        lane1_vehicles = np.random.randint(0, 8)  # 0-7 vehicles
        self.lanes["L1"]["count"] = lane1_vehicles
        
        # Lane 2 (right)
        lane2_vehicles = np.random.randint(0, 6)  # 0-5 vehicles
        self.lanes["L2"]["count"] = lane2_vehicles
        
        # Draw vehicles for visualization
        for i in range(lane1_vehicles):
            y_pos = 100 + i * 50
            if y_pos < h - 50:
                cv2.rectangle(frame, (lane1_center-30, y_pos), (lane1_center+30, y_pos+40), (0, 255, 0), 2)
                cv2.putText(frame, "Car", (lane1_center-25, y_pos+25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        for i in range(lane2_vehicles):
            y_pos = 100 + i * 50
            if y_pos < h - 50:
                cv2.rectangle(frame, (lane2_center-30, y_pos), (lane2_center+30, y_pos+40), (0, 255, 0), 2)
                cv2.putText(frame, "Car", (lane2_center-25, y_pos+25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        # Randomly generate emergency vehicle (5% chance)
        if np.random.random() < 0.05:
            # Pick a lane for emergency vehicle
            emergency_lane = "L1" if np.random.random() < 0.5 else "L2"
            lane_center = lane1_center if emergency_lane == "L1" else lane2_center
            
            # Choose emergency type
            emergency_types = ["ambulance", "fire_truck", "police_car"]
            emergency_type = np.random.choice(emergency_types)
            
            # Update lane data
            self.lanes[emergency_lane]["emergency"] = True
            self.lanes[emergency_lane]["emergency_type"] = emergency_type
            self.lanes[emergency_lane]["emergency_confidence"] = 0.8 + np.random.random() * 0.2  # 0.8-1.0
            
            # Draw emergency vehicle
            y_pos = 200
            cv2.rectangle(frame, (lane_center-40, y_pos), (lane_center+40, y_pos+60), (0, 0, 255), 2)
            cv2.putText(frame, emergency_type.upper(), (lane_center-35, y_pos+30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
            
            logger.info(f"Simulated emergency vehicle: {emergency_type} in lane {emergency_lane}")
        
        # Draw lane divider
        mid_x = int(w * 0.5)
        cv2.line(frame, (mid_x, 0), (mid_x, h), (0, 255, 255), 2)
        cv2.putText(frame, "L1", (lane1_center-10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        cv2.putText(frame, "L2", (lane2_center-10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        
        cv2.putText(frame, "SIMULATION MODE", (mid_x-100, h-20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 140, 255), 2)
        
        return frame

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='AI Traffic Control System')
    parser.add_argument('--model', type=str, default="model/yolov8n.pt",
                        help='Path to YOLOv8 model (default: model/yolov8n.pt)')
    parser.add_argument('--camera', type=str, default="0",
                        help='Camera index or video file path (default: 0)')
    parser.add_argument('--comm_port', type=str, default="/dev/ttyUSB0",
                        help='Serial port for communication (default: /dev/ttyUSB0)')
    parser.add_argument('--test_mode', action='store_true',
                        help='Run in test mode without camera')
    parser.add_argument('--test_cameras', action='store_true',
                        help='Test available cameras and exit')
    parser.add_argument('--pi_camera', action='store_true',
                        help='Use Raspberry Pi camera module')
    parser.add_argument('--use_libcamera', action='store_true',
                        help='Use libcamera for Raspberry Pi camera')
    
    args = parser.parse_args()
    
    # Test cameras if requested
    if args.test_cameras:
        print("Testing available cameras...")
        test_cameras()
        sys.exit(0)
    
    # Convert camera argument to int if it's a number
    camera_source = args.camera
    try:
        camera_source = int(args.camera)
    except ValueError:
        # Not an integer, treat as a file path
        pass
    
    # Special handling for Raspberry Pi camera
    if args.pi_camera:
        logger.info("Using Raspberry Pi camera module")
        # For Pi camera, we use camera index 0
        camera_source = 0
        
        # Check if libcamera-based access is available
        try:
            import subprocess
            subprocess.run(['libcamera-hello'], check=True, capture_output=True, timeout=1)
            logger.info("libcamera is available on this system")
            # Optionally could use libcamera directly instead of OpenCV
        except (ImportError, subprocess.SubprocessError):
            logger.warning("libcamera not available, using standard OpenCV camera access")
    
    try:
        # Initialize and run the system
        system = TrafficDetectionSystem(
            model_path=args.model,
            camera_source=None if args.test_mode else camera_source,
            comm_port=args.comm_port
        )
        system.run()
    except KeyboardInterrupt:
        logger.info("System stopped by user")
    except Exception as e:
        logger.error(f"System error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc()) 