import os
import sys, struct, hashlib, zlib, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tpac import read_tpac
import xxhash

MASK = 0xFFFFFFFFFFFFFFFF
PKG = sys.argv[1] if len(sys.argv) > 1 else "path/to/pack0.tpac"
t = read_tpac(PKG)
# use a handful of assets of different types
samples = []
seen = set()
for a in t["assets"]:
    if a["type_guid"] not in seen:
        seen.add(a["type_guid"])
        samples.append(a)
samples += t["assets"][:6]
print("samples:", len(samples), "types:", len(seen))


def fnv1a64(d, seed=0xCBF29CE484222325):
    h = seed
    for b in d:
        h ^= b
        h = (h * 0x100000001B3) & MASK
    return h


def fnv1_64(d, seed=0xCBF29CE484222325):
    h = seed
    for b in d:
        h = (h * 0x100000001B3) & MASK
        h ^= b
    return h


def u64le(x):
    return x & MASK


def u64be(x):
    return int.from_bytes(x.to_bytes(8, "little"), "big")


HASHERS = {
    "xxh64_s0": lambda d: xxhash.xxh64(d, seed=0).intdigest(),
    "xxh64_s1": lambda d: xxhash.xxh64(d, seed=1).intdigest(),
    "xxh64_s0x9E3779B1": lambda d: xxhash.xxh64(d, seed=0x9E3779B1).intdigest(),
    "xxh64_bswap": lambda d: u64be(xxhash.xxh64(d, seed=0).intdigest()),
    "xxh3_64": lambda d: xxhash.xxh3_64(d).intdigest(),
    "xxh32_s0": lambda d: xxhash.xxh32(d, seed=0).intdigest(),
    "xxh128_low": lambda d: xxhash.xxh128(d).intdigest() & MASK,
    "xxh128_high": lambda d: (xxhash.xxh128(d).intdigest() >> 64) & MASK,
    "fnv1a64": lambda d: fnv1a64(d),
    "fnv1a64_bswap": lambda d: u64be(fnv1a64(d)),
    "fnv1_64": lambda d: fnv1_64(d),
    "crc32": lambda d: zlib.crc32(d) & MASK,
    "crc32_bswap": lambda d: u64be(zlib.crc32(d)),
    "md5_head8le": lambda d: int.from_bytes(hashlib.md5(d).digest()[:8], "little"),
    "md5_tail8le": lambda d: int.from_bytes(hashlib.md5(d).digest()[-8:], "little"),
    "md5_head8be": lambda d: int.from_bytes(hashlib.md5(d).digest()[:8], "big"),
    "md5_int_le": lambda d: int.from_bytes(hashlib.md5(d).digest()[:8], "little"),
    "sha1_head8le": lambda d: int.from_bytes(hashlib.sha1(d).digest()[:8], "little"),
    "sha1_tail8le": lambda d: int.from_bytes(hashlib.sha1(d).digest()[-8:], "little"),
    "sha256_head8le": lambda d: int.from_bytes(hashlib.sha256(d).digest()[:8], "little"),
    "sha256_tail8le": lambda d: int.from_bytes(hashlib.sha256(d).digest()[-8:], "little"),
    "sha256_head8be": lambda d: int.from_bytes(hashlib.sha256(d).digest()[:8], "big"),
    "blake2b8": lambda d: int.from_bytes(hashlib.blake2b(d, digest_size=8).digest(), "little"),
    "blake2s8": lambda d: int.from_bytes(hashlib.blake2s(d, digest_size=8).digest(), "little"),
    "md5_xor_halves": lambda d: (lambda x: int.from_bytes(x[:8], "little") ^ int.from_bytes(x[8:], "little"))(hashlib.md5(d).digest()),
    "sha256_xor4": lambda d: (lambda x: (int.from_bytes(x[0:8], "little") ^ int.from_bytes(x[8:16], "little")
                                         ^ int.from_bytes(x[16:24], "little") ^ int.from_bytes(x[24:32], "little")))(hashlib.sha256(d).digest()),
}


def build_inputs(a):
    meta = a["meta"]
    tg = bytes.fromhex(a["type_guid"])
    ver = struct.pack("<I", a["version"])
    mlen = struct.pack("<Q", a["meta_size"])
    mlen4 = struct.pack("<I", a["meta_size"])
    out = {
        "meta": meta,
        "type+meta": tg + meta,
        "meta+type": meta + tg,
        "ver+meta": ver + meta,
        "len8+meta": mlen + meta,
        "len4+meta": mlen4 + meta,
        "meta+len8": meta + mlen,
        "meta+zeros8": meta + b"\0" * 8,
        "zeros8+meta": b"\0" * 8 + meta,
    }
    return out


# score each (input, hash) combo
score = {}
inputs0 = build_inputs(samples[0])
for iname in inputs0:
    for hname in HASHERS:
        score[(iname, hname)] = 0
total = 0
for a in samples:
    inputs = build_inputs(a)
    total += 1
    for iname, data in inputs.items():
        for hname, hf in HASHERS.items():
            try:
                if hf(data) == a["checksum"]:
                    score[(iname, hname)] += 1
            except Exception:
                pass

print(f"--- best combinations over {total} samples ---")
best = sorted(score.items(), key=lambda kv: -kv[1])[:10]
for (iname, hname), v in best:
    print(f"   {iname:<14} {hname:<20} {v}/{total}")

# also: brute force xxh64 seeds
print("--- xxh64 seed scan (0..4096) on 'meta' ---")
found = []
for seed in range(0, 4096):
    ok = 0
    for a in samples[:4]:
        if xxhash.xxh64(a["meta"], seed=seed).intdigest() == a["checksum"]:
            ok += 1
        else:
            break
    if ok == 4:
        found.append(seed)
print("   seeds matching first 4 samples:", found)

# print a couple of raw values for manual inspection
a = samples[0]
print(f"--- sample[0] {a['name']} meta={a['meta_size']} chk={a['checksum']:#018x} ---")
print("   meta hex head:", a["meta"][:64].hex())
print("   xxh64:", hex(xxhash.xxh64(a['meta'], seed=0).intdigest()))
print("   md5  :", hashlib.md5(a['meta']).hexdigest())
print("   sha1 :", hashlib.sha1(a['meta']).hexdigest())
