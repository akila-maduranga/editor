import os
import struct
import logging
import subprocess

logger = logging.getLogger("tiktok_patcher")

def patch_video(input_path: str, output_path: str, custom_tag: str = "@akila", encode_1080p: bool = False) -> tuple[bool, str]:
    """
    Two-stage patching:
      1) FFmpeg re-encode with exploit-friendly settings.
      2) Binary overlay patches: STSZ x10, MDAT size +1, MVHD duration x10, MDHD language.
    """
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

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
        ffmpeg_cmd.insert(ffmpeg_cmd.index("-c:v") + 1,
            "scale='min(1920,iw)':min(1920,ih):force_original_aspect_ratio=decrease")

    ffmpeg_cmd.append(output_path)

    logger.info(f"Running FFmpeg: {' '.join(ffmpeg_cmd)}")
    try:
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error(f"FFmpeg failed:\n{result.stderr}")
            if os.path.exists(output_path):
                os.remove(output_path)
            return False, f"FFmpeg failed: {result.stderr[:500]}"
        logger.info("FFmpeg remux complete")
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, "FFmpeg timed out after 10 minutes"
    except FileNotFoundError:
        return False, "FFmpeg not found on the server"

    # ------------------------------------------------------------------
    # Stage 2: Binary overlay patches
    # ------------------------------------------------------------------
    try:
        with open(output_path, 'r+b') as f:
            data = bytearray(f.read())
            file_size = len(data)

            logger.info(f"Binary patching: {file_size:,} bytes")

            # --- 1. FTYP safety net ---
            ftyp = data.find(b'ftyp')
            if ftyp != -1:
                data[ftyp+4:ftyp+8] = b'isom'
                ftyp_box_size = struct.unpack('>I', data[ftyp-4:ftyp])[0]
                if ftyp_box_size > 16:
                    data[ftyp+12:ftyp+16] = b'isom'
                logger.info("FTYP verified: major -> 'isom', compatible -> 'isom'")

            # --- 2. MDAT SIZE +1 (safe with faststart — extends into EOF) ---
            mdat = data.find(b'mdat')
            if mdat >= 4:
                current_size = struct.unpack('>I', data[mdat-4:mdat])[0]
                new_size = current_size + 1
                struct.pack_into('>I', data, mdat-4, new_size)
                logger.info(f"MDAT size: {current_size:,} -> {new_size:,}")

            # --- 3. STSZ: patch LAST occurrence (video track) x10 ---
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
                struct.pack_into('>I', data, sample_count_off, new_count)
                logger.info(f"STSZ: count {current_count:,} -> {new_count:,}")

                # --- 4. MVHD: zero dates + inflate duration x10 ---
                moov = data.find(b'moov')
                if moov != -1:
                    mvhd = data.find(b'mvhd', moov)
                    if mvhd != -1:
                        struct.pack_into('>I', data, mvhd + 12, 0)
                        struct.pack_into('>I', data, mvhd + 16, 0)
                        dur_off = mvhd + 24
                        current_dur = struct.unpack('>I', data[dur_off:dur_off+4])[0]
                        new_dur = current_dur * 10
                        struct.pack_into('>I', data, dur_off, new_dur)
                        logger.info(f"MVHD: dates zeroed, duration {current_dur} -> {new_dur}")

            # --- 5. MDHD: set ALL track languages to 'und' ---
            search_start = 0
            mdhd_count = 0
            while True:
                mdhd = data.find(b'mdhd', search_start)
                if mdhd == -1:
                    break
                struct.pack_into('>H', data, mdhd + 28, 0x51A3)
                mdhd_count += 1
                search_start = mdhd + 1
            if mdhd_count:
                logger.info(f"MDHD: language -> 'und' in {mdhd_count} track(s)")

            f.seek(0)
            f.write(data)
            f.truncate()

        logger.info("Binary overlay patches applied")
        return True, "Video patched successfully!"

    except Exception as e:
        logger.error(f"Binary patching error: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, f"Patch failed: {str(e)}"
