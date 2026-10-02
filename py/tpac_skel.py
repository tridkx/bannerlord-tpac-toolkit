"""从任意 .tpac 里按名字 dump 骨架，并能量化两套骨架的差异（不整包加载，GB 级包也能秒开）。

用法:
    python tpac_skel.py <tpac> --list                    # 列骨架名 + guid + 段数
    python tpac_skel.py <tpac> <骨架名>                   # dump 骨骼表
    python tpac_skel.py <tpac> <骨架名> --json out.json   # 导出 JSON
    python tpac_skel.py <tpac> <骨架名> --vs ref.json     # 与参考骨架逐骨对比（骨长比/方向夹角/旋转夹角）

对比输出的三列含义：
    d_len   = 该骨局部平移的长度比（本骨架 / 参考骨架）→ 体型比例差异
    d_dir   = 局部平移方向的夹角（度）→ 关节"朝向"是否被改
    d_rot   = 该骨绑定旋转的夹角（度）→ 绑定姿态是否被改（0 = 与该骨参考姿态一致）

设计说明：只 seek 读文件头，跳过每个资产的 metadata blob（不读入内存），
因此对 1.4GB 的 TOR pack6 也是毫秒级；只有目标骨架的那一个 data segment 会被解压。
"""
import argparse
import io
import json
import math
import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TPAC_MAGIC = 0x43415054
SKELETON_TYPE = "c635a3d5-eabb-45dd-883e-aa57e4196113"
SKEL_DEF_TYPE = "11d07d37-e720-406b-ab67-c846f96a8771"


def guid_hex(raw: bytes) -> str:
    d1, d2, d3 = struct.unpack_from("<IHH", raw, 0)
    tail = raw[8:]
    return "%08x-%04x-%04x-%s-%s" % (d1, d2, d3, tail[:2].hex(), tail[2:].hex())


def read_sized_string(f) -> str:
    (n,) = struct.unpack("<i", f.read(4))
    return f.read(n).decode("utf-8", "replace") if n > 0 else ""


def scan_assets(path: Path):
    """只读文件头 + 每个资产的段表；metadata 用 seek 跳过。"""
    with path.open("rb") as f:
        magic, version = struct.unpack("<II", f.read(8))
        if magic != TPAC_MAGIC:
            raise ValueError("不是 tpac 文件: %s" % path)
        pkg_guid = guid_hex(f.read(16))
        res_num, _data_offset, _reserve = struct.unpack("<III", f.read(12))
        assets = []
        for _ in range(res_num):
            type_guid = guid_hex(f.read(16))
            asset_guid = guid_hex(f.read(16))
            asset_version = struct.unpack("<I", f.read(4))[0] if version > 1 else 0
            name = read_sized_string(f)
            (meta_size,) = struct.unpack("<Q", f.read(8))
            f.seek(meta_size, 1)
            f.seek(8, 1)                                   # checksum
            (seg_num,) = struct.unpack("<i", f.read(4))
            segs = []
            for _j in range(seg_num):
                off, actual, storage = struct.unpack("<QQQ", f.read(24))
                seg_guid = guid_hex(f.read(16))
                seg_type = guid_hex(f.read(16))
                f.seek(12, 1)                              # unk_ulong(8) + unk_uint(4)
                fmt = f.read(1)[0]
                segs.append(dict(offset=off, actual=actual, storage=storage,
                                 seg_guid=seg_guid, seg_type=seg_type, fmt=fmt))
            (dep_num,) = struct.unpack("<i", f.read(4))
            f.seek(dep_num * 48, 1)
            assets.append(dict(type_guid=type_guid, guid=asset_guid, version=asset_version,
                               name=name, segs=segs))
        return pkg_guid, assets


def read_segment(path: Path, seg) -> bytes:
    with path.open("rb") as f:
        f.seek(seg["offset"])
        raw = f.read(seg["storage"])
    if seg["fmt"] == 1:
        import lz4.block
        raw = lz4.block.decompress(raw, uncompressed_size=seg["actual"])
    return raw


def parse_skeleton_definition(blob: bytes):
    f = io.BytesIO(blob)
    name = read_sized_string(f)
    (num,) = struct.unpack("<i", f.read(4))
    bones = []
    for _ in range(num):
        bname = read_sized_string(f)
        (parent,) = struct.unpack("<i", f.read(4))
        mat = struct.unpack("<16f", f.read(64))
        bones.append(dict(name=bname, parent=parent, rest=list(mat)))
    return name, bones


# ---- 矩阵工具：tpac 里是行向量约定的 4x4（平移在 M41..M43 = 下标 12..14）----

def translation(m):
    return (m[12], m[13], m[14])


def basis(m):
    """取左上 3x3 的三行作为基向量（行向量约定）。"""
    return ((m[0], m[1], m[2]), (m[4], m[5], m[6]), (m[8], m[9], m[10]))


def vlen(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def angle_between(a, b):
    la, lb = vlen(a), vlen(b)
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    c = sum(x * y for x, y in zip(a, b)) / (la * lb)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def to_matrix(flat):
    """把 tpac 的 16 个 float 变成 4x4，并补齐次项。

    ★ 坑：tpac 里 Skeleton 的 RestFrame 矩阵 **M44 是很小的非零值（~1e-43），不是 1.0**，
    第 4 列整体为 0。直接用 numpy 做 `L_child @ W_parent` 会**丢掉父骨的平移**
    （子骨世界位置退化成自己的局部平移）。算世界位置前必须把 M[3][3] 置 1。
    """
    import numpy as np
    m = np.array(flat, float).reshape(4, 4)
    m[3, 3] = 1.0
    return m


def world_matrices(bones):
    """沿父链复合出每根骨的世界矩阵（行向量约定：W_child = L_child · W_parent）。"""
    import numpy as np
    cache = {}

    def rec(i):
        if i in cache:
            return cache[i]
        m = to_matrix(bones[i]["rest"])
        p = bones[i]["parent"]
        w = m if p < 0 else m @ rec(p)
        cache[i] = w
        return w

    return [rec(i) for i in range(len(bones))]


def rest_rotation_angle(ma, mb):
    """两套绑定旋转之间的夹角：对 R_a · R_bᵀ 取旋转角。"""
    A, B = basis(ma), basis(mb)
    # R = A · Bᵀ
    R = [[sum(A[i][k] * B[j][k] for k in range(3)) for j in range(3)] for i in range(3)]
    tr = R[0][0] + R[1][1] + R[2][2]
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1.0) / 2.0))))


def find_skeleton(path: Path, want: str, assets):
    hits = [a for a in assets if a["type_guid"] == SKELETON_TYPE and a["name"] == want]
    if not hits:
        hits = [a for a in assets if a["type_guid"] == SKELETON_TYPE and want.lower() in a["name"].lower()]
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tpac")
    ap.add_argument("skeleton", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--vs", help="参考骨架 JSON（用 --json 导出的那份）")
    ap.add_argument("--names-only", action="store_true")
    args = ap.parse_args()

    path = Path(args.tpac)
    pkg_guid, assets = scan_assets(path)
    skels = [a for a in assets if a["type_guid"] == SKELETON_TYPE]

    if args.list or not args.skeleton:
        print("包 %s guid=%s 资产=%d 骨架=%d" % (path.name, pkg_guid, len(assets), len(skels)))
        for a in skels:
            print("  %-45s %s segs=%d" % (a["name"], a["guid"], len(a["segs"])))
        return 0

    hits = find_skeleton(path, args.skeleton, assets)
    if not hits:
        print("没找到骨架: %s（用 --list 看清单）" % args.skeleton)
        return 1

    bones = None
    for a in hits:
        print("=" * 106)
        print("Skeleton '%s' guid=%s" % (a["name"], a["guid"]))
        defs = [s for s in a["segs"] if s["seg_type"] == SKEL_DEF_TYPE]
        if not defs:
            print("  (没有 definition 段，段类型: %s)" % [s["seg_type"] for s in a["segs"]])
            continue
        dname, bones = parse_skeleton_definition(read_segment(path, defs[0]))
        print("  defName='%s' bones=%d" % (dname, len(bones)))
        if args.names_only:
            for i, b in enumerate(bones):
                print("  [%3d] %s" % (i, b["name"]))
        else:
            ws = world_matrices(bones)
            m44 = [b["rest"][15] for b in bones]
            for i, b in enumerate(bones):
                t = translation(b["rest"])
                print("  [%3d] %-40s parent=%3d local=(%+.4f,%+.4f,%+.4f) len=%.4f z_world=%.4f"
                      % (i, b["name"], b["parent"], t[0], t[1], t[2], vlen(t), float(ws[i][3, 2])))
            bad44 = sum(1 for x in m44 if abs(x - 1.0) > 1e-3)
            print("  M44: %d/%d 根骨不是 1.0（tpac 原版骨架就是 ~0，属正常；"
                  "自己写 spec 时若填 1.0 也需实测）" % (bad44, len(bones)))
        if args.json:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(dict(package=str(path), package_guid=pkg_guid,
                                           skeleton=a["name"], guid=a["guid"], bones=bones),
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            print("WROTE %s" % out)

    if args.vs and bones:
        ref = json.loads(Path(args.vs).read_text(encoding="utf-8"))
        rb = ref["bones"]
        print("\n对比 %s(%d 骨)  vs  %s(%d 骨)" % (args.skeleton, len(bones), ref["skeleton"], len(rb)))
        print("  %-4s %-26s %8s %8s %8s   %s" % ("idx", "bone", "len", "d_len", "d_dir", "d_rot"))
        for i in range(min(len(bones), len(rb))):
            a, b = bones[i], rb[i]
            ta, tb = translation(a["rest"]), translation(b["rest"])
            la, lb = vlen(ta), vlen(tb)
            same_name = a["name"] == b["name"]
            flag = "" if same_name else "  <<名称不同>>"
            print("  [%2d] %-26s %8.4f %8.3f %8.1f° %8.1f°%s"
                  % (i, a["name"], la, (la / lb if lb > 1e-9 else float("nan")),
                     angle_between(ta, tb), rest_rotation_angle(a["rest"], b["rest"]), flag))
        if len(bones) != len(rb):
            print("  骨数不同: %d vs %d" % (len(bones), len(rb)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
