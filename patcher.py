import os
import sys
import subprocess
import time

def patch_video(input_path, output_path, custom_tag="@akila", encode_1080p=False):
    """Timescale spoof via FFmpeg stream copy — no binary patches."""
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        return

    ffmpeg_cmd = [
        "ffmpeg", "-y",
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
    ]

    if encode_1080p:
        ffmpeg_cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-vf", "scale='min(1920,iw)':min(1920,ih):force_original_aspect_ratio=decrease",
        ]

    ffmpeg_cmd.append(output_path)

    print("🚀 Running FFmpeg remux (stream copy)...")
    print(f"   {' '.join(ffmpeg_cmd)}")
    start = time.time()
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ FFmpeg failed:\n{result.stderr[:500]}")
        return
    elapsed = time.time() - start
    print(f"✅ Success! Output: {output_path} ({elapsed:.2f}s)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python patcher.py -i <input.mp4> -o <output.mp4>")
        sys.exit(1)

    input_file = sys.argv[1]
    if input_file in ("-i", "--input") and len(sys.argv) > 2:
        input_file = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] in ("-o", "--output") else "bypassed_output.mp4"
    if len(sys.argv) >= 3 and sys.argv[2] not in ("-o", "--output"):
        output_file = sys.argv[2]

    patch_video(input_file, output_file, custom_tag="@akila")
