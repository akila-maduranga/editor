import subprocess
import os
import struct
import logging
import json
import shutil
import mmap

logger = logging.getLogger("tiktok_patcher")

def get_video_info(input_path: str) -> dict:
    """Uses ffprobe to get video stream details."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,bit_rate",
        "-of", "json",
        input_path
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)
        if data.get("streams"):
            return data["streams"][0]
    except Exception as e:
        logger.warning(f"ffprobe failed: {e}")
    return {}

def patch_video(input_path: str, output_path: str, custom_tag: str = "@akila", encode_1080p: bool = False) -> tuple[bool, str]:
    """
    Patches an MP4 video to bypass TikTok compression.
    If encode_1080p is true and video exceeds 1080p, it uses FFmpeg to downscale.
    Otherwise, it avoids FFmpeg entirely and applies a pure binary patch to the MP4 atoms.
    """
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

    # Use a unique temp path to prevent race conditions during concurrent requests
    temp_path = f"{output_path}.temp.mp4"
    needs_encoding = False

    # ---------------------------------------------------------------------
    # OPTIONAL STEP: Downscale to 1080p using FFmpeg
    # ---------------------------------------------------------------------
    if encode_1080p:
        info = get_video_info(input_path)
        width = int(info.get("width", 0))
        height = int(info.get("height", 0))
        
        # Check if height or width exceeds 1080p bounds
        if max(width, height) > 1920 or min(width, height) > 1080:
            needs_encoding = True
            logger.info(f"Video resolution {width}x{height} exceeds 1080p. Downscaling...")
            
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-vf", "scale='min(1920,iw)':min'(1080,ih)':force_original_aspect_ratio=decrease",
                "-c:a", "copy"
            ]
            
            # Try to cap bitrate if known
            bitrate = info.get("bit_rate")
            if bitrate:
                maxrate = int(int(bitrate) * 1.1)
                cmd.extend(["-maxrate", str(maxrate), "-bufsize", str(maxrate * 2)])
                
            cmd.extend(["-movflags", "+faststart", temp_path])

            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                err_msg = e.stderr or e.stdout or "Unknown FFmpeg error"
                logger.error(f"FFmpeg error: {err_msg}")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return False, f"FFmpeg error: {err_msg}"
        else:
            logger.info(f"Video resolution {width}x{height} is 1080p or below. Skipping encode.")

    # If no encoding was needed or done, just copy the original file to temp
    if not needs_encoding:
        logger.info("Direct binary patch mode. Copying original file...")
        shutil.copy2(input_path, temp_path)

    # ---------------------------------------------------------------------
    # CRITICAL STEP: Pure Binary Patch (No FFmpeg Remux)
    # ---------------------------------------------------------------------
    logger.info("Applying binary atom patches...")
    try:
        with open(temp_path, 'r+b') as f:
            # Memory map the file to prevent OOM crashes on large files
            mm = mmap.mmap(f.fileno(), 0)
            
            # 1. PATCH FTYP
            ftyp_offset = mm.find(b'ftyp')
            if ftyp_offset != -1:
                mm[ftyp_offset+4:ftyp_offset+8] = b'isom'
                
            # 2. PATCH MVHD
            moov_offset = mm.find(b'moov')
            if moov_offset != -1:
                mvhd_offset = mm.find(b'mvhd', moov_offset)
                if mvhd_offset != -1:
                    creation_offset = mvhd_offset + 8
                    modification_offset = mvhd_offset + 12
                    mm[creation_offset:creation_offset+4] = b'\x00\x00\x00\x00'
                    mm[modification_offset:modification_offset+4] = b'\x00\x00\x00\x00'

            # 3. PATCH MDHD
            mdhd_offset = mm.find(b'mdhd')
            if mdhd_offset != -1:
                creation_off = mdhd_offset + 8
                mod_off = mdhd_offset + 12
                lang_off = mdhd_offset + 24
                mm[creation_off:creation_off+4] = b'\x00\x00\x00\x00'
                mm[mod_off:mod_off+4] = b'\x00\x00\x00\x00'
                mm[lang_off:lang_off+2] = struct.pack('>H', 0x51A3)

            # 4. PATCH STSZ (Inflate frame count x10)
            stsz_offset = mm.find(b'stsz')
            if stsz_offset != -1:
                sample_count_off = stsz_offset + 12
                current_count = struct.unpack('>I', mm[sample_count_off:sample_count_off+4])[0]
                new_count = current_count * 10
                if new_count > 4294967295:
                    new_count = 4294967295
                mm[sample_count_off:sample_count_off+4] = struct.pack('>I', new_count)

            # 5. PATCH MDAT
            mdat_offset = mm.find(b'mdat')
            if mdat_offset != -1:
                current_size = struct.unpack('>I', mm[mdat_offset-4:mdat_offset])[0]
                new_size = current_size + 1
                mm[mdat_offset-4:mdat_offset] = struct.pack('>I', new_size)

            mm.flush()
            mm.close()
            
        # Move the patched temp file to the final output destination
        if os.path.exists(output_path):
            os.remove(output_path)
        os.rename(temp_path, output_path)
        
        logger.info("Video binary patched successfully!")
        return True, "Video binary patched successfully!"
        
    except Exception as e:
        logger.error(f"Error during binary patching: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False, f"Binary patch failed: {str(e)}"
