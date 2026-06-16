import os
import struct
import sys
import subprocess
import time

def patch_video(input_path, output_path, custom_tag="@akila", encode_1080p=False):
    """FFmpeg stream copy + targeted binary patches (STSZ x10, MDAT +1)."""
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        return

    # ------------------------------------------------------------------
    # Stage 1: FFmpeg fast remux
    # ------------------------------------------------------------------
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
    start = time.time()
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ FFmpeg failed:\n{result.stderr[:500]}")
        return
    print(f"✅ FFmpeg done ({time.time()-start:.2f}s)")

    # ------------------------------------------------------------------
    # Stage 2: Targeted binary patches
    # ------------------------------------------------------------------
    with open(output_path, 'r+b') as f:
        data = bytearray(f.read())

        # Locate moov boundaries
        moov = data.find(b'moov')
        moov_end = len(data)
        if moov != -1 and moov >= 4:
            moov_size = struct.unpack('>I', data[moov-4:moov])[0]
            moov_end = moov - 4 + moov_size

        # A. STSZ: inflate video sample count x10 (within moov only)
        stsz_positions = []
        if moov != -1 and moov >= 4:
            pos = moov
            while pos < moov_end - 4:
                pos = data.find(b'stsz', pos)
                if pos == -1 or pos >= moov_end:
                    break
                stsz_positions.append(pos)
                pos += 1

        if stsz_positions:
            stsz_off = stsz_positions[-1]
            cnt_off = stsz_off + 16
            cur = struct.unpack('>I', data[cnt_off:cnt_off+4])[0]
            data[cnt_off:cnt_off+4] = struct.pack('>I', cur * 10)
            print(f"✅ STSZ: count {cur:,} -> {cur*10:,}")
        else:
            print("⚠️  STSZ not found within moov")

        # B. MDAT: increment size by 1 (search after moov)
        mdat = data.find(b'mdat', moov_end if moov_end < len(data) else 0)
        if mdat >= 4:
            cur_size = struct.unpack('>I', data[mdat-4:mdat])[0]
            data[mdat-4:mdat] = struct.pack('>I', cur_size + 1)
            print(f"✅ MDAT size: {cur_size:,} -> {cur_size+1:,}")

        f.seek(0)
        f.write(data)
        f.truncate()

    print(f"🎉 Done! Output: {output_path}")

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
