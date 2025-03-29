# wa_functions.py
import json
import requests
import time
import paho.mqtt.client as mqtt
import win32api
import win32con
import psutil
import ctypes
import wmi
import GPUtil
import platform
from datetime import datetime

try:
    from pyadl import ADLManager
except ImportError:
    ADLManager = None

from wa_definitions import GAME_PROCESSES
from wa_cred import XMRIG_API_URL, MQTT_BROKER, XMRIG_ACCESS_TOKEN


DEBUG_LOCAL = False

# Detect OS and GPU at startup
OS_TYPE = platform.system().lower()  # "windows", "linux", "darwin" (macOS)
GPU_TYPE = None  # Will be set to "nvidia", "amd", or None

def detect_gpu():
    """Detect the GPU type (NVIDIA, AMD, or None)."""
    global GPU_TYPE
    try:
        # Check for NVIDIA GPU using GPUtil
        gpus = GPUtil.getGPUs()
        if gpus:
            GPU_TYPE = "nvidia"
            print(f"Detected GPU: NVIDIA")
            return
    except Exception as e:
        print(f"Error detecting NVIDIA GPU: {e}")

    # Check for AMD GPU using pyadl
    if ADLManager:
        try:
            devices = ADLManager.getInstance().getDevices()
            if devices:
                GPU_TYPE = "amd"
                print(f"Detected GPU: AMD")
                return
        except Exception as e:
            print(f"Error detecting AMD GPU: {e}")

    GPU_TYPE = None
    print("No supported GPU detected.")

# Run GPU detection at startup
detect_gpu()

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected to MQTT broker at {MQTT_BROKER}")
    else:
        print(f"Failed to connect to MQTT with code: {rc}")

# Check if running as admin
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

# Temperature Monitoring Functions
def get_cpu_temperature():
    """Get CPU temperature based on OS."""
    if OS_TYPE == "windows":
        try:
            w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            temperature_infos = w.Sensor()
            for sensor in temperature_infos:
                if sensor.SensorType == "Temperature" and "CPU" in sensor.Name:
                    return sensor.Value
            print("CPU temperature sensor not found via OpenHardwareMonitor.")
            return None
        except Exception as e:
            print(f"Error getting CPU temperature on Windows: {e}")
            return None
    elif OS_TYPE == "linux":
        try:
            # Use psutil on Linux (requires lm-sensors to be installed)
            temps = psutil.sensors_temperatures()
            if "coretemp" in temps:
                for entry in temps["coretemp"]:
                    if "Package" in entry.label:
                        return entry.current
            print("CPU temperature sensor not found on Linux.")
            return None
        except Exception as e:
            print(f"Error getting CPU temperature on Linux: {e}")
            return None
    elif OS_TYPE == "darwin":
        print("CPU temperature monitoring not supported on macOS.")
        return None
    else:
        print(f"Unsupported OS for CPU temperature monitoring: {OS_TYPE}")
        return None

def get_gpu_temperature():
    """Get GPU temperature based on GPU type."""
    if GPU_TYPE == "nvidia":
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                return gpus[0].temperature  # Get temperature of the first GPU
            print("No NVIDIA GPU found.")
            return None
        except Exception as e:
            print(f"Error getting NVIDIA GPU temperature: {e}")
            return None
    elif GPU_TYPE == "amd" and ADLManager:
        try:
            devices = ADLManager.getInstance().getDevices()
            for device in devices:
                temp = device.getCurrentTemperature()
                if temp is not None:
                    return temp
            print("No AMD GPU temperature data available.")
            return None
        except Exception as e:
            print(f"Error getting AMD GPU temperature: {e}")
            return None
    else:
        print("No supported GPU for temperature monitoring.")
        return None

# XMRig API Functions
def get_xmrig_hashrate():
    headers = {"Authorization": f"Bearer {XMRIG_ACCESS_TOKEN}"}
    url = f"{XMRIG_API_URL}/2/summary"
    for attempt in range(3):  # Retry up to 3 times
        try:
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            raw_text = response.text
            if DEBUG_LOCAL:
                print(f"Raw response from {url}: {raw_text}")
            data = json.loads(raw_text)  # Explicitly parse to catch errors
            hashrate = data.get("hashrate", {}).get("total", [0])[1]
            if DEBUG_LOCAL:
                print(f"Hashrate: {hashrate} H/s")
            return hashrate
        except requests.RequestException as e:
            print(f"Attempt {attempt + 1} - Error fetching hashrate from {url}: {e}")
            if e.response:
                print(f"Status: {e.response.status_code}, Raw response: {e.response.text}")
            if attempt < 2:
                time.sleep(1)
        except json.JSONDecodeError as e:
            print(f"Attempt {attempt + 1} - JSON decode error: {e}")
            print(f"Raw response: {raw_text}")
            if attempt < 2:
                time.sleep(1)
    print("All attempts failed to get hashrate")
    return 0

def pause_xmrig():
    headers = {"Authorization": f"Bearer {XMRIG_ACCESS_TOKEN}"}
    payload = {"method": "pause"}
    try:
        response = requests.post(f"{XMRIG_API_URL}/json_rpc", json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        if DEBUG_LOCAL:
            print("XMRig paused via JSON-RPC")
        return True
    except requests.RequestException as e:
        print(f"Error pausing XMRig via JSON-RPC: {e}")
        return False

def resume_xmrig():
    headers = {"Authorization": f"Bearer {XMRIG_ACCESS_TOKEN}"}
    payload = {"method": "resume"}
    try:
        response = requests.post(f"{XMRIG_API_URL}/json_rpc", json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        if DEBUG_LOCAL:
            print("XMRig resumed via JSON-RPC")
        return True
    except requests.RequestException as e:
        print(f"Error resuming XMRig via JSON-RPC: {e}")
        return False

# Game Monitoring Function
def get_current_game():
    for proc in psutil.process_iter(['name']):
        proc_name = proc.info['name'].lower()
        for game, exe in GAME_PROCESSES.items():
            if isinstance(exe, list):
                if proc_name in [e.lower() for e in exe]:
                    return game
            elif proc_name == exe.lower():
                return game
    return None

# User Activity Detection
def get_idle_time():
    if OS_TYPE == "windows":
        last_input_info = win32api.GetLastInputInfo()
        current_time = win32api.GetTickCount()
        idle_time_ms = current_time - last_input_info
        return idle_time_ms / 1000
    elif OS_TYPE == "linux":
        # Basic implementation for Linux (requires additional libraries like Xlib)
        print("Idle time detection not fully supported on Linux.")
        return 0
    elif OS_TYPE == "darwin":
        print("Idle time detection not supported on macOS.")
        return 0
    else:
        print(f"Unsupported OS for idle time detection: {OS_TYPE}")
        return 0