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

class MyGames(Base):
    __tablename__ = "my_games"
    slug: Mapped[str] = mapped_column(primary_key=True)
    active: Mapped[bool]
    bx4: Mapped[bool]
    bx5: Mapped[bool]
    bx7: Mapped[bool]
    exe_files: Mapped[str]
    version_installed: Mapped[str]
    version_latest: Mapped[str]
    comments_torrent: Mapped[str]
    comments_install: Mapped[str]
    comments_fogplay: Mapped[str]
    saves_path: Mapped[str]
    source: Mapped[str]
    install_path: Mapped[str]
    id_steam: Mapped[int]

class Credentials(Base):
    __tablename__ = "credentials"
    source: Mapped[str] = mapped_column(primary_key=True)
    username: Mapped[str]
    password: Mapped[str]

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
    gpu_fan_speed_percent: Mapped[float]  # New field for GPU fan_speed_percent
    gpu_fan_speed_rpm: Mapped[float]  # New field for GPU fan_speed_rpm
    gpu_temp_memory: Mapped[float]  
    gpu_temp_hotspot: Mapped[float]  
    gpu_clock_core: Mapped[float]  
    gpu_clock_memory: Mapped[float]  
    gpu_voltage_core: Mapped[float]  
    gpu_voltage_memory: Mapped[float]  

class SupportedCoins(Base):
    __tablename__ = "supported_coins"

    symbol: Mapped[str] = mapped_column(primary_key=True)
    worker: Mapped[str] = mapped_column(primary_key=True)
    command_start: Mapped[str] = mapped_column(primary_key=True)
    command_stop: Mapped[str]
    enabled: Mapped[bool]
    rig_hr_kh: Mapped[float]

