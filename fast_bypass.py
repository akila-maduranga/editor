import subprocess
import os
import shutil
import sys
import argparse
import time

def check_ffmpeg():
    """Ensure FFmpeg is installed on the VPS."""
    if shutil.which("ffmpeg") is None:
        print("[-] Error: FFmpeg is not installed on this server.")
        sys.exit(1)

def fast_spoof(input_path, output_path):
    """Executes the timescale spoofing via FFmpeg Stream Copy."""
    if not os.path.exists(input_path):
        print(f"[-] Error: Could not find '{input_path}'")
        sys.exit(1)

    print(f"[*] Analyzing: {input_path}")
    print("[*] Applying Timescale Spoof (Zero CPU / Stream Copy mode)...")
    
    start_time = time.time()

    command = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-c", "copy",
        "-map_metadata", "-1",
        "-brand", "isom",
        "-movflags", "+faststart",
        "-video_track_timescale", "90000",
        "-metadata", "encoder=Lavf60.16.100",
        "-metadata", "title=",
        "-metadata", "artist=",
        "-metadata", "copyright=",
        "-metadata", "comment=",
        output_path
    ]

    try:
        subprocess.run(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            check=True
        )
        
        elapsed_time = time.time() - start_time
        print(f"[+] Success! Output saved to: {output_path}")
        print(f"[+] Processing completed in: {elapsed_time:.2f} seconds")
        
    except subprocess.CalledProcessError as e:
        print("[-] FFmpeg encountered an error.")
        print(e.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lightning Fast TikTok Compression Bypass for VPS")
    parser.add_argument("-i", "--input", required=True, help="Input video file")
    parser.add_argument("-o", "--output", default="bypassed_output.mp4", help="Output video file")
    
    args = parser.parse_args()

    check_ffmpeg()
    fast_spoof(args.input, args.output)
