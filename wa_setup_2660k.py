HOSTNAME = "2660k"
MTS_SERVER_NAME = "2660k"  # Set a proper server name

XMRIG_API_URL = "http://127.0.0.1:37329"  # Base URL for API

USE_MQTT = True
MQTT_BROKER = "mqtt.elit-satin.ru"
MQTT_PORT = 1883
MQTT_HASHRATE_TOPIC = "rigs/hashrate/"+HOSTNAME  # For hashrate data
MQTT_GAME_TOPIC = "rigs/games/"+HOSTNAME        # For game info

IDLE_THRESHOLD = 120  # 10 seconds
PAUSE_XMRIG = False
SLEEP_INTERVAL = 60

CoinsListXmrig = ['SAL', 'SEXT', 'WOW', 'XMR']
CoinsListSrbmimer = ['ETI', 'PEPEW', 'SCASH', 'TDC', 'VRSC']



