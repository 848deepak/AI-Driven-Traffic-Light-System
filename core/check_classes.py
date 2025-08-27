from ultralytics import YOLO

def print_yolo_classes():
    # Load the model
    model = YOLO("detectors/yolov8n.pt")
    
    # Print all available class names with their indices
    print("Available YOLOv8 classes:")
    for idx, class_name in model.names.items():
        print(f"{idx}: {class_name}")

if __name__ == "__main__":
    print_yolo_classes() 