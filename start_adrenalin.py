import os
import time
import pyautogui
import win32gui
import win32con
import subprocess

# Path to Radeon Software executable
ADRENALIN_PATH = r"C:\Program Files\AMD\CNext\CNext\RadeonSoftware.exe"

# Profile name to load
PROFILE_NAME = "xxx"

def start_adrenalin_minimized():
    """Start AMD Radeon Software minimized to the system tray."""
    # Check if Adrenalin is already running
    if not is_adrenalin_running():
        # Start Adrenalin minimized
        subprocess.Popen([ADRENALIN_PATH], shell=True)
        time.sleep(5)  # Wait for Adrenalin to start
        minimize_adrenalin_window()
    else:
        print("Adrenalin is already running.")

def is_adrenalin_running():
    """Check if Adrenalin is already running."""
    for window in pyautogui.getAllTitles():
        if "AMD Software" in window:
            return True
    return False

def minimize_adrenalin_window():
    """Minimize the Adrenalin window to the system tray."""
    hwnd = win32gui.FindWindow(None, "AMD Software: Adrenalin Edition")
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        print("Adrenalin window minimized.")
    else:
        print("Adrenalin window not found.")

def load_adrenalin_profile():
    """Automate loading the underclocked profile in Adrenalin."""
    # Ensure Adrenalin is running
    start_adrenalin_minimized()

    # Open Adrenalin by clicking the system tray icon (requires coordinates)
    # Note: Adjust these coordinates based on your screen resolution
    pyautogui.click(x=1850, y=1050)  # Example: System tray icon location
    time.sleep(2)

    # Navigate to Performance Tuning
    # Click on the search bar and type "Tuning"
    pyautogui.click(x=200, y=150)  # Example: Search bar location
    pyautogui.write("Tuning")
    pyautogui.press("enter")
    time.sleep(1)

    # Click on the profile dropdown to load the saved profile
    pyautogui.click(x=300, y=300)  # Example: Profile dropdown location
    time.sleep(0.5)

    # Type the profile name and select it
    pyautogui.write(PROFILE_NAME)
    pyautogui.press("enter")
    time.sleep(0.5)

    # Minimize Adrenalin again
    minimize_adrenalin_window()
    print(f"Profile '{PROFILE_NAME}' loaded successfully.")

def main():
    """Main function to start Adrenalin minimized and load the profile."""
    print("Starting script to load Adrenalin profile...")
    load_adrenalin_profile()

if __name__ == "__main__":
    # Add a small delay to ensure the script runs after system startup
    time.sleep(10)
    main()