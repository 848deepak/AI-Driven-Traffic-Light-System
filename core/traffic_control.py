import cv2
import time
import numpy as np
import threading
from ultralytics import YOLO
from core.utils import load_config, draw_lanes, is_in_polygon, calculate_center, draw_traffic_light, MovingAverage
from detectors.ocr_utils import OCRDetector
from detectors.color_detector import EmergencyColorDetector

class TrafficLightState:
    """
    Track and manage traffic light state
    """
    def __init__(self, config):
        self.min_green = config['traffic_light']['min_green_duration']
        self.max_green = config['traffic_light']['max_green_duration']
        self.yellow_duration = config['traffic_light']['yellow_duration']
        self.vehicle_scale = config['traffic_light']['vehicle_scale_factor']
        
        # Current states
        self.current_green_lane = "left"
        self.is_yellow = False
        self.yellow_start_time = 0
        self.green_start_time = time.time()
        self.last_switch_time = time.time()
        self.emergency_override = False
        
    def update(self, vehicle_counts, emergency_detected):
        """
        Update traffic light state based on vehicle counts and emergency vehicles
        """
        current_time = time.time()
        # Handle yellow light transition
        if self.is_yellow:
            if current_time - self.yellow_start_time >= self.yellow_duration:
                # Switch lanes after yellow duration
                self.is_yellow = False
                self.current_green_lane = "right" if self.current_green_lane == "left" else "left"
                self.green_start_time = current_time
                self.last_switch_time = current_time
                self.emergency_override = False
            return
        
        # Calculate green light duration based on vehicle count in current lane
        vehicle_count = vehicle_counts[self.current_green_lane]
        green_duration = min(max(self.min_green, vehicle_count * self.vehicle_scale), self.max_green)
        
        # Check for emergency vehicles in the non-green lane
        other_lane = "right" if self.current_green_lane == "left" else "left"
        
        # Check if we need to switch due to emergency vehicle or time elapsed
        if (emergency_detected[other_lane] and not self.emergency_override and
            current_time - self.green_start_time >= self.min_green):
            # Emergency vehicle detected in other lane, switch to yellow
            self.is_yellow = True
            self.yellow_start_time = current_time
            self.emergency_override = True
        elif current_time - self.green_start_time >= green_duration and not self.is_yellow:
            # Green duration elapsed, switch to yellow
            self.is_yellow = True
            self.yellow_start_time = current_time
    
    def get_status(self, lane):
        """
        Get current status for a specific lane
        """
        if self.is_yellow and lane == self.current_green_lane:
            return "YELLOW"
        elif not self.is_yellow and lane == self.current_green_lane:
            return "GREEN"
        else:
            return "RED"
    
    def get_remaining_time(self, vehicle_counts):
        """
        Get remaining time for current phase
        """
        current_time = time.time()
        if self.is_yellow:
            return max(0, self.yellow_duration - (current_time - self.yellow_start_time))
        else:
            vehicle_count = vehicle_counts[self.current_green_lane]
            green_duration = min(max(self.min_green, vehicle_count * self.vehicle_scale), self.max_green)
            return max(0, green_duration - (current_time - self.green_start_time))


class SmartTrafficSystem:
    """
    Main class to handle the traffic control system
    """
    def __init__(self, config_path="config.yaml"):
        self.config = load_config(config_path)
        self.model = self.load_model()
        self.camera = self.init_camera()
        
        # Map YOLOv8 class names to class IDs 
        self.class_mapping = {}
        self.update_class_mapping()
        
        # Initialize lane data
        self.lane_polygons = {
            "left": self.config["lanes"]["left"],
            "right": self.config["lanes"]["right"]
        }
        
        self.lane_colors = {
            "left": (255, 100, 100),   # Blue-ish for left lane
            "right": (100, 100, 255)   # Red-ish for right lane
        }
        
        # Track vehicles in each lane
        self.vehicle_counts = {"left": 0, "right": 0}
        self.emergency_detected = {"left": False, "right": False}
        
        # Cache lane polygons as numpy arrays for faster checking
        self.lane_polygons_np = {
            lane: np.array(polygon, np.int32)
            for lane, polygon in self.lane_polygons.items()
        }
        
        # Moving averages for vehicle counts
        window_size = self.config["traffic_light"]["count_window_size"]
        self.count_averages = {
            "left": MovingAverage(window_size),
            "right": MovingAverage(window_size)
        }
        
        # Initialize OCR detector for emergency text
        self.ocr_detector = OCRDetector(self.config)
        
        # Initialize color detector for emergency lights
        self.color_detector = EmergencyColorDetector(self.config)
        
        # Traffic light controller
        self.traffic_light = TrafficLightState(self.config)
        
        # Threading
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.latest_results = None
        self.processing = True
        
        # Emergency text detection
        self.emergency_text_detected = False
        self.emergency_text_info = None
        
        # Emergency color detection
        self.emergency_color_detected = {"left": False, "right": False}
        
        # Stats
        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        
        # Cache for vehicle centers to reduce computation
        self.cached_centers = {}
    
    def update_class_mapping(self):
        """
        Create a mapping from class names to class IDs
        """
        # Get all model class names
        for class_id, class_name in self.model.names.items():
            self.class_mapping[class_name] = class_id
        
        # Check if configured classes exist in the model
        for class_name in self.config["model"]["classes"]:
            if class_name not in self.class_mapping:
                print(f"Warning: Class '{class_name}' not found in model")
        
        print(f"Loaded {len(self.config['model']['classes'])} vehicle classes to detect")
    
    def load_model(self):
        """
        Load YOLOv8 model
        """
        model_path = self.config["model"]["path"]
        try:
            model = YOLO(model_path)
            print(f"Model loaded from {model_path}")
            return model
        except Exception as e:
            print(f"Error loading model: {e}")
            print("Attempting to use default yolov8n model")
            return YOLO("yolov8n.pt")
    
    def init_camera(self):
        """
        Initialize camera based on config
        """
        source = self.config["camera"]["source"]
        try:
            camera = cv2.VideoCapture(source)
            
            # Set camera properties if specified
            if isinstance(source, int):  # Only set for webcam
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.config["camera"]["width"])
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config["camera"]["height"])
                camera.set(cv2.CAP_PROP_FPS, self.config["camera"]["fps"])
            
            if not camera.isOpened():
                raise Exception("Failed to open camera")
                
            return camera
        except Exception as e:
            print(f"Error initializing camera: {e}")
            print("Please check your camera configuration")
            exit(1)
    
    def check_lane(self, center, cached=True):
        """
        Check which lane a point belongs to, with caching for efficiency
        """
        if cached and tuple(center) in self.cached_centers:
            return self.cached_centers[tuple(center)]
        
        for lane_name, polygon_np in self.lane_polygons_np.items():
            if cv2.pointPolygonTest(polygon_np, center, False) >= 0:
                if cached:
                    self.cached_centers[tuple(center)] = lane_name
                return lane_name
        
        return None
    
    def detection_thread(self):
        """
        Thread for running object detection
        """
        frame_skip = self.config["model"]["frame_skip"]
        confidence = self.config["model"]["confidence"]
        target_classes = [self.class_mapping[class_name] for class_name in self.config["model"]["classes"] 
                          if class_name in self.class_mapping]
        
        skip_counter = 0
        last_processed_time = time.time()
        
        while self.processing:
            ret, frame = self.camera.read()
            
            if not ret:
                print("Failed to get frame from camera")
                time.sleep(0.1)
                continue
            
            current_time = time.time()
            processing_interval = current_time - last_processed_time
            
            # Process every Nth frame for detection to improve performance
            if skip_counter % frame_skip == 0 and processing_interval >= 0.05:  # Limit to 20 fps max for detection
                # Resize frame for faster inference
                input_frame = cv2.resize(frame, (640, 480))
                
                # Run detection with class filtering
                results = self.model(input_frame, conf=confidence, classes=target_classes, verbose=False)
                
                # Reset counts for this frame
                current_counts = {"left": 0, "right": 0}
                current_emergency = {"left": False, "right": False}
                
                # Clear cache for this frame
                self.cached_centers = {}
                
                # Prepare list for processing
                detected_vehicles = []
                
                # Process results
                for r in results:
                    boxes = r.boxes
                    for box in boxes:
                        # Get class and confidence
                        cls_id = int(box.cls.item())
                        conf = box.conf.item()
                        cls_name = self.model.names[cls_id]
                        
                        # Get bounding box coordinates
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                        
                        # Calculate center of bounding box
                        center = calculate_center((x1, y1, x2, y2))
                        
                        # Check which lane the vehicle is in
                        lane_name = self.check_lane(center)
                        
                        if lane_name:
                            current_counts[lane_name] += 1
                            
                            # Add to list for processing
                            detected_vehicles.append({
                                "bbox": (x1, y1, x2, y2),
                                "lane": lane_name,
                                "class": cls_name,
                                "confidence": conf,
                                "center": center
                            })
                
                # Update moving averages
                for lane in ["left", "right"]:
                    self.count_averages[lane].update(current_counts[lane])
                    # Use the smoothed vehicle count
                    self.vehicle_counts[lane] = self.count_averages[lane].get_rounded_average()
                
                # 1. Check for emergency colors
                if self.config["emergency_detection"]["enable_color_detector"]:
                    color_emergency = self.color_detector.detect_emergency_lights(frame, detected_vehicles)
                    # Update emergency status from color detection
                    for lane, is_emergency in color_emergency.items():
                        current_emergency[lane] = current_emergency.get(lane, False) or is_emergency
                    self.emergency_color_detected = color_emergency
                
                # 2. Check for emergency text if OCR is enabled
                if self.config["ocr"]["enabled"] and detected_vehicles:
                    emergency_text_found, emergency_info = self.ocr_detector.process_frame(frame, detected_vehicles)
                    
                    # If emergency text found, update emergency status
                    if emergency_text_found and emergency_info:
                        lane, text, conf = emergency_info
                        current_emergency[lane] = True
                        self.emergency_text_detected = True
                        self.emergency_text_info = emergency_info
                    else:
                        self.emergency_text_detected = False
                        self.emergency_text_info = None
                
                # Update overall emergency status
                self.emergency_detected = current_emergency
                
                with self.frame_lock:
                    self.latest_frame = frame.copy()
                    self.latest_results = results
                    self.latest_detected_vehicles = detected_vehicles
                
                last_processed_time = current_time
            
            skip_counter += 1
            
            # Calculate FPS
            self.frame_count += 1
            current_time = time.time()
            if current_time - self.last_fps_time >= 1.0:
                self.fps = self.frame_count / (current_time - self.last_fps_time)
                self.frame_count = 0
                self.last_fps_time = current_time
    
    def run(self):
        """
        Main loop to run the traffic system
        """
        # Start detection thread
        detection_thread = threading.Thread(target=self.detection_thread)
        detection_thread.daemon = True
        detection_thread.start()
        
        try:
            while self.processing:
                with self.frame_lock:
                    if self.latest_frame is None or self.latest_results is None:
                        time.sleep(0.1)
                        continue
                    
                    frame = self.latest_frame.copy()
                    results = self.latest_results
                    detected_vehicles = getattr(self, 'latest_detected_vehicles', [])
                
                # Update traffic light state
                self.traffic_light.update(self.vehicle_counts, self.emergency_detected)
                
                # Draw lanes on frame
                frame = draw_lanes(frame, self.lane_polygons, self.lane_colors)
                
                # Draw detected objects
                for r in results:
                    boxes = r.boxes
                    for box in boxes:
                        cls_id = int(box.cls.item())
                        conf = box.conf.item()
                        cls_name = self.model.names[cls_id]
                        
                        # Get bounding box coordinates
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                        
                        # Base color is green for regular vehicles
                        color = (0, 255, 0)
                        
                        # Check if this vehicle has been marked as emergency by any detector
                        for vehicle in detected_vehicles:
                            if vehicle["bbox"] == (x1, y1, x2, y2):
                                if vehicle.get("is_emergency_color", False):
                                    color = (0, 0, 255)  # Red for emergency vehicles
                                break
                        
                        # Draw bounding box
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        
                        # Calculate center and draw it
                        center = calculate_center((x1, y1, x2, y2))
                        cv2.circle(frame, center, 3, color, -1)
                        
                        # Check which lane (without caching for display purposes)
                        lane_name = self.check_lane(center, cached=False)
                        
                        # Draw label with lane info if available
                        if lane_name:
                            label = f"{cls_name} ({lane_name}) {conf:.2f}"
                        else:
                            label = f"{cls_name} {conf:.2f}"
                            
                        t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)[0]
                        cv2.rectangle(frame, (x1, y1 - t_size[1] - 3), (x1 + t_size[0], y1), color, -1)
                        cv2.putText(frame, label, (x1, y1 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                
                # Draw OCR detections if available
                if self.config["ocr"]["enabled"]:
                    frame = self.ocr_detector.draw_detections(frame)
                
                # Draw color detections if available
                if self.config["emergency_detection"]["enable_color_detector"]:
                    frame = self.color_detector.draw_detections(frame, detected_vehicles)
                
                # Calculate remaining time
                remaining_time = self.traffic_light.get_remaining_time(self.vehicle_counts)
                
                # Draw traffic light states with remaining time
                left_status = self.traffic_light.get_status("left")
                right_status = self.traffic_light.get_status("right")
                
                draw_traffic_light(frame, f"Left Lane: {left_status}", left_status, (10, 30))
                draw_traffic_light(frame, f"Right Lane: {right_status}", right_status, (10, 60))
                
                # Draw countdown timer for current phase
                current_phase = "YELLOW" if self.traffic_light.is_yellow else "GREEN"
                current_lane = self.traffic_light.current_green_lane.capitalize()
                cv2.putText(frame, f"{current_phase} for {current_lane}: {remaining_time:.1f}s", (10, 150), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
                # Draw vehicle counts
                cv2.putText(frame, f"Left Lane: {self.vehicle_counts['left']} vehicles", (10, 90), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                cv2.putText(frame, f"Right Lane: {self.vehicle_counts['right']} vehicles", (10, 120), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
                # Draw emergency detection status
                y_pos = 180
                if self.emergency_detected["left"]:
                    cv2.putText(frame, "EMERGENCY VEHICLE IN LEFT LANE", (10, y_pos), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    y_pos += 30
                if self.emergency_detected["right"]:
                    cv2.putText(frame, "EMERGENCY VEHICLE IN RIGHT LANE", (10, y_pos), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    y_pos += 30
                
                # Draw detection method info
                methods_active = []
                if self.config["ocr"]["enabled"]:
                    if self.ocr_detector.reader_ready:
                        methods_active.append("OCR")
                if self.config["emergency_detection"]["enable_color_detector"]:
                    methods_active.append("Color")
                
                detection_methods = ", ".join(methods_active)
                cv2.putText(frame, f"Emergency Detection: {detection_methods}", (10, y_pos), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                y_pos += 30
                
                # Draw emergency text detection status
                if self.emergency_text_detected and self.emergency_text_info:
                    lane, text, conf = self.emergency_text_info
                    cv2.putText(frame, f"EMERGENCY TEXT '{text}' DETECTED", 
                                (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    y_pos += 30
                
                # Draw FPS
                cv2.putText(frame, f"FPS: {self.fps:.1f}", (frame.shape[1] - 120, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                
                # Show the frame
                cv2.imshow("Smart Traffic Control System", frame)
                
                # Check for exit key
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    self.processing = False
                    break
        
        finally:
            # Clean up
            self.camera.release()
            cv2.destroyAllWindows()
            print("Exiting Smart Traffic Control System") 