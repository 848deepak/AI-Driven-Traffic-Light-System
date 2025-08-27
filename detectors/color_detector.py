import cv2
import numpy as np

class EmergencyColorDetector:
    """
    Detect emergency vehicle lights based on color thresholds
    Looks for red and blue lights that are typical on ambulances, police cars, etc.
    """
    def __init__(self, config):
        """
        Initialize with color thresholds from config
        """
        self.enabled = config["emergency_detection"]["enable_color_detector"]
        if not self.enabled:
            return
            
        self.colors = []
        self.min_area = config["emergency_detection"]["min_color_area"]
        self.threshold = config["emergency_detection"]["emergency_color_threshold"]
        
        # Load color ranges
        for color_config in config["emergency_detection"]["colors"]:
            self.colors.append({
                "name": color_config["name"],
                "lower": np.array(color_config["lower"], dtype=np.uint8),
                "upper": np.array(color_config["upper"], dtype=np.uint8)
            })
        
        # Indian specific settings
        self.india_specific = config["emergency_detection"].get("india_specific", {})
        self.detect_ambulance_patterns = self.india_specific.get("detect_ambulance_patterns", False)
        self.detect_fire_truck_by_color = self.india_specific.get("detect_fire_truck_by_color", False)
        self.min_white_percentage = self.india_specific.get("min_white_percentage", 0.5)
        
        print(f"Emergency color detector initialized with {len(self.colors)} color ranges")
        print(f"Indian emergency vehicle detection is enabled")
        
        # Keep track of history for vehicles to detect flashing lights
        self.history = {}
        self.max_history = 10
        self.history_threshold = 3  # How many times a color needs to be detected
    
    def detect_emergency_lights(self, frame, vehicle_boxes):
        """
        Detect emergency vehicle lights in the given frame
        Args:
            frame: The image frame
            vehicle_boxes: List of detected vehicles with bounding boxes
        Returns:
            Dictionary with lane as key and boolean as value indicating if emergency vehicle detected
        """
        if not self.enabled:
            return {}
            
        emergency_detected = {}
        
        # Clean up history for vehicles that are no longer present
        current_ids = set()
        for vehicle in vehicle_boxes:
            vehicle_id = self._get_vehicle_id(vehicle)
            current_ids.add(vehicle_id)
        
        # Remove vehicles no longer in frame
        for vehicle_id in list(self.history.keys()):
            if vehicle_id not in current_ids:
                del self.history[vehicle_id]
        
        for vehicle in vehicle_boxes:
            x1, y1, x2, y2 = vehicle["bbox"]
            lane = vehicle["lane"]
            vehicle_id = self._get_vehicle_id(vehicle)
            
            # Extract vehicle region
            roi = frame[y1:y2, x1:x2]
            if roi.size == 0:  # Skip empty regions
                continue
                
            # Calculate total area of the vehicle box
            total_area = (x2 - x1) * (y2 - y1)
            if total_area == 0:
                continue
            
            # Check each color
            is_emergency = False
            color_results = {}
            
            for color in self.colors:
                # Create mask for this color range
                mask = cv2.inRange(roi, color["lower"], color["upper"])
                
                # Find contours in the mask
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                # Calculate total area of color
                color_area = 0
                for contour in contours:
                    area = cv2.contourArea(contour)
                    if area > self.min_area:
                        color_area += area
                
                # Calculate the normalized color percentage
                color_percentage = color_area / total_area
                color_results[color["name"]] = color_percentage
                
                # Check if color area exceeds threshold
                if color_percentage > self.threshold:
                    # Update history for this vehicle
                    if vehicle_id not in self.history:
                        self.history[vehicle_id] = {
                            "colors": {},
                            "frame_count": 0
                        }
                    
                    # Increment color count
                    if color["name"] not in self.history[vehicle_id]["colors"]:
                        self.history[vehicle_id]["colors"][color["name"]] = 0
                    self.history[vehicle_id]["colors"][color["name"]] += 1
                    self.history[vehicle_id]["frame_count"] += 1
                    
                    # Limit history length
                    if self.history[vehicle_id]["frame_count"] > self.max_history:
                        for clr in self.history[vehicle_id]["colors"]:
                            self.history[vehicle_id]["colors"][clr] = max(
                                0, self.history[vehicle_id]["colors"][clr] - 1)
                        self.history[vehicle_id]["frame_count"] = max(
                            0, self.history[vehicle_id]["frame_count"] - 1)
                    
                    # Check if this color has been detected enough times
                    if self.history[vehicle_id]["colors"].get(color["name"], 0) >= self.history_threshold:
                        is_emergency = True
                        vehicle["emergency_color"] = color["name"]
                        vehicle["color_percentage"] = color_percentage
            
            # Store all color percentages
            vehicle["color_percentages"] = color_results
            
            # Store best color match
            best_color = max(color_results.items(), key=lambda x: x[1]) if color_results else (None, 0)
            if best_color[0] and best_color[1] > self.threshold * 0.5:  # Relax threshold for storing
                vehicle["best_color_match"] = {
                    "name": best_color[0],
                    "percentage": best_color[1]
                }
            
            # Calculate a color pattern score - multiple colors are more likely to be emergency
            if self.history.get(vehicle_id, {}).get("colors", {}):
                color_pattern_score = sum(1 for c, count in self.history[vehicle_id]["colors"].items() 
                                        if count >= self.history_threshold)
                if color_pattern_score >= 2:  # If at least 2 different colors detected
                    is_emergency = True
                    vehicle["emergency_pattern"] = True
                    vehicle["pattern_score"] = color_pattern_score
            
            # Indian specific detection - Check for Indian ambulance (white vehicle with red/blue markings)
            if self.detect_ambulance_patterns:
                white_vehicle_pct = color_results.get("white_vehicle", 0)
                red_light_pct = color_results.get("red_light", 0) + color_results.get("bright_red", 0)
                blue_light_pct = color_results.get("blue_light", 0) + color_results.get("police_blue", 0)
                
                # White vehicle with red or blue markings is likely an ambulance
                if white_vehicle_pct > self.min_white_percentage and (red_light_pct > 0.05 or blue_light_pct > 0.05):
                    is_emergency = True
                    vehicle["is_ambulance"] = True
                    vehicle["ambulance_confidence"] = white_vehicle_pct * max(red_light_pct, blue_light_pct) * 10
            
            # Indian specific detection - Check for fire truck (primarily red vehicle)
            if self.detect_fire_truck_by_color:
                red_vehicle_pct = color_results.get("red_vehicle", 0)
                if red_vehicle_pct > 0.3:  # If vehicle is significantly red
                    is_emergency = True
                    vehicle["is_fire_truck"] = True
                    vehicle["fire_truck_confidence"] = red_vehicle_pct * 2
            
            # Update emergency status for this lane
            if is_emergency and lane not in emergency_detected:
                emergency_detected[lane] = True
                
            # Mark the vehicle as emergency if color detected
            vehicle["is_emergency_color"] = is_emergency
        
        return emergency_detected
    
    def _get_vehicle_id(self, vehicle):
        """
        Generate a stable ID for a vehicle based on its position and class
        """
        bbox = vehicle["bbox"]
        # Center point of bounding box
        center_x = (bbox[0] + bbox[2]) // 2
        center_y = (bbox[1] + bbox[3]) // 2
        
        # Create a grid-based position (round to nearest 20 pixels)
        grid_x = center_x // 20
        grid_y = center_y // 20
        
        # Vehicle class
        vehicle_class = vehicle.get("class", "unknown")
        
        return f"{vehicle_class}_{grid_x}_{grid_y}"
    
    def draw_detections(self, frame, vehicle_boxes):
        """
        Draw color detection results on the frame
        """
        if not self.enabled:
            return frame
            
        for vehicle in vehicle_boxes:
            # Draw emergency vehicles
            if vehicle.get("is_emergency_color", False):
                x1, y1, x2, y2 = vehicle["bbox"]
                
                # Set color and label based on what was detected
                if vehicle.get("is_ambulance", False):
                    # Ambulance - white with red/blue markings
                    color = (0, 165, 255)  # Orange for ambulance
                    confidence = vehicle.get("ambulance_confidence", 0)
                    label = f"AMBULANCE ({confidence:.1f}%)"
                    
                elif vehicle.get("is_fire_truck", False):
                    # Fire truck - red vehicle
                    color = (0, 0, 255)  # Red for fire truck
                    confidence = vehicle.get("fire_truck_confidence", 0)
                    label = f"FIRE TRUCK ({confidence:.1f}%)"
                    
                elif vehicle.get("emergency_pattern", False):
                    # Vehicle with multiple emergency colors
                    color = (255, 0, 255)  # Magenta for multiple color patterns
                    pattern_score = vehicle.get("pattern_score", 0)
                    label = f"EMERGENCY PATTERN ({pattern_score} colors)"
                    
                elif "emergency_color" in vehicle:
                    # Vehicle with specific emergency color
                    color_name = vehicle.get("emergency_color", "unknown")
                    percentage = vehicle.get("color_percentage", 0) * 100
                    
                    # Set color based on detected emergency color
                    if "red" in color_name:
                        color = (0, 0, 255)  # Red for red lights
                    elif "blue" in color_name:
                        color = (255, 0, 0)  # Blue for blue lights
                    elif "amber" in color_name:
                        color = (0, 255, 255)  # Yellow for amber lights
                    elif "white" in color_name:
                        color = (255, 255, 255)  # White for white lights
                    else:
                        color = (0, 255, 0)  # Default to green
                        
                    label = f"EMERGENCY: {color_name} ({percentage:.1f}%)"
                else:
                    color = (0, 255, 0)  # Default to green
                    label = "EMERGENCY VEHICLE"
                
                # Draw rectangle and label
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                
                # Text background
                text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
                cv2.rectangle(frame, (x1, y1 - text_size[1] - 10), (x1 + text_size[0], y1), color, -1)
                
                # Text
                cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        
        return frame 