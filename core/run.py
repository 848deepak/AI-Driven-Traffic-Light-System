#!/usr/bin/env python3
"""
AI-Driven Traffic Light Control System
Main runner script that starts all system components.
"""

import os
import sys
import argparse
import subprocess
import time
import signal
import threading
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("hardware/traffic_system.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TrafficSystem")

# Get the absolute path to the project directory
PROJECT_DIR = Path(__file__).resolve().parent
AI_TRAFFIC_DIR = PROJECT_DIR / "ai-traffic-light"

# Process tracking
processes = []
stop_event = threading.Event()

def signal_handler(sig, frame):
    """Handle interruption signals by stopping all processes"""
    logger.info("Received termination signal. Shutting down...")
    stop_event.set()
    stop_processes()
    sys.exit(0)

def stop_processes():
    """Stop all running subprocesses"""
    for p in processes:
        if p.poll() is None:  # If process is still running
            logger.info(f"Terminating process: {p}")
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f"Process {p} did not terminate cleanly, killing it")
                p.kill()

def start_system(args):
    """Start all components of the traffic light system"""
    os.chdir(PROJECT_DIR)
    
    # Start the dashboard first
    if args.with_dashboard:
        dashboard_cmd = [
            sys.executable, 
            str(AI_TRAFFIC_DIR / "dashboard" / "flask_panel.py")
        ]
        logger.info(f"Starting dashboard: {' '.join(dashboard_cmd)}")
        dashboard_process = subprocess.Popen(
            dashboard_cmd,
            stdout=subprocess.PIPE if not args.verbose else None,
            stderr=subprocess.PIPE if not args.verbose else None
        )
        processes.append(dashboard_process)
        # Give the dashboard a moment to start
        time.sleep(2)
    
    # Build the main command for the traffic detection system
    main_cmd = [sys.executable, str(AI_TRAFFIC_DIR / "pi" / "main.py")]
    
    # Add command line options
    if args.model:
        main_cmd.extend(["--model", args.model])
    
    if args.camera is not None:
        main_cmd.extend(["--camera", str(args.camera)])
    
    if args.pi_camera:
        main_cmd.append("--pi_camera")
    
    if args.comm_port:
        main_cmd.extend(["--comm_port", args.comm_port])
    
    if args.test_mode:
        main_cmd.append("--test_mode")
    
    if args.test_cameras:
        main_cmd.append("--test_cameras")
    
    logger.info(f"Starting traffic detection system: {' '.join(main_cmd)}")
    main_process = subprocess.Popen(
        main_cmd,
        stdout=subprocess.PIPE if not args.verbose else None,
        stderr=subprocess.PIPE if not args.verbose else None
    )
    processes.append(main_process)
    
    # Monitor processes
    try:
        while not stop_event.is_set():
            # Check if any process has exited
            for p in processes:
                if p.poll() is not None:
                    logger.error(f"Process exited with code {p.returncode}")
                    stop_event.set()
                    break
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        stop_processes()

def main():
    """Parse arguments and start the system"""
    parser = argparse.ArgumentParser(description="AI Traffic Light Control System Runner")
    
    # System Configuration
    parser.add_argument("--with-dashboard", action="store_true", 
                        help="Start the dashboard web interface")
    parser.add_argument("--verbose", action="store_true", 
                        help="Show output from all processes")
    
    # Camera options
    parser.add_argument("--camera", type=str, default=None,
                        help="Camera source (index or file path)")
    parser.add_argument("--pi-camera", action="store_true",
                        help="Use Raspberry Pi camera module")
    parser.add_argument("--test-cameras", action="store_true",
                        help="Test available cameras and exit")
    
    # Model and processing options
    parser.add_argument("--model", type=str, default=None,
                        help="Path to the YOLOv8 model")
    parser.add_argument("--test-mode", action="store_true",
                        help="Run in test mode without a camera")
    
    # Communication options
    parser.add_argument("--comm-port", type=str, default=None,
                        help="Serial port for Arduino/ESP32 communication")
    
    args = parser.parse_args()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start the system
    start_system(args)

if __name__ == "__main__":
    main() 