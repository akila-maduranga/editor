import os
import sys
import logging
import subprocess

logger = logging.getLogger("tiktok_patcher")

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

def write_atoms(data, atoms):
    result = bytearray()
    for atom in atoms:
        if 'children' in atom:
            child_data = write_atoms(data, atom['children'])
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
        raise ValueError("moov atom not found")

    video_trak = None
    for atom in moov['children']:
        if atom['name'] == b'trak':
            hdlr = find_atom([atom], [b'trak', b'mdia', b'hdlr'])
            if hdlr and b'vide' in hdlr['data']:
                video_trak = atom
                break
    if not video_trak:
        raise ValueError("video track not found")

    stbl = find_atom([video_trak], [b'trak', b'mdia', b'minf', b'stbl'])
    if not stbl:
        raise ValueError("stbl not found in video track")

    stsz = find_atom(stbl['children'], [b'stsz'])
    if not stsz:
        raise ValueError("stsz not found")

    stsz_data = bytearray(stsz['data'])
    orig_count = int.from_bytes(stsz_data[8:12], 'big')
    diff = target_frames - orig_count
    if diff <= 0:
        logger.info(f"Already has {orig_count} frames, no inflation needed")
        result = write_atoms(data, tree)
    else:
        logger.info(f"STSZ: inflating {orig_count} -> {target_frames}")
        stsz_data[8:12] = target_frames.to_bytes(4, 'big')
        stsz_data.extend(b'\x00\x00\x00\x00' * diff)
        stsz['data'] = bytes(stsz_data)

        stts = find_atom(stbl['children'], [b'stts'])
        if stts:
            stts_data = bytearray(stts['data'])
            first_entry_count = int.from_bytes(stts_data[8:12], 'big')
            stts_data[8:12] = (first_entry_count + diff).to_bytes(4, 'big')
            stts['data'] = bytes(stts_data)
            logger.info(f"STTS: entry count {first_entry_count} -> {first_entry_count + diff}")

        result = write_atoms(data, tree)

    # Append invalid atom at the end (size=1, type='free') to trigger
    # "invalid atom size" warning instead of "truncated mdat"
    result += b'\x00\x00\x00\x07free'
    logger.info("Appended invalid trailer atom (size=7 free)")

    return result


def patch_video(input_path: str, output_path: str, custom_tag: str = "@akila", title: str = "", artist: str = "", copyright: str = "", encode_1080p: bool = False) -> tuple[bool, str]:
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

    # Stage 1: FFmpeg clean remux
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c", "copy",
        "-map_metadata", "-1",
        "-brand", "isom",
        "-video_track_timescale", "90000",
        "-bitexact",
        "-metadata", "encoder=Lavf60.16.100",
    ]
    if title:
        ffmpeg_cmd += ["-metadata", f"title={title}"]
    if artist:
        ffmpeg_cmd += ["-metadata", f"artist={artist}"]
    if copyright:
        ffmpeg_cmd += ["-metadata", f"copyright={copyright}"]
    ffmpeg_cmd += ["-metadata", f"comment={custom_tag}"]
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
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, "FFmpeg timed out"
    except FileNotFoundError:
        return False, "FFmpeg not found"

    # Stage 2: stsz injector (proper atom tree manipulation)
    try:
        with open(output_path, 'rb') as f:
            data = f.read()
        patched = inject_fake_frames(data, target_frames=25570)
        with open(output_path, 'wb') as f:
            f.write(patched)
        logger.info("STSZ injection complete")
        return True, "Video patched successfully!"
    except Exception as e:
        logger.error(f"Injection error: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, f"Patch failed: {str(e)}"
