"""Minimal independent Python reader for Bannerlord .tpac files.

Used to cross-check the C# writer and to analyse the unknown per-asset Int64
that sits right after each asset's metadata blob.
"""
import struct
import sys
import os
import hashlib
import zlib


def rd_sized_string(f):
    (n,) = struct.unpack("<i", f.read(4))
    if n == 0:
        return ""
    return f.read(n).decode("utf-8", "replace")


def read_tpac(path, read_meta=True):
    with open(path, "rb") as f:
        magic, version = struct.unpack("<II", f.read(8))
        assert magic == 0x43415054, hex(magic)
        guid = f.read(16)
        res_num, data_offset, reserve = struct.unpack("<III", f.read(12))
        assets = []
        for i in range(res_num):
            type_guid = f.read(16)
            asset_guid = f.read(16)
            asset_version = 0
            if version > 1:
                (asset_version,) = struct.unpack("<I", f.read(4))
            name = rd_sized_string(f)
            (meta_size,) = struct.unpack("<Q", f.read(8))
            meta = f.read(meta_size) if read_meta else f.read(meta_size)
            (checksum,) = struct.unpack("<q", f.read(8))
            (seg_num,) = struct.unpack("<i", f.read(4))
            segs = []
            for j in range(seg_num):
                off, actual, storage = struct.unpack("<QQQ", f.read(24))
                seg_guid = f.read(16)
                seg_type = f.read(16)
                unk_ulong, unk_uint = struct.unpack("<QI", f.read(12))
                (fmt,) = struct.unpack("<B", f.read(1))
                segs.append(dict(offset=off, actual=actual, storage=storage,
                                 seg_guid=seg_guid.hex(), seg_type=seg_type.hex(),
                                 unk_ulong=unk_ulong, unk_uint=unk_uint, fmt=fmt))
            (dep_num,) = struct.unpack("<i", f.read(4))
            deps = []
            for j in range(dep_num):
                deps.append(f.read(48).hex())
            assets.append(dict(index=i, type_guid=type_guid.hex(), guid=asset_guid.hex(),
                               version=asset_version, name=name, meta_size=meta_size,
                               meta=meta, checksum=checksum & 0xFFFFFFFFFFFFFFFF,
                               segs=segs, deps=deps))
        file_size = os.path.getsize(path)
    return dict(path=path, version=version, guid=guid.hex(), res_num=res_num,
                data_offset=data_offset, reserve=reserve, assets=assets, file_size=file_size)


def try_hashes(meta, name, guid_hex, checksum):
    cands = {}
    data = meta
    cands["xxh64_meta"] = None
    cands["fnv1a64_meta"] = fnv1a64(data)
    cands["fnv1a64_name_meta"] = fnv1a64(name.encode() + data)
    cands["fnv1a64_meta_name"] = fnv1a64(data + name.encode())
    cands["crc32_meta"] = zlib.crc32(data)
    cands["sha256_8_meta"] = int.from_bytes(hashlib.sha256(data).digest()[:8], "little")
    cands["md5_8_meta"] = int.from_bytes(hashlib.md5(data).digest()[:8], "little")
    cands["sha256_8_name_meta"] = int.from_bytes(hashlib.sha256(name.encode() + data).digest()[:8], "little")
    cands["sha256_last8_meta"] = int.from_bytes(hashlib.sha256(data).digest()[-8:], "little")
    cands["blake2b_8_meta"] = int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "little")
    hits = [k for k, v in cands.items() if v == checksum]
    return hits, cands


def fnv1a64(data):
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


if __name__ == "__main__":
    path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "summary"
    t = read_tpac(path)
    print(f"{path}: version={t['version']} guid={t['guid']} res={t['res_num']} "
          f"dataOffset={t['data_offset']} size={t['file_size']}")
    if mode == "summary":
        from collections import Counter
        c = Counter(a["type_guid"] for a in t["assets"])
        for k, v in c.most_common():
            print("  ", k, v)
        print("distinct checksums:", len(set(a["checksum"] for a in t["assets"])), "of", len(t["assets"]))
        for a in t["assets"][:12]:
            print(f"   [{a['index']:3d}] {a['name'][:36]:<36} meta={a['meta_size']:6d} chk={a['checksum']:#018x} segs={len(a['segs'])}")
    elif mode == "hash":
        for a in t["assets"][:20]:
            hits, cands = try_hashes(a["meta"], a["name"], a["guid"], a["checksum"])
            print(f"   [{a['index']:3d}] {a['name'][:30]:<30} chk={a['checksum']:#018x} hits={hits}")
