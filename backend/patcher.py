import os
import struct
import logging
import subprocess

logger = logging.getLogger("tiktok_patcher")

def patch_video(input_path: str, output_path: str, custom_tag: str = "@akila", encode_1080p: bool = False) -> tuple[bool, str]:
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

    # ------------------------------------------------------------------
    # Stage 1: FFmpeg fast remux (clean base)
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

    logger.info(f"Running FFmpeg: {' '.join(ffmpeg_cmd)}")
    try:
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"FFmpeg failed:\n{result.stderr}")
            if os.path.exists(output_path):
                os.remove(output_path)
            return False, f"FFmpeg failed: {result.stderr[:500]}"
        logger.info("FFmpeg remux complete")
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, "FFmpeg timed out"
    except FileNotFoundError:
        return False, "FFmpeg not found"

    # ------------------------------------------------------------------
    # Stage 2: Targeted binary patches (scoped to correct atoms)
    # ------------------------------------------------------------------
    try:
        with open(output_path, 'r+b') as f:
            data = bytearray(f.read())

            # Locate moov boundaries
            moov = data.find(b'moov')
            moov_end = len(data)
            if moov != -1 and moov >= 4:
                moov_size = struct.unpack('>I', data[moov-4:moov])[0]
                moov_end = moov - 4 + moov_size

            # --- A. STSZ: inflate video sample count x10 (within moov only) ---
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
                struct.pack_into('>I', data, cnt_off, cur * 10)
                logger.info(f"STSZ: count {cur:,} -> {cur*10:,}")
            else:
                logger.warning("STSZ not found within moov")

            # --- B. MDAT: increment size by 1 (search after moov) ---
            mdat = data.find(b'mdat', moov_end if moov_end < len(data) else 0)
            if mdat >= 4:
                cur_size = struct.unpack('>I', data[mdat-4:mdat])[0]
                struct.pack_into('>I', data, mdat-4, cur_size + 1)
                logger.info(f"MDAT size: {cur_size:,} -> {cur_size+1:,}")

            f.seek(0)
            f.write(data)
            f.truncate()

        logger.info("Binary patches applied")
        return True, "Video patched successfully!"

    except Exception as e:
        logger.error(f"Binary patching error: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, f"Patch failed: {str(e)}"
