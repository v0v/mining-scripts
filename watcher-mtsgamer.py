import time
import json
import requests
import paho.mqtt.client as mqtt
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

from wa_definitions import GAME_PROCESSES

DEBUG = True

# Configuration
from wa_cred import HOSTNAME, MTS_SERVER_NAME, \
    MQTT_USER, MQTT_PASSWORD, MQTT_BROKER, MQTT_PORT, MQTT_HASHRATE_TOPIC, MQTT_GAME_TOPIC, \
    IDLE_THRESHOLD, PAUSE_XMRIG, SLEEP_INTERVAL, \
    XMRIG_API_URL, MQTT_BROKER, XMRIG_ACCESS_TOKEN  
from wa_definitions import engine_fogplayDB, engine_miningDB, Events, BestCoinsForRigView, MinersStats, SupportedCoins


# Check if running as admin
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

# MQTT Client Setup
mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT broker at "+MQTT_BROKER)
    else:
        print(f"Failed to connect to MQTT with code: {rc}")

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
            if DEBUG:
                print(f"Raw response from {url}: {raw_text}")
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

    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()
    is_paused = False
    last_game = None

    while True:
        try:
            Session_miningDB = sessionmaker(bind=engine_miningDB)
            session_miningDB = Session_miningDB()   
            session_miningDB.commit()

            Session_fogplayDB = sessionmaker(bind=engine_fogplayDB)
            session_fogplayDB = Session_fogplayDB()   
            session_fogplayDB.commit()

            # Fetch and publish XMRig hashrate
            hashrate = get_xmrig_hashrate()
            timestamp = datetime.now().isoformat()
            #payload = json.dumps({"hashrate": hashrate, "timestamp": timestamp})
            payload = hashrate
            mqtt_client.publish(MQTT_HASHRATE_TOPIC, payload)
            if DEBUG:
                print(f"Published to {MQTT_HASHRATE_TOPIC}: {payload}")

            # Check user activity
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

            # Monitor games
            current_game = get_current_game()
            if current_game != last_game and current_game is not None:
                game_payload = json.dumps({
                    "event": "new_game_started",
                    "game": current_game,
                    "timestamp": datetime.now().isoformat()
                })
                mqtt_client.publish(MQTT_GAME_TOPIC, game_payload)

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
                    print(f"Published to {MQTT_GAME_TOPIC}: {game_payload}")
                last_game = current_game
            elif current_game is None:
                last_game = None

            MinerStatsData = MinersStats(
                symbol = 'WOW',
                timestamp = time.time(),
                hostname = HOSTNAME,
                hashrate = hashrate
            )		
            session_miningDB.add(MinerStatsData)
            session_miningDB.commit()

            session_miningDB.close()
            session_fogplayDB.close()
            time.sleep(10)

        except Exception as e:
            print(f"Main loop error: {e}")
            session_miningDB.close()
            session_fogplayDB.close()
            time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    main()

