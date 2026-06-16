import os
import subprocess
import logging

logger = logging.getLogger("tiktok_patcher")

def patch_video(input_path: str, output_path: str, custom_tag: str = "@akila", encode_1080p: bool = False) -> tuple[bool, str]:
    """
    Timescale spoof via FFmpeg stream copy — no binary patches.
    """
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

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
        return True, "Video patched successfully!"
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, "FFmpeg timed out after 5 minutes"
    except FileNotFoundError:
        return False, "FFmpeg not found on the server"
    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, f"Patch failed: {str(e)}"
