# wa_grok.py
import asyncio
import json
import subprocess
import time

import os
import threading
import queue
import platform
import signal
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from pathlib import Path

from wa_definitions import engine_fogplayDB, engine_miningDB, Events, BestCoinsForRigView, MinersStats, SupportedCoins
from wa_cred import HOSTNAME, MTS_SERVER_NAME, \
    USE_MQTT, MQTT_BROKER, MQTT_PORT, MQTT_HASHRATE_TOPIC, MQTT_GAME_TOPIC, \
    IDLE_THRESHOLD, \
    CoinsListSrbmimer, CoinsListXmrig, SLEEP_INTERVAL, \
    ENABLE_MINING, PAUSE_XMRIG
from wa_functions import GPU_TYPE, get_current_game, get_idle_time, is_admin, pause_xmrig, resume_xmrig, on_connect, detect_gpu, get_cpu_temperature, get_gpu_temperature, get_gpu_metrics, update_miner_stats
from wa_cred import MQTT_USER, MQTT_PASSWORD, XMRIG_CLI_ARGS_SENSITIVE, SRBMINER_CLI_ARGS_SENSITIVE, DEROLUNA_CLI_ARGS_SENSITIVE

if USE_MQTT: import paho.mqtt.client as mqtt

PAUSE_XMRIG = False ########### =============== !!!!!!!!!!!!!!!!!!!!!! -=================
DEBUG = True  # Detailed logging
PRINT_MINER_LOG = True

# Constants for hashrate monitoring
HASHRATE_WINDOW = 15 * 60  # 15 minutes window for moving average (in seconds)
HASHRATE_THRESHOLD = 0.5  # Restart if hashrate drops below 50% of the target hashrate
HASHRATE_DROP_DURATION = 5 * 60  # Require the drop to persist for 5 minutes (in seconds)
CHECK_INTERVAL = 10  # Check every 10 seconds

# Temperature thresholds (in Celsius)
CPU_TEMP_THRESHOLD = 85.0  # Stop mining if CPU temp exceeds 85°C
GPU_TEMP_THRESHOLD = 90.0  # Stop mining if GPU temp exceeds 90°C

# Cooldown period for failed coins (in seconds)
FAILED_COIN_COOLDOWN = 3600  # 1 hour

# Detect the operating system
OS_NAME = platform.system().lower()
IS_WINDOWS = OS_NAME == "windows"
IS_LINUX = OS_NAME == "linux"

if not (IS_WINDOWS or IS_LINUX):
    raise RuntimeError(f"Unsupported operating system: {OS_NAME}. This script supports Windows and Linux (Ubuntu) only.")

# Platform-specific paths and filenames
if IS_WINDOWS:
    # Windows paths
    # downloads_folder = Path.home() / "Downloads"
    # XMRIG_PATH = str(downloads_folder / "toolz" / "miners" / "xmrig" / "xmrig.exe")
    # SRBMINER_PATH = str(downloads_folder / "toolz" / "miners" / "srbminer" / "SRBMiner-Multi.exe")
    # DEROLUNA_PATH = str(downloads_folder / "toolz" / "miners" / "deroluna" / "deroluna-miner.exe")
    scripts_folder = Path("C:/scripts")
    XMRIG_PATH = str(scripts_folder / "wa" / "miners" / "xmrig" / "xmrig.exe")
    SRBMINER_PATH = str(scripts_folder / "wa" / "miners" / "srbminer" / "SRBMiner-Multi.exe")
    DEROLUNA_PATH = str(scripts_folder / "wa" / "miners" / "deroluna" / "deroluna-miner.exe")
    DEROLUNA_CLI_ARGS = {
        "DERO": []
    }
else:
    # Ubuntu paths
    home_folder = Path.home()
    XMRIG_PATH = str(home_folder / "miners" / "xmrig-6.22.0" / "xmrig")
    SRBMINER_PATH = str(home_folder / "miners" / "SRBMiner-Multi")
    DEROLUNA_PATH = str(home_folder / "miners" / "deroluna")

    # CLI arguments for DeroLuna (DERO) (non-sensitive parts)
    DEROLUNA_CLI_ARGS = {
        "DERO": [
            f"-d {DEROLUNA_CLI_ARGS_SENSITIVE['DERO']['daemon-address']}",
            f"-w {DEROLUNA_CLI_ARGS_SENSITIVE['DERO']['wallet-address']}",
            "-t", "0"
        ]
    }

# Ensure miner executables are executable on Linux
if IS_LINUX:
    for miner_path in [XMRIG_PATH, SRBMINER_PATH, DEROLUNA_PATH]:
        try:
            os.chmod(miner_path, 0o755)  # Make the file executable
            print(f"Set executable permissions for {miner_path}")
        except Exception as e:
            print(f"Error setting executable permissions for {miner_path}: {e}")

# CLI arguments for XMRig-supported coins (non-sensitive parts)
XMRIG_CLI_ARGS = {
    "XMR": [
        "--algo=rx/0",
        f"--url={XMRIG_CLI_ARGS_SENSITIVE['XMR']['url']}",
        f"--user={XMRIG_CLI_ARGS_SENSITIVE['XMR']['user']}",
        f"--pass={XMRIG_CLI_ARGS_SENSITIVE['XMR']['pass']}",
        f"--rig-id={HOSTNAME}",
        "--donate-level=1",
        "--cpu",
        "--no-gpu",
        "--threads=23",
        "--http-port=37329",
        "--http-no-restricted",
        "--http-access-token=auth"
    ],
    "WOW": [
        "--algo=rx/wow",
        f"--url={XMRIG_CLI_ARGS_SENSITIVE['WOW']['url']}",
        f"--user={XMRIG_CLI_ARGS_SENSITIVE['WOW']['user']}",
        f"--pass={XMRIG_CLI_ARGS_SENSITIVE['WOW']['pass']}",
        f"--rig-id={HOSTNAME}",
        "--donate-level=1",
        "--cpu",
        "--no-gpu",
        "--threads=23",
        "--http-port=37329",
        "--http-no-restricted",
        "--http-access-token=auth"
    ],
    "SAL": [
        "--algo=rx/0",
        f"--url={XMRIG_CLI_ARGS_SENSITIVE['SAL']['url']}",
        f"--user={XMRIG_CLI_ARGS_SENSITIVE['SAL']['user']}",
        f"--pass={XMRIG_CLI_ARGS_SENSITIVE['SAL']['pass']}",
        f"--rig-id={HOSTNAME}",
        "--donate-level=1",
        "--cpu",
        "--no-gpu",
        "--threads=23",
        "--http-port=37329",
        "--http-no-restricted",
        "--http-access-token=auth"
    ],
    "SEXT": [
        "--algo=rx/0",
        f"--url={XMRIG_CLI_ARGS_SENSITIVE['SEXT']['url']}",
        f"--user={XMRIG_CLI_ARGS_SENSITIVE['SEXT']['user']}",
        "--pass m=solo",  # Updated as per your specification
        f"--rig-id={HOSTNAME}",
        "--donate-level=1",
        "--cpu",
        "--no-gpu",
        "--tls",  # Added as per your specification
        "--threads=23",
        "--http-port=37329",
        "--http-no-restricted",
        "--http-access-token=auth"
    ]
}

# CLI arguments for SRBMiner-supported coins (non-sensitive parts)
SRBMINER_CLI_ARGS = {
    "ETI": [
        "--algorithm", "etchash",
        "--pool", "etchash.unmineable.com:3333",
        f"--wallet={SRBMINER_CLI_ARGS_SENSITIVE['ETI']['wallet']}",
        "--worker", HOSTNAME,
        "--disable-gpu",
        "--cpu-threads", "0"
    ],
    "PEPEW": [
        "--algorithm", "kawpow",
        "--pool", "kawpow.unmineable.com:3333",
        f"--wallet={SRBMINER_CLI_ARGS_SENSITIVE['PEPEW']['wallet']}",
        "--worker", HOSTNAME,
        "--disable-gpu",
        "--cpu-threads", "0"
    ],
    "SCASH": [
        "--algorithm", "scrypt",
        "--pool", "scrypt.unmineable.com:3333",
        f"--wallet={SRBMINER_CLI_ARGS_SENSITIVE['SCASH']['wallet']}",
        "--worker", HOSTNAME,
        "--disable-gpu",
        "--cpu-threads", "0"
    ],
    "TDC": [
        "--algorithm", "ethash",
        "--pool", "ethash.unmineable.com:3333",
        f"--wallet={SRBMINER_CLI_ARGS_SENSITIVE['TDC']['wallet']}",
        "--worker", HOSTNAME,
        "--disable-gpu",
        "--cpu-threads", "0"
    ],
    "VRSC": [
        "--algorithm", "verushash",
        "--pool", "stratum+tcp://verushash.na.mine.zergpool.com:3300",
        f"--wallet={SRBMINER_CLI_ARGS_SENSITIVE['VRSC']['wallet']}",
        "--worker", HOSTNAME,
        "--disable-gpu",
        "--cpu-threads", "0"
    ]
}

# MQTT Client Setup
if USE_MQTT:
    mqtt_client = mqtt.Client()
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    mqtt_client.on_connect = on_connect

class MinerController:
    def __init__(self, miner_path, cli_args, hashrate_pattern, hashrate_index, session_miningDB, session_fogplayDB):
        self.miner_path = miner_path
        self.cli_args = cli_args
        self.hashrate_pattern = hashrate_pattern
        self.hashrate_index = hashrate_index
        self.session_miningDB = session_miningDB
        self.session_fogplayDB = session_fogplayDB
        self.process = None
        self.is_mining = False
        self.current_coin = None
        self.hashrate = 0.0
        self.target_hashrate = None
        self.output_queue = queue.Queue()
        self.running = False
        self.hashrate_history = []  # List of (timestamp, hashrate) tuples
        self.low_hashrate_start = None  # Timestamp when hashrate drop started
        self.last_output_time = None  # Track last time output was received
        self.restart_count = 0  # Track number of restarts
        self.last_restart_time = None  # Track time of last restart
        self.last_failed_coin = None  # Track the last coin that failed
        self.MAX_RESTARTS = 3  # Max restarts allowed in RESTART_WINDOW
        self.RESTART_WINDOW = 3600  # 1 hour in seconds
        self.OUTPUT_TIMEOUT = 300  # 5 minutes timeout for no output

    def fetch_target_hashrate(self):
        """Fetch the target hashrate (rig_hr_kh) from SupportedCoins table."""
        if not self.current_coin:
            return None
        try:
            coin = self.session_miningDB.query(SupportedCoins).filter(
                SupportedCoins.symbol == self.current_coin,
                SupportedCoins.worker == HOSTNAME
            ).first()
            if coin and coin.rig_hr_kh is not None:
                # Convert rig_hr_kh (kH/s) to H/s for comparison
                self.target_hashrate = coin.rig_hr_kh * 1000
                if DEBUG:
                    print(f"Target hashrate for {self.current_coin}: {self.target_hashrate} H/s")
                return self.target_hashrate
            else:
                print(f"No target hashrate found for {self.current_coin} in SupportedCoins")
                return None
        except Exception as e:
            print(f"Error fetching target hashrate for {self.current_coin}: {e}")
            return None

    def log_event(self, event_name, event_value):
        """Log an event to the Events table."""
        try:
            event_data = Events(
                timestamp=datetime.fromtimestamp(time.time()),  # Convert Unix timestamp to datetime
                event=event_name,
                value=event_value,
                server=MTS_SERVER_NAME
            )
            self.session_fogplayDB.add(event_data)
            self.session_fogplayDB.commit()
            if DEBUG:
                print(f"Logged event: {event_name} - {event_value}")
        except Exception as e:
            print(f"Error logging event {event_name}: {e}")
            self.session_fogplayDB.rollback()

    def read_output(self):
        """Read miner output from stdout and parse hashrate."""
        # Open a log file for miner output
        log_file = f"{self.current_coin}_miner.log"
        with open(log_file, "a", encoding="utf-8") as f:
            while self.running:
                try:
                    # Check if the process has exited
                    if self.process.poll() is not None:
                        print(f"Miner process ({os.path.basename(self.miner_path)}) has exited unexpectedly. Restarting...")
                        self.stop_mining()
                        self.start_mining(self.current_coin)
                        break

                    # Read a line from stdout with a timeout
                    line = self.process.stdout.readline().strip()
                    current_time = time.time()

                    if not line:
                        # Check for output timeout
                        if self.last_output_time and (current_time - self.last_output_time) > self.OUTPUT_TIMEOUT:
                            print(f"No output received for {self.OUTPUT_TIMEOUT} seconds. Restarting miner...")
                            self.stop_mining()
                            self.start_mining(self.current_coin)
                            break
                        time.sleep(0.1)  # Avoid busy-waiting
                        continue

                    # Update last output time
                    self.last_output_time = current_time

                    # Log the output to file
                    f.write(f"[{datetime.now().isoformat()}] {line}\n")
                    f.flush()

                    if PRINT_MINER_LOG:
                        print(line)
                    self.output_queue.put(line)

                    # Parse hashrate based on miner-specific pattern
                    if self.hashrate_pattern in line:
                        try:
                            parts = line.split()
                            hashrate_str = parts[self.hashrate_index]
                            self.hashrate = float(hashrate_str)
                            # Convert hashrate to H/s based on miner type
                            if "deroluna" in self.miner_path.lower():
                                # DeroLuna reports in KH/s, convert to H/s
                                self.hashrate *= 1000
                            if DEBUG:
                                print(f"Parsed hashrate for {self.current_coin}: {self.hashrate} H/s")

                            # Update hashrate history
                            self.hashrate_history.append((current_time, self.hashrate))
                            self.hashrate_history = [(t, hr) for t, hr in self.hashrate_history if t >= current_time - HASHRATE_WINDOW]

                            # Fetch target hashrate if not already set
                            if self.target_hashrate is None:
                                self.fetch_target_hashrate()

                            # Calculate moving average
                            moving_avg = self.calculate_moving_average(current_time)
                            if moving_avg is None:
                                if DEBUG:
                                    print("Not enough hashrate data for moving average yet.")
                                continue

                            # Check for significant hashrate drop compared to target
                            if self.target_hashrate and self.target_hashrate > 0:
                                threshold = self.target_hashrate * HASHRATE_THRESHOLD
                                if moving_avg < threshold:
                                    if self.low_hashrate_start is None:
                                        self.low_hashrate_start = current_time
                                        if DEBUG:
                                            print(f"Moving average hashrate dropped below threshold ({moving_avg} < {threshold}). Monitoring...")
                                    elif current_time - self.low_hashrate_start >= HASHRATE_DROP_DURATION:
                                        print(f"Moving average hashrate has been below threshold for {HASHRATE_DROP_DURATION} seconds ({moving_avg} < {threshold}). Restarting miner...")
                                        self.stop_mining()
                                        success = self.start_mining(self.current_coin)
                                        if not success:
                                            # If start_mining fails (e.g., max restarts exceeded), stop mining this coin
                                            print(f"Failed to restart miner for {self.current_coin}. Marking coin as failed.")
                                            self.current_coin = None  # Signal to the main loop to switch coins
                                            break
                                        self.low_hashrate_start = None  # Reset after restart
                                else:
                                    if self.low_hashrate_start is not None:
                                        if DEBUG:
                                            print(f"Moving average hashrate recovered ({moving_avg} >= {threshold}). Resetting monitor.")
                                        self.low_hashrate_start = None

                        except (IndexError, ValueError) as e:
                            self.hashrate = 0
                            print(f"Error parsing hashrate from line '{line}': {e}")
                except UnicodeDecodeError as e:
                    print(f"Encoding error in miner output: {e}. Skipping line.")
                    continue
                except Exception as e:
                    print(f"Error reading miner output: {e}")
                    time.sleep(0.1)  # Avoid busy-waiting on errors

    def calculate_moving_average(self, current_time):
        """Calculate the moving average hashrate over the last HASHRATE_WINDOW seconds."""
        cutoff_time = current_time - HASHRATE_WINDOW
        recent_hashrates = [hr for timestamp, hr in self.hashrate_history if timestamp >= cutoff_time]
        
        if not recent_hashrates:
            return None  # Not enough data to calculate average
        
        return sum(recent_hashrates) / len(recent_hashrates)

    def start_mining(self, coin_symbol):
        if not ENABLE_MINING:
            return False
        """Start the miner for the specified coin using CLI arguments."""
        if self.is_mining:
            print("Miner is already running. Stopping first...")
            self.stop_mining()

        if coin_symbol not in self.cli_args:
            print(f"Error: No CLI arguments defined for coin {coin_symbol}")
            return False

        # Check restart limit
        current_time = time.time()
        if self.last_restart_time and (current_time - self.last_restart_time) < self.RESTART_WINDOW:
            self.restart_count += 1
            if self.restart_count > self.MAX_RESTARTS:
                print(f"Exceeded maximum restarts ({self.MAX_RESTARTS}) in {self.RESTART_WINDOW} seconds. Aborting mining for {coin_symbol}.")
                self.log_event("mining_failed", f"Exceeded maximum restarts for {coin_symbol}")
                self.last_failed_coin = coin_symbol  # Track the failed coin
                return False
        else:
            # Reset counter if outside the window
            self.restart_count = 0
            self.last_restart_time = current_time

        try:
            cmd = [self.miner_path] + self.cli_args[coin_symbol]
            # Start the subprocess in a platform-agnostic way
            self.process = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(self.miner_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Redirect stderr to stdout
                universal_newlines=True,  # Text mode for output
                bufsize=1,  # Line buffering
                preexec_fn=os.setsid if IS_LINUX else None  # Use process group on Linux
            )
            self.is_mining = True
            self.current_coin = coin_symbol
            self.running = True
            self.hashrate_history = []
            self.low_hashrate_start = None
            self.target_hashrate = None
            self.last_output_time = time.time()

            # Start a thread to read output
            self.output_thread = threading.Thread(target=self.read_output)
            self.output_thread.start()

            print(f"Miner started for {coin_symbol}.")
            self.log_event("mining_started", f"Started mining {coin_symbol}")
            return True
        except Exception as e:
            print(f"Error starting miner: {e}")
            self.log_event("mining_failed", f"Failed to start mining {coin_symbol}: {str(e)}")
            self.is_mining = False
            return False

    def stop_mining(self):
        """Stop the miner gracefully in a platform-agnostic way."""
        if self.is_mining and self.process:
            try:
                self.running = False
                # Use psutil to handle process tree termination on both Windows and Linux
                import psutil
                parent = psutil.Process(self.process.pid)
                # Get all child processes
                children = parent.children(recursive=True)
                
                # Try graceful termination
                if IS_WINDOWS:
                    self.process.terminate()
                    # Terminate children gracefully
                    for child in children:
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            continue
                else:
                    # On Linux, send SIGTERM to the process group
                    os.killpg(self.process.pid, signal.SIGTERM)
                
                # Wait for the process to terminate
                self.process.wait(timeout=5)
            
            except subprocess.TimeoutExpired:
                print("Graceful termination timed out. Forcing termination...")
                try:
                    # Forcefully kill the process and its children using psutil
                    parent = psutil.Process(self.process.pid)
                    children = parent.children(recursive=True)
                    
                    if IS_WINDOWS:
                        # Kill children first
                        for child in children:
                            try:
                                child.kill()
                            except psutil.NoSuchProcess:
                                continue
                        # Kill the parent
                        parent.kill()
                        # Fallback to taskkill to ensure cleanup
                        miner_exe = os.path.basename(self.miner_path)
                        os.system(f"taskkill /IM {miner_exe} /F /T")
                    else:
                        # On Linux, send SIGKILL to the process group
                        os.killpg(self.process.pid, signal.SIGKILL)
                
                except psutil.NoSuchProcess:
                    print("Process already terminated.")
                except Exception as e:
                    print(f"Error during forceful termination: {e}")
            
            except Exception as e:
                if DEBUG: raise
                print(f"Error stopping miner: {e}")
                if IS_WINDOWS:
                    self.process.kill()
                else:
                    os.killpg(self.process.pid, signal.SIGKILL)
            
            finally:
                self.output_thread.join()
                self.process = None
                self.is_mining = False
                self.current_coin = None
                self.hashrate = 0.0
                self.hashrate_history = []
                self.low_hashrate_start = None
                self.target_hashrate = None
                self.last_output_time = None
                print("Miner stopped.")

    def get_hashrate(self):
        """Return the latest hashrate parsed from output."""
        return self.hashrate

class ScreenRunSwitcher:
    class SupportedCoin:
        def __init__(self, symbol, commandStart, commandStop, hashrate):
            self.symbol = symbol
            self.commandStart = commandStart
            self.commandStop = commandStop
            self.hashrate = hashrate

    def __init__(self):
        # Database session for fetching target hashrate
        self.Session_miningDB = sessionmaker(bind=engine_miningDB)
        self.session_miningDB = self.Session_miningDB()

        # Database session for logging events
        self.Session_fogplayDB = sessionmaker(bind=engine_fogplayDB)
        self.session_fogplayDB = self.Session_fogplayDB()

        # Test database connection at startup
        try:
            with engine_miningDB.connect() as conn:
                result = conn.execute(text("SELECT 1")).fetchall()
                print(f"miningDB connection test successful: {result}")
        except Exception as e:
            print(f"miningDB connection test failed: {e}")

        try:
            with engine_fogplayDB.connect() as conn:
                result = conn.execute(text("SELECT 1")).fetchall()
                print(f"fogplayDB connection test successful: {result}")
        except Exception as e:
            print(f"fogplayDB connection test failed: {e}")

        # Initialize controllers for each miner
        self.xmrig_controller = MinerController(
            miner_path=XMRIG_PATH,
            cli_args=XMRIG_CLI_ARGS,
            hashrate_pattern="speed",
            hashrate_index=5,  # 10s hashrate in "speed 10s/60s/15m 1234.5 1230.0 1225.0 H/s"
            session_miningDB=self.session_miningDB,
            session_fogplayDB=self.session_fogplayDB
        )
        self.srbminer_controller = MinerController(
            miner_path=SRBMINER_PATH,
            cli_args=SRBMINER_CLI_ARGS,
            hashrate_pattern="Total Hashrate",
            hashrate_index=2,  # "Total Hashrate: 1234.5 H/s"
            session_miningDB=self.session_miningDB,
            session_fogplayDB=self.session_fogplayDB
        )
        self.deroluna_controller = MinerController(
            miner_path=DEROLUNA_PATH,
            cli_args=DEROLUNA_CLI_ARGS,
            hashrate_pattern="@",  # Updated for DeroLuna
            hashrate_index=7,     # Updated for DeroLuna
            session_miningDB=self.session_miningDB,
            session_fogplayDB=self.session_fogplayDB
        )
        self.last_game = None
        self.is_game_running = False
        self.current_miner = None
        self.is_overheating = False
        # Track failed coins with their cooldown expiration time
        self.failed_coins = {}  # {coin_symbol: expiration_time}

    def is_coin_on_cooldown(self, coin_symbol):
        """Check if a coin is on cooldown due to previous failures."""
        if coin_symbol in self.failed_coins:
            expiration_time = self.failed_coins[coin_symbol]
            if time.time() < expiration_time:
                if DEBUG:
                    print(f"Coin {coin_symbol} is on cooldown until {datetime.fromtimestamp(expiration_time).isoformat()}")
                return True
            else:
                # Cooldown expired, remove from failed coins
                if DEBUG:
                    print(f"Coin {coin_symbol} cooldown expired. Removing from failed list.")
                del self.failed_coins[coin_symbol]
        return False

    async def amain(self):
        if not is_admin():
            print("Warning: Not running as admin. Should work for API calls, but monitor for issues.")

        if USE_MQTT:
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
        is_paused = False

        # Define a list of default coins to try if no valid coin is found
        DEFAULT_COINS = ["WOW", "XMR", "DERO"]

        while True:
            try:
                print("Starting new loop iteration...")

                # Test database session
                try:
                    result = self.session_miningDB.execute(text("SELECT 1")).fetchall()
                    print(f"miningDB session test successful: {result}")
                except Exception as e:
                    print(f"miningDB session test failed: {e}")
                    self.session_miningDB = self.Session_miningDB()  # Reinitialize session

                try:
                    result = self.session_fogplayDB.execute(text("SELECT 1")).fetchall()
                    print(f"fogplayDB session test successful: {result}")
                except Exception as e:
                    print(f"fogplayDB session test failed: {e}")
                    self.session_fogplayDB = self.Session_fogplayDB()  # Reinitialize session

                # Database commits
                try:
                    self.session_miningDB.commit()
                    print("miningDB commit successful")
                except Exception as e:
                    print(f"miningDB commit failed: {e}")
                    self.session_miningDB.rollback()
                    self.session_miningDB = self.Session_miningDB()

                try:
                    self.session_fogplayDB.commit()
                    print("fogplayDB commit successful")
                except Exception as e:
                    print(f"fogplayDB commit failed: {e}")
                    self.session_fogplayDB.rollback()
                    self.session_fogplayDB = self.Session_fogplayDB()

                # Get temperatures
                try:
                    cpu_temp = get_cpu_temperature()
                    gpu_temp = get_gpu_temperature()
                    if DEBUG:
                        print(f"CPU Temp: {cpu_temp}°C, GPU Temp: {gpu_temp}°C")
                except Exception as e:
                    print(f"Error getting temperatures: {e}")
                    cpu_temp = None
                    gpu_temp = None

                # Check for overheating
                if not self.is_overheating:
                    if cpu_temp and cpu_temp > CPU_TEMP_THRESHOLD:
                        print(f"CPU temperature ({cpu_temp}°C) exceeds threshold ({CPU_TEMP_THRESHOLD}°C). Stopping mining...")
                        if self.current_miner:
                            self.current_miner.stop_mining()
                            self.current_miner.log_event("overheating", f"CPU temperature too high: {cpu_temp}°C")
                            self.current_miner = None
                        self.is_overheating = True
                    elif gpu_temp and gpu_temp > GPU_TEMP_THRESHOLD:
                        print(f"GPU temperature ({gpu_temp}°C) exceeds threshold ({GPU_TEMP_THRESHOLD}°C). Stopping mining...")
                        if self.current_miner:
                            self.current_miner.stop_mining()
                            self.current_miner.log_event("overheating", f"GPU temperature too high: {gpu_temp}°C")
                            self.current_miner = None
                        self.is_overheating = True

                # If overheating, check if temperatures have dropped
                if self.is_overheating:
                    if (cpu_temp is None or cpu_temp <= CPU_TEMP_THRESHOLD) and (gpu_temp is None or gpu_temp <= GPU_TEMP_THRESHOLD):
                        print("Temperatures have dropped below thresholds. Resuming mining...")
                        self.is_overheating = False

                # Check if the current miner failed (e.g., max restarts exceeded)
                failed_coin = None
                if self.current_miner and self.current_miner.current_coin is None:
                    failed_coin = getattr(self.current_miner, "last_failed_coin", None)
                    if failed_coin:
                        print(f"Current miner failed for {failed_coin}. Adding to cooldown list for {FAILED_COIN_COOLDOWN} seconds.")
                        self.failed_coins[failed_coin] = time.time() + FAILED_COIN_COOLDOWN
                        self.current_miner.log_event("coin_switch", f"Switched from {failed_coin} due to repeated low hashrate")
                        self.current_miner.stop_mining()
                    self.current_miner = None

                # Select the best coin to mine, excluding coins with NULL rev_rig_correct and those on cooldown
                print(f"Querying BestCoinsForRigView for worker '{HOSTNAME}' with non-NULL rev_rig_correct...")
                best_coin_query = None
                try:
                    # Get all coins with non-NULL rev_rig_correct
                    valid_coins = self.session_miningDB.query(BestCoinsForRigView).filter(
                        BestCoinsForRigView.worker == HOSTNAME,
                        BestCoinsForRigView.rev_rig_correct.isnot(None)  # Exclude NULL values
                    ).order_by(
                        BestCoinsForRigView.rev_rig_correct.desc()
                    ).all()

                    # Filter out coins that are on cooldown
                    for coin in valid_coins:
                        if not self.is_coin_on_cooldown(coin.symbol):
                            best_coin_query = coin
                            break
                except Exception as e:
                    print(f"Error querying BestCoinsForRigView: {e}")
                    self.session_miningDB.rollback()
                    self.session_miningDB = self.Session_miningDB()

                best_coin = None
                if best_coin_query:
                    print(f"Best coin found: symbol={best_coin_query.symbol}, worker={best_coin_query.worker}, rev_rig_correct={best_coin_query.rev_rig_correct}")
                    best_coin = best_coin_query.symbol
                    print(f"Best coin to mine: {best_coin} with revenue {best_coin_query.rev_rig_correct}")
                    if failed_coin:
                        # Log the switch to the new coin
                        self.current_miner.log_event("coin_switch", f"Switched from {failed_coin} to {best_coin} due to repeated low hashrate")
                else:
                    print(f"No valid coin found to mine: No results for worker '{HOSTNAME}' with non-NULL rev_rig_correct or all coins are on cooldown.")
                    # Log all entries in BestCoinsForRigView to debug
                    try:
                        all_coins = self.session_miningDB.query(BestCoinsForRigView).filter(
                            BestCoinsForRigView.worker == HOSTNAME
                        ).all()
                        if all_coins:
                            print("All entries in BestCoinsForRigView for this worker:")
                            for coin in all_coins:
                                print(f"symbol={coin.symbol}, worker={coin.worker}, rev_rig_correct={coin.rev_rig_correct}, on_cooldown={self.is_coin_on_cooldown(coin.symbol)}")
                        else:
                            print(f"No entries in BestCoinsForRigView for worker '{HOSTNAME}'.")
                    except Exception as e:
                        print(f"Error fetching all entries from BestCoinsForRigView: {e}")

                    # Try default coins as a fallback
                    for default_coin in DEFAULT_COINS:
                        if not self.is_coin_on_cooldown(default_coin) and (default_coin in CoinsListXmrig or default_coin in CoinsListSrbmimer or default_coin == "DERO"):
                            best_coin = default_coin
                            print(f"Falling back to default coin: {best_coin}")
                            if failed_coin:
                                # Log the switch to the default coin
                                self.current_miner.log_event("coin_switch", f"Switched from {failed_coin} to {best_coin} due to repeated low hashrate")
                            break
                    if not best_coin:
                        print("No default coin available to mine (all on cooldown). Skipping this iteration.")
                        await asyncio.sleep(SLEEP_INTERVAL)
                        continue

                # Select the appropriate miner for the best coin
                selected_miner = None
                if best_coin in CoinsListXmrig:
                    selected_miner = self.xmrig_controller
                elif best_coin in CoinsListSrbmimer:
                    selected_miner = self.srbminer_controller
                elif best_coin == "DERO":
                    selected_miner = self.deroluna_controller

                # Start the selected miner if no game is running and not overheating
                if not self.is_game_running and not self.is_overheating and selected_miner:
                    # Start the new miner if necessary
                    if self.current_miner != selected_miner or (self.current_miner and self.current_miner.current_coin != best_coin):
                        if self.current_miner:
                            self.current_miner.stop_mining()
                        success = selected_miner.start_mining(best_coin)
                        if success:
                            self.current_miner = selected_miner
                        else:
                            # If starting the new coin fails, add it to the cooldown list
                            print(f"Failed to start mining {best_coin}. Adding to cooldown list.")
                            self.failed_coins[best_coin] = time.time() + FAILED_COIN_COOLDOWN
                            selected_miner.last_failed_coin = best_coin  # Track the failed coin
                            continue

                # Fetch and publish hashrate from the current miner
                hashrate = 0.0
                if self.current_miner:
                    hashrate = self.current_miner.get_hashrate()
                timestamp = datetime.now().isoformat()
                payload = hashrate
                if USE_MQTT: 
                    mqtt_client.publish(MQTT_HASHRATE_TOPIC, payload)
                    if DEBUG:
                        print(f"Published to {MQTT_HASHRATE_TOPIC}: {payload}")

                # Check user activity
                idle_time = get_idle_time()
                if DEBUG:
                    print(f"Idle time: {idle_time:.2f} seconds")

                # Pause or resume based on activity
                if idle_time < IDLE_THRESHOLD and not is_paused and PAUSE_XMRIG:
                    if pause_xmrig():
                        is_paused = True
                elif idle_time >= IDLE_THRESHOLD and is_paused and PAUSE_XMRIG:
                    if resume_xmrig():
                        is_paused = False

                # Monitor games
                current_game = get_current_game()
                if current_game != self.last_game:
                    if current_game is not None:
                        # Game started
                        game_payload = json.dumps({
                            "event": "new_game_started",
                            "game": current_game,
                            "timestamp": datetime.now().isoformat()
                        })
                        if USE_MQTT: mqtt_client.publish(MQTT_GAME_TOPIC, game_payload)

                        EventsData = Events(
                            timestamp=datetime.now(),  # Use datetime.now() directly
                            event="new_game_started",
                            value=current_game,
                            server=MTS_SERVER_NAME
                        )
                        self.session_fogplayDB.add(EventsData)
                        self.session_fogplayDB.commit()

                        if DEBUG:
                            print(f"New game detected: {current_game}")
                            if USE_MQTT: print(f"Published to {MQTT_GAME_TOPIC}: {game_payload}")

                        # Stop the current miner when a game starts
                        if self.current_miner:
                            self.current_miner.stop_mining()
                            self.current_miner = None
                        self.is_game_running = True

                    else:
                        # Game stopped
                        if self.is_game_running:
                            print("Game stopped. Restarting miner with best coin...")
                            if selected_miner and not self.is_overheating:
                                success = selected_miner.start_mining(best_coin)
                                if success:
                                    self.current_miner = selected_miner
                                else:
                                    print(f"Failed to start mining {best_coin} after game stopped. Adding to cooldown list.")
                                    self.failed_coins[best_coin] = time.time() + FAILED_COIN_COOLDOWN
                                    selected_miner.last_failed_coin = best_coin
                            self.is_game_running = False

                    self.last_game = current_game

                # Get GPU metrics
                detect_gpu()
                if GPU_TYPE:
                    gpu_metrics = get_gpu_metrics()
                    print(f"Final GPU Metrics: {gpu_metrics}")
                else:
                    print("Cannot retrieve GPU metrics: No GPU detected.")
                    gpu_metrics = {"temperature": None, "usage": None, "fan_speed_rpm": None, "fan_speed_percent": None}

                # Update miner stats with the current coin, including temperatures
                if self.current_miner and self.current_miner.is_mining and self.current_miner.current_coin:
                    update_miner_stats(self.session_miningDB, HOSTNAME, self.current_miner.current_coin, hashrate, cpu_temp, gpu_metrics)
                    # MinerStatsData = MinersStats(
                    #     symbol=self.current_miner.current_coin,
                    #     timestamp=int(time.time()),  # This is still an integer as per the schema
                    #     hostname=HOSTNAME,
                    #     hashrate=hashrate,
                    #     cpu_temp=cpu_temp,
                    #     gpu_temp=gpu_temp
                    # )
                    # self.session_miningDB.add(MinerStatsData)
                    # self.session_miningDB.commit()

                print("Loop iteration completed successfully.")
                await asyncio.sleep(SLEEP_INTERVAL)

            except Exception as e:
                print(f"Main loop error: {e}")
                self.session_miningDB.close()
                self.session_fogplayDB.close()
                self.session_miningDB = self.Session_miningDB()
                self.session_fogplayDB = self.Session_fogplayDB()
                await asyncio.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(ScreenRunSwitcher().amain())
    print("*" * 100)