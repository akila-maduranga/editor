import os
import struct
import logging
import shutil

logger = logging.getLogger("tiktok_patcher")

def patch_video(input_path: str, output_path: str, custom_tag: str = "@akila", encode_1080p: bool = False) -> tuple[bool, str]:
    """
    Patches an MP4 video to bypass TikTok compression using pure binary patching.
    Preserves the original container structure (no FFmpeg remux).
    """
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

    # Copy input to output (preserves original atom layout)
    shutil.copy2(input_path, output_path)

    try:
        with open(output_path, 'r+b') as f:
            data = bytearray(f.read())
            file_size = len(data)

            logger.info(f"File size: {file_size:,} bytes, scanning for atoms...")

            # --- 1. Patch FTYP major brand to 'isom' ---
            ftyp = data.find(b'ftyp')
            if ftyp != -1:
                data[ftyp+4:ftyp+8] = b'isom'
                logger.info("Patched FTYP major brand to 'isom'")
            else:
                logger.warning("FTYP atom not found")

            # --- 2. Corrupt MDAT declared size (+1 byte) ---
            mdat = data.find(b'mdat')
            if mdat != -1:
                current_size = struct.unpack('>I', data[mdat:mdat+4])[0]
                new_size = current_size + 1
                data[mdat:mdat+4] = struct.pack('>I', new_size)
                logger.info(f"Corrupted MDAT at offset {mdat}, size: {current_size:,} -> {new_size:,}")
            else:
                logger.warning("MDAT atom not found")

            # --- 3. Find ALL stsz atoms, patch the LAST one (usually video track) ---
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
                logger.info(f"Patched STSZ at offset {stsz_offset}, count: {current_count:,} -> {new_count:,}")

                # --- 4. Also inflate mvhd duration 10x ---
                moov = data.find(b'moov')
                if moov != -1:
                    mvhd = data.find(b'mvhd', moov)
                    if mvhd != -1:
                        dur_off = mvhd + 24
                        current_dur = struct.unpack('>I', data[dur_off:dur_off+4])[0]
                        new_dur = current_dur * 10
                        struct.pack_into('>I', data, dur_off, new_dur)
                        logger.info(f"Updated mvhd duration: {current_dur} -> {new_dur}")
            else:
                logger.warning("STSZ atom not found!")

            # Write patched data back
            f.seek(0)
            f.write(data)
            f.truncate()

        logger.info("Binary patches applied successfully!")
        return True, "Video patched successfully!"

    except Exception as e:
        logger.error(f"Error during patching: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, f"Patch failed: {str(e)}"
