import os
import sys
import logging
import subprocess

logger = logging.getLogger("tiktok_patcher")

CONTAINERS = [b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts', b'udta', b'meta', b'ilst']
VERSION_ATOMS = [b'meta']


def build_ilst_entry(key, value):
    value_bytes = value.encode('utf-8')
    data_atom = (8 + 4 + len(value_bytes)).to_bytes(4, 'big') + b'data'
    data_atom += b'\x00\x00\x00\x01' + value_bytes
    entry = (8 + len(data_atom)).to_bytes(4, 'big') + key + data_atom
    return entry


def build_metadata_tree(artist="", copyright="", comment="", encoder=""):
    hdlr_data = b'\x00\x00\x00\x00mdta\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    hdlr_atom = (8 + len(hdlr_data)).to_bytes(4, 'big') + b'hdlr' + hdlr_data

    entries = b''
    if artist: entries += build_ilst_entry(b'\xa9ART', artist)
    if encoder: entries += build_ilst_entry(b'\xa9too', encoder)
    if comment: entries += build_ilst_entry(b'\xa9cmt', comment)
    if copyright: entries += build_ilst_entry(b'\xa9cpy', copyright)

    ilst_atom = (8 + len(entries)).to_bytes(4, 'big') + b'ilst' + entries
    meta_data = b'\x00\x00\x00\x00' + hdlr_atom + ilst_atom
    meta_atom = (8 + len(meta_data)).to_bytes(4, 'big') + b'meta' + meta_data
    udta_atom = (8 + len(meta_atom)).to_bytes(4, 'big') + b'udta' + meta_atom
    return udta_atom


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
            version_offset = 4 if name in VERSION_ATOMS else 0
            children, _ = read_atoms_in_range(data, offset + header_size + version_offset, atom_end)
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


def inject_fake_frames(data, target_frames=None, pre_shift=0, stts_overflow=True):
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
    minf = find_atom(video_trak['children'], [b'mdia', b'minf'])
    mdia = find_atom(video_trak['children'], [b'mdia'])

    stsz = find_atom(stbl['children'], [b'stsz'])
    if not stsz:
        raise ValueError("stsz not found")

    stsz_data = bytearray(stsz['data'])
    orig_count = int.from_bytes(stsz_data[8:12], 'big')
    if target_frames is None:
        target_frames = orig_count * 10
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

    # 2. Update stts entry count (overflow exploit)
    if stts_overflow:
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

    # 3. Update all parent container sizes (stbl -> minf -> mdia -> trak -> moov)
    parents = [stsz, stbl, minf, mdia, video_trak]
    for parent in parents:
        old_sz = parent['size']
        new_sz = old_sz + growth
        result[parent['start']:parent['start'] + 4] = new_sz.to_bytes(4, 'big')
    new_moov_size = moov_size + growth
    result[moov_size_pos:moov_size_pos+4] = new_moov_size.to_bytes(4, 'big')

    # 4. Shift all chunk offsets by growth — moov is before mdat so every
    #    mdat chunk offset increased by the moov size increase.
    video_stsz_start = stsz['start']
    for trak in tree:
        if trak['name'] == b'trak':
            t_stbl = find_atom(trak['children'], [b'mdia', b'minf', b'stbl'])
            if not t_stbl:
                continue
            for child in t_stbl['children']:
                if child['name'] == b'stco':
                    pos_shift = growth if child['start'] > video_stsz_start else 0
                    co_data = bytearray(child['data'])
                    entry_count = int.from_bytes(co_data[4:8], 'big')
                    for i in range(entry_count):
                        idx = 8 + i * 4
                        val = int.from_bytes(co_data[idx:idx+4], 'big')
                        co_data[idx:idx+4] = (val + growth + pre_shift).to_bytes(4, 'big')
                    result[child['start'] + pos_shift + 8:
                           child['start'] + pos_shift + 8 + len(child['data'])] = bytes(co_data)
                elif child['name'] == b'co64':
                    pos_shift = growth if child['start'] > video_stsz_start else 0
                    co_data = bytearray(child['data'])
                    entry_count = int.from_bytes(co_data[4:8], 'big')
                    for i in range(entry_count):
                        idx = 8 + i * 8
                        val = int.from_bytes(co_data[idx:idx+8], 'big')
                        co_data[idx:idx+8] = (val + growth + pre_shift).to_bytes(8, 'big')
                    result[child['start'] + pos_shift + 8:
                           child['start'] + pos_shift + 8 + len(child['data'])] = bytes(co_data)

    return bytes(result)


def patch_video(input_path: str, output_path: str, custom_tag: str = "Patched with VideoBoost", title: str = "", artist: str = "akila", copyright: str = "akila", encode_1080p: bool = False, stts_overflow: bool = True) -> tuple[bool, str]:
    if not os.path.exists(input_path):
        return False, f"Input file '{input_path}' not found."

    # Stage 1: FFmpeg clean remux
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c", "copy",
        "-map_metadata", "-1",
        "-brand", "isom",
        "-video_track_timescale", "90000",
        "-movflags", "+faststart",
        "-bitexact",
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
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, "FFmpeg timed out"
    except FileNotFoundError:
        return False, "FFmpeg not found"

    # Stage 2: stsz injection + free atom + metadata + mdat corruption + fake atom
    try:
        with open(output_path, 'rb') as f:
            data = bytearray(f.read())

        # Insert free atom (size=8) between ftyp and moov (matches working file)
        ftyp_size = int.from_bytes(data[0:4], 'big')
        data[ftyp_size:ftyp_size] = b'\x00\x00\x00\x08free'
        logger.info("Free atom: inserted after ftyp (size=8)")

        # Build and inject iTunes metadata atoms at end of moov
        md_atom = build_metadata_tree(artist=artist, copyright=copyright, comment=custom_tag, encoder="Lavf60.16.100")
        if md_atom:
            moov_pos = data.find(b'moov')
            moov_size = int.from_bytes(data[moov_pos-4:moov_pos], 'big')
            moov_end = moov_pos + moov_size
            data[moov_end:moov_end] = md_atom
            data[moov_pos-4:moov_pos] = (moov_size + len(md_atom)).to_bytes(4, 'big')
            md_growth = len(md_atom)
            logger.info(f"Metadata tree: injected {md_growth} bytes into moov")
        else:
            md_growth = 0

        patched = bytearray(inject_fake_frames(data, pre_shift=8 + md_growth, stts_overflow=stts_overflow))

        # Corrupt mdat type (mdat -> mdau) so parser doesn't recognize it
        mdat_pos = patched.find(b'mdat')
        if mdat_pos >= 4:
            cur_type = patched[mdat_pos:mdat_pos+4]
            new_type = (int.from_bytes(cur_type, 'big') + 1).to_bytes(4, 'big')
            patched[mdat_pos:mdat_pos+4] = new_type
            logger.info(f"MDAT type: {cur_type} -> {new_type}")

        # Append fake atom with invalid size (4 bytes < 8 minimum)
        patched += b'\x00\x00\x00\x04xxxx'
        logger.info("Fake atom: size=4 (invalid, appended at end)")

        with open(output_path, 'wb') as f:
            f.write(patched)
        logger.info("STSZ injection + mdat patch complete")
        return True, "Video patched successfully!"
    except Exception as e:
        logger.error(f"Injection error: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return False, f"Patch failed: {str(e)}"
