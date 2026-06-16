import os
import sys
import subprocess
import time
import struct

CONTAINERS = [b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts']

def read_atoms(data, offset, end_pos):
    atoms = []
    while offset < end_pos:
        if offset + 8 > len(data):
            break
        size = int.from_bytes(data[offset:offset+4], 'big')
        name = bytes(data[offset+4:offset+8])
        if size == 1:
            size = int.from_bytes(data[offset+8:offset+16], 'big')
            header_size = 16
        else:
            header_size = 8
        if name in CONTAINERS:
            children, _ = read_atoms(data, offset + header_size, offset + size)
            atoms.append({'name': name, 'children': children})
        else:
            atoms.append({'name': name, 'data': bytes(data[offset+header_size:offset+size])})
        offset += size
    return atoms, offset

def write_atoms(atoms):
    result = bytearray()
    for atom in atoms:
        if 'children' in atom:
            child_data = write_atoms(atom['children'])
            size = 8 + len(child_data)
            result.extend(size.to_bytes(4, 'big'))
            result.extend(atom['name'])
            result.extend(child_data)
        else:
            size = 8 + len(atom['data'])
            result.extend(size.to_bytes(4, 'big'))
            result.extend(atom['name'])
            result.extend(atom['data'])
    return bytes(result)

def find_atom(atoms, path):
    if not path:
        return atoms
    for atom in atoms:
        if atom['name'] == path[0]:
            if len(path) == 1:
                return atom
            if 'children' in atom:
                res = find_atom(atom['children'], path[1:])
                if res:
                    return res
    return None

def inject_fake_frames(data, target_frames=25570):
    tree, _ = read_atoms(data, 0, len(data))
    moov = find_atom(tree, [b'moov'])
    if not moov:
        print("[-] moov not found")
        return None

    video_trak = None
    for atom in moov['children']:
        if atom['name'] == b'trak':
            hdlr = find_atom([atom], [b'trak', b'mdia', b'hdlr'])
            if hdlr and b'vide' in hdlr['data']:
                video_trak = atom
                break
    if not video_trak:
        print("[-] Video track not found")
        return None

    stbl = find_atom([video_trak], [b'trak', b'mdia', b'minf', b'stbl'])
    if not stbl:
        print("[-] stbl not found")
        return None

    stsz = find_atom(stbl['children'], [b'stsz'])
    if not stsz:
        print("[-] stsz not found")
        return None

    stsz_data = bytearray(stsz['data'])
    orig_count = int.from_bytes(stsz_data[8:12], 'big')
    diff = target_frames - orig_count
    if diff <= 0:
        print(f"[*] Already {orig_count} frames")
        return write_atoms(tree)

    print(f"[*] STSZ: {orig_count} -> {target_frames}")
    stsz_data[8:12] = target_frames.to_bytes(4, 'big')
    stsz_data.extend(b'\x00\x00\x00\x00' * diff)
    stsz['data'] = bytes(stsz_data)

    stts = find_atom(stbl['children'], [b'stts'])
    if stts:
        stts_data = bytearray(stts['data'])
        entry_count = int.from_bytes(stts_data[8:12], 'big')
        stts_data[8:12] = (entry_count + diff).to_bytes(4, 'big')
        stts['data'] = bytes(stts_data)
        print(f"[*] STTS: entries {entry_count} -> {entry_count + diff}")

    shift = diff * 4
    print(f"[*] Shifting chunk offsets by +{shift}")
    for trak in moov['children']:
        if trak['name'] == b'trak':
            t_stbl = find_atom([trak], [b'trak', b'mdia', b'minf', b'stbl'])
            if not t_stbl:
                continue
            for child in list(t_stbl['children']):
                if child['name'] == b'stco':
                    d = bytearray(child['data'])
                    n = int.from_bytes(d[4:8], 'big')
                    for i in range(n):
                        idx = 8 + i * 4
                        v = int.from_bytes(d[idx:idx+4], 'big')
                        d[idx:idx+4] = (v + shift).to_bytes(4, 'big')
                    child['data'] = bytes(d)
                elif child['name'] == b'co64':
                    d = bytearray(child['data'])
                    n = int.from_bytes(d[4:8], 'big')
                    for i in range(n):
                        idx = 8 + i * 8
                        v = int.from_bytes(d[idx:idx+8], 'big')
                        d[idx:idx+8] = (v + shift).to_bytes(8, 'big')
                    child['data'] = bytes(d)

    result = write_atoms(tree)

    # MDAT size +1
    mdat_pos = result.find(b'mdat')
    if mdat_pos >= 4:
        cur = int.from_bytes(result[mdat_pos-4:mdat_pos], 'big')
        result = bytearray(result)
        result[mdat_pos-4:mdat_pos] = (cur + 1).to_bytes(4, 'big')
        result = bytes(result)
        print(f"[*] MDAT size: {cur} -> {cur+1}")

    return result


def patch_video(input_path, output_path, custom_tag="@akila", encode_1080p=False):
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        return

    # Stage 1: FFmpeg clean remux
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", input_path,
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

    print("🚀 FFmpeg remux...")
    start = time.time()
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ FFmpeg failed:\n{result.stderr[:500]}")
        return
    print(f"✅ FFmpeg done ({time.time()-start:.2f}s)")

    # Stage 2: stsz injector
    with open(output_path, 'rb') as f:
        data = f.read()
    patched = inject_fake_frames(data, target_frames=25570)
    if patched is None:
        print("❌ Injection failed")
        return
    with open(output_path, 'wb') as f:
        f.write(patched)
    print(f"🎉 Done! Output: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python patcher.py <input.mp4> [output.mp4]")
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "bypassed_output.mp4"
    patch_video(inp, out)
