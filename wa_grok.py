import asyncio
import json
import subprocess
import time
import os
import threading
import queue
from datetime import datetime
from sqlalchemy import create_engine, func, case, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.expression import column
from pathlib import Path

from wa_definitions import engine_fogplayDB, engine_miningDB, Events, BestCoinsForRigView, MinersStats, SupportedCoins
from wa_cred import HOSTNAME, MTS_SERVER_NAME, \
    USE_MQTT, MQTT_BROKER, MQTT_PORT, MQTT_HASHRATE_TOPIC, MQTT_GAME_TOPIC, \
    IDLE_THRESHOLD, \
    CoinsListSrbmimer, CoinsListXmrig, SLEEP_INTERVAL, \
    ENABLE_MINING, PAUSE_XMRIG, XMRIG_THREADS, MAX_THREADS
from wa_functions import GPU_TYPE, get_current_game, get_idle_time, is_admin, pause_xmrig, resume_xmrig, on_connect, detect_gpu, get_cpu_temperature, get_gpu_temperature, get_gpu_metrics, update_miner_stats
from wa_cred import MQTT_USER, MQTT_PASSWORD, XMRIG_CLI_ARGS_SENSITIVE, SRBMINER_CLI_ARGS_SENSITIVE, DEROLUNA_CLI_ARGS_SENSITIVE

if USE_MQTT: import paho.mqtt.client as mqtt

PAUSE_XMRIG = False
DEBUG = True
PRINT_MINER_LOG = True

# Constants for hashrate monitoring
HASHRATE_WINDOW = 15 * 60
HASHRATE_THRESHOLD = 0.5
HASHRATE_DROP_DURATION = 5 * 60
CHECK_INTERVAL = 10

# Temperature thresholds (in Celsius)
CPU_TEMP_THRESHOLD = 67.0
CPU_TEMP_LOWER_THRESHOLD = 60.0
GPU_TEMP_THRESHOLD = 90.0
FAILED_COIN_COOLDOWN = 300
HYSTERESIS = 1.025

# Thread limits
MIN_THREADS = 1
THREAD_INCREMENT = 1  # Thread adjustment step to reduce oscillations
# Warn if threads are high, but allow up to MAX_THREADS
if XMRIG_THREADS > 16 or MAX_THREADS > 22:
    print(f"Warning: High thread counts detected (XMRIG_THREADS={XMRIG_THREADS}, MAX_THREADS={MAX_THREADS}). Verify CPU capacity.")

# Windows-only paths
scripts_folder = Path("C:/scripts")
XMRIG_PATH = str(scripts_folder / "miners" / "xmrig" / "xmrig.exe")
SRBMINER_PATH = str(scripts_folder / "miners" / "srbminer" / "SRBMiner-Multi.exe")
DEROLUNA_PATH = str(scripts_folder / "miners" / "deroluna" / "deroluna-miner.exe")

# CLI arguments with dynamic threads
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
        "--threads={threads}",
        "--http-port=37329",
        "--http-no-restricted",
        "--http-access-token=auth"
    ],
    "NICEHASH": [
        "--algo=rx/0",
        f"--url={XMRIG_CLI_ARGS_SENSITIVE['NICEHASH']['url']}",
        f"--user={XMRIG_CLI_ARGS_SENSITIVE['NICEHASH']['user']}",
        f"--pass={XMRIG_CLI_ARGS_SENSITIVE['NICEHASH']['pass']}",
        f"--rig-id={HOSTNAME}",
        "--donate-level=1",
        "--cpu",
        "--no-gpu",
        "--threads={threads}",
        "--http-port=37329",
        "--http-no-restricted",
        "--http-access-token=auth"
    ],
    "WOW": [
        "--algo=rx/wow",
        f"--url={XMRIG_CLI_ARGS_SENSITIVE['WOW_STAN']['url']}",
        f"--user={XMRIG_CLI_ARGS_SENSITIVE['WOW_STAN']['user']}",
        f"--pass={XMRIG_CLI_ARGS_SENSITIVE['WOW_STAN']['pass']}",
        f"--rig-id={HOSTNAME}",
        "--donate-level=1",
        "--cpu",
        "--no-gpu",
        "--threads={threads}",
        "--http-port=37329",
        "--http-no-restricted",
        "--http-access-token=auth"
    ],
    "XTM": [
        "--algo=rx/0",
        f"--url={XMRIG_CLI_ARGS_SENSITIVE['XTM']['url']}",
        f"--user={XMRIG_CLI_ARGS_SENSITIVE['XTM']['user']}",
        f"--pass={XMRIG_CLI_ARGS_SENSITIVE['XTM']['pass']}",
        f"--rig-id={HOSTNAME}",
        "--donate-level=1",
        "--cpu",
        "--no-gpu",
        "--threads={threads}",
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
        "--threads={threads}",
        "--http-port=37329",
        "--http-no-restricted",
        "--http-access-token=auth"
    ]
}

SRBMINER_CLI_ARGS = {
    "ETI": [
        "--algorithm", "etchash",
        "--pool", "etchash.unmineable.com:3333",
        f"--wallet={SRBMINER_CLI_ARGS_SENSITIVE['ETI']['wallet']}",
        "--worker", HOSTNAME,
        "--disable-gpu",
        "--cpu-threads", "{threads}"
    ],
    "PEPEW": [
        "--algorithm", "kawpow",
        "--pool", "kawpow.unmineable.com:3333",
        f"--wallet={SRBMINER_CLI_ARGS_SENSITIVE['PEPEW']['wallet']}",
        "--worker", HOSTNAME,
        "--disable-gpu",
        "--cpu-threads", "{threads}"
    ],
    "SCASH": [
        "--algorithm", "scrypt",
        "--pool", "scrypt.unmineable.com:3333",
        f"--wallet={SRBMINER_CLI_ARGS_SENSITIVE['SCASH']['wallet']}",
        "--worker", HOSTNAME,
        "--disable-gpu",
        "--cpu-threads", "{threads}"
    ],
    "TDC": [
        "--algorithm", "ethash",
        "--pool", "ethash.unmineable.com:3333",
        f"--wallet={SRBMINER_CLI_ARGS_SENSITIVE['TDC']['wallet']}",
        "--worker", HOSTNAME,
        "--disable-gpu",
        "--cpu-threads", "{threads}"
    ],
    "VRSC": [
        "--algorithm", "verushash",
        "--pool", "stratum+tcp://verushash.na.mine.zergpool.com:3300",
        f"--wallet={SRBMINER_CLI_ARGS_SENSITIVE['VRSC']['wallet']}",
        "--worker", HOSTNAME,
        "--disable-gpu",
        "--cpu-threads", "{threads}"
    ]
}

DEROLUNA_CLI_ARGS = {
    "DERO": [
        f"-d {DEROLUNA_CLI_ARGS_SENSITIVE['DERO']['daemon-address']}",
        f"-w {DEROLUNA_CLI_ARGS_SENSITIVE['DERO']['wallet-address']}",
        "-t", "{threads}"
    ]
}

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
        self.hashrate_history = []
        self.low_hashrate_start = None
        self.last_output_time = None
        self.restart_count = 0
        self.last_restart_time = None
        self.last_failed_coin = None
        self.current_threads = XMRIG_THREADS  # Initialize with XMRIG_THREADS
        self.MAX_RESTARTS = 10
        self.RESTART_WINDOW = 120
        self.OUTPUT_TIMEOUT = 300

    def fetch_target_hashrate(self):
        if not self.current_coin:
            return None
        try:
            coin = self.session_miningDB.query(SupportedCoins).filter(
                SupportedCoins.symbol == self.current_coin,
                SupportedCoins.worker == HOSTNAME
            ).first()
            if coin and coin.rig_hr_kh is not None:
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
        try:
            event_data = Events(
                timestamp=datetime.fromtimestamp(time.time()),
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

    def update_threads(self, new_threads):
        """Update the thread count for the current coin and log the change."""
        if new_threads == self.current_threads:
            print(f"No thread change needed: {self.current_threads} threads for {self.current_coin}")
            return False
        if new_threads < MIN_THREADS:
            print(f"Cannot reduce threads below {MIN_THREADS}. Keeping {self.current_threads} threads.")
            self.log_event("threads_adjust_failed", f"Attempted threads {new_threads} below minimum for {self.current_coin}")
            return False
        if new_threads > MAX_THREADS:
            print(f"Cannot increase threads above {MAX_THREADS}. Keeping {self.current_threads} threads.")
            # self.log_event("threads_adjust_failed", f"Attempted threads {new_threads} above maximum for {self.current_coin}")
            return False
        if new_threads > 22:
            print(f"Warning: High thread count {new_threads} for {self.current_coin}. Verify CPU capacity.")
            self.log_event("threads_high_warning", f"High thread count {new_threads} for {self.current_coin}")
        self.current_threads = new_threads
        self.log_event("threads_adjusted", f"Changed threads to {self.current_threads} for {self.current_coin}")
        print(f"Updated threads to {self.current_threads} for {self.current_coin}")
        return True

    def read_output(self):
        if not self.current_coin:
            print("Error: read_output called with no current coin. Aborting.")
            return
        log_file = f"{self.current_coin}_miner.log"
        with open(log_file, "a", encoding="utf-8") as f:
            while self.running:
                try:
                    if self.process.poll() is not None:
                        print(f"Miner process ({os.path.basename(self.miner_path)}) has exited unexpectedly. Restarting...")
                        self.stop_mining()
                        self.start_mining(self.current_coin)
                        break
                    line = self.process.stdout.readline().strip()
                    current_time = time.time()
                    if not line:
                        if self.last_output_time and (current_time - self.last_output_time) > self.OUTPUT_TIMEOUT:
                            print(f"No output received for {self.OUTPUT_TIMEOUT} seconds. Restarting miner...")
                            self.stop_mining()
                            self.start_mining(self.current_coin)
                            break
                        time.sleep(0.1)
                        continue
                    self.last_output_time = current_time
                    f.write(f"[{datetime.now().isoformat()}] {line}\n")
                    f.flush()
                    if PRINT_MINER_LOG:
                        print(line)
                    self.output_queue.put(line)
                    if self.hashrate_pattern in line:
                        try:
                            parts = line.split()
                            hashrate_str = parts[self.hashrate_index]
                            self.hashrate = float(hashrate_str)
                            if "deroluna" in self.miner_path.lower():
                                self.hashrate *= 1000
                            if DEBUG:
                                print(f"Parsed hashrate for {self.current_coin}: {self.hashrate} H/s")
                            self.hashrate_history.append((current_time, self.hashrate))
                            self.hashrate_history = [(t, hr) for t, hr in self.hashrate_history if t >= current_time - HASHRATE_WINDOW]
                            if self.target_hashrate is None:
                                self.fetch_target_hashrate()
                            moving_avg = self.calculate_moving_average(current_time)
                            if moving_avg is None:
                                if DEBUG:
                                    print("Not enough hashrate data for moving average yet.")
                                continue
                            if self.target_hashrate and self.target_hashrate > 0:
                                threshold = self.target_hashrate * HASHRATE_THRESHOLD
                                if moving_avg < threshold:
                                    if self.low_hashrate_start is None:
                                        self.low_hashrate_start = current_time
                                        if DEBUG:
                                            print(f"Moving average hashrate dropped below threshold ({moving_avg} < {threshold}). Monitoring...")
                                    elif current_time - self.low_hashrate_start >= HASHRATE_DROP_DURATION:
                                        print(f"Moving average hashrate below threshold for {HASHRATE_DROP_DURATION}s ({moving_avg} < {threshold}). Restarting...")
                                        self.stop_mining()
                                        success = self.start_mining(self.current_coin)
                                        if not success:
                                            print(f"Failed to restart miner for {self.current_coin}. Marking coin as failed.")
                                            self.last_failed_coin = self.current_coin
                                            break
                                        self.low_hashrate_start = None
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
                    time.sleep(0.1)

    def calculate_moving_average(self, current_time):
        cutoff_time = current_time - HASHRATE_WINDOW
        recent_hashrates = [hr for timestamp, hr in self.hashrate_history if timestamp >= cutoff_time]
        if not recent_hashrates:
            return None
        return sum(recent_hashrates) / len(recent_hashrates)

    def start_mining(self, coin_symbol):
        if not ENABLE_MINING:
            print("Mining disabled by ENABLE_MINING flag.")
            return False
        if not coin_symbol:
            print(f"Error: Attempted to start mining with coin None. Falling back to default coin.")
            self.log_event("mining_failed", "Attempted to start mining with coin None")
            coin_symbol = "WOW" if "WOW" in self.cli_args else "NICEHASH"
            print(f"Falling back to {coin_symbol}")
        if self.is_mining:
            print(f"Miner is already running for {self.current_coin}. Stopping first...")
            self.stop_mining()
        if coin_symbol not in self.cli_args:
            print(f"Error: No CLI arguments defined for coin {coin_symbol}")
            self.log_event("mining_failed", f"No CLI arguments for coin {coin_symbol}")
            return False
        current_time = time.time()
        if self.last_restart_time and (current_time - self.last_restart_time) < self.RESTART_WINDOW:
            self.restart_count += 1
            if self.restart_count > self.MAX_RESTARTS:
                print(f"Exceeded maximum restarts ({self.MAX_RESTARTS}) in {self.RESTART_WINDOW}s. Aborting mining for {coin_symbol}.")
                self.log_event("mining_failed", f"Exceeded maximum restarts for {coin_symbol}")
                self.last_failed_coin = coin_symbol
                return False
        else:
            self.restart_count = 0
            self.last_restart_time = current_time
        # Verify thread count
        if self.current_threads < MIN_THREADS or self.current_threads > MAX_THREADS:
            print(f"Invalid thread count {self.current_threads} for {coin_symbol}. Resetting to XMRIG_THREADS ({XMRIG_THREADS}).")
            self.current_threads = XMRIG_THREADS
            self.log_event("threads_reset", f"Reset threads to {XMRIG_THREADS} for {coin_symbol} due to invalid count")
        # Verify miner executable
        if not os.path.exists(self.miner_path):
            print(f"Error: Miner executable not found at {self.miner_path}")
            self.log_event("mining_failed", f"Miner executable not found: {self.miner_path}")
            return False
        for attempt in range(3):
            try:
                cmd = [self.miner_path] + [arg.format(threads=self.current_threads) for arg in self.cli_args[coin_symbol]]
                print(f"Attempt {attempt + 1}/3: Starting miner with command: {' '.join(cmd)}")
                self.process = subprocess.Popen(
                    cmd,
                    cwd=os.path.dirname(self.miner_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    bufsize=1
                )
                self.is_mining = True
                self.current_coin = coin_symbol
                self.running = True
                self.hashrate_history = []
                self.low_hashrate_start = None
                self.target_hashrate = None
                self.last_output_time = time.time()
                self.output_thread = threading.Thread(target=self.read_output)
                self.output_thread.start()
                print(f"Miner started for {coin_symbol} with {self.current_threads} threads.")
                self.log_event("mining_started", f"Started mining {coin_symbol} with {self.current_threads} threads")
                return True
            except Exception as e:
                print(f"Attempt {attempt + 1}/3 failed to start miner for {coin_symbol}: {e}")
                self.log_event("mining_failed", f"Attempt {attempt + 1}/3 failed for {coin_symbol}: {str(e)}")
                time.sleep(2)  # Wait before retry
        print(f"Failed to start miner for {coin_symbol} after 3 attempts.")
        self.log_event("mining_failed", f"Failed to start {coin_symbol} after 3 attempts")
        self.last_failed_coin = coin_symbol
        return False

    def stop_mining(self):
        if self.is_mining and self.process:
            try:
                self.running = False
                import psutil
                parent = psutil.Process(self.process.pid)
                children = parent.children(recursive=True)
                self.log_event("mining_stopped", f"Stopping mining {self.current_coin}...")
                self.process.terminate()
                for child in children:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        continue
                self.process.wait(timeout=5)
                self.log_event("mining_stopped", f"Stopped mining {self.current_coin}")
            except subprocess.TimeoutExpired:
                print("Graceful termination timed out. Forcing termination...")
                try:
                    parent = psutil.Process(self.process.pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            continue
                    parent.kill()
                    miner_exe = os.path.basename(self.miner_path)
                    os.system(f"taskkill /IM {miner_exe} /F /T")
                except psutil.NoSuchProcess:
                    print("Process already terminated.")
                except Exception as e:
                    print(f"Error during forceful termination: {e}")
            except Exception as e:
                if DEBUG: raise
                print(f"Error stopping miner: {e}")
                self.process.kill()
            finally:
                self.output_thread.join()
                self.process = None
                self.is_mining = False
                self.hashrate = 0.0
                self.hashrate_history = []
                self.low_hashrate_start = None
                self.target_hashrate = None
                self.last_output_time = None
                print(f"Miner stopped for {self.current_coin}.")
                # Preserve current_coin unless switching coins

    def get_hashrate(self):
        return self.hashrate

class ScreenRunSwitcher:
    class SupportedCoin:
        def __init__(self, symbol, commandStart, commandStop, hashrate):
            self.symbol = symbol
            self.commandStart = commandStart
            self.commandStop = commandStop
            self.hashrate = hashrate

    def fetch_start_options_for_symbol(self, symbol):
        try:
            coin = self.session_miningDB.query(SupportedCoins).filter(
                SupportedCoins.symbol == symbol,
                SupportedCoins.worker == HOSTNAME
            ).first()
            if coin and coin.command_start is not None:
                self.command_start = coin.command_start
                if DEBUG:
                    print(f"Start command for {symbol}: {self.command_start}")
                return self.command_start
            else:
                print(f"No start command found for {symbol} in SupportedCoins")
                self.log_event("start_command_failed", f"No start command found {symbol}")
                return None
        except Exception as e:
            print(f"Error fetching start command for {symbol}: {e}")
            self.log_event("start_command_failed", f"Error fetching start command for {symbol}: {str(e)}")
            return None

    def __init__(self):
        self.Session_miningDB = sessionmaker(bind=engine_miningDB)
        self.session_miningDB = self.Session_miningDB()
        self.Session_fogplayDB = sessionmaker(bind=engine_fogplayDB)
        self.session_fogplayDB = self.Session_fogplayDB()
        wow_startup_option = 'stan'
        try:
            with engine_miningDB.connect() as conn:
                result = conn.execute(text("SELECT 1")).fetchall()
                print(f"miningDB connection test successful: {result}")
                wow_startup_option = self.fetch_start_options_for_symbol('WOW')
        except Exception as e:
            print(f"miningDB connection test failed: {e}")
        try:
            with engine_fogplayDB.connect() as conn:
                result = conn.execute(text("SELECT 1")).fetchall()
                print(f"fogplayDB connection test successful: {result}")
        except Exception as e:
            print(f"fogplayDB connection test failed: {e}")
        if wow_startup_option == 'solo':
            XMRIG_CLI_ARGS['WOW'] = [
                "--algo=rx/wow",
                f"--url={XMRIG_CLI_ARGS_SENSITIVE['WOW_SOLO']['url']}",
                f"--user={XMRIG_CLI_ARGS_SENSITIVE['WOW_SOLO']['user']}",
                f"--spend-secret-key={XMRIG_CLI_ARGS_SENSITIVE['WOW_SOLO']['key']}",
                f"--pass={XMRIG_CLI_ARGS_SENSITIVE['WOW_SOLO']['pass']}",
                f"--rig-id={HOSTNAME}",
                "--donate-level=1",
                "--cpu",
                "--no-gpu",
                "--threads={threads}",
                "--http-port=37329",
                "--http-no-restricted",
                "--http-access-token=auth"
            ]
        self.xmrig_controller = MinerController(
            miner_path=XMRIG_PATH,
            cli_args=XMRIG_CLI_ARGS,
            hashrate_pattern="speed",
            hashrate_index=5,
            session_miningDB=self.session_miningDB,
            session_fogplayDB=self.session_fogplayDB
        )
        self.srbminer_controller = MinerController(
            miner_path=SRBMINER_PATH,
            cli_args=SRBMINER_CLI_ARGS,
            hashrate_pattern="Total Hashrate",
            hashrate_index=2,
            session_miningDB=self.session_miningDB,
            session_fogplayDB=self.session_fogplayDB
        )
        self.deroluna_controller = MinerController(
            miner_path=DEROLUNA_PATH,
            cli_args=DEROLUNA_CLI_ARGS,
            hashrate_pattern="@",
            hashrate_index=7,
            session_miningDB=self.session_miningDB,
            session_fogplayDB=self.session_fogplayDB
        )
        self.last_game = None
        self.is_game_running = False
        self.current_miner = None
        self.is_overheating = False
        self.failed_coins = {}

    def is_coin_on_cooldown(self, coin_symbol):
        if coin_symbol in self.failed_coins:
            expiration_time = self.failed_coins[coin_symbol]
            if time.time() < expiration_time:
                if DEBUG:
                    print(f"Coin {coin_symbol} is on cooldown until {datetime.fromtimestamp(expiration_time).isoformat()}")
                return True
            else:
                if DEBUG:
                    print(f"Coin {coin_symbol} cooldown expired. Removing from failed list.")
                del self.failed_coins[coin_symbol]
        return False

    def log_event(self, event_name, event_value):
        try:
            event_data = Events(
                timestamp=datetime.fromtimestamp(time.time()),
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

    async def amain(self):
        if not is_admin():
            print("Warning: Not running as admin. Should work for API calls, but monitor for issues.")
        if USE_MQTT:
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
        is_paused = False
        DEFAULT_COINS = ["WOW", "NICEHASH"]
        best_coin = None
        while True:
            try:
                print("Starting new loop iteration...")
                try:
                    result = self.session_miningDB.execute(text("SELECT 1")).fetchall()
                    print(f"miningDB session test successful: {result}")
                except Exception as e:
                    print(f"miningDB session test failed: {e}")
                    self.session_miningDB = self.Session_miningDB()
                    continue
                try:
                    result = self.session_fogplayDB.execute(text("SELECT 1")).fetchall()
                    print(f"fogplayDB session test successful: {result}")
                except Exception as e:
                    print(f"fogplayDB session test failed: {e}")
                    self.session_fogplayDB = self.Session_fogplayDB()
                    continue
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
                current_game = get_current_game(self.session_fogplayDB)
                if current_game != self.last_game:
                    if current_game is not None:
                        game_payload = json.dumps({
                            "event": "new_game_started",
                            "game": current_game,
                            "timestamp": datetime.now().isoformat()
                        })
                        if USE_MQTT: mqtt_client.publish(MQTT_GAME_TOPIC, game_payload)
                        EventsData = Events(
                            timestamp=datetime.now(),
                            event="new_game_started",
                            value=current_game,
                            server=MTS_SERVER_NAME
                        )
                        self.session_fogplayDB.add(EventsData)
                        self.session_fogplayDB.commit()
                        if DEBUG:
                            print(f"New game detected: {current_game}")
                            if USE_MQTT: print(f"Published to {MQTT_GAME_TOPIC}: {game_payload}")
                        if self.current_miner:
                            self.current_miner.stop_mining()
                            self.current_miner = None
                        self.is_game_running = True
                    else:
                        if self.is_game_running:
                            print("Game stopped. Restarting miner with best coin...")
                            if best_coin and selected_miner and not self.is_overheating:
                                success = selected_miner.start_mining(best_coin)
                                if success:
                                    self.current_miner = selected_miner
                                else:
                                    print(f"Failed to start mining {best_coin}. Adding to cooldown.")
                                    self.failed_coins[best_coin] = time.time() + FAILED_COIN_COOLDOWN
                                    selected_miner.last_failed_coin = best_coin
                            self.is_game_running = False
                    self.last_game = current_game
                try:
                    cpu_temp = get_cpu_temperature()
                    gpu_temp = get_gpu_temperature()
                    if DEBUG:
                        print(f"CPU Temp: {cpu_temp}°C, GPU Temp: {gpu_temp}°C")
                except Exception as e:
                    print(f"Error getting temperatures: {e}")
                    cpu_temp = None
                    gpu_temp = None
                if self.current_miner and self.current_miner.is_mining and self.current_miner.current_coin:
                    if cpu_temp and cpu_temp > CPU_TEMP_THRESHOLD:
                        print(f"CPU temperature ({cpu_temp}°C) exceeds threshold ({CPU_TEMP_THRESHOLD}°C). Reducing threads...")
                        new_threads = self.current_miner.current_threads - THREAD_INCREMENT
                        if self.current_miner.update_threads(new_threads):
                            self.current_miner.stop_mining()
                            success = self.current_miner.start_mining(self.current_miner.current_coin)
                            if not success:
                                print(f"Failed to restart miner with {new_threads} threads for {self.current_miner.current_coin}. Adding to cooldown.")
                                self.failed_coins[self.current_miner.current_coin] = time.time() + FAILED_COIN_COOLDOWN
                                self.current_miner.last_failed_coin = self.current_miner.current_coin
                                self.current_miner = None
                    elif cpu_temp and cpu_temp <= CPU_TEMP_LOWER_THRESHOLD:
                        print(f"CPU temperature ({cpu_temp}°C) below lower threshold ({CPU_TEMP_LOWER_THRESHOLD}°C). Increasing threads...")
                        new_threads = self.current_miner.current_threads + THREAD_INCREMENT
                        if self.current_miner.update_threads(new_threads):
                            self.current_miner.stop_mining()
                            success = self.current_miner.start_mining(self.current_miner.current_coin)
                            if not success:
                                print(f"Failed to restart miner with {new_threads} threads for {self.current_miner.current_coin}. Adding to cooldown.")
                                self.failed_coins[self.current_miner.current_coin] = time.time() + FAILED_COIN_COOLDOWN
                                self.current_miner.last_failed_coin = self.current_miner.current_coin
                                self.current_miner = None
                if not self.is_overheating:
                    if gpu_temp and gpu_temp > GPU_TEMP_THRESHOLD:
                        print(f"GPU temperature ({gpu_temp}°C) exceeds threshold ({GPU_TEMP_THRESHOLD}°C). Stopping mining...")
                        if self.current_miner:
                            self.current_miner.stop_mining()
                            self.current_miner.log_event("overheating", f"GPU temperature too high: {gpu_temp}°C")
                            self.current_miner = None
                        self.is_overheating = True
                if self.is_overheating:
                    if (cpu_temp is None or cpu_temp <= CPU_TEMP_THRESHOLD) and (gpu_temp is None or gpu_temp <= GPU_TEMP_THRESHOLD):
                        print("Temperatures have dropped below thresholds. Resuming mining...")
                        self.is_overheating = False
                failed_coin = None
                if self.current_miner and not self.current_miner.is_mining and self.current_miner.last_failed_coin:
                    failed_coin = self.current_miner.last_failed_coin
                    print(f"Current miner failed for {failed_coin}. Adding to cooldown for {FAILED_COIN_COOLDOWN}s.")
                    self.failed_coins[failed_coin] = time.time() + FAILED_COIN_COOLDOWN
                    self.current_miner.log_event("coin_switch", f"Switched from {failed_coin} due to repeated low hashrate")
                    self.current_miner = None
                print(f"Querying BestCoinsForRigView for worker '{HOSTNAME}' with non-NULL rev_rig_correct...")
                best_coin_query = None
                try:
                    current_symbol = best_coin_query.symbol if best_coin_query is not None else 'WOW'
                    valid_coins = self.session_miningDB.query(
                        BestCoinsForRigView.position,
                        BestCoinsForRigView.symbol,
                        BestCoinsForRigView.worker,
                        BestCoinsForRigView.rev_rig_correct,
                        case(
                            (BestCoinsForRigView.symbol == current_symbol, BestCoinsForRigView.rev_rig_correct * HYSTERESIS),
                            else_=BestCoinsForRigView.rev_rig_correct
                        ).label('modified_rev_rig_correct')
                    ).filter(
                        BestCoinsForRigView.worker == HOSTNAME,
                        BestCoinsForRigView.rev_rig_correct.isnot(None)
                    ).order_by(
                        case(
                            (BestCoinsForRigView.symbol == current_symbol, BestCoinsForRigView.rev_rig_correct * HYSTERESIS),
                            else_=BestCoinsForRigView.rev_rig_correct
                        ).desc()
                    ).all()
                    if DEBUG:
                        for r in valid_coins:
                            print(f"Raw view data: {r.position}, {r.symbol}, {r.worker}, {r.rev_rig_correct}, {r.modified_rev_rig_correct}")
                    for coin in valid_coins:
                        print(f"coin found: symbol={coin.symbol}, worker={coin.worker}, rev_rig_correct={coin.rev_rig_correct}")
                        if not self.is_coin_on_cooldown(coin.symbol):
                            best_coin_query = coin
                            break
                except Exception as e:
                    print(f"Error querying BestCoinsForRigView: {e}")
                    self.session_miningDB.rollback()
                    self.session_miningDB = self.Session_miningDB()
                if best_coin_query:
                    print(f"Best coin found: symbol={best_coin_query.symbol}, worker={best_coin_query.worker}, rev_rig_correct={best_coin_query.rev_rig_correct}")
                    best_coin = best_coin_query.symbol
                    print(f"Best coin to mine: {best_coin} with revenue {best_coin_query.rev_rig_correct}")
                    if failed_coin:
                        self.log_event("coin_switch", f"Switched from {failed_coin} to {best_coin} due to repeated low hashrate")
                else:
                    print(f"No valid coin found to mine: No results for worker '{HOSTNAME}' with non-NULL rev_rig_correct or all coins are on cooldown.")
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
                    for default_coin in DEFAULT_COINS:
                        if not self.is_coin_on_cooldown(default_coin) and (default_coin in CoinsListXmrig or default_coin in CoinsListSrbmimer or default_coin == "DERO"):
                            best_coin = default_coin
                            print(f"Falling back to default coin: {best_coin}")
                            if failed_coin:
                                self.log_event("coin_switch", f"Switched from {failed_coin} to {best_coin} due to repeated low hashrate")
                            break
                    if not best_coin:
                        print("No default coin available to mine (all on cooldown). Skipping this iteration.")
                        await asyncio.sleep(SLEEP_INTERVAL)
                        continue
                selected_miner = None
                if best_coin in CoinsListXmrig:
                    selected_miner = self.xmrig_controller
                elif best_coin in CoinsListSrbmimer:
                    selected_miner = self.srbminer_controller
                elif best_coin == "DERO":
                    selected_miner = self.deroluna_controller
                if not self.is_game_running and not self.is_overheating and selected_miner:
                    if self.current_miner != selected_miner or (self.current_miner and self.current_miner.current_coin != best_coin):
                        if self.current_miner:
                            self.current_miner.stop_mining()
                        success = selected_miner.start_mining(best_coin)
                        if success:
                            self.current_miner = selected_miner
                        else:
                            print(f"Failed to start mining {best_coin}. Adding to cooldown.")
                            self.failed_coins[best_coin] = time.time() + FAILED_COIN_COOLDOWN
                            selected_miner.last_failed_coin = best_coin
                            continue
                hashrate = 0.0
                if self.current_miner:
                    hashrate = self.current_miner.get_hashrate()
                timestamp = datetime.now().isoformat()
                payload = hashrate
                if USE_MQTT:
                    mqtt_client.publish(MQTT_HASHRATE_TOPIC, payload)
                    if DEBUG:
                        print(f"Published to {MQTT_HASHRATE_TOPIC}: {payload}")
                idle_time = get_idle_time()
                if DEBUG:
                    print(f"Idle time: {idle_time:.2f} seconds")
                if idle_time < IDLE_THRESHOLD and not is_paused and PAUSE_XMRIG:
                    if pause_xmrig():
                        is_paused = True
                elif idle_time >= IDLE_THRESHOLD and is_paused and PAUSE_XMRIG:
                    if resume_xmrig():
                        is_paused = False
                detect_gpu()
                if GPU_TYPE:
                    gpu_metrics = get_gpu_metrics()
                    print(f"Final GPU Metrics: {gpu_metrics}")
                else:
                    print("Cannot retrieve GPU metrics: No GPU detected.")
                    gpu_metrics = {"temperature": None, "usage": None, "fan_speed_rpm": None, "fan_speed_percent": None}
                if self.current_miner and self.current_miner.is_mining and self.current_miner.current_coin:
                    update_miner_stats(self.session_miningDB, HOSTNAME, self.current_miner.current_coin, hashrate, cpu_temp, gpu_metrics)
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