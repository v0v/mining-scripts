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
        # Handle cases where duration is 'N/A' or empty
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

    # Extract session IDs from filenames
    session_ids = set()
    for chunk_file in chunk_files:
        # Filename format: <server_prefix>_<session_id>_<date>_<time>_chunk.mkv
        filename = os.path.basename(chunk_file)
        parts = filename.split("_")
        if len(parts) >= 5 and parts[0] == server_prefix and parts[-1] == "chunk.mkv":
            # Session ID is the second part (e.g., b60e71b418a14930a01e2600e102c595)
            session_id = parts[1]
            session_ids.add(session_id)

    return session_ids

def merge_chunks(server_prefix, session_id, output_format="mkv"):
    """Merge all chunks for a given server prefix and session ID into a single file using FFmpeg with re-encoding."""
    # Find all chunk files for the given server prefix and session ID
    chunk_pattern = os.path.join(NETWORK_PATH, f"{server_prefix}_{session_id}_*_chunk.mkv")
    chunk_files = sorted(glob.glob(chunk_pattern))
    
    if not chunk_files:
        print(f"No chunks found for server {server_prefix}, session ID {session_id} in {NETWORK_PATH}")
        return

    print(f"Found {len(chunk_files)} chunks for server {server_prefix}, session ID {session_id}: {chunk_files}")

    # Calculate total expected duration of chunks, excluding corrupted ones
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

    # Extract the game session start time from the first valid chunk's filename
    first_chunk = valid_chunks[0]  # First valid chunk (earliest timestamp due to sorting)
    filename = os.path.basename(first_chunk)
    parts = filename.split("_")
    # Filename format: <server_prefix>_<session_id>_<date>_<time>_chunk.mkv
    # Date is parts[2], time is parts[3] (e.g., 20250328_001433)
    if len(parts) >= 5:
        game_session_start_time = f"{parts[2]}_{parts[3]}"  # e.g., 20250328_001433
    else:
        print(f"Warning: Could not parse timestamp from chunk filename {filename}. Using current time instead.")
        game_session_start_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create a temporary file listing all valid chunks for FFmpeg
    concat_file = os.path.join(NETWORK_PATH, f"concat_{server_prefix}_{session_id}.txt")
    with open(concat_file, "w") as f:
        for chunk in valid_chunks:
            f.write(f"file '{chunk}'\n")

    # Generate the output filename in the order: server name, game session start time, session ID
    output_file = os.path.join(SAVE_PATH, f"{server_prefix}_{game_session_start_time}_{session_id}_merged.{output_format}")

    # Use FFmpeg to merge the chunks with re-encoding to ensure consistent frame rate and duration
    try:
        ffmpeg_cmd = [
            FFMPEG_PATH,
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c:v", MERGE_VIDEO_CODEC,  # Re-encode video with specified codec
            "-crf", "33",  # Use CRF instead of bitrate (lower values = better quality, higher file size)
            "-r", str(VIDEO_FPS),  # Set frame rate
            "-vsync", MERGE_VSYNC,  # Ensure proper frame timing
            "-c:a", MERGE_AUDIO_CODEC,  # Handle audio stream
            output_file
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True)
        print(f"Successfully merged {len(valid_chunks)} chunks into {output_file}")
        print("FFmpeg output:", result.stdout)
        if result.stderr:
            print("FFmpeg errors:", result.stderr)

        # Verify the duration of the merged file
        merged_duration = get_duration(output_file)
        if merged_duration is not None:
            print(f"Merged file duration: {merged_duration:.2f} seconds (expected: {total_chunk_duration:.2f} seconds)")
        else:
            print(f"Could not determine duration of merged file {output_file}.")

    except subprocess.CalledProcessError as e:
        print(f"Error merging chunks for server {server_prefix}, session ID {session_id}: {e}")
        print("FFmpeg output:", e.output)
    except FileNotFoundError as e:
        print(f"FFmpeg executable not found at {FFMPEG_PATH}. Please ensure FFmpeg is installed and the path is correct.")
    finally:
        # Clean up the temporary concat file
        if os.path.exists(concat_file):
            os.remove(concat_file)

def merge_all_sessions(output_format="mkv"):
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
            merge_chunks(server_prefix, session_id, output_format)

def main():
    """Main function to merge chunks, either for a specific session ID or all sessions."""
    parser = argparse.ArgumentParser(description="Merge video chunks for one or all session IDs across servers.")
    parser.add_argument("session_id", nargs="?", default=None, help="Session ID to merge chunks for (e.g., b60e71b418a14930a01e2600e102c595). If not provided, all sessions will be merged.")
    parser.add_argument("--server", default=None, choices=SERVER_PREFIXES, help=f"Server prefix to process the session ID for (choices: {SERVER_PREFIXES}). Required if session_id is specified.")
    parser.add_argument("--format", default="mkv", choices=["mkv", "mp4"], help="Output format for the merged file (default: mkv)")
    args = parser.parse_args()

    if args.session_id:
        # Merge chunks for the specified session ID
        if not args.server:
            # Check all servers for the session ID
            found = False
            for server_prefix in SERVER_PREFIXES:
                session_ids = get_session_ids(server_prefix)
                if args.session_id in session_ids:
                    print(f"Found session ID {args.session_id} on server {server_prefix}.")
                    merge_chunks(server_prefix, args.session_id, args.format)
                    found = True
                    break
            if not found:
                print(f"Session ID {args.session_id} not found on any server in {NETWORK_PATH}.")
        else:
            # Use the specified server
            session_ids = get_session_ids(args.server)
            if args.session_id in session_ids:
                merge_chunks(args.server, args.session_id, args.format)
            else:
                print(f"Session ID {args.session_id} not found for server {args.server} in {NETWORK_PATH}.")
    else:
        # Merge chunks for all detected sessions across all servers
        merge_all_sessions(args.format)

if __name__ == "__main__":
    main()