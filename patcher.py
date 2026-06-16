import os
import struct
import sys
import subprocess

def patch_video(input_path, output_path, custom_tag="@akila", encode_1080p=False):
    """
    Two-stage patching:
      1) FFmpeg re-encode with exploit-friendly settings.
      2) Binary overlay patches: STSZ x10, MDAT size +1, MVHD duration x10, MDHD language.
    """
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        return

    # ------------------------------------------------------------------
    # Stage 1: FFmpeg re-encode
    # ------------------------------------------------------------------
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-r", "1200",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-map_metadata", "-1",
        "-brand", "isom",
        "-movflags", "+faststart",
        "-video_track_timescale", "12000",
        "-metadata", "encoder=Lavf60.16.100",
        "-metadata", "title=",
        "-metadata", "artist=",
        "-metadata", "copyright=",
        "-metadata", "comment=",
    ]

    if encode_1080p:
        idx = ffmpeg_cmd.index("-c:v") + 1
        ffmpeg_cmd.insert(idx,
            "scale='min(1920,iw)':min(1920,ih):force_original_aspect_ratio=decrease")

    ffmpeg_cmd.append(output_path)

    print("🚀 Running FFmpeg re-encode...")
    print(f"   {' '.join(ffmpeg_cmd)}")
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ FFmpeg failed:\n{result.stderr[:500]}")
        return
    print("✅ FFmpeg re-encode complete")

    # ------------------------------------------------------------------
    # Stage 2: Binary overlay patches
    # ------------------------------------------------------------------
    with open(output_path, 'r+b') as f:
        data = bytearray(f.read())
        file_size = len(data)

        print(f"📁 File size: {file_size:,} bytes")
        print("🔍 Applying binary overlay patches...")

        # 1. FTYP safety net
        ftyp = data.find(b'ftyp')
        if ftyp != -1:
            data[ftyp+4:ftyp+8] = b'isom'
            ftyp_box_size = struct.unpack('>I', data[ftyp-4:ftyp])[0]
            if ftyp_box_size > 16:
                data[ftyp+12:ftyp+16] = b'isom'
            print("✅ FTYP: major -> 'isom', compatible -> 'isom'")

        # 2. MDAT SIZE +1 (safe with faststart — extends into EOF)
        mdat = data.find(b'mdat')
        if mdat >= 4:
            current_size = struct.unpack('>I', data[mdat-4:mdat])[0]
            new_size = current_size + 1
            data[mdat-4:mdat] = struct.pack('>I', new_size)
            print(f"✅ MDAT size: {current_size:,} -> {new_size:,}")

        # 3. STSZ: patch LAST occurrence x10
        stsz_positions = []
        pos = 0
        while pos < len(data) - 4:
            pos = data.find(b'stsz', pos)
            if pos == -1:
                break
            stsz_positions.append(pos)
            pos += 1

        if stsz_positions:
            stsz_offset = stsz_positions[-1]
            sample_count_off = stsz_offset + 16
            current_count = struct.unpack('>I', data[sample_count_off:sample_count_off+4])[0]
            new_count = current_count * 10
            data[sample_count_off:sample_count_off+4] = struct.pack('>I', new_count)
            print(f"✅ STSZ: count {current_count:,} -> {new_count:,}")

            # 4. MVHD: zero dates + inflate duration x10
            moov = data.find(b'moov')
            if moov != -1:
                mvhd = data.find(b'mvhd', moov)
                if mvhd != -1:
                    data[mvhd+12:mvhd+16] = b'\x00\x00\x00\x00'
                    data[mvhd+16:mvhd+20] = b'\x00\x00\x00\x00'
                    dur_off = mvhd + 24
                    current_dur = struct.unpack('>I', data[dur_off:dur_off+4])[0]
                    new_dur = current_dur * 10
                    data[dur_off:dur_off+4] = struct.pack('>I', new_dur)
                    print(f"✅ MVHD: dates zeroed, duration {current_dur} -> {new_dur}")

        # 5. MDHD: set ALL track languages to 'und'
        search_start = 0
        mdhd_count = 0
        while True:
            mdhd = data.find(b'mdhd', search_start)
            if mdhd == -1:
                break
            data[mdhd+28:mdhd+30] = struct.pack('>H', 0x51A3)
            mdhd_count += 1
            search_start = mdhd + 1
        if mdhd_count:
            print(f"✅ MDHD: language -> 'und' in {mdhd_count} track(s)")

        f.seek(0)
        f.write(data)
        f.truncate()

    print(f"\n🎉 Done! Patched video saved to: {output_path}")
    print("📤 Upload from PC browser with 'Allow high-quality uploads' ON.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python patcher.py <input_video.mp4> [output_video.mp4]")
        print("Example: python patcher.py my_video.mp4 my_video_patched.mp4")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "patched_akila.mp4"
    patch_video(input_file, output_file, custom_tag="@akila")
