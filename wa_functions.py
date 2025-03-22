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
from datetime import datetime

from wa_setup_2660k import HOSTNAME, MTS_SERVER_NAME, \
    engine_fogplayDB, engine_miningDB, Events, BestCoinsForRigView, MinersStats, SupportedCoins, \
    GAME_PROCESSES, CoinsListSrbmimer, CoinsListXmrig, \
    XMRIG_API_URL, \
    MQTT_BROKER, MQTT_PORT, MQTT_HASHRATE_TOPIC, MQTT_GAME_TOPIC, \
    IDLE_THRESHOLD, PAUSE_XMRIG, \
    SLEEP_INTERVAL
from wa_cred import XMRIG_ACCESS_TOKEN

DEBUG_LOCAL = False

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
    """Get CPU temperature using WMI (requires OpenHardwareMonitor running)."""
    try:
        w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        temperature_infos = w.Sensor()
        for sensor in temperature_infos:
            if sensor.SensorType == "Temperature" and "CPU" in sensor.Name:
                return sensor.Value
        print("CPU temperature sensor not found via OpenHardwareMonitor.")
        return None
    except Exception as e:
        print(f"Error getting CPU temperature: {e}")
        return None

def get_gpu_temperature():
    """Get GPU temperature using GPUtil."""
    try:
        gpus = GPUtil.getGPUs()
        if gpus:
            return gpus[0].temperature  # Get temperature of the first GPU
        print("No GPU found.")
        return None
    except Exception as e:
        print(f"Error getting GPU temperature: {e}")
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
    last_input_info = win32api.GetLastInputInfo()
    current_time = win32api.GetTickCount()
    idle_time_ms = current_time - last_input_info
    return idle_time_ms / 1000