import argparse
import os
import subprocess
import sys
import chardet
import time
import threading
import queue
from sqlalchemy.orm import sessionmaker
from sqlalchemy import and_
import traceback
from datetime import datetime
from wa_definitions import engine_fogplayDB, MyGames, Credentials, Events
from wa_cred import MTS_SERVER_NAME

def log_event(session, event_name, event_value):
    """Log an event to the Events table, truncating value to 128 characters."""
    try:
        event_value = event_value[:128]
        event_data = Events(
            timestamp=datetime.now(),
            event=event_name,
            value=event_value,
            server=MTS_SERVER_NAME
        )
        session.add(event_data)
        session.commit()
        safe_print(f"Logged event: {event_name} - {event_value}")
    except Exception as e:
        safe_print(f"Error logging event {event_name}: {e}")
        session.rollback()

def get_console_encoding():
    """Get the active console codepage using chcp command."""
    try:
        result = subprocess.run(['chcp'], capture_output=True, text=True)
        codepage = result.stdout.split()[-1]
        return f'cp{codepage}'
    except:
        return 'utf-8'

def safe_print(text):
    """Print text safely, handling console encoding issues."""
    console_encoding = get_console_encoding()
    try:
        print(text.encode(console_encoding, errors='replace').decode(console_encoding))
    except:
        print(text.encode('utf-8', errors='replace').decode('utf-8'))

def read_output(pipe, output_queue, pipe_name):
    """Read output from a pipe and put it into a queue with pipe identifier."""
    for line in iter(pipe.readline, ''):
        output_queue.put((pipe_name, line))
    pipe.close()

def generate_batch_file(games, steamcmd_exe, validate, output_path):
    """Generate a Windows batch file with steamcmd commands for all games."""
    batch_content = [
        "@echo off",
        "chcp 65001 > nul",
        "echo Starting SteamCMD updates..."
    ]
    valid_steam_sources = ["steam", "steam free", "steam family"]
    
    for game, cred in games:
        install_path = game.install_path
        app_id = game.id_steam
        source = game.source
        if not install_path or not app_id:
            batch_content.append(f"echo Skipping game {game.slug}: missing install_path or id_steam")
            continue
        if source not in valid_steam_sources:
            continue
        cmd = [
            f'"{steamcmd_exe}"',
            "+force_install_dir", f'"{install_path}"',
            "+login", cred.username, cred.password,
            "+app_update", str(app_id)
        ]
        if validate:
            cmd.append("validate")
        cmd.append("+quit")
        batch_content.append(f"echo Updating game {game.slug} (AppID: {app_id}) at {install_path}")
        batch_content.append(' '.join(cmd))
    
    batch_content.append("echo All updates completed.")
    batch_content.append("pause")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(batch_content))
    safe_print(f"Batch file generated at {output_path}")

def main():
    safe_print("Starting wa_update_steam_games.py...")
    session = None
    try:
        parser = argparse.ArgumentParser(description="Update Steam games using steamcmd.exe or generate a batch file")
        parser.add_argument("--validate", action="store_true", default=False, help="Use 'validate' option in steamcmd (default: False)")
        parser.add_argument("--no-validate", dest="validate", action="store_false", help="Disable 'validate' option")
        parser.add_argument("--show-steamcmd-output", action="store_true", default=False, help="Show full steamcmd.exe output in console")
        parser.add_argument("--generate-batch", action="store_true", default=False, help="Generate a batch file for manual execution and exit")
        args = parser.parse_args()

        safe_print("Connecting to fogplay database...")
        Session = sessionmaker(bind=engine_fogplayDB)
        session = Session()

        log_event(session, "script_started", "wa_update_steam_games.py execution started")

        safe_print("Querying my_games and credentials tables for active games with credentials...")
        games = session.query(MyGames, Credentials).join(
            Credentials, MyGames.source == Credentials.source
        ).filter(
            MyGames.active == True
        ).all()
        safe_print(f"Found {len(games)} active games with credentials.")

        steamcmd_dir = r"C:\SCRIPTS\STEAMCMD"
        steamcmd_exe = os.path.join(steamcmd_dir, "steamcmd.exe")

        if not os.path.exists(steamcmd_exe):
            error_msg = f"Error: steamcmd.exe not found at {steamcmd_exe}"
            safe_print(error_msg)
            log_event(session, "game_update_failed", error_msg)
            session.close()
            return

        if args.generate_batch:
            batch_path = r"C:\scripts\wa\update_steam_games.bat"
            generate_batch_file(games, steamcmd_exe, args.validate, batch_path)
            log_event(session, "batch_file_generated", f"Batch file created at {batch_path}")
            session.close()
            safe_print("Script completed.")
            return

        valid_steam_sources = ["steam", "steam free", "steam family"]

        for game, cred in games:
            install_path = game.install_path
            app_id = game.id_steam
            source = game.source
            safe_print(f"Processing game {game.slug} (Source: {source}, AppID: {app_id}, Path: {install_path})")

            if not install_path or not app_id:
                skip_msg = f"Skipping game {game.slug}: missing install_path or id_steam"
                safe_print(skip_msg)
                log_event(session, "game_skipped", skip_msg)
                continue

            if source not in valid_steam_sources:
                continue

            cmd = [
                steamcmd_exe,
                "+force_install_dir", install_path,
                "+login", cred.username, cred.password,
                "+app_update", str(app_id)
            ]
            if args.validate:
                cmd.append("validate")
            cmd.append("+quit")

            safe_print(f"Updating game {game.slug} (AppID: {app_id}) at {install_path} with command: {' '.join(cmd)}")
            log_event(session, "game_update_started", f"Started update for {game.slug} (AppID: {app_id}) at {install_path}")
            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=steamcmd_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    universal_newlines=True,
                    bufsize=1
                )
                output_queue = queue.Queue()
                stdout_thread = threading.Thread(target=read_output, args=(process.stdout, output_queue, "stdout"))
                stderr_thread = threading.Thread(target=read_output, args=(process.stderr, output_queue, "stderr"))
                stdout_thread.start()
                stderr_thread.start()

                stdout_lines = []
                stderr_lines = []
                start_time = time.time()
                timeout = 1800  # 30-minute timeout
                steam_guard_detected = False
                while process.poll() is None and time.time() - start_time < timeout:
                    try:
                        pipe_name, line = output_queue.get_nowait()
                        if "Steam Guard code" in line:
                            steam_guard_detected = True
                            safe_print("Steam Guard code required. Please enter the code:")
                            code = input().strip()
                            if code:
                                cmd.insert(-2, "+set_steam_guard_code")
                                cmd.insert(-2, code)
                                process.terminate()
                                process.wait(timeout=5)
                                try:
                                    process.kill()
                                except:
                                    pass
                                process = subprocess.Popen(
                                    cmd,
                                    cwd=steamcmd_dir,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True,
                                    universal_newlines=True,
                                    bufsize=1
                                )
                                stdout_thread = threading.Thread(target=read_output, args=(process.stdout, output_queue, "stdout"))
                                stderr_thread = threading.Thread(target=read_output, args=(process.stderr, output_queue, "stderr"))
                                stdout_thread.start()
                                stderr_thread.start()
                                start_time = time.time()
                        if pipe_name == "stdout":
                            stdout_lines.append(line)
                        else:
                            stderr_lines.append(line)
                        if args.show_steamcmd_output:
                            safe_print(f"SteamCMD [{pipe_name}]: {line.strip()}")
                    except queue.Empty:
                        time.sleep(0.1)
                    except KeyboardInterrupt:
                        safe_print(f"Received Ctrl+C, terminating update for game {game.slug}...")
                        process.terminate()
                        process.wait(timeout=5)
                        try:
                            process.kill()
                        except:
                            pass
                        error_msg = f"Update for game {game.slug} interrupted by user."
                        safe_print(error_msg)
                        log_event(session, "game_update_failed", error_msg)
                        raise
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                    try:
                        process.kill()
                    except:
                        pass
                    error_msg = f"Update for game {game.slug} timed out after {timeout} seconds."
                    safe_print(error_msg)
                    log_event(session, "game_update_failed", error_msg)
                while True:
                    try:
                        pipe_name, line = output_queue.get_nowait()
                        if "Steam Guard code" in line:
                            steam_guard_detected = True
                        if pipe_name == "stdout":
                            stdout_lines.append(line)
                        else:
                            stderr_lines.append(line)
                        if args.show_steamcmd_output:
                            safe_print(f"SteamCMD [{pipe_name}]: {line.strip()}")
                    except queue.Empty:
                        break
                stdout_thread.join()
                stderr_thread.join()
                stdout = ''.join(stdout_lines)
                stderr = ''.join(stderr_lines)
                with open('steamcmd_raw_output.txt', 'w', encoding='utf-8') as f:
                    f.write(stdout)
                    f.write(stderr)
                with open('steamcmd_decoded_output.txt', 'w', encoding='utf-8') as f:
                    f.write(stdout)
                    f.write(stderr)
                combined_output = (stdout + stderr).encode('utf-8', errors='ignore')
                detected = chardet.detect(combined_output)
                encoding = detected['encoding'] if detected['encoding'] else 'utf-8'
                confidence = detected['confidence'] if detected['encoding'] else 0.0
                safe_print(f"Successfully decoded steamcmd output with {encoding} (confidence: {confidence})")
                if steam_guard_detected:
                    error_msg = f"Update for game {game.slug} failed: Steam Guard code required."
                    safe_print(error_msg)
                    if args.show_steamcmd_output:
                        safe_print(f"SteamCMD output: {stdout}")
                        safe_print(f"SteamCMD error output: {stderr}")
                    log_event(session, "game_update_failed", error_msg)
                    continue
                if process.returncode == 0:
                    success_msg = f"Updated game {game.slug} successfully."
                    safe_print(success_msg)
                    if args.show_steamcmd_output:
                        safe_print(f"SteamCMD output: {stdout}")
                        safe_print(f"SteamCMD error output: {stderr}")
                    log_event(session, "game_update_success", success_msg)
                else:
                    error_msg = f"Error updating game {game.slug}: {stderr or stdout}"
                    safe_print(error_msg)
                    if args.show_steamcmd_output:
                        safe_print(f"SteamCMD output: {stdout}")
                        safe_print(f"SteamCMD error output: {stderr}")
                    log_event(session, "game_update_failed", error_msg)
            except subprocess.SubprocessError as e:
                error_msg = f"Error updating game {game.slug}: {str(e)}"
                safe_print(error_msg)
                log_event(session, "game_update_failed", error_msg)

        session.close()
        safe_print("Script completed.")
        log_event(session, "script_completed", "wa_update_steam_games.py execution completed")
    except KeyboardInterrupt:
        safe_print("Script interrupted by user (Ctrl+C).")
        log_event(session, "script_failed", "Script interrupted by user (Ctrl+C)")
        if session:
            session.close()
        raise
    except Exception as e:
        error_msg = f"Script failed with error: {str(e)}\n{traceback.format_exc()}"
        safe_print(error_msg)
        log_event(session, "script_failed", error_msg)
        if session:
            session.close()
        raise

if __name__ == "__main__":
    main()