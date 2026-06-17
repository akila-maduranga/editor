import os
import sys
import subprocess
import time

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


def inject_fake_frames(data, target_frames=None, pre_shift=0, stts_overflow=True):
    moov_pos = data.find(b'moov')
    if moov_pos < 4:
        print("[-] moov not found")
        return None
    moov_size_pos = moov_pos - 4
    moov_size = int.from_bytes(data[moov_size_pos:moov_size_pos+4], 'big')

    tree, _ = read_atoms_in_range(data, moov_pos + 4, moov_pos + moov_size)

    video_trak = None
    for atom in tree:
        if atom['name'] == b'trak':
            hdlr = find_atom(atom['children'], [b'mdia', b'hdlr'])
            if hdlr and b'vide' in hdlr['data']:
                video_trak = atom
                break
    if not video_trak:
        print("[-] Video track not found")
        return None

    stbl = find_atom(video_trak['children'], [b'mdia', b'minf', b'stbl'])
    if not stbl:
        print("[-] stbl not found")
        return None
    minf = find_atom(video_trak['children'], [b'mdia', b'minf'])
    mdia = find_atom(video_trak['children'], [b'mdia'])

    stsz = find_atom(stbl['children'], [b'stsz'])
    if not stsz:
        print("[-] stsz not found")
        return None

    stsz_data = bytearray(stsz['data'])
    orig_count = int.from_bytes(stsz_data[8:12], 'big')
    if target_frames is None:
        target_frames = orig_count * 10
    diff = target_frames - orig_count
    if diff <= 0:
        print(f"[*] Already {orig_count} frames")
        return data

    print(f"[*] STSZ: {orig_count} -> {target_frames}")
    new_entries = b'\x00\x00\x00\x00' * diff

    result = bytearray(data)

    stsz_start_in_file = stsz['start']
    old_stsz_data_len = len(stsz['data'])
    stsz_data[8:12] = target_frames.to_bytes(4, 'big')
    new_stsz_data = bytes(stsz_data) + new_entries
    growth = len(new_stsz_data) - old_stsz_data_len

    result[stsz_start_in_file + 8:stsz_start_in_file + 8 + old_stsz_data_len] = new_stsz_data

    if stts_overflow:
        stts = find_atom(stbl['children'], [b'stts'])
        if stts:
            stts_start = stts['start']
            old_stts_data_len = len(stts['data'])
            stts_data = bytearray(stts['data'])
            entry_count = int.from_bytes(stts_data[8:12], 'big')
            stts_data[8:12] = (entry_count + diff).to_bytes(4, 'big')
            result[stts_start + 8:stts_start + 8 + old_stts_data_len] = bytes(stts_data)
            print(f"[*] STTS: entries {entry_count} -> {entry_count + diff}")

    for parent in [stsz, stbl, minf, mdia, video_trak]:
        old_sz = parent['size']
        new_sz = old_sz + growth
        result[parent['start']:parent['start'] + 4] = new_sz.to_bytes(4, 'big')
    new_moov_size = moov_size + growth
    result[moov_size_pos:moov_size_pos+4] = new_moov_size.to_bytes(4, 'big')

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


def patch_video(input_path, output_path, custom_tag="Patched with VideoBoost", title="", artist="akila", copyright="akila", encode_1080p=False, stts_overflow=True):
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        return

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

    print("FFmpeg remux...")
    start = time.time()
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FFmpeg failed:\n{result.stderr[:500]}")
        return
    print(f"FFmpeg done ({time.time()-start:.2f}s)")

    with open(output_path, 'rb') as f:
        data = bytearray(f.read())

    # Insert free atom (size=8) between ftyp and moov (matches working file)
    ftyp_size = int.from_bytes(data[0:4], 'big')
    data[ftyp_size:ftyp_size] = b'\x00\x00\x00\x08free'
    print("Free atom: inserted after ftyp (size=8)")

    # Build and inject iTunes metadata atoms at end of moov
    md_atom = build_metadata_tree(artist=artist, copyright=copyright, comment=custom_tag, encoder="Lavf60.16.100")
    if md_atom:
        moov_pos = data.find(b'moov')
        moov_size = int.from_bytes(data[moov_pos-4:moov_pos], 'big')
        moov_end = moov_pos + moov_size
        data[moov_end:moov_end] = md_atom
        data[moov_pos-4:moov_pos] = (moov_size + len(md_atom)).to_bytes(4, 'big')
        md_growth = len(md_atom)
        print(f"Metadata tree: injected {md_growth} bytes into moov")
    else:
        md_growth = 0

    patched = inject_fake_frames(data, pre_shift=8 + md_growth, stts_overflow=stts_overflow)
    if patched is None:
        print("Injection failed")
        return
    patched = bytearray(patched)

    # Corrupt mdat type (mdat -> mdau) so parser doesn't recognize it
    mdat_pos = patched.find(b'mdat')
    if mdat_pos >= 4:
        cur_type = patched[mdat_pos:mdat_pos+4]
        new_type = (int.from_bytes(cur_type, 'big') + 1).to_bytes(4, 'big')
        patched[mdat_pos:mdat_pos+4] = new_type
        print(f"MDAT type: {cur_type} -> {new_type}")

    # Append fake atom with invalid size (4 bytes < 8 minimum)
    patched += b'\x00\x00\x00\x04xxxx'
    print("Fake atom: size=4 (invalid, appended at end)")

    with open(output_path, 'wb') as f:
        f.write(patched)
    print(f"Done! Output: {output_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="VideoBoost CLI")
    p.add_argument("input", help="Input MP4 file")
    p.add_argument("-o", "--output", default="enhanced_output.mp4", help="Output file")
    p.add_argument("--title", default="", help="Video title metadata")
    p.add_argument("--artist", default="akila", help="Artist/creator metadata")
    p.add_argument("--copyright", default="akila", help="Copyright metadata")
    p.add_argument("--tag", default="Patched with VideoBoost", help="Comment/social tag")
    p.add_argument("--hd", action="store_true", help="HD Optimizer")
    p.add_argument("--no-stts", action="store_true", help="Disable STTS overflow exploit")
    args = p.parse_args()
    patch_video(args.input, args.output, custom_tag=args.tag, title=args.title, artist=args.artist, copyright=args.copyright, encode_1080p=args.hd, stts_overflow=not args.no_stts)
