import os
import sys
import subprocess
import time

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

    stsz = find_atom(stbl['children'], [b'stsz'])
    if not stsz:
        print("[-] stsz not found")
        return None

    stsz_data = bytearray(stsz['data'])
    orig_count = int.from_bytes(stsz_data[8:12], 'big')
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

    stts = find_atom(stbl['children'], [b'stts'])
    if stts:
        stts_start = stts['start']
        old_stts_data_len = len(stts['data'])
        stts_data = bytearray(stts['data'])
        entry_count = int.from_bytes(stts_data[8:12], 'big')
        stts_data[8:12] = (entry_count + diff).to_bytes(4, 'big')
        result[stts_start + 8:stts_start + 8 + old_stts_data_len] = bytes(stts_data)
        print(f"[*] STTS: entries {entry_count} -> {entry_count + diff}")

    new_moov_size = moov_size + growth
    result[moov_size_pos:moov_size_pos+4] = new_moov_size.to_bytes(4, 'big')

    return bytes(result)


def patch_video(input_path, output_path, custom_tag="@akila", title="", artist="", copyright="", encode_1080p=False):
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        return

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

    print("FFmpeg remux...")
    start = time.time()
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FFmpeg failed:\n{result.stderr[:500]}")
        return
    print(f"FFmpeg done ({time.time()-start:.2f}s)")

    with open(output_path, 'rb') as f:
        data = f.read()
    patched = inject_fake_frames(data, target_frames=25570)
    if patched is None:
        print("Injection failed")
        return
    with open(output_path, 'wb') as f:
        f.write(patched)
    print(f"Done! Output: {output_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="VideoBoost CLI")
    p.add_argument("input", help="Input MP4 file")
    p.add_argument("-o", "--output", default="enhanced_output.mp4", help="Output file")
    p.add_argument("--title", default="", help="Video title metadata")
    p.add_argument("--artist", default="", help="Artist/creator metadata")
    p.add_argument("--copyright", default="", help="Copyright metadata")
    p.add_argument("--tag", default="@akila", help="Comment/social tag")
    p.add_argument("--hd", action="store_true", help="HD Optimizer")
    args = p.parse_args()
    patch_video(args.input, args.output, custom_tag=args.tag, title=args.title, artist=args.artist, copyright=args.copyright, encode_1080p=args.hd)
