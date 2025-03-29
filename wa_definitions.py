import cv2  #pip install opencv-python
import mss
import numpy as np
import time
from pynput import mouse, keyboard
from threading import Thread
import os

from sqlalchemy import create_engine, String, Column, Integer, ForeignKey
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import inspect
from datetime import datetime  # Add this import

from wa_cred import DB_USER, DB_PASSWORD, DB_SERVER_IP

def get_output_filename():
    os.makedirs("recordings", exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    return f"recordings/screen_record_{timestamp}.mp4"

class ScreenRecorder:
    def __init__(self, fps=10, resolution=(1920, 1080), codec="mp4v", bitrate=2000000, duration=360):
        self.fps = fps
        self.resolution = resolution
        self.codec = codec
        self.bitrate = bitrate
        self.running = False
        self.filename = get_output_filename()
        self.fourcc = cv2.VideoWriter_fourcc(*self.codec)
        self.out = cv2.VideoWriter(self.filename, self.fourcc, self.fps, self.resolution)
        self.duration = duration
    
    def record(self):
        start_time = time.time()
        with mss.mss() as sct:
            while self.running and (time.time() - start_time < self.duration):
                screenshot = sct.grab({"top": 0, "left": 0, "width": self.resolution[0], "height": self.resolution[1]})
                frame = np.array(screenshot)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                self.out.write(frame)
                time.sleep(1 / self.fps)
        self.stop()
    
    def start(self):
        if not self.running:
            self.running = True
            self.thread = Thread(target=self.record)
            self.thread.start()
    
    def stop(self):
        self.running = False
        self.out.release()


# Configuration
engine_miningDB = create_engine(f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_SERVER_IP}/mining")
engine_fogplayDB = create_engine(f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_SERVER_IP}/fogplay")
Base = declarative_base()
# Tables from fogplay db
class Events(Base):
    __tablename__ = "events"
    timestamp: Mapped[datetime] = mapped_column(primary_key=True)  # Change to datetime
    event: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]
    server: Mapped[str]

# Tables from mining db
class BestCoinsForRigView(Base):
    __tablename__ = "best_coins_for_rig"

    position: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str]
    worker: Mapped[str]
    rev_rig_correct: Mapped[float]

class MinersStats(Base):
    __tablename__ = "miner_stats"
    timestamp: Mapped[int] = mapped_column(primary_key=True)
    hostname: Mapped[str] = mapped_column(primary_key=True)
    symbol: Mapped[str]
    hashrate: Mapped[float]
    cpu_temp: Mapped[float]  # New field for CPU temperature
    gpu_temp: Mapped[float]  # New field for GPU temperature

class SupportedCoins(Base):
    __tablename__ = "supported_coins"

    symbol: Mapped[str] = mapped_column(primary_key=True)
    worker: Mapped[str] = mapped_column(primary_key=True)
    command_start: Mapped[str] = mapped_column(primary_key=True)
    command_stop: Mapped[str]
    enabled: Mapped[bool]
    rig_hr_kh: Mapped[float]


# Game executable names
GAME_PROCESSES = {
    "counterstrike2": "cs2.exe",
    "cyberpunk 2077": "Cyberpunk2077.exe",
    "dark-and-darker": ["TavernDart.exe", "Tavern.exe", "TavernWorker.exe"],
    "deep-rock-galactic": ["FSD.exe","FSD-Win64-Shipping.exe"],
    "destiny-2": "destiny2.exe",
    "disco-elysium": ["disco.exe","DiscoElysium.exe"],
    "dota2": "dota2.exe",
    "fortnite": "FortniteClient-Win64-Shipping_EAC_EOS.exe",
    "frostpunk-2": "Frostpunk2-Win64-Shipping.exe",
    "ghost of tsushima": "GhostOfTsushima.exe",
    "grounded": ["Grounded.exe","Maine-WinGDK-Shipping.exe","Maine-Win64-Shipping.exe"],
    "grand-theft-auto-v-enhanced": "PlayGTAV.exe",
    "kingdomcome": "KingdomCome.exe", 
    "marvels-spider-man-2": "Spider-Man2.exe",
    "path-of-exile": ["PathOfExile_x64Steam.exe", "PathOfExileSteam.exe"],
    "portal-2": "portal2.exe",
    "pubg": ["PUBG.exe", "TslGame.exe"],
    "split fiction": "SplitFiction.exe",
    "supermarket-together": ["Supermarket Together.exe", "SupermarketTogether.exe"],
    "warframe": "warframe.exe",
    "warhammer-40000-rogue-trader": ["WH40KRT.exe","RogueTrader.exe"],
    "war thunder": "aces.exe",
    "world-of-warships":"WorldOfWarships.exe"
}