import time
import json
import requests
import win32api
import win32con
import psutil
import ctypes
from datetime import datetime

from sqlalchemy import create_engine, String, Column, Integer, ForeignKey
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import inspect


DEBUG = True
LOCAL_DEBUG = True

# Configuration
from wa_cred import HOSTNAME, MTS_SERVER_NAME, \
    USE_MQTT, MQTT_USER, MQTT_PASSWORD, MQTT_BROKER, MQTT_PORT, MQTT_HASHRATE_TOPIC, MQTT_GAME_TOPIC, \
    IDLE_THRESHOLD, PAUSE_XMRIG, SLEEP_INTERVAL, \
    XMRIG_API_URL, MQTT_BROKER, XMRIG_ACCESS_TOKEN, REPORT_STATS_WATCHER
from wa_definitions import GAME_PROCESSES, engine_fogplayDB, engine_miningDB, Events, BestCoinsForRigView, MinersStats, SupportedCoins
from wa_functions import update_miner_stats, get_gpu_metrics, get_cpu_temperature, detect_gpu, GPU_TYPE
# from wa_functions import GPU_TYPE, detect_gpu, get_cpu_temperature, get_gpu_metrics, get_gpu_temperature #, get_idle_time, get_current_game, get_xmrig_hashrate, pause_xmrig, resume_xmrig

if USE_MQTT: import paho.mqtt.client as mqtt

# Check if running as admin
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

# MQTT Client Setup
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT broker at "+MQTT_BROKER)
    else:
        print(f"Failed to connect to MQTT with code: {rc}")
if USE_MQTT:
    mqtt_client = mqtt.Client()
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    mqtt_client.on_connect = on_connect

# XMRig API Functions
def get_xmrig_hashrate():
    headers = {"Authorization": f"Bearer {XMRIG_ACCESS_TOKEN}"}
    url = f"{XMRIG_API_URL}/2/summary"
    for attempt in range(3):  # Retry up to 3 times
        try:
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            raw_text = response.text
            # if DEBUG:
            #     print(f"Raw response from {url}: {raw_text}")
            data = json.loads(raw_text)  # Explicitly parse to catch errors
            hashrate = data.get("hashrate", {}).get("total", [0])[1]
            if DEBUG:
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
        if DEBUG:
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
        if DEBUG:
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

# Main Loop
def main():
    if not is_admin():
        print("Warning: Not running as admin. Should work for API calls, but monitor for issues.")

    if USE_MQTT:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    is_paused = False
    last_game = None

    # if LOCAL_DEBUG:
    #     try:
    #         detect_gpu()
    #         if GPU_TYPE:
    #             metrics = get_gpu_metrics()
    #             print(f"Final GPU Metrics: {metrics}")
    #         else:
    #             print("Cannot retrieve GPU metrics: No GPU detected.")
    #     except:
    #         pass

    while True:
        try:
            if LOCAL_DEBUG: print("starting new iteration...")
            Session_miningDB = sessionmaker(bind=engine_miningDB)
            session_miningDB = Session_miningDB()   
            session_miningDB.commit()

            Session_fogplayDB = sessionmaker(bind=engine_fogplayDB)
            session_fogplayDB = Session_fogplayDB()   
            session_fogplayDB.commit()
            if LOCAL_DEBUG: print("db connections ready...")

            # Fetch and publish XMRig hashrate
            hashrate = get_xmrig_hashrate()
            timestamp = datetime.now().isoformat()
            #payload = json.dumps({"hashrate": hashrate, "timestamp": timestamp})
            payload = hashrate
            if USE_MQTT:
                mqtt_client.publish(MQTT_HASHRATE_TOPIC, payload)
                if DEBUG:
                    print(f"Published to {MQTT_HASHRATE_TOPIC}: {payload}")

            # Check user activity
            if LOCAL_DEBUG: print("checking idle time...")
            idle_time = get_idle_time()
            if DEBUG:
                print(f"Idle time: {idle_time:.2f} seconds")

            # Pause or resume XMRig based on activity
            if idle_time < IDLE_THRESHOLD and not is_paused and PAUSE_XMRIG:
                if pause_xmrig():
                    is_paused = True
            elif idle_time >= IDLE_THRESHOLD and is_paused and PAUSE_XMRIG:
                if resume_xmrig():
                    is_paused = False
            if LOCAL_DEBUG: print("xmrig is_paused status:",is_paused)

            # Monitor games
            current_game = get_current_game()
            if current_game != last_game and current_game is not None:
                game_payload = json.dumps({
                    "event": "new_game_started",
                    "game": current_game,
                    "timestamp": datetime.now().isoformat()
                })
                if USE_MQTT: mqtt_client.publish(MQTT_GAME_TOPIC, game_payload)

                EventsData = Events(
                    timestamp = datetime.now(),
                    event = "new_game_started",
                    value = current_game,
                    server = MTS_SERVER_NAME
                )		
                session_fogplayDB.add(EventsData)
                session_fogplayDB.commit()

                if DEBUG:
                    print(f"New game detected: {current_game}")
                    if USE_MQTT: print(f"Published to {MQTT_GAME_TOPIC}: {game_payload}")
                last_game = current_game
            elif current_game is None:
                last_game = None

            if REPORT_STATS_WATCHER:
                cpu_temp = get_cpu_temperature()
                # Get GPU metrics
                detect_gpu()
                if GPU_TYPE:
                    gpu_metrics = get_gpu_metrics()
                    print(f"Final GPU Metrics: {gpu_metrics}")
                else:
                    print("Cannot retrieve GPU metrics: No GPU detected.")
                    gpu_metrics = {"temperature": None, "usage": None, "fan_speed_rpm": None, "fan_speed_percent": None}

                # Update miner stats with the current coin, including temperatures
                update_miner_stats(session_miningDB, HOSTNAME, "XXX", hashrate, cpu_temp, gpu_metrics)

            session_miningDB.close()
            session_fogplayDB.close()
            print("timestamp",datetime.now().isoformat())
            time.sleep(SLEEP_INTERVAL)

        except Exception as e:
            print(f"Main loop error: {e}")
            session_miningDB.close()
            session_fogplayDB.close()
            if LOCAL_DEBUG: raise
            time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    main()

