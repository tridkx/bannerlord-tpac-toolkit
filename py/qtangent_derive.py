import numpy as np
import struct

PATH = r".\ref\empire_legion_a.bin"


def load(path):
    d = open(path, "rb").read()
    off = 0

    def i32():
        nonlocal off
        v = struct.unpack_from("<i", d, off)[0]; off += 4; return v

    magic = i32()
    n = i32(); idx = i32(); bi = i32(); nn = i32(); tn = i32(); u1 = i32(); u2 = i32()
    c1 = i32(); cn = i32(); cp = i32(); ct = i32(); qt = i32(); anp = i32()
    out = {"n": n, "indexCount": idx}

    def f32arr(c, per):
        nonlocal off
        a = np.frombuffer(d, dtype="<f4", count=c * per, offset=off).reshape(-1, per).copy()
        off += c * per * 4
        return a

    def u8arr(c, per):
        nonlocal off
        a = np.frombuffer(d, dtype="u1", count=c * per, offset=off).reshape(-1, per).copy()
        off += c * per
        return a

    out["pos"] = f32arr(n, 3)
    out["nrm"] = f32arr(nn, 3) if nn > 0 else None
    out["tan"] = f32arr(tn, 4) if tn > 0 else None
    out["uv1"] = f32arr(u1, 2)
    out["uv2"] = f32arr(u2, 2)
    out["col1"] = u8arr(c1, 4)
    out["bidx"] = u8arr(bi, 4)
    out["bwgt"] = u8arr(n, 4)
    out["idx"] = np.frombuffer(d, dtype="<i4", count=idx, offset=off).copy(); off += idx * 4
    qn = i32()
    out["qtan"] = None
    if qn > 0:
        q = np.frombuffer(d, dtype="<i2", count=qn * 4, offset=off).reshape(-1, 4).copy()
        off += qn * 4 * 2
        qf = np.where(q < 0, -(q.astype(np.float64) / -32768.0), q.astype(np.float64) / 32767.0)
        out["qtan"] = qf
        out["qtan_raw"] = q
    out["cnrm"] = np.frombuffer(d, dtype="<u4", count=cn, offset=off).copy(); off += cn * 4
    out["cpos"] = np.frombuffer(d, dtype="<u2", count=cp * 4, offset=off).reshape(-1, 4).copy(); off += cp * 8
    out["ctan"] = np.frombuffer(d, dtype="<u4", count=ct, offset=off).copy(); off += ct * 4
    out["anotherPos"] = f32arr(anp, 3) if anp > 0 else None
    print("parsed bytes:", off, "of", len(d))
    return out


def quat_from_matrix(m):
    """m: (n,3,3) rotation matrices (rows) -> quaternion (x,y,z,w)."""
    tr = m[:, 0, 0] + m[:, 1, 1] + m[:, 2, 2]
    q = np.zeros((m.shape[0], 4))
    # use the standard branch selection
    for i in range(m.shape[0]):
        M = m[i]
        t = M[0, 0] + M[1, 1] + M[2, 2]
        if t > 0:
            s = np.sqrt(t + 1.0) * 2
            w = 0.25 * s
            x = (M[2, 1] - M[1, 2]) / s
            y = (M[0, 2] - M[2, 0]) / s
            z = (M[1, 0] - M[0, 1]) / s
        elif M[0, 0] > M[1, 1] and M[0, 0] > M[2, 2]:
            s = np.sqrt(1.0 + M[0, 0] - M[1, 1] - M[2, 2]) * 2
            w = (M[2, 1] - M[1, 2]) / s
            x = 0.25 * s
            y = (M[0, 1] + M[1, 0]) / s
            z = (M[0, 2] + M[2, 0]) / s
        elif M[1, 1] > M[2, 2]:
            s = np.sqrt(1.0 + M[1, 1] - M[0, 0] - M[2, 2]) * 2
            w = (M[0, 2] - M[2, 0]) / s
            x = (M[0, 1] + M[1, 0]) / s
            y = 0.25 * s
            z = (M[1, 2] + M[2, 1]) / s
        else:
            s = np.sqrt(1.0 + M[2, 2] - M[0, 0] - M[1, 1]) * 2
            w = (M[1, 0] - M[0, 1]) / s
            x = (M[0, 2] + M[2, 0]) / s
            y = (M[1, 2] + M[2, 1]) / s
            z = 0.25 * s
        q[i] = (x, y, z, w)
    return q


def main():
    d = load(PATH)
    N = d["nrm"]
    T4 = d["tan"]
    Q = d["qtan"]
    print("counts", d["n"], "qtan", None if Q is None else Q.shape)
    # normalise
    N = N / np.linalg.norm(N, axis=1, keepdims=True)
    T = T4[:, :3]
    W = T4[:, 3]
    print("tangent w stats: min %.3f max %.3f mean %.3f  unique-ish %s" % (W.min(), W.max(), W.mean(), np.unique(np.round(W, 3))[:6]))

    # orthonormalise T against N
    T = T - N * np.sum(N * T, axis=1, keepdims=True)
    T = T / np.linalg.norm(T, axis=1, keepdims=True)
    B = np.cross(N, T)
    print("check T.N dot max", np.abs(np.sum(N * T, axis=1)).max())

    # candidate 1: columns [T B N]
    M1 = np.stack([T, B, N], axis=2)   # columns
    q1 = quat_from_matrix(M1)

    def score(name, q):
        # quaternions are double-cover: match q or -q
        for flip in (1.0, -1.0):
            err = np.abs(q * flip - Q)
            # for 4 components
            print(f"  {name} flip={flip:+.0f}: mean abs err {err.mean():.6f} max {err.max():.4f} exact-ish {np.mean(err.max(axis=1) < 0.01)*100:.1f}%")

    print("candidate 1: M=[T,B,N] as columns, B=cross(N,T)")
    score("c1", q1)

    # candidate 2: rows [T B N]
    M2 = np.stack([T, B, N], axis=1)
    q2 = quat_from_matrix(M2)
    print("candidate 2: M=[T,B,N] as rows")
    score("c2", q2)

    # show a few samples
    print("sample qtan:", np.round(Q[:3], 4).tolist())
    print("sample q1  :", np.round(q1[:3], 4).tolist())
    print("sample q2  :", np.round(q2[:3], 4).tolist())


if __name__ == "__main__":
    main()
