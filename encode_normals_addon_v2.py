bl_info = {
    "name": "Encode Normals",
    "author": "sentharn",
    "blender": (2, 90, 0),
    "category": "Mesh",
    "version": (2, 1, 2),
}

import bpy
from mathutils import Vector, Color
from bpy.app.handlers import persistent

import gc

# Sentharn's Normal Encoder
# Based on the 'Mesh Tension' addon by Steve Miller
# https://blenderartists.org/t/revised-mesh-tension-add-on/1239091
# GPL2 license
# See LICENSE files for your rights

# globals
rendering = False
modifiers_off = False
skip = False
generative_modifiers = ['ARRAY','BEVEL','BOOLEAN', 'BUILD', 'DECIMATE','EDGE_SPLIT','MASK','MIRROR','MULTIRES','REMESH','SCREW','SKIN','SOLIDIFY','SUBSURF','TRIANGULATE','WELD','WIREFRAME']

class RENDER_OT_RenderEncodedAnimation(bpy.types.Operator):
    """ By Default there are side effects when using encoded normals and rendering from separate 
    frame than the animation. This makes sure rigs do not explode during the deptree navigation
    Runs frame_current = frame_start and then starts rendering animation
    """

    bl_label = "Render Animation (With Encoded Normals)"
    bl_idname = 'normal_encoder.render_animation'

    @classmethod
    def poll(cls, context):
        return context.scene.render.use_lock_interface

    def execute(self, context):
        context.scene.frame_current = context.scene.frame_start #Solves a side effect of rigs exploding. Should make this into a BoolProperty instead.
        bpy.ops.render.render({'dict': "override"}, 'INVOKE_DEFAULT', False, animation=True)
        return {"FINISHED"}
        
class ParticleNormalTransferPanel(bpy.types.Panel):
    bl_label = 'Particle Normals'
    bl_idname = 'MESH_PT_partnorm'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'MESH'


    def draw_header(self, context):
        if not context.scene.render.use_lock_interface:
            self.layout.enabled = False
        self.layout.prop(context.object.data.normal_props, 'enable', text='')


    def draw(self,context):
        global generative_modifiers
        if context.scene.render.use_lock_interface:
            self.layout.use_property_split = True
            ob = context.object

            row = self.layout.row()
            row.enabled = ob.data.normal_props.enable
            row.prop_search(ob.data.normal_props, 'vcol', ob.data, 'vertex_colors')
            #row.operator('id.mask_refresh',text='',icon='FILE_REFRESH')

            row = self.layout.row()
            row.enabled = ob.data.normal_props.enable
            row.prop(ob.data.normal_props, 'always_update')

            row = self.layout.row()
            row.enabled = ob.data.normal_props.enable
            row.operator(NormalUpdateNowOp.bl_idname)
            row.operator(SecretRuaidriOp.bl_idname)
        else:
            self.layout.label(text="Enable 'Render > Lock Interface' to use")


def panel_enable_checkbox(self, context):
    ob = context.object
    if 'vc_normals' not in ob.data.vertex_colors and not ob.data.normal_props.default_vcol_created:
        ob.data.vertex_colors.new(name = 'vc_normals')
        ob.data.normal_props.default_vcol_created = True

def add_render_encoded_normal_animation(self, context):
    self.layout.operator(RENDER_OT_RenderEncodedAnimation.bl_idname, text="Render Animation With Encoded Normals")



class NormalUpdateNowOp(bpy.types.Operator):
    """Encode normals to vertex group"""
    bl_idname = "mesh.encode_normals"
    bl_label = "Encode Normals"

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return (ob is not None and ob.type == 'MESH' and ob.data.normal_props.vcol)

    def execute(self, context):
        print("\n [!] encode button clicked")
        for ob in context.selected_objects:
            disable_modifiers(ob)       

        depsgraph = bpy.context.evaluated_depsgraph_get()  
        
        for ob in context.selected_objects:
            encode_normals(ob, depsgraph)
            enable_modifiers(ob)
   
        return {'FINISHED'}

    
class SecretRuaidriOp(bpy.types.Operator):
    """hi ruaidri"""
    bl_idname = "mesh.ruaidri"
    bl_label = "Ru Button"


    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return (ob is not None and ob.type == 'MESH')


    def execute(self, context):
        return {'FINISHED'}


# Modifier storage
class NormalItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name='Name')
    viewport: bpy.props.BoolProperty(name='Show Viewport')
    render: bpy.props.BoolProperty(name='Show Render')
    driver_index: bpy.props.IntProperty(name='Driver Index')
    driver_mute: bpy.props.BoolProperty(name='Driver Muted')


class NormalProps(bpy.types.PropertyGroup):
    default_vcol_created: bpy.props.BoolProperty(name = 'Default Vertex Color Layer Created', default=False)
    enable: bpy.props.BoolProperty(name = 'Enable', default=False, update=panel_enable_checkbox) #,update=call_list_refresh)
    always_update: bpy.props.BoolProperty(name = 'Always Update', default=False) #,update=call_list_refresh)
    vcol: bpy.props.StringProperty(name = 'Vertex Color Layer', default='vc_normals')
    delayed_modifiers: bpy.props.CollectionProperty(type=NormalItem)
    delayed_drivers: bpy.props.CollectionProperty(type=NormalItem)
    


# Use as a hook for anytime the rendering stars
@persistent
def render_start(scene, test):
    global rendering
    if not scene.render.use_lock_interface: return
    print('\n [!] render_start', test)
    rendering = True


# Use as a hook for anytime the rendering stops
@persistent
def render_end(scene):
    global rendering, modifiers_off
    if not scene.render.use_lock_interface: return
    rendering = False

    if modifiers_off:
        print(' [!] was interrupted while modifiers were off, restoring previous modifiers')
        objs_list = [obj for obj in bpy.data.objects if obj.type == 'MESH' and obj.data.normal_props.enable]
        for ob in objs_list:
            enable_modifiers(ob)
        modifiers_off = False
        print(' [!] modifiers restored')
    
    print(' [!] render_end')
        

def valid_driver(obj, datapath):
    global generative_modifiers
    if 'modifiers' not in datapath: return False
    path_prop, path_attr = datapath.rsplit(".", 1) # get modifiers["name"]
    try:
        modifier = obj.path_resolve(path_prop)
    except ValueError:
        print(' [!] Driver referencing modifier that no longer exists')
        return False
    if modifier.type in generative_modifiers and path_attr in ('show_viewport', 'show_render'): return True
    return False


def disable_modifiers(ob):
    global generative_modifiers
    print(' [-] disabling drivers for', ob.name)
    # disable modifiers that are generative or dependant on our vertex groups (?????)
    # store their state for restoring
    delayed_modifiers = ob.data.normal_props.delayed_modifiers
    delayed_modifiers.clear()
    
    delayed_drivers = ob.data.normal_props.delayed_drivers
    delayed_drivers.clear()
    
    def delay_modifier(m, delayed_modifiers):
        dm = delayed_modifiers.add()
        dm.name = m.name
        dm.viewport = m.show_viewport
        dm.render = m.show_render
        m.show_viewport = False
        m.show_render = False

        
    def delay_driver(d, delayed_drivers, idx):
        dd = delayed_drivers.add()
        dd.driver_index = idx
        dd.driver_muted = d.mute
        d.mute = True

    try:
        for idx, d in enumerate(ob.animation_data.drivers):
            if valid_driver(ob, d.data_path):
                 print('  |---', d.data_path, idx)
                 delay_driver(d, delayed_drivers, idx)
    except AttributeError:
        print(' [-] no drivers for', ob.name)

    print(' [-] disabling modifiers for', ob.name)      
    for m in ob.modifiers:
        if m.type in generative_modifiers:
            print('  |---', m.name)
            delay_modifier(m, delayed_modifiers)
    
    print(' [-] drivers and modifiers disabled for', ob.name)


def enable_modifiers(ob):    
    print(' [-] enabling modifiers for', ob.name)
    delayed_modifiers = ob.data.normal_props.delayed_modifiers
    for m in delayed_modifiers:
        if m.name in ob.modifiers:
            print('  |---', m.name)
            ob.modifiers[m.name].show_viewport = m.viewport
            ob.modifiers[m.name].show_render = m.render
            
    print(' [-] enabling drivers for', ob.name) 
    delayed_drivers = ob.data.normal_props.delayed_drivers
    for d in delayed_drivers:
        driver = ob.animation_data.drivers[d.driver_index]
        print('  |---', driver.data_path, d.driver_index)
        driver.mute = d.driver_mute
            
    print(' [-] drivers and modifiers enabled for', ob.name)

            
def encode_normals(ob, depsgraph):
    print(" [-] Encoding normals for ", ob)
    orig_obj = ob 
    # get evaluated (modifiers applied) version of obj  
    eval_obj = orig_obj.evaluated_get(depsgraph)

    orig_mesh = orig_obj.data
    eval_mesh = eval_obj.data

    # idk just do it ///  Allows access to  the loops - mal
    eval_mesh.calc_normals_split()

    # Mal:L Remove any possibility of active  changing during vertice selection, so lets  use direct references instead.
    eval_vertex_att = eval_mesh.vertex_colors[eval_mesh.normal_props.vcol]
    orig_vertex_att = orig_mesh.vertex_colors[orig_mesh.normal_props.vcol]

    for poly in eval_mesh.polygons:
            for loop_index in poly.loop_indices:
                normal = eval_mesh.loops[loop_index].normal.copy()
                normal = eval_obj.matrix_world.to_3x3() @ normal # @ => dot product
                normal.normalize()
                color = (normal * 0.5) + Vector((0.5,) * 3)
                del normal # this is no longer used so delete for gc and stability later.

                # shader editor only understands sRGB.
                # thanks to Bobbe on Blender Community Discord for
                # pointing me in this direction
                color = Vector(Color(color).from_scene_linear_to_srgb())
                color.resize_4d()
                
                # Copy to both original and new
                eval_vertex_att.data[loop_index].color = color
                orig_vertex_att.data[loop_index].color = color

                del color # this is no longer used so delete for gc and stability later.

    print(f" [n] orig object has {len(orig_mesh.polygons)} faces")
    print(f" [n] eval object has {len(eval_mesh.polygons)} faces")
    
    # clean up
    print(f" [n] Cleanup")
    eval_mesh.free_normals_split()
    del eval_vertex_att
    del orig_vertex_att

    gc.collect() 
    print(f" [n] Garbage Collection complete")

# pre depsgraph generation on frame change
@persistent
def frame_pre(scene):
    global skip, rendering, modifiers_off
    if skip or not rendering: return
    # If use lock is NOT enabled, lets not even TRY
    if not bpy.context.scene.render.use_lock_interface: return
            
    # only update on render
    print(' [-] frame_pre frame', bpy.context.scene.frame_current)
    # borrowed from mesh_tension addon
    modifiers_off = True
    objs_list = [obj for obj in bpy.data.objects if obj.type == 'MESH' and obj.data.normal_props.enable]
    for ob in objs_list:     
        disable_modifiers(ob)
        

# post depsgraph generation frame handler
@persistent
def frame_post(scene, depsgraph):
    global rendering, skip, modifiers_off
    if skip or not rendering: return
    # If use lock is NOT enabled, lets not even TRY
    if not bpy.context.scene.render.use_lock_interface: return

    print(' [-] frame_post frame', bpy.context.scene.frame_current)
    
    # Only update on render
    
    # Get objects with encode_normal custom prop.
    # Bonus: make encode_normal contain the vertex color layer so we can 
    # stop clobbering Col
    objs_list = [obj for obj in bpy.data.objects if obj.type == 'MESH' and obj.data.normal_props.enable]

    # iterate
    for ob in objs_list:
        encode_normals(ob, depsgraph)
        enable_modifiers(ob)
    modifiers_off = False
    print(' [-] Vertex colors updated on ', objs_list)
        

def uppend(target, handler):
    if handler in target:
        target.remove(handler)
    
    target.append(handler)

def register():
    print(' [-] Registering Encode Normals Plugin')
    
    bpy.utils.register_class(NormalItem)
    bpy.utils.register_class(NormalProps)
    bpy.utils.register_class(ParticleNormalTransferPanel)
    
    bpy.utils.register_class(NormalUpdateNowOp)
    bpy.utils.register_class(SecretRuaidriOp)
    
    bpy.utils.register_class(RENDER_OT_RenderEncodedAnimation)
    bpy.types.TOPBAR_MT_render.append(add_render_encoded_normal_animation)

    bpy.types.Mesh.normal_props = bpy.props.PointerProperty(type=NormalProps)
    
    uppend(bpy.app.handlers.render_init, render_start)
    uppend(bpy.app.handlers.render_complete, render_end)
    uppend(bpy.app.handlers.render_cancel, render_end) # Must have a cancel hook as complete does not trigger if rendering is cancelled.
    
    uppend(bpy.app.handlers.frame_change_pre, frame_pre) 
    uppend(bpy.app.handlers.frame_change_post, frame_post)
                       

    
def unregister():
    print(' [-] Unregistering Encode Normals Plugin')

    bpy.app.handlers.render_init.remove(render_start)
    bpy.app.handlers.render_complete.remove(render_end)
    bpy.app.handlers.render_cancel.remove(render_end)

    bpy.app.handlers.frame_change_pre.remove(frame_pre)
    bpy.app.handlers.frame_change_post.remove(frame_post)

    del bpy.types.Mesh.normal_props
 
    bpy.utils.unregister_class(SecretRuaidriOp)
    bpy.utils.unregister_class(NormalUpdateNowOp)

    bpy.utils.unregister_class(RENDER_OT_RenderEncodedAnimation)
    bpy.types.TOPBAR_MT_render.remove(add_render_encoded_normal_animation)
    bpy.utils.unregister_class(ParticleNormalTransferPanel)
    bpy.utils.unregister_class(NormalProps)
    bpy.utils.unregister_class(NormalItem)  


if __name__ == "__main__":
    register()
