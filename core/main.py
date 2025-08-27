#!/usr/bin/env python3

import os
import argparse
from core.traffic_control import SmartTrafficSystem

def ensure_model_directory():
    """
    Ensure that the model directory exists and yolov8n.pt is available
    """
    model_dir = os.path.join(os.path.dirname(__file__), "model")
    model_path = os.path.join(model_dir, "yolov8n.pt")
    
    if not os.path.exists(model_dir):
        print(f"Creating model directory: {model_dir}")
        os.makedirs(model_dir)
    
    if not os.path.exists(model_path):
        print("YOLOv8n model not found. Attempting to download...")
        try:
            from ultralytics import YOLO
            # This will download the model to the specified path
            YOLO("yolov8n.pt").export(format="onnx")  # Just to trigger download
            
            # Now copy it to our model directory
            import shutil
            yolo_cache = os.path.expanduser("~/.cache/torch/hub/ultralytics_yolov8_master/yolov8n.pt")
            if os.path.exists(yolo_cache):
                shutil.copy(yolo_cache, model_path)
                print(f"Model downloaded to {model_path}")
            else:
                print("Warning: Couldn't find YOLOv8 model in cache. Will use default location.")
        except Exception as e:
            print(f"Error downloading model: {e}")
            print("Please download yolov8n.pt manually and place it in the 'model' directory")

def parse_arguments():
    """
    Parse command line arguments
    """
    parser = argparse.ArgumentParser(description='Smart Traffic Control System')
    parser.add_argument('-c', '--config', type=str, default='config.yaml',
                        help='Path to configuration file (default: config.yaml)')
    return parser.parse_args()

def main():
    """
    Main entry point
    """
    args = parse_arguments()
    ensure_model_directory()
    
    # Create and run the traffic control system
    try:
        traffic_system = SmartTrafficSystem(config_path=args.config)
        print("Starting Smart Traffic Control System...")
        print("Press 'q' to exit")
        traffic_system.run()
    except KeyboardInterrupt:
        print("Interrupted by user")
    except Exception as e:
        print(f"Error running traffic system: {e}")
    
    print("System shutdown complete")

if __name__ == "__main__":
    main() 