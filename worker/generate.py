"""Run only inside a dedicated isolated Blender worker."""
import sys
from pathlib import Path
import bpy

args = sys.argv[sys.argv.index("--") + 1:]
shape, size, output_dir = args[0], float(args[1]), Path(args[2])
output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
if shape == "cube":
    bpy.ops.mesh.primitive_cube_add(size=size)
elif shape == "sphere":
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=size / 2)
elif shape == "cylinder":
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=size / 2, depth=size)
else:
    raise ValueError("Unsupported shape")
obj = bpy.context.object
obj.name = "MainObject"
mat = bpy.data.materials.new("Material")
mat.diffuse_color = (0.18, 0.55, 0.85, 1.0)
obj.data.materials.append(mat)
bpy.ops.object.camera_add(location=(size * 2.5, -size * 3, size * 2))
camera = bpy.context.object
camera.rotation_euler = (-camera.location).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = camera
bpy.ops.object.light_add(type="AREA", location=(size, -size, size * 4))
bpy.context.object.data.energy = 800
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = 640
scene.render.resolution_y = 480
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(output_dir / "preview.png")
bpy.ops.wm.save_as_mainfile(filepath=str(output_dir / "scene.blend"))
bpy.ops.export_scene.gltf(filepath=str(output_dir / "scene.glb"), export_format="GLB", use_selection=False)
bpy.ops.render.render(write_still=True)
