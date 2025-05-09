bl_info = {
    "name": "VRM Normal Map Generator",
    "author": "Meringue Rouge",
    "version": (1, 3),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > VRM",
    "description": "Generates DirectX normal maps for VRM 1.0 materials (SKIN, CLOTH, HAIR) asynchronously with progress bar",
    "category": "VRM",
}

import bpy
import numpy as np
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import BoolProperty, FloatProperty, PointerProperty

# Custom Sobel operator using NumPy convolution
def sobel_custom(image, axis):
    sobel_x = np.array([[1, 0, -1], [2, 0, -2], [1, 0, -1]])
    sobel_y = np.array([[1, 2, 1], [0, 0, 0], [-1, -2, -1]])
    kernel = sobel_y if axis == 0 else sobel_x
    result = np.zeros_like(image)
    padded = np.pad(image, ((1, 1), (1, 1)), mode='edge')
    for i in range(image.shape[0]):
        for j in range(image.shape[1]):
            result[i, j] = np.sum(padded[i:i+3, j:j+3] * kernel)
    return result

# Operator to generate normal maps asynchronously
class VRM_OT_GenerateNormalMaps(Operator):
    bl_idname = "vrm.generate_normal_maps"
    bl_label = "Generate Normal Maps"
    bl_description = "Generate DirectX normal maps for selected VRM materials asynchronously"

    _timer = None
    _materials = None
    _current_material_index = 0
    _total_materials = 0
    _allowed_types = None
    _armature = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            if self._current_material_index >= len(self._materials):
                # Cleanup and finish
                context.window_manager.event_timer_remove(self._timer)
                context.scene.vrm_normal_map_props.progress = 0.0
                self.report({'INFO'}, "Normal map generation completed")
                context.area.tag_redraw()
                return {'FINISHED'}

            mat = self._materials[self._current_material_index]
            self._current_material_index += 1

            # Update progress
            context.scene.vrm_normal_map_props.progress = (self._current_material_index / self._total_materials) * 100.0

            # Process material
            if not any(word in mat.name.upper() for word in self._allowed_types):
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            try:
                mtoon = mat.vrm_addon_extension.mtoon1
            except AttributeError:
                self.report({'WARNING'}, f"VRM MToon extension not found for material {mat.name}")
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            try:
                lit_color_image = mtoon.pbr_metallic_roughness.base_color_texture.index.source
            except AttributeError:
                self.report({'WARNING'}, f"Base Color Texture not found in {mat.name}")
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            if not lit_color_image:
                self.report({'WARNING'}, f"Base Color Texture image is invalid in {mat.name}")
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            width, height = lit_color_image.size
            normal_map_image = bpy.data.images.new(name=f"{mat.name}_normal", width=width, height=height, alpha=False)

            # Extract height map
            pixels = np.array(lit_color_image.pixels).reshape(height, width, 4)
            height_map = (pixels[:,:,0] + pixels[:,:,1] + pixels[:,:,2]) / 3

            # Compute gradients
            dx = sobel_custom(height_map, axis=1)
            dy = sobel_custom(height_map, axis=0)

            # Apply normal strength and flip if enabled
            props = context.scene.vrm_normal_map_props
            strength = props.normal_strength
            flip_factor = -1.0 if props.flip_normals else 1.0
            nx = -dx * strength * flip_factor
            ny = -dy * strength * flip_factor
            nz = np.ones_like(nx)

            # Normalize normals
            normal = np.stack([nx, ny, nz], axis=2)
            norm = np.linalg.norm(normal, axis=2, keepdims=True)
            normal = normal / np.where(norm == 0, 1, norm)

            # Create DirectX normal map
            color = np.zeros((height, width, 4), dtype=np.float32)
            color[:,:,0] = 0.5 + 0.5 * normal[:,:,0]  # R = X
            color[:,:,1] = 0.5 - 0.5 * normal[:,:,1]  # G = -Y (DirectX)
            color[:,:,2] = 0.5 + 0.5 * normal[:,:,2]  # B = Z
            color[:,:,3] = 1.0

            normal_map_image.pixels = color.ravel()

            # Update normal texture
            try:
                mtoon.normal_texture.index.source = normal_map_image
                mtoon.normal_texture.scale = 1.0
                self.report({'INFO'}, f"Updated normal map for material {mat.name}")
            except AttributeError:
                self.report({'WARNING'}, f"Failed to update normal texture for {mat.name}")

            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        props = context.scene.vrm_normal_map_props

        # Find VRM armature
        self._armature = None
        for obj in bpy.data.objects:
            if obj.type == 'ARMATURE' and any(child.type == 'MESH' for child in obj.children):
                self._armature = obj
                break

        if not self._armature:
            self.report({'ERROR'}, "No VRM 1.0 armature found in the scene")
            return {'CANCELLED'}

        # Select armature
        bpy.ops.object.select_all(action='DESELECT')
        self._armature.select_set(True)
        context.view_layer.objects.active = self._armature

        # Get meshes
        meshes = [child for child in self._armature.children if child.type == 'MESH']
        if not meshes:
            self.report({'ERROR'}, "No mesh objects found under the VRM armature")
            return {'CANCELLED'}

        # Collect materials
        self._materials = list(set(mat for mesh in meshes for mat in mesh.data.materials if mat))
        self._total_materials = len(self._materials)
        self._current_material_index = 0

        # Set allowed material types
        self._allowed_types = []
        if props.enable_skin:
            self._allowed_types.append("SKIN")
        if props.enable_cloth:
            self._allowed_types.append("CLOTH")
        if props.enable_hair:
            self._allowed_types.append("HAIR")

        if not self._allowed_types:
            self.report({'ERROR'}, "No material types selected (SKIN, CLOTH, HAIR)")
            return {'CANCELLED'}

        # Start timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        props.progress = 0.0
        self.report({'INFO'}, "Started normal map generation...")
        return {'RUNNING_MODAL'}

# Property group for settings
class VRMNormalMapProperties(PropertyGroup):
    enable_skin: BoolProperty(
        name="Process SKIN Materials",
        description="Generate normal maps for materials containing 'SKIN'",
        default=True
    )
    enable_cloth: BoolProperty(
        name="Process CLOTH Materials",
        description="Generate normal maps for materials containing 'CLOTH'",
        default=True
    )
    enable_hair: BoolProperty(
        name="Process HAIR Materials",
        description="Generate normal maps for materials containing 'HAIR'",
        default=True
    )
    normal_strength: FloatProperty(
        name="Normal Strength",
        description="Strength of the normal map effect",
        default=1.0,
        min=0.1,
        max=10.0
    )
    flip_normals: BoolProperty(
        name="Flip Normals",
        description="Invert the normal map effect (flip embossing direction)",
        default=False
    )
    progress: FloatProperty(
        name="Progress",
        description="Progress of normal map generation",
        default=0.0,
        min=0.0,
        max=100.0,
        subtype='PERCENTAGE',
        options={'HIDDEN'}
    )

# Panel in the Sidebar
class VRM_PT_NormalMapGenerator(Panel):
    bl_label = "VRM Normal Map Generator"
    bl_idname = "PT_VRMNormalMapGenerator"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VRM'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return True

    def draw_header(self, context):
        self.layout.label(text="", icon='TEXTURE')

    def draw(self, context):
        layout = self.layout
        props = context.scene.vrm_normal_map_props

        layout.label(text="Material Types:")
        layout.prop(props, "enable_skin")
        layout.prop(props, "enable_cloth")
        layout.prop(props, "enable_hair")

        layout.label(text="Settings:")
        layout.prop(props, "normal_strength")
        layout.prop(props, "flip_normals")

        # Progress bar
        if props.progress > 0.0:
            layout.label(text=f"Progress: {props.progress:.1f}%")
            layout.progress(factor=props.progress / 100.0)

        layout.operator("vrm.generate_normal_maps", text="Generate Normal Maps")

# Register classes
classes = (
    VRM_OT_GenerateNormalMaps,
    VRMNormalMapProperties,
    VRM_PT_NormalMapGenerator,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.vrm_normal_map_props = PointerProperty(type=VRMNormalMapProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.vrm_normal_map_props

if __name__ == "__main__":
    register()