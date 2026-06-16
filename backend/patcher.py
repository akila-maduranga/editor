import subprocess
import os
import struct
import logging
import json

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
    Patches an MP4 video to bypass TikTok compression by:
    1. Remuxing (or encoding) with FFmpeg.
    2. Changing container brand to 'isom'.
    3. Injecting custom metadata.
    4. Slightly corrupting the 'mdat' atom size to trigger a parser fallback.
    
    Returns (success, message).
    """
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

    # Use a unique temp path to prevent race conditions/collisions during concurrent requests
    temp_path = f"{output_path}.temp.mp4"

    # ---------------------------------------------------------------------
    # STEP 1: FFmpeg Remux / Encode - Strip old metadata, inject new ones
    # ---------------------------------------------------------------------
    cmd = [
        "ffmpeg",
        "-y",                   # Overwrite output file if it exists
        "-i", input_path
    ]

    needs_encoding = False
    if encode_1080p:
        info = get_video_info(input_path)
        width = int(info.get("width", 0))
        height = int(info.get("height", 0))
        
        # Check if height or width exceeds 1080p bounds
        if max(width, height) > 1920 or min(width, height) > 1080:
            needs_encoding = True
            logger.info(f"Video resolution {width}x{height} exceeds 1080p. Downscaling...")
            
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-vf", "scale='min(1920,iw)':min'(1080,ih)':force_original_aspect_ratio=decrease",
                "-c:a", "copy"
            ])
            
            # Try to cap bitrate if known
            bitrate = info.get("bit_rate")
            if bitrate:
                # Add 10% buffer
                maxrate = int(int(bitrate) * 1.1)
                cmd.extend(["-maxrate", str(maxrate), "-bufsize", str(maxrate * 2)])
        else:
            logger.info(f"Video resolution {width}x{height} is 1080p or below. Copying stream...")
            cmd.extend(["-c", "copy"])
    else:
        cmd.extend(["-c", "copy"])

    cmd.extend([
        "-map_metadata", "-1",
        "-brand", "isom",
        "-compatible_brands", "isomiso2avc1mp41",
        "-metadata", f"comment=Patched by {custom_tag} - 120fps Optimized",
        "-metadata", "encoder=Lavf60.16.100",
        "-metadata", f"title=fixed_by_{custom_tag.replace('@', '')}",
        "-metadata:s:a:0", "language=und",   # Set audio language to 'und' (undefined)
        "-movflags", "+faststart",
        temp_path
    ])

    logger.info("🔧 Running FFmpeg remux...")
    logger.info(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr or e.stdout or "Unknown FFmpeg error"
        logger.error(f"FFmpeg error: {err_msg}")
        # Clean up if temp_path was somehow created
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False, f"FFmpeg error: {err_msg}"

    # ---------------------------------------------------------------------
    # STEP 2: Binary Patch - Corrupt 'mdat' atom size to trigger invalid trailer
    # ---------------------------------------------------------------------
    try:
        with open(temp_path, 'rb') as f:
            data = bytearray(f.read())
    except Exception as e:
        logger.error(f"Failed to read temp file: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False, f"Failed to read intermediate file: {str(e)}"

    # Parse top-level atoms to find 'mdat'
    index = 0
    mdat_offset = -1
    mdat_size = 0

    while index < len(data) - 8:
        try:
            atom_size = struct.unpack('>I', data[index:index+4])[0]
            atom_type = data[index+4:index+8].decode('ascii', errors='ignore')
        except Exception as e:
            logger.warning(f"Error unpacking atom header at index {index}: {e}")
            break
        
        if atom_type == 'mdat':
            mdat_offset = index
            mdat_size = atom_size
            break
        
        # Safety: if size is less than 8, we can't advance properly
        if atom_size < 8:
            break
        
        index += atom_size
        if index >= len(data):
            break

    try:
        if mdat_offset == -1:
            logger.warning("⚠️  Warning: Could not find 'mdat' atom. Skipping binary patch.")
            # Still copy the temp file to output
            os.rename(temp_path, output_path)
            message = "FFmpeg remux successful, but mdat atom not found. Binary patch skipped."
        else:
            # Increase the declared size by exactly 1 byte
            new_size = mdat_size + 1
            logger.info(f"✅ Found 'mdat' at offset {mdat_offset}")
            logger.info(f"   Old declared size: {mdat_size} bytes")
            logger.info(f"   New declared size: {new_size} bytes (injected invalid trailer)")

            struct.pack_into('>I', data, mdat_offset, new_size)

            # Write the patched binary to the final output
            with open(output_path, 'wb') as f:
                f.write(data)
            logger.info("💾 Binary patch applied successfully!")
            message = "Video remuxed and metadata binary patched successfully!"
    except Exception as e:
        logger.error(f"Error writing patched video: {e}")
        return False, f"Failed to apply binary patch: {str(e)}"
    finally:
        # Clean up temporary file
        if os.path.exists(temp_path) and temp_path != output_path:
            try:
                os.remove(temp_path)
            except Exception as e:
                logger.warning(f"Failed to remove temp file {temp_path}: {e}")

    return True, message
