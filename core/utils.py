import yaml
import cv2
import numpy as np
from collections import deque

def load_config(config_path="hardware/config.yaml"):
    """
    Load configuration from YAML file
    """
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

def draw_lanes(frame, lane_polygons, lane_colors):
    """
    Draw lane polygons onto the frame
    """
    for lane_name, polygon in lane_polygons.items():
        color = lane_colors[lane_name]
        # Draw filled polygon with transparency
        overlay = frame.copy()
        cv2.fillPoly(overlay, [np.array(polygon, np.int32)], color)
        # Apply the overlay with transparency
        alpha = 0.3
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        # Draw polygon outline
        cv2.polylines(frame, [np.array(polygon, np.int32)], True, color, 2)
    
    return frame

def is_in_polygon(point, polygon):
    """
    Check if a point is inside a polygon using cv2.pointPolygonTest
    Returns True if inside, False otherwise
    """
    result = cv2.pointPolygonTest(np.array(polygon, np.int32), point, False)
    return result >= 0

def calculate_center(bbox):
    """
    Calculate center point of a bounding box [x1, y1, x2, y2]
    """
    x1, y1, x2, y2 = bbox
    return (int((x1 + x2) / 2), int((y1 + y2) / 2))

def draw_traffic_light(frame, lane_name, status, position):
    """
    Draw traffic light status on frame
    """
    if status == "GREEN":
        color = (0, 255, 0)
    elif status == "YELLOW":
        color = (0, 255, 255)
    else:  # RED
        color = (0, 0, 255)
    
    cv2.putText(frame, f"{lane_name}: {status}", position, 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    
    return frame

class MovingAverage:
    """
    Calculate moving average for a value
    """
    def __init__(self, window_size=5):
        self.window_size = window_size
        self.values = deque(maxlen=window_size)
        
    def update(self, value):
        self.values.append(value)
        
    def get_average(self):
        if not self.values:
            return 0
        return sum(self.values) / len(self.values)
    
    def get_rounded_average(self):
        return round(self.get_average()) 