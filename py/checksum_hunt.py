import os
import sys, os, glob, struct, hashlib, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tpac import read_tpac

MASK = 0xFFFFFFFFFFFFFFFF

# ---------- hash implementations ----------
def fnv1a64(data, seed=0xCBF29CE484222325):
    h = seed
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & MASK
    return h

def fnv1_64(data, seed=0xCBF29CE484222325):
    h = seed
    for b in data:
        h = (h * 0x100000001B3) & MASK
        h ^= b
    return h

def xxh64(data, seed=0):
    P1, P2, P3, P4, P5 = 11400714785074694791, 14029467366897019727, 1609587929392839161, 9650029242287828579, 2870177450012600261
    def rotl(x, r): return ((x << r) | (x >> (64 - r))) & MASK
    n = len(data); i = 0
    if n >= 32:
        v1 = (seed + P1 + P2) & MASK; v2 = (seed + P2) & MASK; v3 = seed & MASK; v4 = (seed - P1) & MASK
        while i + 32 <= n:
            for vi in range(4):
                lane = struct.unpack_from("<Q", data, i + vi * 8)[0]
                v = [v1, v2, v3, v4][vi]
                v = (v + lane * P2) & MASK
                v = rotl(v, 31)
                v = (v * P1) & MASK
                if vi == 0: v1 = v
                elif vi == 1: v2 = v
                elif vi == 2: v3 = v
                else: v4 = v
            i += 32
        h = (rotl(v1, 1) + rotl(v2, 7) + rotl(v3, 12) + rotl(v4, 18)) & MASK
        for v in (v1, v2, v3, v4):
            v = (v * P2) & MASK; v = rotl(v, 31); v = (v * P1) & MASK
            h ^= v; h = (h * P1 + P4) & MASK
    else:
        h = (seed + P5) & MASK
    h = (h + n) & MASK
    while i + 8 <= n:
        k = struct.unpack_from("<Q", data, i)[0]
        k = (k * P2) & MASK; k = rotl(k, 31); k = (k * P1) & MASK
        h ^= k; h = (rotl(h, 27) * P1 + P4) & MASK
        i += 8
    if i + 4 <= n:
        k = struct.unpack_from("<I", data, i)[0]
        h ^= (k * P1) & MASK; h = (rotl(h, 23) * P2 + P3) & MASK
        i += 4
    while i < n:
        h ^= (data[i] * P5) & MASK; h = (rotl(h, 11) * P1) & MASK
        i += 1
    h ^= h >> 33; h = (h * P2) & MASK
    h ^= h >> 29; h = (h * P3) & MASK
    h ^= h >> 32
    return h

def murmur64a(data, seed=0):
    m = 0xc6a4a7935bd1e995; r = 47
    h = (seed ^ (len(data) * m)) & MASK
    n = len(data) // 8 * 8
    for i in range(0, n, 8):
        k = struct.unpack_from("<Q", data, i)[0]
        k = (k * m) & MASK; k ^= k >> r; k = (k * m) & MASK
        h ^= k; h = (h * m) & MASK
    tail = data[n:]
    if tail:
        for i, b in enumerate(tail):
            h ^= b << (8 * i)
        h = (h * m) & MASK
    h ^= h >> r; h = (h * m) & MASK; h ^= h >> r
    return h

def crc64_ecma(data):
    poly = 0xC96C5795D7870F42
    crc = MASK
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (poly if crc & 1 else 0)
    return crc ^ MASK

def sha8(data, which="first"):
    d = hashlib.sha256(data).digest()
    return int.from_bytes(d[:8] if which == "first" else d[-8:], "little")

HASHES = {
    "fnv1a64": fnv1a64,
    "fnv1_64": fnv1_64,
    "xxh64": xxh64,
    "murmur64a": murmur64a,
    "crc64ecma": crc64_ecma,
    "crc32": lambda d: zlib.crc32(d) & MASK,
    "sha256_head8": lambda d: sha8(d, "first"),
    "sha256_tail8": lambda d: sha8(d, "tail"),
    "blake2b8": lambda d: int.from_bytes(hashlib.blake2b(d, digest_size=8).digest(), "little"),
    "md5_head8": lambda d: int.from_bytes(hashlib.md5(d).digest()[:8], "little"),
}


def report(paths, limit=8):
    rows = []
    for p in paths:
        try:
            t = read_tpac(p)
        except Exception as e:
            print("  skip", os.path.basename(p), e)
            continue
        for a in t["assets"][:limit]:
            rows.append((os.path.basename(p), a))
    print(f"collected {len(rows)} assets")
    score = {k: 0 for k in HASHES}
    score["const0"] = 0
    for fn, a in rows:
        meta = a["meta"]
        name = a["name"].encode()
        chk = a["checksum"]
        for hname, hf in HASHES.items():
            if hf(meta) == chk: score[hname] += 1
        if chk == 0: score["const0"] += 1
    n = len(rows)
    print("--- matches over metadata ---")
    for k, v in sorted(score.items(), key=lambda x: -x[1]):
        if v: print(f"   {k:<16} {v}/{n}")
    # does the checksum depend only on the name?
    byname = {}
    for fn, a in rows:
        byname.setdefault(a["name"], set()).add(a["checksum"])
    dup = {k: v for k, v in byname.items() if len(v) > 1}
    print(f"names appearing in several packages with DIFFERENT checksums: {len(dup)}")
    for k, v in list(dup.items())[:5]:
        print("   ", k, [hex(x) for x in v])
    same = {k: v for k, v in byname.items() if len(v) == 1}
    print(f"names with a consistent checksum: {len(same)}")
    # checksum vs meta size correlation
    import collections
    sizes = collections.Counter((a["meta_size"], a["checksum"]) for fn, a in rows)
    print("distinct (metasize, checksum) pairs:", len(sizes), "of", len(rows))
    for (fn, a) in rows[:10]:
        print(f"   {a['name'][:34]:<34} meta={a['meta_size']:6d} chk={a['checksum']:#018x}")
    return rows


if __name__ == "__main__":
    games = r"D:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Native\EmAssetPackages"
    paths = []
    for d in ["armor555", "armor666", "armor888", "head_female", "human_underwear", "womens_headwrap"]:
        paths += glob.glob(os.path.join(games, d, "*.tpac"))
    paths += glob.glob(r".\rt\*.tpac")
    report(paths)
