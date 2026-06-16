import os
import struct
import logging
import shutil

logger = logging.getLogger("tiktok_patcher")

def patch_video(input_path: str, output_path: str, custom_tag: str = "@akila", encode_1080p: bool = False) -> tuple[bool, str]:
    """
    Patches an MP4 video to bypass TikTok compression using pure binary patching.
    Preserves the original container structure.
    """
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

    shutil.copy2(input_path, output_path)

    try:
        with open(output_path, 'r+b') as f:
            data = bytearray(f.read())
            file_size = len(data)

            logger.info(f"File size: {file_size:,} bytes, scanning for atoms...")

            # --- 1. FTYP: major brand + first compatible brand ---
            ftyp = data.find(b'ftyp')
            if ftyp != -1:
                # ftyp points to the type string ("ftyp"), so:
                # ftyp-4 = box start, ftyp+4 = major_brand, ftyp+8 = minor_version
                # ftyp+12 = first compatible_brand, etc.
                ftyp_box_size = struct.unpack('>I', data[ftyp-4:ftyp])[0]
                data[ftyp+4:ftyp+8] = b'isom'
                if ftyp_box_size > 16:
                    data[ftyp+12:ftyp+16] = b'isom'
                    logger.info("Patched FTYP: major brand -> 'isom', first compatible -> 'isom'")
                else:
                    logger.info("Patched FTYP: major brand -> 'isom' (no compatible brands to patch)")
            else:
                logger.warning("FTYP atom not found")

            # --- 2. MDAT: corrupt the SIZE field (+1 byte) ---
            mdat = data.find(b'mdat')
            if mdat >= 4:
                size_bytes = data[mdat-4:mdat]
                current_size = struct.unpack('>I', size_bytes)[0]
                new_size = current_size + 1
                struct.pack_into('>I', data, mdat-4, new_size)
                logger.info(f"Corrupted MDAT size at offset {mdat-4}: {current_size:,} -> {new_size:,}")
            else:
                logger.warning("MDAT atom not found or at unsafe offset")

            # --- 3. STSZ: find ALL occurrences, patch the LAST one (video track) 10x ---
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

                # --- 4. MVHD: inflate duration 10x + zero dates ---
                moov = data.find(b'moov')
                if moov != -1:
                    mvhd = data.find(b'mvhd', moov)
                    if mvhd != -1:
                        # Zero creation_time (mvhd + 12) and modification_time (mvhd + 16)
                        struct.pack_into('>I', data, mvhd + 12, 0)
                        struct.pack_into('>I', data, mvhd + 16, 0)
                        logger.info("Zeroed mvhd creation and modification dates")

                        # Inflate duration (mvhd + 24)
                        dur_off = mvhd + 24
                        current_dur = struct.unpack('>I', data[dur_off:dur_off+4])[0]
                        new_dur = current_dur * 10
                        struct.pack_into('>I', data, dur_off, new_dur)
                        logger.info(f"Updated mvhd duration: {current_dur} -> {new_dur}")

            else:
                logger.warning("STSZ atom not found!")

            # --- 5. MDHD: set ALL track languages to 'und' ---
            search_start = 0
            mdhd_count = 0
            while True:
                mdhd = data.find(b'mdhd', search_start)
                if mdhd == -1:
                    break
                # mdhd v0: language is at offset 28 (2 bytes)
                struct.pack_into('>H', data, mdhd + 28, 0x51A3)
                mdhd_count += 1
                search_start = mdhd + 1
            if mdhd_count:
                logger.info(f"Set language to 'und' in {mdhd_count} mdhd atom(s)")

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
