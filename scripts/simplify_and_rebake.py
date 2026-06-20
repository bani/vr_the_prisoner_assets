"""
simplify_and_rebake.py
----------------------
Simplify a PBR material down to just Base Color + Normal mapped directly to a
Principled BSDF (Metallic=0, Roughness=1), create a clean UV map (Smart UV
Project), and rebake the base color & normal from the original material onto the
new UV layout.

Designed for the "prisoner/parade" VRChat models, which all share the same
structure: a single mesh object with one material whose Base Color / Metallic /
Roughness / Normal are driven by 4 image textures through an "st" UV map.

USAGE
=====
Inside Blender (Scripting tab) or via the Blender MCP, just call:

    simplify_and_rebake()

Everything is auto-detected: the single mesh object, its material, the existing
UV map (used as the bake *source*), and an output base-name derived from the
object. Override any of it if needed, e.g.:

    simplify_and_rebake(obj_name="parade2", resolution=2048, save_blend=False)

When run via the Blender MCP execute tool, the bottom of this file assigns the
returned summary to `result` so it round-trips as JSON.

PARAMETERS
==========
    obj_name        Mesh object to process. Default: active object if it's a
                    mesh, else the only mesh in the scene.
    mat_name        Material to simplify. Default: the object's first material.
    base_name       Prefix for the new textures / files. Default: object name.
    resolution      Bake resolution (px). Default 4096 (matches source).
    margin          Bake margin in px to avoid seam bleeding. Default 16.
    island_margin   Smart UV Project island margin. Default 0.003.
    new_uv_name     Name for the clean UV map. Default "UVMap".
    save_textures   Write baked PNGs to ./textures next to the .blend. Default True.
    pack            Pack the baked textures into the .blend. Default True.
    save_blend      Save the .blend at the end. Default True.
    cleanup_orphans Remove image datablocks left with 0 users. Default True.
"""

import bpy
import os


def _find_mesh_object(obj_name=None):
    if obj_name:
        obj = bpy.data.objects.get(obj_name)
        if obj is None or obj.type != 'MESH':
            raise ValueError(f"Object {obj_name!r} not found or not a mesh")
        return obj
    act = bpy.context.view_layer.objects.active
    if act and act.type == 'MESH':
        return act
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if len(meshes) == 1:
        return meshes[0]
    raise ValueError(f"Could not auto-detect mesh object; found {len(meshes)}. "
                     f"Pass obj_name explicitly.")


def _make_image(name, resolution, non_color, fill):
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])
    img = bpy.data.images.new(name, resolution, resolution,
                              alpha=False, float_buffer=False)
    img.colorspace_settings.name = 'Non-Color' if non_color else 'sRGB'
    img.generated_color = fill
    return img


def _bake_to(nt, bake_node, image, **bake_kwargs):
    bake_node.image = image
    for n in nt.nodes:
        n.select = False
    bake_node.select = True
    nt.nodes.active = bake_node
    bpy.ops.object.bake(**bake_kwargs)


def simplify_and_rebake(obj_name=None, mat_name=None, base_name=None,
                        resolution=4096, margin=16, island_margin=0.003,
                        new_uv_name="UVMap", save_textures=True, pack=True,
                        save_blend=True, cleanup_orphans=True):
    scene = bpy.context.scene
    obj = _find_mesh_object(obj_name)
    me = obj.data

    if mat_name:
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            raise ValueError(f"Material {mat_name!r} not found")
    else:
        mat = next((s.material for s in obj.material_slots if s.material), None)
        if mat is None:
            raise ValueError(f"Object {obj.name!r} has no material")
    if not mat.use_nodes:
        raise ValueError(f"Material {mat.name!r} does not use nodes")

    base_name = base_name or obj.name
    nt = mat.node_tree

    # --- remember original state so we can restore the engine ----------------
    original_engine = scene.render.engine

    # --- ensure object mode, selected & active -------------------------------
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # --- identify the SOURCE uv map (the existing one) -----------------------
    if len(me.uv_layers) == 0:
        raise ValueError("Mesh has no UV layers to bake from")
    old_uv = (me.uv_layers.active or me.uv_layers[0]).name
    if old_uv == new_uv_name:
        old_uv = me.uv_layers[0].name  # avoid clobbering the source

    # Pin every UV Map node in the material to the source UV so the bake reads
    # from the original layout regardless of active-render changes below.
    for n in nt.nodes:
        if n.type == 'UVMAP':
            n.uv_map = old_uv

    # --- create the clean UV map (Smart UV Project) --------------------------
    if new_uv_name in me.uv_layers:
        me.uv_layers.remove(me.uv_layers[new_uv_name])
    new_uv = me.uv_layers.new(name=new_uv_name)
    me.uv_layers.active = new_uv
    new_uv.active_render = True  # bake destination layout

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=island_margin,
                             area_weight=0.0, correct_aspect=True,
                             scale_to_bounds=False)
    bpy.ops.object.mode_set(mode='OBJECT')

    # --- create bake targets -------------------------------------------------
    img_base = _make_image(f"{base_name}_BaseColor", resolution, False, (0, 0, 0, 1))
    img_norm = _make_image(f"{base_name}_Normal", resolution, True, (0.5, 0.5, 1.0, 1))

    bake_node = nt.nodes.new('ShaderNodeTexImage')
    bake_node.name = "BAKE_TARGET"
    bake_node.location = (-600, 600)

    # --- bake (Cycles) -------------------------------------------------------
    scene.render.engine = 'CYCLES'
    try:
        scene.cycles.samples = 1  # color/normal bakes are noiseless
    except Exception:
        pass
    scene.render.bake.margin = margin
    scene.render.bake.use_clear = True
    scene.render.bake.use_selected_to_active = False

    _bake_to(nt, bake_node, img_base, type='DIFFUSE', pass_filter={'COLOR'},
             margin=margin, use_clear=True)
    _bake_to(nt, bake_node, img_norm, type='NORMAL', margin=margin,
             use_clear=True, normal_space='TANGENT',
             normal_r='POS_X', normal_g='POS_Y', normal_b='POS_Z')

    # --- save the baked textures to disk -------------------------------------
    paths = {}
    if save_textures and bpy.data.filepath:
        tex_dir = os.path.join(os.path.dirname(bpy.data.filepath), "textures")
        os.makedirs(tex_dir, exist_ok=True)
        for img, fname in ((img_base, f"{base_name}_basecolor.png"),
                           (img_norm, f"{base_name}_normal.png")):
            path = os.path.join(tex_dir, fname)
            img.filepath_raw = path
            img.file_format = 'PNG'
            img.save()
            img.filepath = path
            img.source = 'FILE'
            paths[img.name] = path

    # --- rebuild the material clean ------------------------------------------
    nodes, links = nt.nodes, nt.links
    nodes.clear()
    out = nodes.new('ShaderNodeOutputMaterial'); out.location = (400, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (0, 0)
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    uvn = nodes.new('ShaderNodeUVMap'); uvn.location = (-900, 0)
    uvn.uv_map = new_uv_name

    tb = nodes.new('ShaderNodeTexImage'); tb.location = (-600, 200)
    tb.image = img_base; tb.image.colorspace_settings.name = 'sRGB'
    links.new(uvn.outputs['UV'], tb.inputs['Vector'])
    links.new(tb.outputs['Color'], bsdf.inputs['Base Color'])

    tn = nodes.new('ShaderNodeTexImage'); tn.location = (-600, -200)
    tn.image = img_norm; tn.image.colorspace_settings.name = 'Non-Color'
    nm = nodes.new('ShaderNodeNormalMap'); nm.location = (-250, -250)
    nm.uv_map = new_uv_name
    links.new(uvn.outputs['UV'], tn.inputs['Vector'])
    links.new(tn.outputs['Color'], nm.inputs['Color'])
    links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])

    bsdf.inputs['Metallic'].default_value = 0.0
    bsdf.inputs['Roughness'].default_value = 1.0

    # --- drop the old UV map -------------------------------------------------
    if old_uv in me.uv_layers and old_uv != new_uv_name:
        me.uv_layers.remove(me.uv_layers[old_uv])
    me.uv_layers[new_uv_name].active_render = True
    me.uv_layers.active = me.uv_layers[new_uv_name]

    # --- cleanup orphaned image datablocks -----------------------------------
    removed = []
    if cleanup_orphans:
        for img in list(bpy.data.images):
            if img.name in ("Render Result", "Viewer Node"):
                continue
            if img.users == 0:
                removed.append(img.name)
                bpy.data.images.remove(img)

    # --- pack + restore engine + save ----------------------------------------
    if pack:
        for img in (img_base, img_norm):
            if not img.packed_file:
                img.pack()

    scene.render.engine = original_engine

    if save_blend and bpy.data.filepath:
        bpy.ops.wm.save_mainfile()

    return {
        "object": obj.name,
        "material": mat.name,
        "base_name": base_name,
        "old_uv_source": old_uv,
        "new_uv": new_uv_name,
        "resolution": resolution,
        "textures": paths,
        "packed": pack,
        "removed_orphans": removed,
        "engine_restored_to": original_engine,
        "blend_saved": bool(save_blend and bpy.data.filepath),
        "blend_path": bpy.data.filepath,
    }


# When executed via the Blender MCP execute tool, expose the summary as `result`.
if __name__ == "__main__":
    result = simplify_and_rebake()
    print(result)
