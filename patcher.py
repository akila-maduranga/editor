import subprocess
import os
import struct
import sys

def patch_video(input_path, output_path, custom_tag="@akila"):
    """
    Patches an MP4 video to bypass TikTok compression by:
    1. Remuxing with FFmpeg (no re-encode).
    2. Changing container brand to 'isom'.
    3. Injecting custom metadata.
    4. Slightly corrupting the 'mdat' atom size to trigger a parser fallback.
    """
    
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        return

    temp_path = "temp_remuxed_akila.mp4"

    # ---------------------------------------------------------------------
    # STEP 1: FFmpeg Remux - Strip old metadata, inject new ones
    # ---------------------------------------------------------------------
    # -c copy               : No re-encoding (preserves bitrate/fps)
    # -map_metadata -1      : Remove all existing metadata (zeros out dates)
    # -brand isom           : Set major brand to ISO Base Media (generic)
    # -compatible_brands    : Set compatible brands to match TikTok's preferences
    # -metadata ...         : Inject our custom tags
    # NOTE: Do NOT use +faststart. moov must stay at end of file for
    #       the mdat corruption to produce "invalid atom size".
    # ---------------------------------------------------------------------
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-c", "copy",
        "-map_metadata", "-1",
        "-brand", "isom",
        "-compatible_brands", "isomiso2avc1mp41",
        "-metadata", f"comment=Patched by {custom_tag} - 120fps Optimized",
        "-metadata", "encoder=Lavf60.16.100",
        "-metadata", f"title=fixed_by_{custom_tag.replace('@', '')}",
        "-metadata:s:a:0", "language=und",
        temp_path
    ]

    print("🔧 Running FFmpeg remux...")
    print(f"Command: {' '.join(cmd)}\n")
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e.stderr}")
        return

    # ---------------------------------------------------------------------
    # STEP 2: Binary Patches - Inflate stsz frame count + corrupt mdat size
    # ---------------------------------------------------------------------
    # The real exploit: inflating stsz sample count 10x tricks TikTok's
    # encoder into seeing ~1200 fps, hitting a safety threshold that skips
    # re-encoding. The mdat +1 creates a secondary "invalid atom size" flag.
    # ---------------------------------------------------------------------
    with open(temp_path, 'rb') as f:
        data = bytearray(f.read())

    # --- 2a. Inflate ALL stsz sample counts 10x ---
    stsz_patched = 0
    search_start = 0
    while True:
        stsz_offset = data.find(b'stsz', search_start)
        if stsz_offset == -1:
            break
        sample_count_off = stsz_offset + 16
        current_count = struct.unpack('>I', data[sample_count_off:sample_count_off+4])[0]
        new_count = current_count * 10
        struct.pack_into('>I', data, sample_count_off, new_count)
        print(f"✅ Found 'stsz' at offset {stsz_offset}, count: {current_count} -> {new_count}")
        stsz_patched += 1
        search_start = stsz_offset + 4
    if stsz_patched == 0:
        print("⚠️  Warning: Could not find any 'stsz' atom.")
    else:
        print(f"💪 Patched {stsz_patched} stsz atom(s)")

    # --- 2b. Corrupt mdat declared size (+1 byte) ---
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

    if mdat_offset != -1:
        new_size = mdat_size + 1
        struct.pack_into('>I', data, mdat_offset, new_size)
        print(f"✅ Corrupted 'mdat' at offset {mdat_offset}, size: {mdat_size} -> {new_size}")
    else:
        print("⚠️  Warning: Could not find 'mdat' atom.")

    # Write the patched binary to the final output
    with open(output_path, 'wb') as f:
        f.write(data)
    print(f"💾 Binary patches applied successfully!")

    # Clean up temporary file
    if os.path.exists(temp_path) and temp_path != output_path:
        os.remove(temp_path)

    print(f"\n🎉 Done! Patched video saved to: {output_path}")
    print(f"🏷️  Custom tag '{custom_tag}' injected into metadata.")

# ---------------------------------------------------------------------
# RUN THE SCRIPT
# ---------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python akila_patcher.py <input_video.mp4> [output_video.mp4]")
        print("Example: python akila_patcher.py my_video.mp4 my_video_patched.mp4")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "patched_akila.mp4"
    
    patch_video(input_file, output_file, custom_tag="@akila")