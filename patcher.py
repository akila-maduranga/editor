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

        # 1. Patch FTYP major brand to 'isom'
        ftyp = data.find(b'ftyp')
        if ftyp != -1:
            data[ftyp+4:ftyp+8] = b'isom'
            print("✅ Patched FTYP major brand to 'isom'")
        else:
            print("⚠️  FTYP not found")

        # 2. Corrupt MDAT declared size (+1 byte)
        mdat = data.find(b'mdat')
        if mdat != -1:
            current_size = struct.unpack('>I', data[mdat:mdat+4])[0]
            new_size = current_size + 1
            data[mdat:mdat+4] = struct.pack('>I', new_size)
            print(f"✅ Corrupted MDAT at offset {mdat}, size: {current_size:,} -> {new_size:,}")
        else:
            print("⚠️  MDAT not found")

        # 3. Find ALL stsz atoms, patch the LAST one (usually video track)
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

            # Verify
            verify_count = struct.unpack('>I', data[sample_count_off:sample_count_off+4])[0]
            if verify_count == new_count:
                print(f"   ✅ Verification: {verify_count:,} matches expected")
            else:
                print(f"   ❌ Verification failed!")

            # 4. Also inflate mvhd duration 10x
            moov = data.find(b'moov')
            if moov != -1:
                mvhd = data.find(b'mvhd', moov)
                if mvhd != -1:
                    dur_off = mvhd + 24
                    current_dur = struct.unpack('>I', data[dur_off:dur_off+4])[0]
                    new_dur = current_dur * 10
                    data[dur_off:dur_off+4] = struct.pack('>I', new_dur)
                    print(f"   ✅ Updated mvhd duration: {current_dur} -> {new_dur}")
        else:
            print("⚠️  STSZ atom not found!")

        # Write back
        f.seek(0)
        f.write(data)
        f.truncate()

        print(f"\n🎉 Done! Patched video saved to: {output_path}")

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
