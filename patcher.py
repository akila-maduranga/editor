import os
import struct
import sys
import subprocess

def patch_video(input_path, output_path, custom_tag="@akila", encode_1080p=False):
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
        "-video_track_timescale", "12000",
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
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ FFmpeg failed:\n{result.stderr[:500]}")
        return
    print("✅ FFmpeg remux complete")

    # ------------------------------------------------------------------
    # Stage 2: Binary overlay patches (all scoped to correct boundaries)
    # ------------------------------------------------------------------
    with open(output_path, 'r+b') as f:
        data = bytearray(f.read())
        file_size = len(data)

        print(f"📁 File size: {file_size:,} bytes")
        print("🔍 Applying binary overlay patches...")

        # Locate moov boundaries once
        moov = data.find(b'moov')
        moov_end = file_size
        if moov != -1 and moov >= 4:
            moov_size = struct.unpack('>I', data[moov-4:moov])[0]
            moov_end = moov - 4 + moov_size

        # 1. FTYP
        ftyp = data.find(b'ftyp')
        if ftyp != -1:
            data[ftyp+4:ftyp+8] = b'isom'
            ftyp_box_size = struct.unpack('>I', data[ftyp-4:ftyp])[0]
            if ftyp_box_size > 16:
                data[ftyp+12:ftyp+16] = b'isom'
            print("✅ FTYP: major -> 'isom', compatible -> 'isom'")

        # 2. MDAT: corrupt TYPE field (reference approach — preserves box boundaries)
        mdat = data.find(b'mdat', moov_end)
        if mdat >= 4:
            current_val = struct.unpack('>I', data[mdat:mdat+4])[0]
            data[mdat:mdat+4] = struct.pack('>I', current_val + 1)
            print(f"✅ MDAT type corrupted: 0x{current_val:08X} -> 0x{current_val+1:08X}")

        # 3. STSZ: last occurrence within moov x10
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

            # 4. MVHD (within moov slice)
            if moov != -1:
                moov_region = data[moov:moov_end]
                mvhd_rel = moov_region.find(b'mvhd')
                if mvhd_rel != -1:
                    mvhd = moov + mvhd_rel
                    data[mvhd+12:mvhd+16] = b'\x00\x00\x00\x00'
                    data[mvhd+16:mvhd+20] = b'\x00\x00\x00\x00'
                    dur_off = mvhd + 24
                    cur_dur = struct.unpack('>I', data[dur_off:dur_off+4])[0]
                    data[dur_off:dur_off+4] = struct.pack('>I', cur_dur * 10)
                    print(f"✅ MVHD: dates zeroed, duration {cur_dur} -> {cur_dur*10}")

        # 5. MDHD: scope search to within moov only
        if moov != -1 and moov >= 4:
            moov_data = data[moov:moov_end]
            mdhd_count = 0
            search_pos = 0
            while True:
                mdhd = moov_data.find(b'mdhd', search_pos)
                if mdhd == -1:
                    break
                abs_mdhd = moov + mdhd
                data[abs_mdhd+28:abs_mdhd+30] = struct.pack('>H', 0x51A3)
                mdhd_count += 1
                search_pos = mdhd + 1
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
