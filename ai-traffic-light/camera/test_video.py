#!/usr/bin/env python3
import cv2
import argparse
import time
import logging
import sys
import os

# Add parent directory to path for importing
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('camera_test')

def test_camera(camera_id=0, width=640, height=480, fps=30, output_file=None, duration=0):
    """
    Test camera by displaying video feed and optionally recording
    
    Args:
        camera_id: Camera device ID (usually 0 for built-in/first camera)
        width: Frame width
        height: Frame height
        fps: Frames per second for recording
        output_file: Output video file (if recording)
        duration: Recording duration in seconds (0 for unlimited)
    """
    try:
        # Initialize camera
        logger.info(f"Initializing camera {camera_id} with resolution {width}x{height}")
        cap = cv2.VideoCapture(camera_id)
        
        # Set camera properties
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        
        # Check if camera opened successfully
        if not cap.isOpened():
            logger.error("Failed to open camera")
            return False
        
        # Get actual camera properties (may differ from requested)
        actual_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        
        logger.info(f"Camera initialized with actual resolution: {actual_width}x{actual_height}, FPS: {actual_fps}")
        
        # Initialize video writer if output file specified
        video_writer = None
        if output_file:
            fourcc = cv2.VideoWriter_fourcc(*'XVID')  # Use 'XVID' codec
            video_writer = cv2.VideoWriter(output_file, fourcc, fps, (int(actual_width), int(actual_height)))
            logger.info(f"Recording video to {output_file}")
        
        # Start time for duration tracking
        start_time = time.time()
        frame_count = 0
        
        # Display info
        print("Press 'q' or 'ESC' to quit")
        print("Press 's' to save a snapshot")
        
        while True:
            # Read frame
            ret, frame = cap.read()
            
            if not ret:
                logger.error("Failed to read frame from camera")
                break
            
            # Add frame info overlay
            elapsed = time.time() - start_time
            fps_real = frame_count / elapsed if elapsed > 0 else 0
            
            cv2.putText(
                frame, f"Frame: {frame_count} | FPS: {fps_real:.1f} | Time: {elapsed:.1f}s",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
            )
            
            # Add lane division lines (for traffic system visualization)
            h, w = frame.shape[:2]
            
            # Draw vertical lines separating lanes
            for i in range(1, 4):
                x = int(w * i / 4)
                cv2.line(frame, (x, 0), (x, h), (0, 255, 255), 2)
                cv2.putText(
                    frame, f"L{i} | L{i+1}", (x - 40, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1
                )
            
            # Display frame
            cv2.imshow("Camera Test", frame)
            
            # Record frame if enabled
            if video_writer is not None:
                video_writer.write(frame)
            
            # Increment frame counter
            frame_count += 1
            
            # Check for key press
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:  # 'q' or ESC key
                logger.info("Test terminated by user")
                break
            elif key == ord('s'):  # 's' key for snapshot
                snapshot_file = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
                cv2.imwrite(snapshot_file, frame)
                logger.info(f"Snapshot saved to {snapshot_file}")
            
            # Check duration limit
            if duration > 0 and (time.time() - start_time) >= duration:
                logger.info(f"Reached specified duration of {duration} seconds")
                break
        
        # Clean up
        cap.release()
        if video_writer is not None:
            video_writer.release()
        cv2.destroyAllWindows()
        
        logger.info(f"Camera test completed: {frame_count} frames captured in {time.time() - start_time:.1f} seconds")
        return True
        
    except Exception as e:
        logger.error(f"Error during camera test: {str(e)}")
        return False

def test_file_video(video_file):
    """
    Test playing a video file
    
    Args:
        video_file: Path to video file
    """
    try:
        # Open video file
        logger.info(f"Opening video file: {video_file}")
        cap = cv2.VideoCapture(video_file)
        
        # Check if file opened successfully
        if not cap.isOpened():
            logger.error(f"Failed to open video file: {video_file}")
            return False
        
        # Get video properties
        width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        logger.info(f"Video properties: {width}x{height}, {fps} FPS, {frame_count} frames")
        
        # Start time for FPS calculation
        start_time = time.time()
        current_frame = 0
        
        while True:
            # Read frame
            ret, frame = cap.read()
            
            # Break if end of video
            if not ret:
                logger.info("Reached end of video file")
                break
            
            # Add frame info overlay
            current_frame += 1
            elapsed = time.time() - start_time
            playback_fps = current_frame / elapsed if elapsed > 0 else 0
            
            # Add text overlay
            cv2.putText(
                frame, f"Frame: {current_frame}/{frame_count} | FPS: {playback_fps:.1f}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
            )
            
            # Add lane division lines
            h, w = frame.shape[:2]
            for i in range(1, 4):
                x = int(w * i / 4)
                cv2.line(frame, (x, 0), (x, h), (0, 255, 255), 2)
                cv2.putText(
                    frame, f"L{i} | L{i+1}", (x - 40, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1
                )
            
            # Display frame
            cv2.imshow("Video Test", frame)
            
            # Wait for specified time to maintain original FPS
            if fps > 0:
                wait_time = int(1000 / fps)
            else:
                wait_time = 30  # Default to 30ms (approx 33 FPS)
            
            # Check for key press
            key = cv2.waitKey(wait_time) & 0xFF
            if key == ord('q') or key == 27:  # 'q' or ESC key
                logger.info("Test terminated by user")
                break
            elif key == ord('s'):  # 's' key for snapshot
                snapshot_file = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
                cv2.imwrite(snapshot_file, frame)
                logger.info(f"Snapshot saved to {snapshot_file}")
        
        # Clean up
        cap.release()
        cv2.destroyAllWindows()
        
        logger.info(f"Video playback completed: {current_frame} frames in {time.time() - start_time:.1f} seconds")
        return True
        
    except Exception as e:
        logger.error(f"Error during video test: {str(e)}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Camera and Video Testing Tool")
    
    # Create mode subparsers
    subparsers = parser.add_subparsers(dest="mode", help="Test mode")
    
    # Camera test arguments
    camera_parser = subparsers.add_parser("camera", help="Test camera feed")
    camera_parser.add_argument("-i", "--id", type=int, default=0, help="Camera ID (default: 0)")
    camera_parser.add_argument("-w", "--width", type=int, default=640, help="Frame width (default: 640)")
    camera_parser.add_argument("-h", "--height", type=int, default=480, help="Frame height (default: 480)")
    camera_parser.add_argument("-o", "--output", type=str, help="Output video file (optional)")
    camera_parser.add_argument("-d", "--duration", type=int, default=0, help="Recording duration in seconds (0 for unlimited)")
    
    # Video file test arguments
    video_parser = subparsers.add_parser("video", help="Test video file playback")
    video_parser.add_argument("file", type=str, help="Video file path")
    
    args = parser.parse_args()
    
    if args.mode == "camera":
        test_camera(
            camera_id=args.id,
            width=args.width,
            height=args.height,
            output_file=args.output,
            duration=args.duration
        )
    elif args.mode == "video":
        test_file_video(args.file)
    else:
        parser.print_help() 