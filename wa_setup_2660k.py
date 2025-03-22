# wa_setup_2660k.py
from sqlalchemy import create_engine, String, Column, Integer, ForeignKey
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import inspect

from wa_cred import DB_USER, DB_PASSWORD, DB_SERVER_IP

HOSTNAME = "2660k"
MTS_SERVER_NAME = None

XMRIG_API_URL = "http://127.0.0.1:37329"  # Base URL for API

USE_MQTT = True
MQTT_BROKER = "mqtt.elit-satin.ru"
MQTT_PORT = 1883
MQTT_HASHRATE_TOPIC = "rigs/hashrate/"+HOSTNAME  # For hashrate data
MQTT_GAME_TOPIC = "rigs/games/"+HOSTNAME        # For game info

IDLE_THRESHOLD = 120  # 10 seconds
PAUSE_XMRIG = False
SLEEP_INTERVAL = 60

# Configuration
engine_miningDB = create_engine(f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_SERVER_IP}/mining")
engine_fogplayDB = create_engine(f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_SERVER_IP}/fogplay")
Base = declarative_base()

# Tables from fogplay db
class Events(Base):
    __tablename__ = "events"
    timestamp: Mapped[int] = mapped_column(primary_key=True)
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

class SupportedCoins(Base):
    __tablename__ = "supported_coins"

    symbol: Mapped[str] = mapped_column(primary_key=True)
    worker: Mapped[str] = mapped_column(primary_key=True)
    command_start: Mapped[str] = mapped_column(primary_key=True)
    command_stop: Mapped[str]
    enabled: Mapped[bool]
    rig_hr_kh: Mapped[float]

CoinsListXmrig = ['SAL', 'SEXT', 'WOW', 'XMR']
CoinsListSrbmimer = ['ETI', 'PEPEW', 'SCASH', 'TDC', 'VRSC']

# Game executable names
GAME_PROCESSES = {
    "counterstrike2": "cs2.exe",
    "cyberpunk 2077": "Cyberpunk2077.exe",
    "dark&darker": ["TavernDart.exe", "Tavern.exe", "TavernWorker.exe"],
    "destiny2": "destiny2.exe",
    "dota2": "dota2.exe",
    "fortnite": "FortniteClient-Win64-Shipping_EAC_EOS.exe",
    "frostpunk2": "Frostpunk2-Win64-Shipping.exe",
    "ghost of tsushima": "GhostOfTsushima.exe",
    "GTA V Enhanced": "PlayGTAV.exe",
    "kingdomcome": "KingdomCome.exe",
    "pubg": ["PUBG.exe", "TslGame.exe"],
    "split fiction": "SplitFiction.exe",
    "warframe": "warframe.exe",
    "war thunder": "aces.exe"
}