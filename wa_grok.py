# wa_grok.py
import asyncio
import json
import subprocess
import time
import paho.mqtt.client as mqtt
import os
import threading
import queue
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from pathlib import Path

from wa_setup_2660k import HOSTNAME, MTS_SERVER_NAME, \
    engine_fogplayDB, engine_miningDB, Events, BestCoinsForRigView, MinersStats, SupportedCoins, \
    GAME_PROCESSES, CoinsListSrbmimer, CoinsListXmrig, \
    XMRIG_API_URL, \
    MQTT_BROKER, MQTT_PORT, MQTT_HASHRATE_TOPIC, MQTT_GAME_TOPIC, \
    IDLE_THRESHOLD, PAUSE_XMRIG, \
    SLEEP_INTERVAL
from wa_functions import get_current_game, get_idle_time, is_admin, pause_xmrig, resume_xmrig, on_connect
from wa_cred import MQTT_USER, MQTT_PASSWORD, XMRIG_CLI_ARGS_SENSITIVE, SRBMINER_CLI_ARGS_SENSITIVE, DEROLUNA_CLI_ARGS_SENSITIVE

DEBUG = True  # Detailed logging
PRINT_MINER_LOG = True

# Constants for hashrate monitoring
HASHRATE_WINDOW = 15 * 60  # 15 minutes window for moving average (in seconds)
HASHRATE_THRESHOLD = 0.5  # Restart if hashrate drops below 50% of the target hashrate
HASHRATE_DROP_DURATION = 2 * 60  # Require the drop to persist for 2 minutes (in seconds)
CHECK_INTERVAL = 10  # Check every 10 seconds

# MQTT Client Setup
mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
mqtt_client.on_connect = on_connect

# Path to miner executables (in Downloads/toolz)
downloads_folder = Path.home() / "Downloads"
XMRIG_PATH = str(downloads_folder / "_miner_current" / "xmrig-6.22.0" / "xmrig.exe")
SRBMINER_PATH = str(downloads_folder / "toolz" / "SRBMiner-Multi.exe")
DEROLUNA_PATH = str(downloads_folder / "toolz" / "deroluna.exe")

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
        "--http-port 37329 --http-no-restricted --http-access-token auth"
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
        "--http-port 37329 --http-no-restricted --http-access-token auth"
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
        "--http-port 37329 --http-no-restricted --http-access-token auth"
    ],
    "SEXT": [
        "--algo=rx/0",
        f"--url={XMRIG_CLI_ARGS_SENSITIVE['SEXT']['url']}",
        f"--user={XMRIG_CLI_ARGS_SENSITIVE['SEXT']['user']}",
        f"--pass={XMRIG_CLI_ARGS_SENSITIVE['SEXT']['pass']}",
        f"--rig-id={HOSTNAME}",
        "--donate-level=1",
        "--cpu",
        "--no-gpu",
        "--http-port 37329 --http-no-restricted --http-access-token auth"
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

# CLI arguments for DeroLuna (DERO) (non-sensitive parts)
DEROLUNA_CLI_ARGS = {
    "DERO": [
        f"--daemon-address={DEROLUNA_CLI_ARGS_SENSITIVE['DERO']['daemon-address']}",
        f"--wallet-address={DEROLUNA_CLI_ARGS_SENSITIVE['DERO']['wallet-address']}",
        "--worker", HOSTNAME,
        "--mining-threads", "0"
    ]
}

class MinerController:
    def __init__(self, miner_path, cli_args, hashrate_pattern, hashrate_index, session_miningDB):
        self.miner_path = miner_path
        self.cli_args = cli_args
        self.hashrate_pattern = hashrate_pattern
        self.hashrate_index = hashrate_index
        self.session_miningDB = session_miningDB
        self.process = None
        self.is_mining = False
        self.current_coin = None
        self.hashrate = 0.0
        self.target_hashrate = None
        self.output_queue = queue.Queue()
        self.running = False
        self.hashrate_history = []  # List of (timestamp, hashrate) tuples
        self.low_hashrate_start = None  # Timestamp when hashrate drop started

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

    def read_output(self):
        """Read miner output from stdout and parse hashrate."""
        while self.running:
            try:
                # Check if the process has exited
                if self.process.poll() is not None:
                    print(f"Miner process ({os.path.basename(self.miner_path)}) has exited unexpectedly. Restarting...")
                    self.stop_mining()
                    self.start_mining(self.current_coin)
                    break

                # Read a line from stdout
                line = self.process.stdout.readline().strip()
                if not line:
                    time.sleep(0.1)  # Avoid busy-waiting
                    continue

                if PRINT_MINER_LOG:
                    print(line)
                self.output_queue.put(line)

                # Parse hashrate based on miner-specific pattern
                if self.hashrate_pattern in line:
                    try:
                        parts = line.split()
                        hashrate_str = parts[self.hashrate_index]
                        self.hashrate = float(hashrate_str)
                        if DEBUG:
                            print(f"Parsed hashrate for {self.current_coin}: {self.hashrate} H/s")

                        # Update hashrate history
                        current_time = time.time()
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
                                    self.start_mining(self.current_coin)
                                    self.low_hashrate_start = None  # Reset after restart
                            else:
                                if self.low_hashrate_start is not None:
                                    if DEBUG:
                                        print(f"Moving average hashrate recovered ({moving_avg} >= {threshold}). Resetting monitor.")
                                    self.low_hashrate_start = None

                    except (IndexError, ValueError) as e:
                        print(f"Error parsing hashrate from line '{line}': {e}")
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
        """Start the miner for the specified coin using CLI arguments."""
        if self.is_mining:
            print("Miner is already running. Stopping first...")
            self.stop_mining()

        if coin_symbol not in self.cli_args:
            print(f"Error: No CLI arguments defined for coin {coin_symbol}")
            return False

        try:
            cmd = [self.miner_path] + self.cli_args[coin_symbol]
            self.process = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(self.miner_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Redirect stderr to stdout
                universal_newlines=True,  # Text mode for output
                bufsize=1,  # Line buffering
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP  # For Windows
            )
            self.is_mining = True
            self.current_coin = coin_symbol
            self.running = True
            self.hashrate_history = []
            self.low_hashrate_start = None
            self.target_hashrate = None

            # Start a thread to read output
            self.output_thread = threading.Thread(target=self.read_output)
            self.output_thread.start()

            print(f"Miner started for {coin_symbol}.")
            return True
        except Exception as e:
            print(f"Error starting miner: {e}")
            self.is_mining = False
            return False

    def stop_mining(self):
        """Stop the miner gracefully."""
        if self.is_mining and self.process:
            try:
                self.running = False
                # Try graceful termination
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("Graceful termination timed out. Forcing termination...")
                self.process.kill()
                # Fallback to taskkill to ensure cleanup
                miner_exe = os.path.basename(self.miner_path)
                os.system(f"taskkill /IM {miner_exe} /F /T")
            except Exception as e:
                print(f"Error stopping miner: {e}")
                self.process.kill()
            finally:
                self.output_thread.join()
                self.process = None
                self.is_mining = False
                self.current_coin = None
                self.hashrate = 0.0
                self.hashrate_history = []
                self.low_hashrate_start = None
                self.target_hashrate = None
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

        # Initialize controllers for each miner
        self.xmrig_controller = MinerController(
            miner_path=XMRIG_PATH,
            cli_args=XMRIG_CLI_ARGS,
            hashrate_pattern="speed",
            hashrate_index=5,  # 10s hashrate in "speed 10s/60s/15m 1234.5 1230.0 1225.0 H/s"
            session_miningDB=self.session_miningDB
        )
        self.srbminer_controller = MinerController(
            miner_path=SRBMINER_PATH,
            cli_args=SRBMINER_CLI_ARGS,
            hashrate_pattern="Total Hashrate",
            hashrate_index=2,  # "Total Hashrate: 1234.5 H/s"
            session_miningDB=self.session_miningDB
        )
        self.deroluna_controller = MinerController(
            miner_path=DEROLUNA_PATH,
            cli_args=DEROLUNA_CLI_ARGS,
            hashrate_pattern="Hashrate",
            hashrate_index=1,  # "Hashrate: 1234.5 H/s"
            session_miningDB=self.session_miningDB
        )
        self.last_game = None
        self.is_game_running = False
        self.current_miner = None

    async def amain(self):
        if not is_admin():
            print("Warning: Not running as admin. Should work for API calls, but monitor for issues.")

        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        is_paused = False

        while True:
            try:
                # Database sessions
                self.session_miningDB.commit()
                Session_fogplayDB = sessionmaker(bind=engine_fogplayDB)
                session_fogplayDB = Session_fogplayDB()
                session_fogplayDB.commit()

                # Select the best coin to mine
                best_coin_query = self.session_miningDB.query(BestCoinsForRigView).filter(
                    BestCoinsForRigView.worker == HOSTNAME).order_by(
                    BestCoinsForRigView.rev_rig_correct.desc()).first()
                best_coin = None
                if best_coin_query and best_coin_query.rev_rig_correct is not None:
                    best_coin = best_coin_query.symbol
                    print(f"Best coin to mine: {best_coin} with revenue {best_coin_query.rev_rig_correct}")
                else:
                    print("No valid coin found to mine.")
                    best_coin = "WOW"  # Fallback to WOW if no coin is found

                # Select the appropriate miner for the best coin
                selected_miner = None
                if best_coin in CoinsListXmrig:
                    selected_miner = self.xmrig_controller
                elif best_coin in CoinsListSrbmimer:
                    selected_miner = self.srbminer_controller
                elif best_coin == "DERO":
                    selected_miner = self.deroluna_controller

                # Start the selected miner if no game is running
                if not self.is_game_running and selected_miner and (self.current_miner != selected_miner or selected_miner.current_coin != best_coin):
                    if self.current_miner:
                        self.current_miner.stop_mining()
                    selected_miner.start_mining(best_coin)
                    self.current_miner = selected_miner

                # Fetch and publish hashrate from the current miner
                hashrate = 0.0
                if self.current_miner:
                    hashrate = self.current_miner.get_hashrate()
                timestamp = datetime.now().isoformat()
                payload = hashrate
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
                        mqtt_client.publish(MQTT_GAME_TOPIC, game_payload)

                        EventsData = Events(
                            timestamp=datetime.now(),
                            event="new_game_started",
                            value=current_game,
                            server=MTS_SERVER_NAME
                        )
                        session_fogplayDB.add(EventsData)
                        session_fogplayDB.commit()

                        if DEBUG:
                            print(f"New game detected: {current_game}")
                            print(f"Published to {MQTT_GAME_TOPIC}: {game_payload}")

                        # Stop the current miner when a game starts
                        if self.current_miner:
                            self.current_miner.stop_mining()
                            self.current_miner = None
                        self.is_game_running = True

                    else:
                        # Game stopped
                        if self.is_game_running:
                            print("Game stopped. Restarting miner with best coin...")
                            if selected_miner:
                                selected_miner.start_mining(best_coin)
                                self.current_miner = selected_miner
                            self.is_game_running = False

                    self.last_game = current_game

                # Update miner stats with the current coin
                if self.current_miner and self.current_miner.is_mining and self.current_miner.current_coin:
                    MinerStatsData = MinersStats(
                        symbol=self.current_miner.current_coin,
                        timestamp=time.time(),
                        hostname=HOSTNAME,
                        hashrate=hashrate
                    )
                    self.session_miningDB.add(MinerStatsData)
                    self.session_miningDB.commit()

                session_fogplayDB.close()
                await asyncio.sleep(SLEEP_INTERVAL)

            except Exception as e:
                print(f"Main loop error: {e}")
                self.session_miningDB.close()
                session_fogplayDB.close()
                await asyncio.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(ScreenRunSwitcher().amain())
    print("*" * 100)