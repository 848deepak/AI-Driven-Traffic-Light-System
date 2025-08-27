import cv2
import numpy as np
import time
import threading
import easyocr
import re
import string

class OCRDetector:
    """
    Class for detecting emergency-related text on vehicles using OCR
    """
    def __init__(self, config):
        """
        Initialize OCR detector with config
        """
        # Check if OCR config exists
        if "ocr" not in config:
            print("OCR configuration not found, disabling OCR detection")
            self.enabled = False
            return
            
        self.enabled = config["ocr"]["enabled"]
        if not self.enabled:
            return
            
        self.frame_skip = config["ocr"]["frame_skip"]
        self.confidence = config["ocr"]["confidence"]
        
        # Convert all keywords to strings and lowercase
        self.emergency_keywords = []
        self.hindi_keywords = []
        
        for keyword in config["ocr"]["emergency_keywords"]:
            if isinstance(keyword, (str, int, float)):
                keyword_str = str(keyword).lower()
                # Check if keyword is Hindi (Unicode range for Devanagari script)
                if any(ord(c) >= 0x0900 and ord(c) <= 0x097F for c in keyword_str):
                    self.hindi_keywords.append(keyword_str)
                else:
                    self.emergency_keywords.append(keyword_str)
            else:
                print(f"Warning: Skipping invalid keyword type: {type(keyword)}")
        
        print(f"OCR configured with {len(self.emergency_keywords)} emergency keywords and {len(self.hindi_keywords)} Hindi keywords")
        
        # Load EasyOCR model in a separate thread to not block startup
        self.reader = None
        self.reader_ready = False
        self.loading_thread = threading.Thread(target=self._load_reader)
        self.loading_thread.daemon = True
        self.loading_thread.start()
        
        # Store detection results
        self.detected_texts = []
        self.frame_count = 0
        self.last_process_time = time.time()
        
        # Flag for emergency text detection
        self.emergency_text_detected = False
        self.emergency_text_location = None  # (lane, text, confidence)
        
        # Debug information
        self.debug_info = {}
        
        # Tracking for improved detection
        self.text_history = {}
        self.history_length = 5
    
    def _load_reader(self):
        """
        Load EasyOCR model in background thread
        """
        print("Loading OCR model (this may take a moment)...")
        try:
            # Use English and Hindi for Indian emergency vehicles
            self.reader = easyocr.Reader(['en', 'hi'], gpu=False, quantize=True)
            self.reader_ready = True
            print("OCR model loaded successfully with English and Hindi support")
        except Exception as e:
            print(f"Error loading OCR model: {e}")
            try:
                # Fallback to English only
                self.reader = easyocr.Reader(['en'], gpu=False, quantize=True)
                self.reader_ready = True
                print("OCR model loaded with English only (Hindi support failed)")
            except Exception as e:
                print(f"Failed to load OCR model completely: {e}")
    
    def preprocess_image(self, image):
        """
        Apply various preprocessing techniques to improve OCR accuracy
        """
        # Make a copy to avoid modifying original
        enhanced = image.copy()
        
        # Resize if too small
        if enhanced.shape[0] < 50 or enhanced.shape[1] < 100:
            scale = max(100 / enhanced.shape[1], 50 / enhanced.shape[0])
            enhanced = cv2.resize(enhanced, None, fx=scale, fy=scale, 
                              interpolation=cv2.INTER_CUBIC)
        
        # Method 1: CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe_img = enhanced.copy()
        lab = cv2.cvtColor(clahe_img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        enhanced_lab = cv2.merge((cl, a, b))
        enhanced1 = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
        
        # Method 2: Thresholding to improve text/background contrast
        enhanced2 = enhanced.copy()
        gray = cv2.cvtColor(enhanced2, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        enhanced2 = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        
        # Method 3: Edge enhancement
        enhanced3 = enhanced.copy()
        gray = cv2.cvtColor(enhanced3, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)
        dilated = cv2.dilate(edges, None, iterations=1)
        enhanced3 = cv2.cvtColor(dilated, cv2.COLOR_GRAY2BGR)
        
        # Method 4: Sharpening - especially good for Hindi text
        enhanced4 = enhanced.copy()
        kernel = np.array([[-1, -1, -1], 
                          [-1, 9, -1], 
                          [-1, -1, -1]])
        enhanced4 = cv2.filter2D(enhanced4, -1, kernel)
        
        # Method 5: Red text enhancement (common for emergency markings)
        enhanced5 = enhanced.copy()
        hsv = cv2.cvtColor(enhanced5, cv2.COLOR_BGR2HSV)
        # Target red color range
        lower_red1 = np.array([0, 70, 50])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 70, 50])
        upper_red2 = np.array([180, 255, 255])
        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        mask = mask1 + mask2
        # Enhance red regions
        enhanced5[mask > 0] = (0, 0, 255)
        
        return [enhanced1, enhanced2, enhanced3, enhanced4, enhanced5]
    
    def check_for_emergency_text(self, text, confidence):
        """
        Check if the detected text contains any emergency keywords
        Returns: (is_emergency, matched_keyword)
        """
        # Convert to string and lowercase
        text_str = str(text).lower()
        
        # Remove punctuation and compress spaces
        translator = str.maketrans('', '', string.punctuation)
        text_clean = text_str.translate(translator).strip()
        text_clean = re.sub(r'\s+', ' ', text_clean)
        
        # Check direct matches (with substring)
        for keyword in self.emergency_keywords:
            if keyword in text_clean:
                return True, keyword
        
        # Check Hindi keywords
        for keyword in self.hindi_keywords:
            if keyword in text_str:  # Use raw text for Hindi, don't clean
                return True, keyword
        
        # Check for partial matches (minimum 3 characters)
        partial_match_threshold = 3
        for keyword in self.emergency_keywords:
            if len(keyword) >= partial_match_threshold:
                for i in range(len(keyword) - partial_match_threshold + 1):
                    partial = keyword[i:i+partial_match_threshold]
                    if partial in text_clean:
                        return True, f"{partial}({keyword})"
        
        # Check word boundary matches (with regex)
        for keyword in self.emergency_keywords:
            if re.search(r'\b' + re.escape(keyword) + r'\b', text_clean):
                return True, keyword
            
        # Check for common emergency numbers with more permissive matching
        emergency_numbers = ['100', '101', '102', '108', '112', '911', '999']
        for num in emergency_numbers:
            if num in text_clean:
                return True, num
        
        return False, None
    
    def _get_vehicle_id(self, vehicle):
        """
        Generate a stable ID for a vehicle based on its position
        """
        bbox = vehicle["bbox"]
        center_x = (bbox[0] + bbox[2]) // 2
        center_y = (bbox[1] + bbox[3]) // 2
        grid_x = center_x // 20
        grid_y = center_y // 20
        vehicle_class = vehicle.get("class", "unknown")
        
        return f"{vehicle_class}_{grid_x}_{grid_y}"
    
    def process_frame(self, frame, detected_vehicles):
        """
        Process frame for OCR text detection
        Args:
            frame: The image frame
            detected_vehicles: List of detected vehicles with bounding boxes
        """
        if not self.enabled or not self.reader_ready:
            return False, None
        
        # Process only every Nth frame to save resources
        self.frame_count += 1
        if self.frame_count % self.frame_skip != 0:
            return self.emergency_text_detected, self.emergency_text_location
        
        # Check if enough time has passed since last OCR (it's resource-intensive)
        current_time = time.time()
        if current_time - self.last_process_time < 0.5:  # Max twice per second
            return self.emergency_text_detected, self.emergency_text_location
            
        self.last_process_time = current_time
        
        # Reset detection for this frame
        self.emergency_text_detected = False
        self.detected_texts = []
        
        # Clean up history for vehicles no longer present
        current_ids = set(self._get_vehicle_id(v) for v in detected_vehicles)
        for vehicle_id in list(self.text_history.keys()):
            if vehicle_id not in current_ids:
                del self.text_history[vehicle_id]
        
        # Process each detected vehicle
        for vehicle in detected_vehicles:
            try:
                x1, y1, x2, y2 = vehicle["bbox"]
                vehicle_id = self._get_vehicle_id(vehicle)
                
                # Skip if too small - OCR needs reasonable size text
                if (x2 - x1) < 60 or (y2 - y1) < 30:
                    continue
                    
                # Extract the vehicle region
                vehicle_img = frame[y1:y2, x1:x2].copy()
                if vehicle_img.size == 0:  # Skip empty regions
                    continue
                    
                # Apply preprocessing to enhance text visibility
                enhanced_images = self.preprocess_image(vehicle_img)
                
                # Try OCR on each enhanced image
                emergency_detected = False
                best_result = None
                
                for idx, img in enumerate(enhanced_images):
                    try:
                        # Run OCR on the enhanced image
                        results = self.reader.readtext(img)
                        
                        # Process OCR results
                        for (bbox, text, prob) in results:
                            if prob >= self.confidence:
                                # Check if text contains any emergency keywords
                                is_emergency, matched_keyword = self.check_for_emergency_text(text, prob)
                                
                                # Update history for this vehicle
                                if vehicle_id not in self.text_history:
                                    self.text_history[vehicle_id] = {
                                        "texts": [],
                                        "emergency_detections": 0,
                                        "last_emergency_match": None
                                    }
                                
                                # Add current text to history
                                self.text_history[vehicle_id]["texts"].append(text)
                                if len(self.text_history[vehicle_id]["texts"]) > self.history_length:
                                    self.text_history[vehicle_id]["texts"].pop(0)
                                
                                if is_emergency:
                                    # Increment emergency detection counter
                                    self.text_history[vehicle_id]["emergency_detections"] += 1
                                    self.text_history[vehicle_id]["last_emergency_match"] = matched_keyword
                                    
                                    # If we've detected emergency text multiple times, increase confidence
                                    detection_count = self.text_history[vehicle_id]["emergency_detections"]
                                    if detection_count >= 2:
                                        prob += min(0.3, detection_count * 0.05)
                                
                                if is_emergency or (vehicle_id in self.text_history and 
                                                  self.text_history[vehicle_id]["emergency_detections"] >= 3):
                                    # If we detected emergency text now, or have consistently detected it
                                    emergency_detected = True
                                    text_str = str(text)
                                    
                                    # If this isn't an emergency text but we've seen emergency text on this vehicle before
                                    if not is_emergency and vehicle_id in self.text_history:
                                        matched_keyword = self.text_history[vehicle_id].get("last_emergency_match", "consistent_detection")
                                        text_str = f"History: {matched_keyword}"
                                    
                                    best_result = {
                                        "text": text_str,
                                        "confidence": prob,
                                        "bbox": bbox,
                                        "vehicle_bbox": vehicle["bbox"],
                                        "lane": vehicle["lane"],
                                        "matched_keyword": matched_keyword,
                                        "is_emergency": True,
                                        "method": f"enhancement_{idx+1}"
                                    }
                                    
                                    # Exit early once emergency text is found
                                    self.emergency_text_detected = True
                                    self.emergency_text_location = (vehicle["lane"], text_str, prob)
                                    self.detected_texts.append(best_result)
                                    return True, self.emergency_text_location
                                else:
                                    # Store non-emergency text
                                    self.detected_texts.append({
                                        "text": str(text),
                                        "confidence": prob,
                                        "bbox": bbox,
                                        "vehicle_bbox": vehicle["bbox"],
                                        "lane": vehicle["lane"],
                                        "is_emergency": False,
                                        "method": f"enhancement_{idx+1}"
                                    })
                    except Exception as e:
                        # Just skip this enhancement method if it fails
                        print(f"Error in OCR processing (method {idx+1}): {e}")
                        continue
                
            except Exception as e:
                print(f"Error processing vehicle for OCR: {e}")
        
        return self.emergency_text_detected, self.emergency_text_location
    
    def draw_detections(self, frame):
        """
        Draw OCR detections on frame
        """
        if not self.enabled or not self.reader_ready or not self.detected_texts:
            return frame
            
        for detection in self.detected_texts:
            try:
                # Get vehicle bounding box
                x1, y1, x2, y2 = detection["vehicle_bbox"]
                
                if detection["is_emergency"]:
                    color = (0, 0, 255)  # Red for emergency
                    matched = detection.get("matched_keyword", "")
                    
                    # Check if it's a Hindi match
                    is_hindi = any(ord(c) >= 0x0900 and ord(c) <= 0x097F for c in matched)
                    
                    if is_hindi:
                        text = f"हिंदी पहचान: '{detection['text']}'"
                        color = (255, 0, 128)  # Pink for Hindi
                    else:
                        text = f"EMERGENCY: '{detection['text']}' ({matched})"
                    
                    method = detection.get("method", "")
                    
                    # Draw box with highlighted pattern
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    
                    # Add diagonal cross for emergency vehicles
                    cv2.line(frame, (x1, y1), (x2, y2), color, 1)
                    cv2.line(frame, (x1, y2), (x2, y1), color, 1)
                else:
                    color = (255, 0, 255)  # Purple for normal text
                    text = f"Text: {detection['text']} ({detection['confidence']:.2f})"
                    
                # Draw text at top of vehicle bounding box
                cv2.putText(frame, text, (x1, y1 - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            except Exception as e:
                print(f"Error drawing OCR detection: {e}")
            
        return frame 