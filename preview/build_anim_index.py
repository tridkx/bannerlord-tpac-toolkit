# -*- coding: utf-8 -*-
"""build_anim_index —— 给 anims/ 里的动画 JSON 配上「游戏里到底播多久」。

解决什么问题
------------
动画 JSON 的时间轴 `t`（0..1267 这种）与**秒**之间没有写在数据里的换算关系，
之前离线预览只能"拍一个 24fps"，于是 GIF 快慢跟游戏对不上 —— 姿势对了但
节奏不像，仍然看不出"待机时手是不是一直在轻微晃"。

换算依据（有据可查，不是猜的）
------------------------------
`animation_clips.tpac` 里的 `AnimationClip` 是游戏自己声明"这段动画播多久"的地方：

    AnimationClip  inventory_idle  dur=15.000  anim=ff08c5be-…  flags=[cyclic]

`dur` 单位是秒（15 秒的装备页待机、5 秒的换装、1.3 秒的走路循环，量级都对），
`anim` 就是它引用的 SkeletalAnimation 的 guid —— 而我们的动画 JSON 里正好存着
同一个 guid。于是：

    播放速率 rate = t_end / dur      [t 单位/秒]

实测三个点（换一个模型/动画不用改代码，重新生成索引即可）::

    walk_barmaid      t_end= 40  dur= 1.30s  ->  30.8 t/s   （与 30fps 采样自洽）
    inv_movements     t_end=300  dur= 5.00s  ->  60.0 t/s
    inventory_idle    t_end=1267 dur=15.00s  ->  84.5 t/s

★ 但**不要**把 rate 当成"引擎帧率"—— 它只是"把这段动画铺满 clip 时长"的比例。
  真正可靠的只有 clip 自己写的 dur；动画内部 t 的采样刻度是另一回事。

用法
----
    python build_anim_index.py --clips clips.txt --anims . --out index.json

    # 也可以让它自己跑 mbtool 生成 clips.txt（--mbtool + --clips-tpac）
    python build_anim_index.py --mbtool <mbtool.exe> \
        --clips-tpac <game>/Modules/Native/AssetPackages/animation_clips.tpac \
        --anims . --out index.json
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CLIP_RE = re.compile(
    r"^AnimationClip\s+(\S+)\s+dur=([\d.]+)\s+anim=(\S+)"
    r"(?:\s+flags=\[([^\]]*)\])?(?:\s+prio=(-?\d+))?\s*$")


def parse_clips(path):
    """clips.txt（mbtool cliplist 的输出）-> {anim guid: [clip, ...]}"""
    by_guid = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = CLIP_RE.match(line.strip())
        if not m:
            continue
        name, dur, guid, flags, prio = m.groups()
        by_guid.setdefault(guid, []).append({
            "name": name,
            "duration": float(dur),
            "flags": [f for f in (flags or "").split(",") if f],
            "priority": int(prio) if prio is not None else 0,
        })
    return by_guid


def pick_clip(stem, anim_name, clips):
    """一个动画常被多个 clip 引用（如 inventory_idle / inventory_idle_start）。

    挑法：先看有没有"clip 名 == 动画名去掉 anim_ 前缀"，再看 cyclic（循环动画
    更可能是我们要预览的那种），最后按 duration 从大到小。
    """
    want = (anim_name or "").replace("anim_", "")

    def score(c):
        exact = 1 if c["name"] == want else 0
        cyc = 1 if "cyclic" in c["flags"] else 0
        return (-exact, -cyc, -c["duration"], c["name"])

    return sorted(clips, key=score)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anims", default=".", help="动画 JSON 所在目录")
    ap.add_argument("--clips", default=None, help="mbtool cliplist 的输出文件")
    ap.add_argument("--clips-tpac", default=None, help="直接给 animation_clips.tpac（自动跑 mbtool）")
    ap.add_argument("--mbtool", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    anims_dir = Path(a.anims)
    out = Path(a.out) if a.out else anims_dir / "index.json"

    clips_file = a.clips
    if not clips_file and a.clips_tpac:
        if not a.mbtool:
            raise SystemExit("--clips-tpac 需要同时给 --mbtool")
        clips_file = str(anims_dir / "clips.txt")
        print(f"[index] 跑 mbtool cliplist …")
        with open(clips_file, "w", encoding="utf-8") as fh:
            r = subprocess.run([a.mbtool, "cliplist", a.clips_tpac],
                               stdout=fh, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            raise SystemExit("mbtool cliplist 失败")
    if not clips_file or not Path(clips_file).exists():
        raise SystemExit("需要 --clips <cliplist 输出> 或 --clips-tpac + --mbtool")

    by_guid = parse_clips(clips_file)
    print(f"[index] clips.txt: {sum(len(v) for v in by_guid.values())} 个 clip，"
          f"覆盖 {len(by_guid)} 个动画 guid")

    files = sorted(p for p in anims_dir.glob("*.json") if p.name != out.name)
    index, matched, unmatched = {}, 0, []
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [skip] {p.name}: {type(e).__name__}")
            continue
        if "boneAnims" not in d:
            continue
        guid = str(d.get("guid", ""))
        t_end = max((b["rot"][-1]["t"] for b in d["boneAnims"] if b.get("rot")),
                    default=0)
        clips = by_guid.get(guid, [])
        ent = {
            "file": p.name,
            "animName": d.get("name", ""),
            "guid": guid,
            "tEnd": t_end,
            "animDuration": d.get("duration"),
            "clips": clips,
        }
        if clips:
            c = pick_clip(p.stem, d.get("name", ""), clips)
            ent.update(clip=c["name"], clipDuration=c["duration"],
                       clipFlags=c["flags"], clipPriority=c["priority"],
                       cyclic="cyclic" in c["flags"],
                       fps=(t_end / c["duration"]) if c["duration"] > 0 else None,
                       seconds=c["duration"])
            matched += 1
            print(f"  {p.stem:22s} t_end={t_end:<6} clip={c['name']:28s} "
                  f"dur={c['duration']:7.3f}s -> {ent['fps']:7.2f} t/s"
                  + ("  [cyclic]" if ent["cyclic"] else ""))
        else:
            ent["seconds"] = None
            unmatched.append(p.stem)
            print(f"  {p.stem:22s} t_end={t_end:<6} 没有 clip 引用它 —— "
                  f"播放速率只能用兜底 fps")
        index[p.stem] = ent

    out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"[index] {len(index)} 个动画（{matched} 个配上了 clip 时长）-> {out}")
    if unmatched:
        print(f"[index] 没有 clip 的：{unmatched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())