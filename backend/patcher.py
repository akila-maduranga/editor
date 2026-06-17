import os
import sys
import logging
import subprocess

logger = logging.getLogger("tiktok_patcher")

CONTAINERS = [b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts']


def read_atoms_in_range(data, offset, end_pos):
    atoms = []
    while offset + 8 <= end_pos and offset + 8 <= len(data):
        size = int.from_bytes(data[offset:offset+4], 'big')
        if size == 0:
            break
        if size == 1:
            size = int.from_bytes(data[offset+8:offset+16], 'big')
            header_size = 16
        else:
            header_size = 8
        atom_end = offset + size
        if atom_end > end_pos:
            atom_end = end_pos
        name = bytes(data[offset+4:offset+8])
        if name in CONTAINERS:
            children, _ = read_atoms_in_range(data, offset + header_size, atom_end)
            atoms.append({'name': name, 'children': children, 'start': offset, 'size': size})
        else:
            atoms.append({'name': name, 'data': bytes(data[offset+header_size:atom_end]),
                          'start': offset, 'size': size})
        offset = atom_end
    return atoms, offset


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
    # Find moov position via byte search (preserves everything outside moov)
    moov_pos = data.find(b'moov')
    if moov_pos < 4:
        raise ValueError("moov not found")
    moov_size_pos = moov_pos - 4
    moov_size = int.from_bytes(data[moov_size_pos:moov_size_pos+4], 'big')

    # Parse only within moov (content starts after the 4-byte type field)
    tree, _ = read_atoms_in_range(data, moov_pos + 4, moov_pos + moov_size)

    # Find video track stbl
    video_trak = None
    for atom in tree:
        if atom['name'] == b'trak':
            hdlr = find_atom(atom['children'], [b'mdia', b'hdlr'])
            if hdlr and b'vide' in hdlr['data']:
                video_trak = atom
                break
    if not video_trak:
        raise ValueError("video track not found")

    stbl = find_atom(video_trak['children'], [b'mdia', b'minf', b'stbl'])
    if not stbl:
        raise ValueError("stbl not found")

    stsz = find_atom(stbl['children'], [b'stsz'])
    if not stsz:
        raise ValueError("stsz not found")

    stsz_data = bytearray(stsz['data'])
    orig_count = int.from_bytes(stsz_data[8:12], 'big')
    diff = target_frames - orig_count

    if diff <= 0:
        logger.info(f"Already has {orig_count} frames, no inflation needed")
        return data

    logger.info(f"STSZ: inflating {orig_count} -> {target_frames}")
    new_entries = b'\x00\x00\x00\x00' * diff

    # Build the new moov byte-for-byte by walking the moov subtree
    # replacing stsz and stts data in-place
    result = bytearray(data)

    # 1. Replace stsz: overwrite count + insert dummy entries
    stsz_start_in_file = stsz['start']
    old_stsz_data_len = len(stsz['data'])
    stsz_data[8:12] = target_frames.to_bytes(4, 'big')
    new_stsz_data = bytes(stsz_data) + new_entries
    growth = len(new_stsz_data) - old_stsz_data_len

    result[stsz_start_in_file + 8:stsz_start_in_file + 8 + old_stsz_data_len] = new_stsz_data

    # 2. Update stts entry count
    stts = find_atom(stbl['children'], [b'stts'])
    if stts:
        stts_start = stts['start']
        old_stts_data_len = len(stts['data'])
        stts_data = bytearray(stts['data'])
        entry_count = int.from_bytes(stts_data[8:12], 'big')
        stts_data[8:12] = (entry_count + diff).to_bytes(4, 'big')
        # stts size doesn't change (only 4-byte count field updated, no new entries)
        result[stts_start + 8:stts_start + 8 + old_stts_data_len] = bytes(stts_data)
        logger.info(f"STTS: entry count {entry_count} -> {entry_count + diff}")

    # 3. Update moov size in header
    new_moov_size = moov_size + growth
    result[moov_size_pos:moov_size_pos+4] = new_moov_size.to_bytes(4, 'big')

    # 4. The growth happened inside moov (stsz data region). Since moov is at
    #    the end (no faststart), growing moov just extends the file.
    #    All chunk offsets (stco/co64) point into mdat which is BEFORE moov,
    #    so they remain correct.
    return bytes(result)


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

    # Stage 2: stsz injector (in-place byte patching within moov only)
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
