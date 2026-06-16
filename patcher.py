import os
import struct
import sys
import shutil

def patch_video(input_path, output_path, custom_tag="@akila"):
    """
    Patches an MP4 video to bypass TikTok compression using pure binary patching.
    Preserves the original container structure.
    """
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        return

    shutil.copy2(input_path, output_path)

    with open(output_path, 'r+b') as f:
        data = bytearray(f.read())
        file_size = len(data)

        print(f"📁 File size: {file_size:,} bytes")
        print("🔍 Scanning for atoms...")

        # 1. FTYP: major brand + first compatible brand
        ftyp = data.find(b'ftyp')
        if ftyp != -1:
            # ftyp points to type string; ftyp-4=box start, ftyp+4=major_brand,
            # ftyp+8=minor_version, ftyp+12=first compatible_brand
            ftyp_box_size = struct.unpack('>I', data[ftyp-4:ftyp])[0]
            data[ftyp+4:ftyp+8] = b'isom'
            if ftyp_box_size > 16:
                data[ftyp+12:ftyp+16] = b'isom'
                print("✅ Patched FTYP: major brand -> 'isom', first compatible -> 'isom'")
            else:
                print("✅ Patched FTYP: major brand -> 'isom'")
        else:
            print("⚠️  FTYP not found")

        # 2. MDAT: corrupt the SIZE field (+1 byte)
        mdat = data.find(b'mdat')
        if mdat >= 4:
            current_size = struct.unpack('>I', data[mdat-4:mdat])[0]
            new_size = current_size + 1
            data[mdat-4:mdat] = struct.pack('>I', new_size)
            print(f"✅ Corrupted MDAT size at offset {mdat-4}: {current_size:,} -> {new_size:,}")
        else:
            print("⚠️  MDAT not found or at unsafe offset")

        # 3. STSZ: find ALL occurrences, patch the LAST one (video track) 10x
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

            data[sample_count_off:sample_count_off+4] = struct.pack('>I', new_count)
            print(f"   📊 STSZ at offset {stsz_offset}")
            print(f"   Current sample count: {current_count:,}")
            print(f"   New sample count: {new_count:,}")

            # 4. MVHD: inflate duration 10x + zero dates
            moov = data.find(b'moov')
            if moov != -1:
                mvhd = data.find(b'mvhd', moov)
                if mvhd != -1:
                    # Zero creation_time (mvhd + 12) and modification_time (mvhd + 16)
                    data[mvhd+12:mvhd+16] = b'\x00\x00\x00\x00'
                    data[mvhd+16:mvhd+20] = b'\x00\x00\x00\x00'
                    print("   ✅ Zeroed mvhd creation and modification dates")

                    # Inflate duration (mvhd + 24)
                    dur_off = mvhd + 24
                    current_dur = struct.unpack('>I', data[dur_off:dur_off+4])[0]
                    new_dur = current_dur * 10
                    data[dur_off:dur_off+4] = struct.pack('>I', new_dur)
                    print(f"   ✅ Updated mvhd duration: {current_dur} -> {new_dur}")

        else:
            print("⚠️  STSZ atom not found!")

        # 5. MDHD: set ALL track languages to 'und'
        mdhd_count = 0
        search_start = 0
        while True:
            mdhd = data.find(b'mdhd', search_start)
            if mdhd == -1:
                break
            data[mdhd+28:mdhd+30] = struct.pack('>H', 0x51A3)
            mdhd_count += 1
            search_start = mdhd + 1
        if mdhd_count:
            print(f"   ✅ Set language to 'und' in {mdhd_count} mdhd atom(s)")

        # Write back
        f.seek(0)
        f.write(data)
        f.truncate()

        print(f"\n🎉 Done! Patched video saved to: {output_path}")
        print("📤 Upload from PC browser with 'Allow high-quality uploads' ON.")

# ---------------------------------------------------------------------
# RUN THE SCRIPT
# ---------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python patcher.py <input_video.mp4> [output_video.mp4]")
        print("Example: python patcher.py my_video.mp4 my_video_patched.mp4")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "patched_akila.mp4"

    patch_video(input_file, output_file, custom_tag="@akila")
