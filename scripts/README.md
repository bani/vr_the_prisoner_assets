# Prisoner / Parade VRChat models — material cleanup

These models come out of a USD/PBR export with a **messy material and UV map**.
Each `.blend` has a single mesh object and one material whose Base Color,
Metallic, Roughness, and Normal are all driven by separate 4096² image textures
(`texture_pbr_20250901*.png`) sampled through a UV map named `st`.

The goal for every file is the same:

1. **Simplify the material** to just Base Color + Normal mapped directly to the
   Principled BSDF, with **Metallic = 0** and **Roughness = 1**.
2. **Re-unwrap** the model into a cleaner UV layout.
3. **Rebake** the Base Color and Normal onto the new UVs so the textures still
   line up.

## The script

[`simplify_and_rebake.py`](simplify_and_rebake.py) does all of the above in one
call. It is parameterized but auto-detects sensible defaults, so usually you run
it with no arguments.

```python
simplify_and_rebake()
```

What it does, in order:

1. Pins the existing material's UV Map nodes to the **old** UV (`st`) so the bake
   reads from the original layout.
2. Creates a clean `UVMap` via **Smart UV Project** and makes it the active /
   render UV (the bake destination).
3. Bakes, in **Cycles**:
   - Base Color → `<name>_BaseColor` (`DIFFUSE`, color only), sRGB
   - Normal → `<name>_Normal` (`NORMAL`, tangent space), Non-Color
4. Saves the baked PNGs to `./textures/`.
5. Rebuilds the material clean: Base Color + Normal → Principled BSDF,
   Metallic = 0, Roughness = 1.
6. Removes the old `st` UV map and any now-orphaned image datablocks.
7. Packs the new textures, restores the original render engine, and saves the
   `.blend`.

### Useful overrides

```python
simplify_and_rebake(
    obj_name="parade2",     # default: active object, else the only mesh
    mat_name=None,          # default: object's first material
    base_name=None,         # default: object name (prefix for textures/files)
    resolution=4096,        # bake size; drop to 2048 for lighter files
    margin=16,              # px margin to avoid seam bleeding
    island_margin=0.003,    # Smart UV Project island spacing
    new_uv_name="UVMap",
    save_textures=True,     # write PNGs to ./textures
    pack=True,              # pack textures into the .blend
    save_blend=True,        # save the .blend when done
    cleanup_orphans=True,   # remove image datablocks left with 0 users
)
```

## How to run

- **Blender Scripting tab:** open `simplify_and_rebake.py` and press Run, or
  paste it into the console and call `simplify_and_rebake()`.
- **Via Claude / the Blender MCP:** the file's `__main__` block calls
  `simplify_and_rebake()` and assigns the JSON summary to `result`, so executing
  the file's contents through the MCP execute tool runs the whole pipeline and
  returns a summary.

## Notes / assumptions

- Baking requires **Cycles**; the script switches to it temporarily and restores
  whatever engine the file was using afterward.
- It assumes the source textures are reachable through UV Map nodes (true for
  these exports). If a future file differs, inspect it before running.


Baked outputs live in [`textures/`](textures/) as `<name>_basecolor.png` and
`<name>_normal.png` (also packed into each `.blend`).
