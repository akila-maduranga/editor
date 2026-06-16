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
    Patches an MP4 video to bypass TikTok compression using FFmpeg remuxing + binary patch.
    """
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

    temp_path = f"{output_path}.temp.mp4"

    # ---------------------------------------------------------------------
    # STEP 1: FFmpeg Remux - Strip old metadata, inject new ones
    # ---------------------------------------------------------------------
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c", "copy",
        "-map_metadata", "-1",
        "-brand", "isom",
        "-compatible_brands", "isomiso2avc1mp41",
        "-metadata", f"comment=Patched by {custom_tag} - 120fps Optimized",
        "-metadata", "encoder=Lavf60.16.100",
        "-metadata", f"title=fixed_by_{custom_tag.replace('@', '')}",
        "-metadata:s:a:0", "language=und",
        "-movflags", "+faststart",
        temp_path
    ]

    logger.info("Running FFmpeg remux...")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr or e.stdout or "Unknown FFmpeg error"
        logger.error(f"FFmpeg error: {err_msg}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False, f"FFmpeg error: {err_msg}"

    # ---------------------------------------------------------------------
    # STEP 2: Binary Patch - Corrupt 'mdat' atom size
    # ---------------------------------------------------------------------
    logger.info("Applying binary patch to mdat atom...")
    try:
        with open(temp_path, 'rb') as f:
            data = bytearray(f.read())

        # Parse top-level atoms to find 'mdat'
        index = 0
        mdat_offset = -1
        mdat_size = 0

        while index < len(data) - 8:
            atom_size = struct.unpack('>I', data[index:index+4])[0]
            atom_type = data[index+4:index+8].decode('ascii', errors='ignore')
            
            if atom_type == 'mdat':
                mdat_offset = index
                mdat_size = atom_size
                break
            
            if atom_size < 8:
                break
            
            index += atom_size
            if index >= len(data):
                break

        if mdat_offset == -1:
            logger.warning("Could not find 'mdat' atom. Skipping binary patch.")
            os.rename(temp_path, output_path)
        else:
            # Increase the declared size by exactly 1 byte
            new_size = mdat_size + 1
            logger.info(f"Found 'mdat' at offset {mdat_offset}, old size: {mdat_size}, new size: {new_size}")
            struct.pack_into('>I', data, mdat_offset, new_size)

            # Write the patched binary to the final output
            with open(output_path, 'wb') as f:
                f.write(data)
            
            # Clean up temp file
            os.remove(temp_path)
            logger.info("Binary patch applied successfully!")

        return True, "Video patched successfully!"
        
    except Exception as e:
        logger.error(f"Error during binary patching: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False, f"Binary patch failed: {str(e)}"
