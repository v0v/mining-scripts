import os
import glob
import subprocess
import argparse
from datetime import datetime

from wa_cred import SERVER_PREFIXES

# Configuration
NETWORK_PATH = "Y:/"  # Network drive path (e.g., Z:\)
SAVE_PATH = "C:/temp/"  # Network drive path (e.g., Z:\)
FFMPEG_PATH = "C:/ffmpeg/bin/ffmpeg.exe"  # Adjust this to the full path of ffmpeg.exe
VIDEO_FPS = 15  # Fixed frame rate for the merged file (match the target FPS from recording)

# Compression settings for merging
MERGE_VIDEO_CODEC = "libx265"  # Video codec for re-encoding (H.265)
MERGE_VIDEO_BITRATE = "4000k"  # Target bitrate for the merged video (2 Mbps, increased from 1 Mbps)
MERGE_VSYNC = "1"  # Frame timing method (1 = passthrough with frame dropping/duplication)
MERGE_AUDIO_CODEC = "copy"  # Audio codec ("copy" to avoid re-encoding audio)
DURATION_TOLERANCE = 0.05  # 5% tolerance for merged duration vs. total chunk duration

def get_duration(file_path):
    """Get the duration of a video file using ffprobe."""
    try:
        ffprobe_cmd = [
            FFMPEG_PATH.replace("ffmpeg.exe", "ffprobe.exe"),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
        duration_str = result.stdout.strip()
        if duration_str in ("N/A", ""):
            print(f"Warning: Could not determine duration for {file_path}. File may be corrupted.")
            return None
        duration = float(duration_str)
        return duration
    except subprocess.CalledProcessError as e:
        print(f"Error getting duration for {file_path}: {e}")
        return None
    except ValueError as e:
        print(f"Error parsing duration for {file_path}: {e}")
        return None

def get_session_ids(server_prefix):
    """Detect all unique session IDs for a given server prefix in the network folder."""
    chunk_pattern = os.path.join(NETWORK_PATH, f"{server_prefix}_*_chunk.mkv")
    chunk_files = glob.glob(chunk_pattern)
    
    if not chunk_files:
        print(f"No chunks found for server {server_prefix} in {NETWORK_PATH}")
        return set()

    session_ids = set()
    for chunk_file in chunk_files:
        filename = os.path.basename(chunk_file)
        parts = filename.split("_")
        if len(parts) >= 5 and parts[0] == server_prefix and parts[-1] == "chunk.mkv":
            session_id = parts[1]
            session_ids.add(session_id)

    return session_ids

def merge_chunks(server_prefix, session_id, output_format="mkv", delete_chunks=False):
    """Merge all chunks for a given server prefix and session ID into a single file using FFmpeg with re-encoding."""
    chunk_pattern = os.path.join(NETWORK_PATH, f"{server_prefix}_{session_id}_*_chunk.mkv")
    chunk_files = sorted(glob.glob(chunk_pattern))
    
    if not chunk_files:
        print(f"No chunks found for server {server_prefix}, session ID {session_id} in {NETWORK_PATH}")
        return

    print(f"Found {len(chunk_files)} chunks for server {server_prefix}, session ID {session_id}: {chunk_files}")

    total_chunk_duration = 0
    valid_chunks = []
    for chunk in chunk_files:
        duration = get_duration(chunk)
        if duration is None:
            print(f"Skipping chunk {chunk} due to invalid duration.")
            continue
        total_chunk_duration += duration
        valid_chunks.append(chunk)
        print(f"Chunk {chunk}: Duration = {duration:.2f} seconds")

    if not valid_chunks:
        print(f"No valid chunks to merge for server {server_prefix}, session ID {session_id}.")
        return

    first_chunk = valid_chunks[0]
    filename = os.path.basename(first_chunk)
    parts = filename.split("_")
    if len(parts) >= 5:
        game_session_start_time = f"{parts[2]}_{parts[3]}"
    else:
        print(f"Warning: Could not parse timestamp from chunk filename {filename}. Using current time instead.")
        game_session_start_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    concat_file = os.path.join(NETWORK_PATH, f"concat_{server_prefix}_{session_id}.txt")
    with open(concat_file, "w") as f:
        for chunk in valid_chunks:
            f.write(f"file '{chunk}'\n")

    output_file = os.path.join(SAVE_PATH, f"{server_prefix}_{game_session_start_time}_{session_id}_merged.{output_format}")

    try:
        ffmpeg_cmd = [
            FFMPEG_PATH,
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c:v", MERGE_VIDEO_CODEC,
            "-crf", "33",
            "-r", str(VIDEO_FPS),
            "-vsync", MERGE_VSYNC,
            "-c:a", MERGE_AUDIO_CODEC,
            output_file
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True)
        print(f"Successfully merged {len(valid_chunks)} chunks into {output_file}")
        print("FFmpeg output:", result.stdout)
        if result.stderr:
            print("FFmpeg errors:", result.stderr)

        # Verify merged file duration
        merged_duration = get_duration(output_file)
        if merged_duration is not None:
            print(f"Merged file duration: {merged_duration:.2f} seconds (expected: {total_chunk_duration:.2f} seconds)")
            # Check if merged duration is within tolerance
            if abs(merged_duration - total_chunk_duration) <= total_chunk_duration * DURATION_TOLERANCE:
                print(f"Merged duration within {DURATION_TOLERANCE*100}% tolerance of expected duration.")
                if delete_chunks:
                    for chunk in valid_chunks:
                        try:
                            os.remove(chunk)
                            print(f"Deleted chunk: {chunk}")
                        except OSError as e:
                            print(f"Error deleting chunk {chunk}: {e}")
            else:
                print(f"Warning: Merged duration differs significantly from expected ({abs(merged_duration - total_chunk_duration):.2f}s). Skipping chunk deletion.")
        else:
            print(f"Could not verify merged file duration. Skipping chunk deletion.")

    except subprocess.CalledProcessError as e:
        print(f"Error merging chunks for server {server_prefix}, session ID {session_id}: {e}")
        print("FFmpeg output:", e.output)
    except FileNotFoundError as e:
        print(f"FFmpeg executable not found at {FFMPEG_PATH}. Please ensure FFmpeg is installed and the path is correct.")
    finally:
        if os.path.exists(concat_file):
            os.remove(concat_file)

def merge_all_sessions(output_format="mkv", delete_chunks=False):
    """Merge chunks for all detected session IDs across all servers in the network folder."""
    for server_prefix in SERVER_PREFIXES:
        print(f"\nProcessing server: {server_prefix}")
        session_ids = get_session_ids(server_prefix)
        if not session_ids:
            print(f"No sessions found for server {server_prefix}.")
            continue

        print(f"Detected {len(session_ids)} sessions for server {server_prefix}: {session_ids}")
        for session_id in session_ids:
            print(f"\nMerging chunks for server {server_prefix}, session ID {session_id}...")
            merge_chunks(server_prefix, session_id, output_format, delete_chunks)

def main():
    """Main function to merge chunks, either for a specific session ID or all sessions."""
    parser = argparse.ArgumentParser(description="Merge video chunks for one or all session IDs across servers.")
    parser.add_argument("session_id", nargs="?", default=None, help="Session ID to merge chunks for (e.g., b60e71b418a14930a01e2600e102c595). If not provided, all sessions will be merged.")
    parser.add_argument("--server", default=None, choices=SERVER_PREFIXES, help=f"Server prefix to process the session ID for (choices: {SERVER_PREFIXES}). Required if session_id is specified.")
    parser.add_argument("--format", default="mkv", choices=["mkv", "mp4"], help="Output format for the merged file (default: mkv)")
    parser.add_argument("--delete-chunks", action="store_true", help="Delete chunk files after successful merging (if merged duration is within tolerance)")
    args = parser.parse_args()

    if args.session_id:
        if not args.server:
            found = False
            for server_prefix in SERVER_PREFIXES:
                session_ids = get_session_ids(server_prefix)
                if args.session_id in session_ids:
                    print(f"Found session ID {args.session_id} on server {server_prefix}.")
                    merge_chunks(server_prefix, args.session_id, args.format, args.delete_chunks)
                    found = True
                    break
            if not found:
                print(f"Session ID {args.session_id} not found on any server in {NETWORK_PATH}.")
        else:
            session_ids = get_session_ids(args.server)
            if args.session_id in session_ids:
                merge_chunks(args.server, args.session_id, args.format, args.delete_chunks)
            else:
                print(f"Session ID {args.session_id} not found for server {args.server} in {NETWORK_PATH}.")
    else:
        merge_all_sessions(args.format, args.delete_chunks)

if __name__ == "__main__":
    main()