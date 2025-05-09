bl_info = {
    "name": "VRM Normal Map Generator",
    "author": "Meringue Rouge",
    "version": (1, 3, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > VRM",
    "description": "Generates DirectX normal maps for VRM 1.0 materials (SKIN, CLOTH, HAIR) asynchronously with progress bar",
    "category": "VRM",
}

import bpy
from . import vrm_normal_map_generator

def register():
    vrm_normal_map_generator.register()

def unregister():
    vrm_normal_map_generator.unregister()

if __name__ == "__main__":
    register()