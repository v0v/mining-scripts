import os
import cv2
import numpy as np
import mss  # For faster screen capture
import psutil
import time
from datetime import datetime
import keyboard
import threading
import sys
import atexit
import ctypes
from ctypes import wintypes
import uuid  # For generating unique session IDs
import shutil  # For file operations

# Configuration
NETWORK_PATH = "Z:/"  # Network drive path (e.g., Z:\)
LOCAL_PATH = "C:/temp"  # Local directory for temporary storage (set to None to disable)
SERVER_PREFIX = "1216bX4"  # Predefined server prefix for filenames
RECORD_DURATION = 300  # Total recording duration in seconds (5 minutes for testing)
CHUNK_DURATION = 30  # Duration of each chunk in seconds (save every 30 seconds)
GAME_PROCESSES = ["notepad.exe", "csgo.exe", "dota2.exe"]  # List of game executable names (update as needed)
IDLE_THRESHOLD = 5  # Idle time in seconds to consider user inactive
VIDEO_FPS = 15  # Target frames per second for recording
VIDEO_RESOLUTION = (960, 540)  # Recording resolution
TARGET_BITRATE = 1000  # Target bitrate in kbps (1 Mbps)

# Global variables
recording = False
writer = None
chunk_start_time = None
current_chunk_file = None
stop_recording_event = threading.Event()
session_id = None  # Unique session ID for this recording session
chunk_files = []  # List to store chunk filenames for reference (network paths)

# Windows API structures and functions for idle time detection
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]

# Load Windows user32.dll to access GetLastInputInfo
user32 = ctypes.WinDLL("user32", use_last_error=True)
GetLastInputInfo = user32.GetLastInputInfo
GetLastInputInfo.restype = wintypes.BOOL
GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]

# Load kernel32.dll to access GetTickCount
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
GetTickCount = kernel32.GetTickCount
GetTickCount.restype = wintypes.DWORD

def get_idle_time():
    """Get the time since the last user input (mouse or keyboard) using Windows API."""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    
    if not GetLastInputInfo(ctypes.byref(lii)):
        raise ctypes.WinError(ctypes.get_last_error())
    
    current_ticks = GetTickCount()
    idle_ticks = current_ticks - lii.dwTime
    idle_seconds = idle_ticks / 1000.0
    return idle_seconds

def get_filename(suffix=""):
    """Generate a unique filename for the recording chunk."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Use local path if enabled, otherwise use network path
    base_path = LOCAL_PATH if LOCAL_PATH else NETWORK_PATH
    return os.path.join(base_path, f"{SERVER_PREFIX}_{session_id}_{timestamp}{suffix}.mkv")

def copy_to_network(local_file):
    """Copy a file from the local directory to the network drive and delete the local copy."""
    if not os.path.exists(local_file):
        print(f"Local file {local_file} does not exist. Cannot copy to network drive.")
        return None
    network_file = os.path.join(NETWORK_PATH, os.path.basename(local_file))
    max_retries = 3
    for attempt in range(max_retries):
        try:
            shutil.copy2(local_file, network_file)
            print(f"Copied {local_file} to {network_file}")
            # Delete the local file after successful copy
            os.remove(local_file)
            print(f"Deleted local file: {local_file}")
            return network_file
        except Exception as e:
            print(f"Failed to copy {local_file} to {network_file} (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                print("Max retries reached. Could not copy to network drive.")
                return None
            time.sleep(5)
    return None

def is_game_running():
    """Check if any game process is running."""
    for proc in psutil.process_iter(['name']):
        if proc.info['name'].lower() in [game.lower() for game in GAME_PROCESSES]:
            return True
    return False

def start_new_chunk(chunk_duration, chunk_frames):
    """Start a new video chunk with the actual frame rate based on captured frames."""
    global writer, chunk_start_time, current_chunk_file
    # Close the previous chunk if it exists
    if writer is not None:
        writer.release()
        # Delay to ensure the file is fully written
        time.sleep(1)
        if current_chunk_file and os.path.exists(current_chunk_file):
            # Copy to network drive if using local storage
            if LOCAL_PATH:
                network_file = copy_to_network(current_chunk_file)
                if network_file:
                    chunk_files.append(network_file)
            else:
                chunk_files.append(current_chunk_file)
    # Generate a new filename for the chunk
    current_chunk_file = get_filename("_chunk")
    # Calculate the actual frame rate for this chunk
    if chunk_duration > 0 and chunk_frames > 0:
        actual_fps = chunk_frames / chunk_duration
    else:
        actual_fps = VIDEO_FPS  # Fallback to target FPS if no frames captured
    print(f"Setting chunk frame rate to {actual_fps:.2f} FPS (captured {chunk_frames} frames in {chunk_duration:.1f} seconds)")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Try H264 codec first
            fourcc = cv2.VideoWriter_fourcc(*'H264')
            writer = cv2.VideoWriter(current_chunk_file, fourcc, actual_fps, VIDEO_RESOLUTION)
            if writer.isOpened():
                print("Using H264 codec for chunk recording")
                # Explicitly set bitrate (if supported by backend)
                writer.set(cv2.CAP_PROP_BITRATE, TARGET_BITRATE)
                break
            else:
                print("H264 codec failed. Falling back to mp4v...")
                # Fallback to mp4v if H264 fails
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                writer = cv2.VideoWriter(current_chunk_file, fourcc, actual_fps, VIDEO_RESOLUTION)
                if writer.isOpened():
                    print("Using mp4v codec for chunk recording")
                    break
                else:
                    raise Exception("Failed to open video writer with mp4v")
        except Exception as e:
            print(f"Codec failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                print("Max retries reached. Cannot save chunk.")
                writer = None
                return
            time.sleep(5)
    chunk_start_time = time.time()
    print(f"Started new chunk: {current_chunk_file}")

def record_screen():
    """Record the screen and save to chunks, using local storage if enabled."""
    global recording, writer, session_id
    recording = True
    # Generate a unique session ID for this recording session
    session_id = str(uuid.uuid4()).replace("-", "")# + "_" + datetime.now().strftime("%Y%m%d")
    print(f"Starting recording session with ID: {session_id}")
    # Ensure local directory exists if enabled
    if LOCAL_PATH and not os.path.exists(LOCAL_PATH):
        os.makedirs(LOCAL_PATH)
    start_time = time.time()
    chunk_files.clear()  # Reset the list of chunks
    start_new_chunk(0, 0)  # Initial chunk (pass 0 duration and frames to use default FPS)

    frame_interval = 1 / VIDEO_FPS  # Target time per frame in seconds (e.g., 1/15 = 0.0667s)
    frame_count = 0  # Total frames recorded
    chunk_frame_count = 0  # Frames in the current chunk
    last_log_time = start_time  # For logging actual frame rate
    last_frame_count = 0  # For calculating frame rate

    # Initialize mss for screen capture
    sct = mss.mss()
    # Adjust monitor dimensions to your screen resolution (e.g., 1920x1080)
    monitor = {"top": 0, "left": 0, "width": 1920, "height": 1080}

    while not stop_recording_event.is_set():
        frame_start = time.time()

        # Capture the screen using mss
        try:
            screenshot = sct.grab(monitor)
            frame = np.array(screenshot)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)  # Convert from BGRA to BGR
            frame = cv2.resize(frame, VIDEO_RESOLUTION)
        except Exception as e:
            print(f"Error capturing screen: {e}")
            continue

        # Write the frame to the current chunk
        if writer is not None:
            writer.write(frame)
            frame_count += 1
            chunk_frame_count += 1

        # Log actual frame rate every 5 seconds
        current_time = time.time()
        if current_time - last_log_time >= 5:
            elapsed = current_time - last_log_time
            frames_in_interval = frame_count - last_frame_count
            actual_fps = frames_in_interval / elapsed
            print(f"Actual frame rate: {actual_fps:.2f} FPS (target: {VIDEO_FPS} FPS)")
            last_log_time = current_time
            last_frame_count = frame_count

        # Check if it's time to start a new chunk (based on elapsed time)
        chunk_elapsed = current_time - chunk_start_time
        if chunk_elapsed >= CHUNK_DURATION:
            print(f"Chunk duration reached ({chunk_elapsed:.1f} seconds, {chunk_frame_count} frames). Starting new chunk...")
            start_new_chunk(chunk_elapsed, chunk_frame_count)
            chunk_frame_count = 0

        # Check if the total recording duration has been reached
        total_elapsed = current_time - start_time
        if total_elapsed >= RECORD_DURATION:
            print(f"Total duration reached ({total_elapsed:.1f} seconds, {frame_count} frames). Stopping recording...")
            # Calculate the actual duration of the last chunk
            last_chunk_duration = current_time - chunk_start_time
            if last_chunk_duration > 0 and chunk_frame_count > 0:
                print(f"Final chunk duration: {last_chunk_duration:.1f} seconds, {chunk_frame_count} frames")
            break

        # Adjust sleep to maintain target frame rate
        elapsed = time.time() - frame_start
        sleep_time = max(0, frame_interval - elapsed)
        time.sleep(sleep_time)

    # Finalize the recording
    if writer is not None:
        writer.release()
        # Delay to ensure the file is fully written
        time.sleep(1)
        if current_chunk_file and os.path.exists(current_chunk_file):
            if LOCAL_PATH:
                network_file = copy_to_network(current_chunk_file)
                if network_file:
                    chunk_files.append(network_file)
            else:
                chunk_files.append(current_chunk_file)
    recording = False
    print(f"Recording stopped. Chunks saved for session ID {session_id}: {chunk_files}")

def cleanup():
    """Ensure the current chunk is saved on script exit and clean up local files."""
    global recording, writer
    if recording and writer is not None:
        print("Saving current chunk before exit...")
        writer.release()
        # Delay to ensure the file is fully written
        time.sleep(1)
        if current_chunk_file and os.path.exists(current_chunk_file):
            if LOCAL_PATH:
                network_file = copy_to_network(current_chunk_file)
                if network_file:
                    chunk_files.append(network_file)
                    print(f"Chunk saved due to script exit: {network_file}")
            else:
                chunk_files.append(current_chunk_file)
                print(f"Chunk saved due to script exit: {current_chunk_file}")

def main():
    """Main loop to monitor user activity and game processes, stopping after one recording session."""
    print("Starting game session monitor...")
    last_game_detected = False

    while True:
        try:
            # Check for user activity and game processes
            idle_time = get_idle_time()
            game_running = is_game_running()
            user_active = idle_time < IDLE_THRESHOLD

            # Start recording if a game is running and the user is active
            if (game_running or user_active) and not last_game_detected and not recording:
                print("Game session or user activity detected. Starting recording...")
                stop_recording_event.clear()
                recording_thread = threading.Thread(target=record_screen)
                recording_thread.start()
                last_game_detected = True

            # If recording has finished, exit the script
            if last_game_detected and not recording:
                print("Recording session completed. Exiting script...")
                # Ensure the recording thread has finished
                if 'recording_thread' in locals():
                    recording_thread.join()
                break

            # Check for a manual stop (e.g., press 'q' to quit the script)
            if keyboard.is_pressed('q'):
                print("Manual stop requested. Exiting...")
                stop_recording_event.set()
                # Ensure the recording thread has finished
                if 'recording_thread' in locals():
                    recording_thread.join()
                break

            time.sleep(1)

        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    atexit.register(cleanup)
    main()