# Smart Traffic Control System

An AI-powered traffic management system using computer vision to detect vehicles and dynamically control traffic signals.

## Features

- Real-time vehicle detection and counting using YOLOv8
- Dynamic traffic light timing based on vehicle density
- Emergency vehicle priority handling
- Multi-lane traffic management
- Visual overlay showing lane boundaries and vehicle statistics
- Configurable camera input (webcam or IP camera)

## Requirements

- Python 3.8+
- OpenCV
- Ultralytics YOLOv8
- NumPy
- PyYAML
- A camera source (laptop webcam or smartphone camera via IP camera app)

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/smart-traffic-control-system.git
cd smart-traffic-control-system
```

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

3. The YOLOv8 model will be automatically downloaded when you first run the system. If you prefer to download it manually, get `yolov8n.pt` from the Ultralytics repository and place it in the `model` directory.

## Configuration

All settings are stored in `config.yaml`:

- **Camera Settings**: Change the camera source, resolution, and FPS
- **YOLOv8 Settings**: Adjust model path, confidence threshold, and target classes
- **Traffic Light Timings**: Modify min/max durations and scaling factors
- **Lane Definitions**: Update the polygon coordinates to match your camera view

### Camera Configuration

You can use either:
1. Your laptop webcam: Set `camera.source: 0` in the config file
2. A smartphone IP camera app:
   - Install an IP camera app (like IP Webcam for Android or EpocCam for iOS)
   - Set `camera.source: "http://your-phone-ip:port/video"` in the config file

### Lane Configuration

The system uses polygon coordinates to define lanes. Update the coordinates in `config.yaml` to match your camera view:

```yaml
lanes:
  left:
    - [100, 480]  # Bottom-left point
    - [280, 100]  # Top-left point
    - [360, 100]  # Top-right point
    - [320, 480]  # Bottom-right point
  right:
    - [320, 480]  # Bottom-left point
    - [360, 100]  # Top-left point
    - [440, 100]  # Top-right point
    - [540, 480]  # Bottom-right point
```

## Usage

Run the system with:

```bash
python main.py
```

Or specify a custom config file:

```bash
python main.py --config my_custom_config.yaml
```

### Controls

- Press 'q' to exit the program

## How It Works

1. **Camera Input**: Frames are captured from your specified camera source
2. **Vehicle Detection**: YOLOv8 detects vehicles in each frame
3. **Lane Assignment**: Each detected vehicle is assigned to a lane based on its center point
4. **Traffic Light Logic**:
   - Green light duration is calculated based on vehicle count
   - Emergency vehicles trigger an immediate light change (after minimum green time)
   - Yellow light provides a transition period before switching
5. **Visualization**: The system displays lane overlays, vehicle counts, and traffic light status

## Optimization Features

- Frame skipping for better performance
- Multithreading separates detection from visualization
- Moving average smoothing for vehicle counts
- Confidence threshold filtering
- Frame resizing before inference

## Troubleshooting

- **Camera Access Issues**: Ensure your camera is not being used by another application
- **Model Loading Errors**: Check that the model file exists in the specified location
- **Performance Issues**: Adjust the frame skip and resize values in the config to reduce processing load

## License

This project is licensed under the MIT License - see the LICENSE file for details. 