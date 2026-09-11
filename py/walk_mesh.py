import os
import sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tpac import read_tpac


class R:
    def __init__(self, m):
        self.m = m
        self.off = 0

    def _v(self, fmt, size, label):
        v = struct.unpack_from(fmt, self.m, self.off)[0]
        print(f"    {self.off:4d} {label:<10} {v}")
        self.off += size
        return v

    def u32(self): return self._v("<I", 4, "u32")
    def i32(self): return self._v("<i", 4, "i32")
    def u64(self): return self._v("<Q", 8, "u64")
    def f32(self): return self._v("<f", 4, "f32")
    def u16(self): return self._v("<H", 2, "u16")
    def by(self): return self._v("<B", 1, "byte")
    def boolean(self): return self._v("<B", 1, "bool")

    def guid(self, label="guid"):
        v = self.m[self.off:self.off + 16]
        print(f"    {self.off:4d} {label:<10} {v.hex()}")
        self.off += 16
        return v

    def sstr(self, label="str"):
        n = struct.unpack_from("<i", self.m, self.off)[0]
        start = self.off
        self.off += 4
        s = self.m[self.off:self.off + n].decode("utf-8", "replace")
        self.off += n
        print(f"    {start:4d} {label:<10} [{n}] " + s.encode('ascii', 'replace').decode())
        return s

    def slist(self, label="list"):
        n = struct.unpack_from("<i", self.m, self.off)[0]
        start = self.off
        self.off += 4
        print(f"    {start:4d} {label:<10} count={n}")
        return [self.sstr("  item") for _ in range(n)]

    def vec4(self, label="vec4"):
        print(f"    {self.off:4d} {label}")
        return (self.f32(), self.f32(), self.f32(), self.f32())


def walk_mesh(r, indent="      "):
    global PRE
    print(f"{indent}--- submesh at {r.off} ---")
    r.boolean()                 # IsCompleteMesh
    r.i32()                     # Lod
    r.u32()                     # UnknownUint1
    r.guid("GUID_A")            # TpacTool: SecondMaterial
    r.u32()                     # subVersion
    r.guid("mesh guid")
    r.sstr("mesh name")
    r.u32()                     # UnknownUInt2
    r.slist("flags")
    r.guid("GUID_B")            # TpacTool: Material
    r.vec4("FactorColor")
    r.vec4("Factor2Color")
    r.vec4("VectorArgument")
    r.vec4("VectorArgument2")
    r.i32()                     # VertexKeyCount
    r.i32()                     # PositionCount
    r.i32()                     # FaceCount
    r.i32()                     # VertexCount
    r.i32()                     # SkinDataSize
    r.i32()                     # bbox type
    r.vec4("bbox min"); r.vec4("bbox max"); r.vec4("bbox center")
    r.f32()                     # sphere radius
    r.i32()                     # UnknownInt2
    r.slist("materialFlags")
    r.f32()                     # UnknownFloat1
    # ClothingMaterial primary
    r.sstr("clothName")
    for _ in range(9): r.f32()          # stiffness / damping / gravity ...
    r.i32()                             # UnknownInt3
    r.boolean(); r.boolean()
    r.f32(); r.f32(); r.boolean()       # extra data (subVersion >= 1)
    r.i32()                     # UnknownInt3
    r.boolean()                 # UnknownBool1
    r.boolean()                 # UnknownBool2
    # extra (subVersion>=1)
    r.f32(); r.f32(); r.f32(); r.u32(); r.u32(); r.u32()
    r.boolean()                 # UnknownBool3


def walk_metamesh(a):
    print(f"=== {a['name']}  meta={a['meta_size']} ===")
    r = R(a["meta"])
    ver = r.u32()
    r.guid("metamesh mat")
    r.f32()
    r.sstr("bodyPart")
    r.guid("clothMetamesh")
    if ver >= 1:
        r.u32(); cu = r.u32()
        if cu > 0:
            r.sstr("clothString")
    n = r.i32()
    print(f"    submeshes={n}")
    for i in range(n):
        walk_mesh(r)
    r.guid("Original")
    vn = r.i32()
    print(f"    variations={vn}")
    for _ in range(vn):
        r.guid("var")
    r.boolean(); r.boolean()
    print(f"    consumed {r.off} / {len(a['meta'])}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].endswith(".tpac"):
        tpac, name = sys.argv[1], sys.argv[2]
    else:
        tpac = r"D:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Native\EmAssetPackages\armor555\armor555.tpac"
        name = "empire_legion_a"
    t = read_tpac(tpac)
    for a in t["assets"]:
        if a["name"] == name and a["type_guid"].startswith("978b8fa0"):
            walk_metamesh(a)
            break
