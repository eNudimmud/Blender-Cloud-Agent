"""Trusted Blender script. Input is declarative JSON, never Python from an agent."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def linear(channel):
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def generate(spec_file, output):
    spec = json.loads(spec_file.read_text())
    objects = spec["objects"]
    if spec["schema_version"] != 1 or len(objects) > 24:
        raise ValueError("Invalid scene schema")
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    meshes = []
    for item in objects:
        size = item["size"]
        position = item["position"]
        if not math.isfinite(size) or not 0.1 <= size <= 20 or len(position) != 3 or any(not math.isfinite(c) or abs(c) > 50 for c in position):
            raise ValueError("Scene bounds exceeded")
        if item["shape"] == "cube":
            bpy.ops.mesh.primitive_cube_add(size=size, location=position)
        elif item["shape"] == "sphere":
            bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=size / 2, location=position)
        elif item["shape"] == "cylinder":
            bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=size / 2, depth=size, location=position)
        else:
            raise ValueError("Unsupported primitive")
        obj = bpy.context.object
        obj.name = item["name"]
        obj["bca_object_id"] = item["id"]
        color = item["color"].lstrip("#")
        rgba = tuple(linear(int(color[i:i + 2], 16)) for i in (0, 2, 4)) + (1,)
        material = bpy.data.materials.new("Material_" + item["id"])
        material.diffuse_color = rgba
        material.use_nodes = True
        material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = rgba
        material.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = 0.38
        obj.data.materials.append(material)
        meshes.append(obj)
    corners = [obj.matrix_world @ Vector(c) for obj in meshes for c in obj.bound_box]
    if corners:
        low = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
        high = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
        center = (high + low) / 2
        span = max((high - low).length, 1)
    else:
        center, span = Vector((0, 0, 0)), 4
    bpy.ops.object.camera_add(location=center + Vector((span, -span * 1.4, span)))
    camera = bpy.context.object
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.clip_end = 1000
    scene = bpy.context.scene
    scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=center + Vector((span, -span / 2, span * 2)))
    bpy.context.object.data.energy = 100 * span**2
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = span
    scene.world.color = (0.2, 0.2, 0.2)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 12
    scene.cycles.use_denoising = False
    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output / "preview.png")
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "scene.blend"), compress=False)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    # Export mesh content only. glTF performs Blender Z-up -> viewer Y-up conversion.
    bpy.ops.export_scene.gltf(filepath=str(output / "scene.glb"), export_format="GLB", use_selection=True, export_extras=True)
    bpy.ops.render.render(write_still=True)
    (output / "metadata.json").write_text(json.dumps({"blender_version": bpy.app.version_string}))


if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1:]
    generate(Path(arguments[0]), Path(arguments[1]))
