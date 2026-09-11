import bpy, json, sys, os, mathutils

FBX = r"D:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\modding_resources\skeletons\human_skeleton.fbx"
OUT = r".\human_skeleton.json"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=FBX)

arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
print("ARMATURES:", [a.name for a in arms])
arm = arms[0]
arm.data.pose_position = 'REST'
bpy.context.view_layer.update()

bones = []
for b in arm.data.bones:
    m = b.matrix_local  # bone space -> armature space (rest)
    bones.append({
        "name": b.name,
        "parent": b.parent.name if b.parent else None,
        "matrix_local": [list(r) for r in m],
        "head": list(b.head_local),
        "tail": list(b.tail_local),
        "length": b.length,
    })

# also record what order Blender reports them (should mirror FBX node order)
data = {
    "armature": arm.name,
    "armature_matrix_world": [list(r) for r in arm.matrix_world],
    "bone_count": len(bones),
    "bones": bones,
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=1)
print("WROTE", OUT, len(bones), "bones")
for i, b in enumerate(bones):
    h = b["head"]
    print(f'{i:3d} {b["name"]:<40} parent={str(b["parent"]):<30} head=({h[0]:+.4f},{h[1]:+.4f},{h[2]:+.4f})')
