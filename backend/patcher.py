import os
import struct
import logging
import subprocess

logger = logging.getLogger("tiktok_patcher")

def patch_video(input_path: str, output_path: str, custom_tag: str = "@akila", encode_1080p: bool = False) -> tuple[bool, str]:
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

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
    # Stage 2: Binary overlay patches (all scoped to correct atom boundaries)
    # ------------------------------------------------------------------
    try:
        with open(output_path, 'r+b') as f:
            data = bytearray(f.read())
            file_size = len(data)
            logger.info(f"Binary patching: {file_size:,} bytes")

            # Locate moov boundaries once; all moov-internal searches use this.
            moov = data.find(b'moov')
            moov_end = file_size
            if moov != -1 and moov >= 4:
                moov_size = struct.unpack('>I', data[moov-4:moov])[0]
                moov_end = moov - 4 + moov_size

            # --- 1. FTYP ---
            ftyp = data.find(b'ftyp')
            if ftyp != -1:
                data[ftyp+4:ftyp+8] = b'isom'
                ftyp_box_size = struct.unpack('>I', data[ftyp-4:ftyp])[0]
                if ftyp_box_size > 16:
                    data[ftyp+12:ftyp+16] = b'isom'

            # --- 2. MDAT: corrupt TYPE field (original reference approach) ---
            # Search for mdat AFTER moov to skip any false "mdat" bytes inside moov.
            mdat = data.find(b'mdat', moov_end)
            if mdat >= 4:
                # Read the 4-byte TYPE as an integer, add 1, write back.
                # This corrupts the type (e.g. "mdat" -> "mdau") without changing box size,
                # so box boundaries remain intact — safe with any atom layout.
                current_val = struct.unpack('>I', data[mdat:mdat+4])[0]
                struct.pack_into('>I', data, mdat, current_val + 1)
                logger.info(f"MDAT type corrupted: 0x{current_val:08X} -> 0x{current_val+1:08X}")

            # --- 3. STSZ: last occurrence within moov, inflate sample count x10 ---
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

                # --- 4. MVHD ---
                if moov != -1:
                    moov_region = data[moov:moov_end]
                    mvhd_rel = moov_region.find(b'mvhd')
                    if mvhd_rel != -1:
                        mvhd = moov + mvhd_rel
                        struct.pack_into('>I', data, mvhd + 12, 0)
                        struct.pack_into('>I', data, mvhd + 16, 0)
                        dur_off = mvhd + 24
                        cur_dur = struct.unpack('>I', data[dur_off:dur_off+4])[0]
                        struct.pack_into('>I', data, dur_off, cur_dur * 10)
                        logger.info(f"MVHD: dates zeroed, duration {cur_dur} -> {cur_dur*10}")

            # --- 5. MDHD: scope search to within moov only ---
            if moov != -1 and moov >= 4:
                # Use a sub-bytearray of just the moov atom region
                moov_data = data[moov:moov_end]
                mdhd_count = 0
                search_pos = 0
                while True:
                    mdhd = moov_data.find(b'mdhd', search_pos)
                    if mdhd == -1:
                        break
                    abs_mdhd = moov + mdhd
                    struct.pack_into('>H', data, abs_mdhd + 28, 0x51A3)
                    mdhd_count += 1
                    search_pos = mdhd + 1
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
