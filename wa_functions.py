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
import platform
from datetime import datetime

try:
    from pyadl import ADLManager
except ImportError:
    ADLManager = None

from wa_definitions import GAME_PROCESSES, MinersStats
from wa_cred import XMRIG_API_URL, MQTT_BROKER, XMRIG_ACCESS_TOKEN

GPU_TYPE = None
OHM_PROCESS = None  # To keep track of the OpenHardwareMonitor process
DEBUG_LOCAL = False

# Detect OS and GPU at startup
OS_TYPE = platform.system().lower()  # "windows", "linux", "darwin" (macOS)
GPU_TYPE = None  # Will be set to "nvidia", "amd", or None

import GPUtil
import subprocess
import psutil  # To check if OpenHardwareMonitor is running
import time

try:
    from pyadl import ADLManager
    print("Successfully imported ADLManager from pyadl")
except ImportError as e:
    ADLManager = None
    print(f"Failed to import ADLManager: {e}")

try:
    import pyopencl as cl
    print("Successfully imported pyopencl")
except ImportError as e:
    print(f"Failed to import pyopencl: {e}")
    cl = None

try:
    import wmi
    print("Successfully imported wmi")
except ImportError as e:
    print(f"Failed to import wmi: {e}")
    wmi = None

try:
    import clr  # For OpenHardwareMonitor
    print("Successfully imported clr for OpenHardwareMonitor")
except ImportError as e:
    print(f"Failed to import clr: {e}")
    clr = None

GPU_TYPE = None
OHM_PROCESS = None  # To keep track of the OpenHardwareMonitor process

def start_openhardwaremonitor():
    """Start OpenHardwareMonitor if it's not already running."""
    global OHM_PROCESS
    ohm_exe_path = r"C:\scripts\OpenHardwareMonitor\OpenHardwareMonitor.exe"  # Update this path
    process_name = "OpenHardwareMonitor.exe"

    # Check if OpenHardwareMonitor is already running
    for proc in psutil.process_iter(['name']):
        if proc.info['name'].lower() == process_name.lower():
            print("OpenHardwareMonitor is already running.")
            return

    # Start OpenHardwareMonitor
    try:
        OHM_PROCESS = subprocess.Popen([ohm_exe_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("Started OpenHardwareMonitor.")
        # Give it a moment to initialize
        time.sleep(2)
    except Exception as e:
        print(f"Error starting OpenHardwareMonitor: {e}")

def stop_openhardwaremonitor():
    """Stop OpenHardwareMonitor if we started it."""
    global OHM_PROCESS
    if OHM_PROCESS:
        OHM_PROCESS.terminate()
        OHM_PROCESS = None
        print("Stopped OpenHardwareMonitor.")

def detect_gpu():
    """Detect the GPU type (NVIDIA, AMD, or None)."""
    global GPU_TYPE
    try:
        # Check for NVIDIA GPU using GPUtil
        gpus = GPUtil.getGPUs()
        if gpus:
            GPU_TYPE = "nvidia"
            print(f"Detected GPU: NVIDIA")
            return
    except Exception as e:
        print(f"Error detecting NVIDIA GPU: {e}")

    # Check for AMD GPU using pyadl
    if ADLManager:
        try:
            devices = ADLManager.getInstance().getDevices()
            if devices:
                GPU_TYPE = "amd"
                print(f"Detected GPU: AMD (via pyadl)")
                return
        except Exception as e:
            print(f"Error detecting AMD GPU with pyadl: {e}")

    # Fallback: Check for AMD GPU using pyopencl
    if cl:
        try:
            platforms = cl.get_platforms()
            for platform in platforms:
                if "AMD" in platform.name or "Advanced Micro Devices" in platform.name:
                    devices = platform.get_devices(device_type=cl.device_type.GPU)
                    if devices:
                        GPU_TYPE = "amd"
                        print(f"Detected GPU: AMD (via pyopencl)")
                        return
        except Exception as e:
            print(f"Error detecting AMD GPU with pyopencl: {e}")

    # Fallback: Check for AMD GPU using WMI
    if wmi:
        try:
            c = wmi.WMI()
            for gpu in c.Win32_VideoController():
                if "AMD" in gpu.Name or "Radeon" in gpu.Name:
                    GPU_TYPE = "amd"
                    print(f"Detected GPU: AMD (via WMI) - {gpu.Name}")
                    return
        except Exception as e:
            print(f"Error detecting AMD GPU with WMI: {e}")

    GPU_TYPE = None
    print("No supported GPU detected.")

def get_cpu_temperature():
    """Get the CPU temperature using OpenHardwareMonitor, with WMI as a fallback."""
    # Try OpenHardwareMonitor first
    if clr:
        try:
            clr.AddReference(r"C:\scripts\OpenHardwareMonitor\OpenHardwareMonitorLib.dll")  # Update this path
            from OpenHardwareMonitor.Hardware import Computer, HardwareType, SensorType

            computer = Computer()
            computer.CPUEnabled = True  # Enable CPU monitoring
            computer.Open()
            for hardware in computer.Hardware:
                if hardware.HardwareType == HardwareType.CPU:  # For CPUs
                    hardware.Update()
                    print(f"CPU Device: {hardware.Name}")
                    for sensor in hardware.Sensors:
                        if sensor.SensorType == SensorType.Temperature:
                            temperature = sensor.Value
                            print(f"Successfully retrieved CPU temperature via OpenHardwareMonitor: {temperature}°C")
                            return temperature
            print("No CPU temperature sensor found via OpenHardwareMonitor.")
        except Exception as e:
            print(f"Error getting CPU temperature with OpenHardwareMonitor: {e}")

    # Fallback to WMI
    if wmi:
        try:
            w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            temperature_sensors = w.Sensor(SensorType="Temperature", Name="CPU Package")
            if temperature_sensors:
                temperature = temperature_sensors[0].Value
                print(f"Successfully retrieved CPU temperature via WMI: {temperature}°C")
                return temperature
            print("No CPU temperature sensor found via WMI.")
        except Exception as e:
            print(f"Error getting CPU temperature with WMI: {e}")

    # Fallback to psutil
    try:
        temps = psutil.sensors_temperatures()
        if "coretemp" in temps:
            for entry in temps["coretemp"]:
                if "Package" in entry.label:
                    temperature = entry.current
                    print(f"Successfully retrieved CPU temperature via psutil: {temperature}°C")
                    return temperature
        print("No CPU temperature sensor found via psutil.")
    except Exception as e:
        print(f"Error getting CPU temperature with psutil: {e}")

    print("CPU temperature monitoring not supported.")
    return None

def get_gpu_metrics():
    """Get GPU temperature, usage, fan speed, frequencies, and voltages based on the detected GPU type."""
    metrics = {
        "temperature": None,
        "usage": None,
        "fan_speed_rpm": None,
        "fan_speed_percent": None,
        "core_clock": None,
        "memory_clock": None,
        "core_voltage": None,
        "memory_voltage": None
    }

    if GPU_TYPE == "nvidia":
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu = gpus[0]
                metrics["temperature"] = gpu.temperature
                metrics["usage"] = gpu.load * 100  # Convert to percentage
                # Get handle for pynvml
                handle = gpu.handle
                # Get clock speeds
                metrics["core_clock"] = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS)
                metrics["memory_clock"] = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
                # Get fan speed
                try:
                    metrics["fan_speed_percent"] = pynvml.nvmlDeviceGetFanSpeed(handle)
                except pynvml.NVMLError as e:
                    print(f"Error getting fan speed: {e}")
                # Get voltage using nvidia-smi
                try:
                    output = subprocess.check_output(["nvidia-smi", "--query-gpu=voltage.gpu", "--format=csv,noheader,nounits"])
                    metrics["core_voltage"] = float(output.strip())
                except Exception as e:
                    print(f"Error getting NVIDIA GPU voltage: {e}")
                print(f"NVIDIA GPU Metrics: Temperature={metrics['temperature']}°C, Usage={metrics['usage']}%, "
                      f"Core Clock={metrics['core_clock']} MHz, Memory Clock={metrics['memory_clock']} MHz, "
                      f"Fan Speed={metrics['fan_speed_percent']}%, Voltage={metrics['core_voltage']} mV")
        except Exception as e:
            print(f"Error getting NVIDIA GPU metrics: {e}")

    elif GPU_TYPE == "amd":
        print("Skipping pyadl for metrics retrieval due to compatibility issues.")

        if clr:
            try:
                clr.AddReference(r"C:\scripts\OpenHardwareMonitor\OpenHardwareMonitorLib.dll")  # Update this path
                from OpenHardwareMonitor.Hardware import Computer, HardwareType, SensorType

                computer = Computer()
                computer.GPUEnabled = True
                computer.Open()
                for hardware in computer.Hardware:
                    if hardware.HardwareType == HardwareType.GpuAti:  # For AMD GPUs
                        hardware.Update()
                        print(f"AMD Device: {hardware.Name}")
                        for sensor in hardware.Sensors:
                            if DEBUG_LOCAL: print(sensor.Name)
                            if DEBUG_LOCAL: print(sensor.Value)
                            if sensor.SensorType == SensorType.Temperature:
                                if "hot spot" in sensor.Name.lower():
                                    metrics["hotspot_temperature"] = sensor.Value
                                    print(f"Successfully retrieved hot spot temperature: {metrics['hotspot_temperature']}°C")
                                elif "gpu memory" in sensor.Name.lower():
                                    metrics["memory_temperature"] = sensor.Value
                                    print(f"Successfully retrieved memory temperature: {metrics['memory_temperature']}°C")
                                elif metrics["temperature"] is None:
                                    metrics["temperature"] = sensor.Value
                                    print(f"Successfully retrieved main GPU temperature: {metrics['temperature']}°C")
                            elif sensor.SensorType == SensorType.Load and metrics["usage"] is None:
                                metrics["usage"] = sensor.Value
                                print(f"Successfully retrieved usage: {metrics['usage']}%")
                            elif sensor.SensorType == SensorType.Fan and metrics["fan_speed_rpm"] is None:
                                metrics["fan_speed_rpm"] = sensor.Value
                                print(f"Successfully retrieved fan speed (RPM): {metrics['fan_speed_rpm']} RPM")
                            elif sensor.SensorType == SensorType.Control and "fan" in sensor.Name.lower() and metrics["fan_speed_percent"] is None:
                                metrics["fan_speed_percent"] = sensor.Value
                                print(f"Successfully retrieved fan speed (Percent): {metrics['fan_speed_percent']}%")
                            elif sensor.SensorType == SensorType.Clock:
                                if "core" in sensor.Name.lower() and metrics["core_clock"] is None:
                                    metrics["core_clock"] = sensor.Value
                                    print(f"Successfully retrieved core clock: {metrics['core_clock']} MHz")
                                elif "memory" in sensor.Name.lower() and metrics["memory_clock"] is None:
                                    metrics["memory_clock"] = sensor.Value
                                    print(f"Successfully retrieved memory clock: {metrics['memory_clock']} MHz")
                            elif sensor.SensorType == SensorType.Voltage:
                                if "core" in sensor.Name.lower() and metrics["core_voltage"] is None:
                                    metrics["core_voltage"] = sensor.Value
                                    print(f"Successfully retrieved core voltage: {metrics['core_voltage']} V")
                                elif "memory" in sensor.Name.lower() and metrics["memory_voltage"] is None:
                                    metrics["memory_voltage"] = sensor.Value
                                    print(f"Successfully retrieved memory voltage: {metrics['memory_voltage']} V")
            except Exception as e:
                print(f"Error getting AMD GPU metrics with OpenHardwareMonitor: {e}")

        if all(value is None for value in metrics.values()):
            print("No GPU metrics could be retrieved for AMD GPU.")

    else:
        print("No supported GPU for metrics monitoring.")

    return metrics

def update_miner_stats(session, hostname, symbol, hashrate, cpu_temp, gpu_metrics):
    """Update the miner_stats table with the latest metrics."""
    timestamp = int(time.time())
    try:
        miner_stats = MinersStats(
            timestamp=timestamp,
            hostname=hostname,
            symbol=symbol,
            hashrate=hashrate,
            cpu_temp=cpu_temp,
            gpu_temp=gpu_metrics["temperature"],
            gpu_fan_speed_percent=gpu_metrics["fan_speed_percent"],
            gpu_fan_speed_rpm=gpu_metrics["fan_speed_rpm"],
            gpu_temp_memory=gpu_metrics["memory_temperature"],
            gpu_temp_hotspot=gpu_metrics["hotspot_temperature"],
            gpu_clock_core=gpu_metrics["core_clock"],
            gpu_clock_memory=gpu_metrics["memory_clock"],
            gpu_voltage_core=gpu_metrics["core_voltage"],
            gpu_voltage_memory=gpu_metrics["memory_voltage"]
        )
        session.add(miner_stats)
        session.commit()
        print(f"Updated miner_stats for {hostname} at {timestamp}")
    except Exception as e:
        print(f"Error updating miner_stats: {e}")
        session.rollback()

##def main():
##    try:
##        # Get CPU temperature
##        start_openhardwaremonitor()  # Start OpenHardwareMonitor if needed
##        cpu_temp = get_cpu_temperature()
##        if cpu_temp is not None:
##            print(f"CPU Temperature: {cpu_temp}°C")
##        else:
##            print("Failed to retrieve CPU temperature.")
##
##        # Get GPU metrics
##        detect_gpu()
##        if GPU_TYPE:
##            gpu_metrics = get_gpu_metrics()
##            print(f"Final GPU Metrics: {gpu_metrics}")
##        else:
##            print("Cannot retrieve GPU metrics: No GPU detected.")
##    finally:
##        stop_openhardwaremonitor()  # Clean up by stopping OpenHardwareMonitor
##
##if __name__ == "__main__":
##    main()

def get_gpu_temperature():
    """Get the GPU temperature based on the detected GPU type."""
    if GPU_TYPE == "nvidia":
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                return gpus[0].temperature
        except Exception as e:
            print(f"Error getting NVIDIA GPU temperature: {e}")
            return None

    elif GPU_TYPE == "amd":
        # Skip pyadl for temperature retrieval due to consistent failures
        print("Skipping pyadl for temperature retrieval due to compatibility issues.")

        # Use OpenHardwareMonitor for temperature
        if clr:
            try:
                clr.AddReference(r"C:\scripts\OpenHardwareMonitor\OpenHardwareMonitorLib.dll")  # Update this path
                from OpenHardwareMonitor.Hardware import Computer, HardwareType, SensorType

                computer = Computer()
                computer.GPUEnabled = True
                computer.Open()
                for hardware in computer.Hardware:
                    if hardware.HardwareType == HardwareType.GpuAti:  # For AMD GPUs
                        hardware.Update()
                        print(f"AMD Device: {hardware.Name}")
                        for sensor in hardware.Sensors:
                            if sensor.SensorType == SensorType.Temperature:
                                temperature = sensor.Value
                                print(f"Successfully retrieved temperature via OpenHardwareMonitor: {temperature}°C")
                                return temperature
                print("No GPU temperature sensor found via OpenHardwareMonitor.")
            except Exception as e:
                print(f"Error getting AMD GPU temperature with OpenHardwareMonitor: {e}")

        print("Temperature monitoring not supported for AMD GPU.")
        return None

    else:
        print("No supported GPU for temperature monitoring.")
        return None

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
    if OS_TYPE == "windows":
        last_input_info = win32api.GetLastInputInfo()
        current_time = win32api.GetTickCount()
        idle_time_ms = current_time - last_input_info
        return idle_time_ms / 1000
    elif OS_TYPE == "linux":
        # Basic implementation for Linux (requires additional libraries like Xlib)
        print("Idle time detection not fully supported on Linux.")
        return 0
    elif OS_TYPE == "darwin":
        print("Idle time detection not supported on macOS.")
        return 0
    else:
        print(f"Unsupported OS for idle time detection: {OS_TYPE}")
        return 0

start_openhardwaremonitor()  # Start OpenHardwareMonitor if needed
try:
    detect_gpu()
    if GPU_TYPE:
        metrics = get_gpu_metrics()
        print(f"Final GPU Metrics: {metrics}")
    else:
        print("Cannot retrieve GPU metrics: No GPU detected.")
except:
    pass
    #stop_openhardwaremonitor()  # Clean up by stopping OpenHardwareMonitor

def start_adrenalin_minimized():
    """Start AMD Radeon Software (Adrenalin) minimized and load the underclock profile."""
    adrenalin_exe_path = r"C:\Program Files\AMD\CNext\CNext\RadeonSoftware.exe"  # Update this path
    profile_path = r"C:\ProgramData\AMD\Profiles\vb.xml"  # Update this path
    process_name = "RadeonSoftware.exe"

    # Check if Radeon Software is already running
    for proc in psutil.process_iter(['name']):
        if proc.info['name'].lower() == process_name.lower():
            print("Radeon Software is already running.")
            # Load the profile even if Adrenalin is already running
            try:
                subprocess.run([adrenalin_exe_path, "--load-profile", profile_path], 
                             creationflags=subprocess.CREATE_NO_WINDOW, 
                             check=True)
                print(f"Loaded underclock profile: {profile_path}")
            except Exception as e:
                print(f"Error loading underclock profile: {e}")
            return

    # Start Radeon Software minimized
    try:
        subprocess.Popen([adrenalin_exe_path], creationflags=subprocess.CREATE_NO_WINDOW)
        print("Started Radeon Software minimized.")
        # Give it a moment to initialize
        time.sleep(2)
        # Load the underclock profile
        subprocess.run([adrenalin_exe_path, "--load-profile", profile_path], 
                     creationflags=subprocess.CREATE_NO_WINDOW, 
                     check=True)
        print(f"Loaded underclock profile: {profile_path}")
    except Exception as e:
        print(f"Error starting Radeon Software or loading profile: {e}")