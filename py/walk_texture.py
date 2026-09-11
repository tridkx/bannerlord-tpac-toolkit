import os
import sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tpac import read_tpac


class R:
    def __init__(self, m):
        self.m = m
        self.off = 0

    def u32(self):
        v = struct.unpack_from("<I", self.m, self.off)[0]
        print(f"  {self.off:4d} u32   {v}")
        self.off += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.m, self.off)[0]
        print(f"  {self.off:4d} i32   {v}")
        self.off += 4
        return v

    def u64(self):
        v = struct.unpack_from("<Q", self.m, self.off)[0]
        print(f"  {self.off:4d} u64   {v:#x}")
        self.off += 8
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.m, self.off)[0]
        print(f"  {self.off:4d} f32   {v}")
        self.off += 4
        return v

    def by(self):
        v = self.m[self.off]
        print(f"  {self.off:4d} byte  {v}")
        self.off += 1
        return v

    def boolean(self):
        v = self.m[self.off]
        print(f"  {self.off:4d} bool  {bool(v)}")
        self.off += 1
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.m, self.off)[0]
        print(f"  {self.off:4d} u16   {v}")
        self.off += 2
        return v

    def guid(self):
        v = self.m[self.off:self.off + 16]
        print(f"  {self.off:4d} guid  {v.hex()}")
        self.off += 16
        return v

    def sstr(self):
        n = struct.unpack_from("<i", self.m, self.off)[0]
        start = self.off
        self.off += 4
        s = self.m[self.off:self.off + n].decode("utf-8", "replace")
        self.off += n
        print(f"  {start:4d} str[{n}] {s!r}")
        return s

    def slist(self):
        n = struct.unpack_from("<i", self.m, self.off)[0]
        start = self.off
        self.off += 4
        print(f"  {start:4d} list  count={n}")
        return [self.sstr() for _ in range(n)]


def walk_texture(name, m):
    print(f"=== {name}  meta len={len(m)} ===")
    r = R(m)
    version = r.u32()
    r.guid()          # billboard material
    r.u32()           # unknown uint1
    r.sstr()          # source
    r.u64()           # unknown ulong
    r.boolean()       # unknown bool
    r.u32()           # unknown uint2
    r.slist()         # flags
    u3 = r.u32()      # unknown uint3
    r.by()            # unknown byte
    w = r.u32()
    h = r.u32()
    r.u32()           # unknown uint4
    mips = r.by()
    arr = r.u16()
    fmt = r.sstr()
    r.u32()           # unknown uint5
    r.slist()         # system flags
    if u3 > 0:
        r.u32()       # unknown uint6
        r.u32()       # unknown uint7
    # dirty hack region
    if version >= 1 or len(m) - r.off == 4:
        n = r.u32()
        for _ in range(n):
            r.guid()
            r.guid()
    if version >= 2:
        r.u64()
    print(f"  --> consumed {r.off} / {len(m)}   REMAINING {len(m)-r.off}: {m[r.off:].hex()}")


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "path/to/pack0.tpac"
    t = read_tpac(p)
    tex = [a for a in t["assets"] if a["type_guid"].startswith("cbcb74c9")]
    print(f"{len(tex)} textures in {p}")
    if len(sys.argv) > 2:
        tex = [a for a in tex if a["name"] == sys.argv[2]]
    for a in tex[:3]:
        walk_texture(a["name"], a["meta"])
