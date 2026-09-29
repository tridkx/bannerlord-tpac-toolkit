# -*- coding: utf-8 -*-
"""project_map —— 从**工程自己的代码/配置**里取「源材质名 → 贴图」的映射。

为什么需要它
------------
`work/posed/*.npz` 里的材质名是**源模型的材质名**（`MI_MAJ02_01_hair`），
而贴图是按工程的命名走的（`yue_hair_d.png`）。这层对应关系**没有写进 npz**，
只存在于工程的打包脚本里（`pipeline/render.py` / `pipeline/build_assets.py`）。

早先预览器只能靠"拿材质名里的词去猜文件名"，猜不中（`eyelash_new_Inst`、
`M_ProxyHide`、`MI_MAJ02_01_TearLine`…）就统统落到关键词表的第一个词
⇒ **十几个组被套上同一张 cloth1 贴图，整个模型贴图紊乱**。

这个模块按优先级取映射：
  1. `<proj>/work/texmap_project.json`  —— 显式提供（换工程时最稳）
  2. `<proj>/pipeline/render.py`        —— 用 ast 解析里面的材质表
  3. `<proj>/pipeline/build_assets.py`  —— 同上（表结构不同，取第二个元素）
都取不到就返回 None，由调用方回退到猜测并给出警告。
"""
import ast
import json
from pathlib import Path


def _tuple_pick(node, i_stem, i_alpha=None):
    """从一个元组字面量里取 (贴图 stem, 是否镂空)。取不到返回 (None, None)。"""
    if not isinstance(node, ast.Tuple) or len(node.elts) <= i_stem:
        return None, None
    e = node.elts[i_stem]
    stem = e.value if (isinstance(e, ast.Constant) and isinstance(e.value, str)) else None
    alpha = None
    if i_alpha is not None and len(node.elts) > i_alpha:
        a = node.elts[i_alpha]
        if isinstance(a, ast.Constant) and isinstance(a.value, bool):
            alpha = a.value
    return stem, alpha


def _parse_mat_table(path, i_stem=0, i_alpha=2):
    """解析渲染脚本里的材质表，返回 ({角色: {材质: (stem, alpha)}}, {材质: (stem, alpha)})。

    ★ 用 ast 而不是 import：渲染脚本顶部就是 `import bpy`，普通 Python 根本
      import 不进来。
    ★ 表**可能是嵌套的**（外层键是角色名，内层才是材质名，见 render.py 的
      MAT_TABLE = {"yue": {...}, "bai": {...}}）。早先只取"最大的那个字典"，
      于是拿到了条目更多的 bai 表、yue 的材质一个也没配上 —— 贴图全落到猜测。
    """
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}, {}
    nested, flat = {}, {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        n_here, f_here = {}, {}
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            if isinstance(v, ast.Dict):
                inner = {}
                for k2, v2 in zip(v.keys, v.values):
                    if isinstance(k2, ast.Constant) and isinstance(k2.value, str):
                        stem, alpha = _tuple_pick(v2, i_stem, i_alpha)
                        if stem:
                            inner[k2.value] = (stem, alpha)
                if inner:
                    n_here[k.value] = inner
            else:
                stem, alpha = _tuple_pick(v, i_stem, i_alpha)
                if stem:
                    f_here[k.value] = (stem, alpha)
        if len(n_here) > len(nested):
            nested = n_here
        if len(f_here) > len(flat):
            flat = f_here
    return nested, flat


def load_project_drop_mats(proj_dir, verbose=True):
    """解析工程里「要丢弃的材质」清单（`DROP_MATS`）。

    这些是游戏靠专用 shader 隐藏的片子（走光保护片 `M_ProxyHide`、
    眼遮挡 `*_Eye_Occlusion`、泪线 `*_TearLine`）：**最终 mod 里根本没有它们**，
    但 `work/posed` 这种中间产物还带着。预览中间产物时要像工程渲染那样跳过，
    否则保护片会直接挡在身体前面。
    """
    for rel in ("pipeline/render.py", "pipeline/build_assets.py"):
        f = Path(proj_dir) / rel
        if not f.exists():
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not isinstance(node.value, (ast.Set, ast.List, ast.Tuple)):
                continue
            hit = any(isinstance(t, ast.Name) and "DROP" in t.id.upper()
                      for t in targets)
            if not hit:
                continue
            names = {e.value for e in node.value.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if names:
                # 清单里可能只写前缀（如 "MAJ03_01_Eye_Occlusion"），
                # 也可能写全名；两种都当"前缀匹配"用
                if verbose:
                    print(f"  [drop] 工程声明丢弃 {len(names)} 类材质："
                          f"{', '.join(sorted(names)[:4])}"
                          f"{' …' if len(names) > 4 else ''}")
                return names
    return set()


def load_project_texmap(proj_dir, tex_dir=None, verbose=True):
    """返回与 import_mod 的 texmap.json 同构的 dict，取不到返回 None。

    结构::

        { "__by_char__": {"yue": {材质名: 条目}, "bai": {...}},   # 按角色查（首选）
          "__materials__": {材质名: 条目},                        # 跨角色扁平（键不冲突时）
          "__dir__": <png 目录> }

    条目 = ``{"material", "slots": {"0": <stem>}, "alphaTest", "blendMode"}``，
    stem **不带 .png**（与 import_mod 的槽位值一致）。
    """
    proj = Path(proj_dir)
    tex_dir = Path(tex_dir) if tex_dir else None

    def _mk(mat, stem, has_alpha):
        return {
            "material": mat,
            "slots": {"0": stem},
            "alphaTest": 0.2745 if has_alpha else None,
            "blendMode": None,
        }

    def _have(stem):
        return (not tex_dir) or (tex_dir / f"{stem}.png").exists()

    # ---- 1. 显式文件 ----
    explicit = proj / "work" / "texmap_project.json"
    if explicit.exists():
        try:
            d = json.loads(explicit.read_text(encoding="utf-8"))
            if verbose:
                n = len(d.get("__materials__") or {}) or len(d)
                print(f"  [texmap] 用 work/texmap_project.json（{n} 条）")
            if tex_dir:
                d.setdefault("__dir__", str(tex_dir))
            return d
        except Exception as e:
            if verbose:
                print(f"  [texmap] texmap_project.json 读取失败 {type(e).__name__}: {e}")

    # ---- 2/3. 从工程脚本里解析 ----
    for rel, i_stem, i_alpha, tag in (
            ("pipeline/render.py", 0, 2, "render.py"),
            ("pipeline/build_assets.py", 1, 3, "build_assets.py")):
        f = proj / rel
        if not f.exists():
            continue
        nested, flat = _parse_mat_table(f, i_stem, i_alpha)
        if not nested and not flat:
            continue
        by_char = {ch: {m: _mk(m, s, a) for m, (s, a) in mats.items() if _have(s)}
                   for ch, mats in nested.items()}
        by_char = {ch: mats for ch, mats in by_char.items() if mats}
        allmat = {m: _mk(m, s, a) for m, (s, a) in flat.items() if _have(s)}
        for mats in by_char.values():
            for m, e in mats.items():
                allmat.setdefault(m, e)
        if not by_char and not allmat:
            continue
        out = {"__by_char__": by_char, "__materials__": allmat}
        if tex_dir:
            out["__dir__"] = str(tex_dir)
        if verbose:
            detail = "，".join(f"{ch}×{len(m)}" for ch, m in by_char.items())
            print(f"  [texmap] 从 {tag} 解析出映射：{detail or f'扁平 {len(allmat)} 条'}")
        try:
            (proj / "work" / "texmap_project.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            if verbose:
                print("  [texmap] 已缓存到 work/texmap_project.json（下次直接读）")
        except Exception:
            pass
        return out
    return None