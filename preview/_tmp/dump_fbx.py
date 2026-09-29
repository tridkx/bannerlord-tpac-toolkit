# -*- coding: utf-8 -*-
"""dump human_skeleton.fbx 的骨骼 rest、内嵌动画/姿势。"""
import bpy, json, sys, math
from mathutils import Matrix

path = sys.argv[-1]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.fbx(filepath=path)

arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
print("=== 导入结果 ===")
print("  armature:", [a.name for a in arms])
print("  动作(actions):", [(a.name, len(a.fcurves)) for a in bpy.data.actions])
print("  其它对象:", [(o.name, o.type) for o in bpy.data.objects if o.type != "ARMATURE"][:6])

for arm in arms:
    bones = arm.data.bones
    print(f"\n=== {arm.name}: {len(bones)} 根骨 ===")
    print(f"  matrix_world 平移 = {tuple(round(v,4) for v in arm.matrix_world.translation)}")
    for i, b in enumerate(bones[:6]):
        mL = b.matrix_local
        print(f"  [{i:2d}] {b.name:28s} parent={b.parent.name if b.parent else None}")
        print(f"        head={tuple(round(v,4) for v in b.head_local)}  "
              f"tail={tuple(round(v,4) for v in b.tail_local)}")
        # rest 朝向：matrix_local 的 3x3
        for r in range(3):
            print(f"        rest[{r}] = [{mL[r][0]:+.4f} {mL[r][1]:+.4f} {mL[r][2]:+.4f}]")
    # 内嵌姿势：pose bones 的 matrix（如果有 action，第 0 帧）
    if bpy.data.actions:
        act = bpy.data.actions[0]
        arm.animation_data_create()
        arm.animation_data.action = act
        sc = bpy.context.scene
        sc.frame_set(int(act.frame_range[0]))
        bpy.context.view_layer.update()
        print(f"\n  动作 '{act.name}' 第 {int(act.frame_range[0])} 帧的姿势（前 6 骨）：")
        for i, pb in enumerate(arm.pose.bones[:6]):
            m = pb.matrix
            print(f"  [{i:2d}] {pb.name:28s} loc={tuple(round(v,4) for v in m.translation)}")
            for r in range(3):
                print(f"        pose[{r}] = [{m[r][0]:+.4f} {m[r][1]:+.4f} {m[r][2]:+.4f}]")
