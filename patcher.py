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
    # -movflags +faststart  : Move 'moov' atom to the front (like your patched file)
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
        "-metadata", "title=fixed_by_{custom_tag.replace('@', '')}",
        "-metadata:s:a:0", "language=und",   # Set audio language to 'und' (undefined)
        "-movflags", "+faststart",
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
    # STEP 2: Binary Patch - Corrupt 'mdat' atom size to trigger invalid trailer
    # ---------------------------------------------------------------------
    # The patched file had: "Warning: Unknown trailer with invalid atom size"
    # We replicate this by increasing the declared 'mdat' size by 1 byte.
    # Media players ignore this and read until EOF, but TikTok's parser
    # gets confused and skips re-encoding.
    # ---------------------------------------------------------------------
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
        
        # Safety: if size is 0 or 1, we can't advance properly
        if atom_size < 8:
            break
        
        index += atom_size
        if index >= len(data):
            break

    if mdat_offset == -1:
        print("⚠️  Warning: Could not find 'mdat' atom. Skipping binary patch.")
        # Still copy the temp file to output
        os.rename(temp_path, output_path)
    else:
        # Increase the declared size by exactly 1 byte
        new_size = mdat_size + 1
        print(f"✅ Found 'mdat' at offset {mdat_offset}")
        print(f"   Old declared size: {mdat_size} bytes")
        print(f"   New declared size: {new_size} bytes (injected invalid trailer)")

        struct.pack_into('>I', data, mdat_offset, new_size)

        # Write the patched binary to the final output
        with open(output_path, 'wb') as f:
            f.write(data)
        print(f"💾 Binary patch applied successfully!")

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