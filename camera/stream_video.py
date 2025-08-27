#!/usr/bin/env python3
"""
Video Streaming Server for AI Traffic Light System
Streams camera feed from Raspberry Pi to web browser
"""

import cv2
import time
import argparse
import logging
import threading
from flask import Flask, Response, render_template
import socket
import numpy as np

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("camera/stream_video.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("VideoStream")

# Initialize Flask app
app = Flask(__name__)

# Global variables
camera = None
output_frame = None
lock = threading.Lock()
camera_source = 0
use_pi_camera = False
frame_width = 640
frame_height = 480

def get_ip_address():
    """Get the local IP address of the machine"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def setup_camera():
    """Initialize and configure the camera"""
    global camera, camera_source, use_pi_camera, frame_width, frame_height
    
    if use_pi_camera:
        try:
            # Try to use libcamera for Raspberry Pi camera
            logger.info("Attempting to use libcamera for Pi Camera")
            # For Pi Camera with libcamera in OpenCV 4.5+
            camera = cv2.VideoCapture(camera_source, cv2.CAP_V4L2)
        except Exception as e:
            logger.error(f"Error setting up Pi Camera with libcamera: {e}")
            # Fallback to traditional picamera if available
            try:
                import picamera
                from picamera.array import PiRGBArray
                
                camera = picamera.PiCamera()
                camera.resolution = (frame_width, frame_height)
                camera.framerate = 30
                # Warm up the camera
                time.sleep(2)
                logger.info("Successfully initialized PiCamera")
                return True
            except ImportError:
                logger.error("picamera module not available")
                return False
    else:
        # Regular webcam or video file
        logger.info(f"Opening camera source: {camera_source}")
        camera = cv2.VideoCapture(camera_source)
    
    if not camera.isOpened():
        logger.error(f"Failed to open camera source: {camera_source}")
        return False
    
    # Set resolution
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
    
    # Set buffer size to minimize latency
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    
    logger.info(f"Camera initialized: resolution {frame_width}x{frame_height}")
    return True

def capture_frames():
    """
    Capture frames from the camera and update the global output_frame
    """
    global output_frame, lock, camera, use_pi_camera
    
    # Track FPS
    frame_count = 0
    start_time = time.time()
    fps = 0
    
    while True:
        # Get current frame
        if use_pi_camera and hasattr(camera, 'capture'):
            # Using picamera
            raw_capture = PiRGBArray(camera, size=(frame_width, frame_height))
            camera.capture(raw_capture, format="bgr", use_video_port=True)
            frame = raw_capture.array
            success = True
        else:
            # Using OpenCV VideoCapture
            success, frame = camera.read()
        
        if not success:
            logger.error("Failed to capture frame")
            time.sleep(0.1)
            continue
        
        # Calculate and display FPS
        frame_count += 1
        elapsed_time = time.time() - start_time
        if elapsed_time > 1:
            fps = frame_count / elapsed_time
            frame_count = 0
            start_time = time.time()
        
        # Add FPS text to frame
        cv2.putText(frame, f"FPS: {fps:.2f}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        # Add timestamp
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (10, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        # Update the global frame with lock to prevent race conditions
        with lock:
            output_frame = frame.copy()

def generate_frames():
    """
    Generator function for streaming frames to web clients
    """
    global output_frame, lock
    
    while True:
        # Wait until a frame is available
        with lock:
            if output_frame is None:
                continue
            
            # Convert frame to JPEG
            (flag, encoded_image) = cv2.imencode(".jpg", output_frame)
            
            if not flag:
                continue
        
        # Yield the frame in HTTP multipart format
        yield(b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + 
              bytearray(encoded_image) + b'\r\n')
        
        # Small delay to control streaming rate
        time.sleep(0.03)  # ~30 FPS

@app.route("/")
def index():
    """
    Serve the main page with video stream
    """
    ip = get_ip_address()
    # Return a simple HTML page with the video stream
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Traffic Light System - Camera Stream</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; text-align: center; }}
            h1 {{ color: #333; }}
            .video-container {{ margin: 20px auto; max-width: 800px; }}
            .video-stream {{ width: 100%; border: 1px solid #ccc; }}
            .info {{ margin-top: 20px; color: #666; }}
            .dashboard-link {{ margin-top: 20px; }}
            .dashboard-link a {{ background-color: #4CAF50; color: white; padding: 10px 15px; 
                               text-decoration: none; border-radius: 4px; }}
        </style>
    </head>
    <body>
        <h1>AI Traffic Light System - Camera Stream</h1>
        <div class="video-container">
            <img src="/video_feed" class="video-stream">
        </div>
        <div class="info">
            <p>Stream resolution: {frame_width}x{frame_height}</p>
            <p>Server IP: {ip}:{args.port}</p>
        </div>
        <div class="dashboard-link">
            <a href="http://{ip}:8080" target="_blank">Open Dashboard</a>
        </div>
    </body>
    </html>
    """

@app.route("/video_feed")
def video_feed():
    """
    Route for the video feed
    """
    return Response(generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Video Streaming Server for AI Traffic System")
    parser.add_argument("--camera", type=str, default="0",
                        help="Camera index or video file path (default: 0)")
    parser.add_argument("--pi-camera", action="store_true",
                        help="Use Raspberry Pi camera module")
    parser.add_argument("--width", type=int, default=640,
                        help="Frame width (default: 640)")
    parser.add_argument("--height", type=int, default=480,
                        help="Frame height (default: 480)")
    parser.add_argument("--port", type=int, default=5000,
                        help="Port for web server (default: 5000)")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="Host to bind server (default: 0.0.0.0)")
    
    args = parser.parse_args()
    
    # Set global variables from arguments
    if args.camera.isdigit():
        camera_source = int(args.camera)
    else:
        camera_source = args.camera
    
    use_pi_camera = args.pi_camera
    frame_width = args.width
    frame_height = args.height
    
    # Initialize camera
    if not setup_camera():
        logger.error("Failed to initialize camera. Exiting.")
        exit(1)
    
    # Start frame capture thread
    capture_thread = threading.Thread(target=capture_frames, daemon=True)
    capture_thread.start()
    
    # Get and display IP address
    ip_address = get_ip_address()
    logger.info(f"Starting server at http://{ip_address}:{args.port}")
    logger.info(f"Access the video stream in a web browser at http://{ip_address}:{args.port}")
    
    # Start Flask server
    try:
        app.run(host=args.host, port=args.port, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt. Shutting down...")
    finally:
        # Clean up camera resources
        if camera is not None and hasattr(camera, 'release'):
            camera.release()
        logger.info("Camera resources released. Exiting.") 