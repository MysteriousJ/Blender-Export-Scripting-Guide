bl_info = {
    "name": "Game Asset Exporter",
    "author": "Jacob Bell",
    "version": (2022, 7, 18),
    "blender": (3, 2, 1),
    "location": "Properties > Object > Export",
    "description": "One-click export game asset files.",
    "category": "Export"}

import bpy
import bmesh
import struct
import mathutils
import sys
from bpy.utils import (register_class, unregister_class)
from bpy.types import (Panel, PropertyGroup)
from bpy.props import (StringProperty, BoolProperty, IntProperty, FloatProperty, FloatVectorProperty, EnumProperty, PointerProperty)
from bpy_extras.io_utils import (axis_conversion)

# Set to "wb" to output binary, or "w" to output plain text
fileWriteMode = "wb"

class Vertex:
    def __init__(self, position, uv, normal, jointIndices, jointWeights):
        self.position = position
        self.uv = uv
        self.normal = normal
        self.jointIndices = jointIndices
        self.jointWeights = jointWeights
    
    def __eq__(self, other):
        return self.__dict__ == other.__dict__
    def __hash__(self):
        return hash(self.position.x)
        
class Face:
    def __init__(self, vertexIndices):
        self.vertexIndices = vertexIndices

def writeUint32(file, value):
    if fileWriteMode == "wb": file.write(struct.pack("I", value))
    else: file.write(str(value) + ' ')

def writeUint16(file, value):
    if fileWriteMode == "wb": file.write(struct.pack("H", value))
    else: file.write(str(value) + ' ')

def writeUint8(file, value):
    if fileWriteMode == "wb": file.write(struct.pack("B", value))
    else: file.write(str(value) + ' ')

def writeFloat(file, value):
    if fileWriteMode == "wb": file.write(struct.pack("f", value))
    else: file.write(str(value) + ' ')
    
def writeBool(file, value):
    if fileWriteMode == "wb": file.write(struct.pack("?", value))
    else: file.write(str(value) + ' ')

def writeString(file, text):
    if fileWriteMode == "wb": file.write(text.encode('ascii'))
    else: file.write(text)

def writeVertices(file, vertices, writeJointBindings):
    for vertex in vertices:
        writeFloat(file, vertex.position.x)
        writeFloat(file, vertex.position.y)
        writeFloat(file, vertex.position.z)
        writeFloat(file, vertex.uv[0])
        writeFloat(file, vertex.uv[1])
        writeFloat(file, vertex.normal.x)
        writeFloat(file, vertex.normal.y)
        writeFloat(file, vertex.normal.z)
        if writeJointBindings:
            for i in range(4): writeUint8(file, vertex.jointIndices[i])
            for i in range(4): writeFloat(file, vertex.jointWeights[i])

def normalizeJointWeights(weights):
    totalWeights = sum(weights)
    result = [0,0,0,0]
    if totalWeights != 0:
        for i, weight in enumerate(weights): result[i] = weight/totalWeights
    return result

def triangulateMesh(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(mesh)

def getDataFromMeshObjects(objects, armature, transformMatrix):
    vertices = {}
    faces = []
    sceneWithAppliedModifiers = bpy.context.evaluated_depsgraph_get()
    for object in objects:
        # Make a copy of the mesh with applied modifiers
        mesh = object.evaluated_get(sceneWithAppliedModifiers).to_mesh(preserve_all_data_layers=True, depsgraph=bpy.context.evaluated_depsgraph_get())
        
        mesh.transform(transformMatrix @ object.matrix_world)
        triangulateMesh(mesh)
        mesh.calc_normals_split()
        
        for polygon in mesh.polygons:
            if len(polygon.loop_indices) == 3:
                faceIndices = []
                for loopIndex in polygon.loop_indices:
                    loop = mesh.loops[loopIndex]
                    position = mesh.vertices[loop.vertex_index].undeformed_co
                    uv = mesh.uv_layers.active.data[loop.index].uv
                    uv.y = 1-uv.y
                    normal = loop.normal
                    
                    jointIndices = [0,0,0,0]
                    jointWeights = [0,0,0,0]
                    if armature:
                        for jointBindingIndex, group in enumerate(mesh.vertices[loop.vertex_index].groups):
                            if jointBindingIndex < 4:
                                groupIndex = group.group
                                boneName = object.vertex_groups[groupIndex].name
                                jointIndices[jointBindingIndex] = armature.data.bones.find(boneName)
                                jointWeights[jointBindingIndex] = group.weight
                    
                    vertex = Vertex(position, uv, normal, jointIndices, normalizeJointWeights(jointWeights))
                    if vertices.get(vertex) == None:
                        vertices[vertex] = len(vertices)
                    faceIndices.append(vertices[vertex])
                faces.append(Face(faceIndices))
    
    return vertices.keys(), faces

def writeFaces(file, faces):
    for face in faces:
        for vertexIndex in face.vertexIndices:
            writeUint16(file, vertexIndex)

def writeJoints(file, armature, transform):
    for bone in armature.data.bones:
        writeUint8(file, armature.data.bones.find(bone.parent.name) if bone.parent else 0)
        modelSpacePose = transform @ bone.matrix_local
        inverseModelSpacePose = modelSpacePose.inverted()
        for vector in inverseModelSpacePose:
            for float in vector:
                writeFloat(file, float)

def writeAnimation(file, armature, animation, transform):
    startFrame = int(animation.frame_range.x)
    endFrame = int(animation.frame_range.y)
    armature.animation_data.action = animation
    
    writeUint32(file, endFrame-startFrame + 1)
    print(endFrame-startFrame + 1)
    writeUint32(file, len(animation.name))
    writeString(file, animation.name)
    for frame in range(startFrame, endFrame+1):
        bpy.context.scene.frame_set(frame)
        for bone in armature.pose.bones:
            parentSpacePose = bone.matrix
            if bone.parent:
                parentSpacePose = bone.parent.matrix.inverted() @ bone.matrix
            else:
                parentSpacePose = transform @ bone.matrix
            translation = parentSpacePose.to_translation()
            writeFloat(file, translation.x)
            writeFloat(file, translation.y)
            writeFloat(file, translation.z)
            rotation = parentSpacePose.to_quaternion()
            writeFloat(file, rotation.w)
            writeFloat(file, rotation.x)
            writeFloat(file, rotation.y)
            writeFloat(file, rotation.z)
            # Does not support negative scales
            scale = parentSpacePose.to_scale()
            writeFloat(file, scale.x)
            writeFloat(file, scale.y)
            writeFloat(file, scale.z)


def getSelectedMeshObjects():
    meshList = []
    for object in bpy.context.selected_objects:
        if object.type == "MESH":
            meshList.append(object)
    return meshList
            
def getSelectedArmature():
    for object in bpy.context.selected_objects:
        if object.type == "ARMATURE":
            return object
    return 0

def getAxisMappingMatrix():
    return axis_conversion("-Y", "Z", bpy.context.scene.exportProperties.forwardAxis, bpy.context.scene.exportProperties.upAxis).to_4x4()

def setArmaturePosition(armature, position):
    armature.data.pose_position = position
    armature.data.update_tag()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)

axesEnum = [("X","X","",1),("-X","-X","",2),("Y","Y","",3),("-Y","-Y","",4),("Z","Z","",5),("-Z","-Z","",6)]
    
class ExportProperties(bpy.types.PropertyGroup):
    meshPath: bpy.props.StringProperty(name="Mesh Path", subtype='FILE_PATH')
    skeletonPath: bpy.props.StringProperty(name="Skeleton+animations Path", subtype='FILE_PATH')
    forwardAxis: bpy.props.EnumProperty(name="Forward", items=axesEnum, default="-Y")
    upAxis: bpy.props.EnumProperty(name="Up", items=axesEnum, default="Z")

class ExportMeshOperator(bpy.types.Operator):
    bl_idname = "object.export_mesh"
    bl_label = "Export Mesh"
    
    def execute(self, context):
        armature = getSelectedArmature()
        
        # If the mesh has an armature modifier, the current pose will be applied to vertices, so change it to rest position
        originalArmaturePosition = "REST"
        if armature:
            originalArmaturePosition = armature.data.pose_position
            setArmaturePosition(armature, "REST")
        
        objects = getSelectedMeshObjects()
        if len(objects) > 0:
            vertices, faces = getDataFromMeshObjects(objects, armature, getAxisMappingMatrix())
            file = open(bpy.path.abspath(context.scene.exportProperties.meshPath), fileWriteMode)
            writeBool(file, armature!=0)
            writeUint16(file, len(faces))
            writeUint16(file, len(vertices))
            writeFaces(file, faces)
            writeVertices(file, vertices, armature)
        
        # Change armature back to the pose it was in.
        if armature:
            setArmaturePosition(armature, originalArmaturePosition)
        
        return {'FINISHED'}

class ExportSkeletonOperator(bpy.types.Operator):
    bl_idname = "object.export_skeleton"
    bl_label = "Export Skeleton and Animations"
    
    def execute(self, context):
        armature = getSelectedArmature()
        originalArmaturePosition = armature.data.pose_position
        originalAnimation = armature.animation_data.action
        originalFrame = bpy.context.scene.frame_current
        
        setArmaturePosition(armature, "POSE")
        skeletonFile = open(bpy.path.abspath(context.scene.exportProperties.skeletonPath), fileWriteMode)
        writeUint8(skeletonFile, len(armature.data.bones))
        writeJoints(skeletonFile, armature, getAxisMappingMatrix())
        
        writeUint32(skeletonFile, len(bpy.data.actions))
        for animation in bpy.data.actions:
            writeAnimation(skeletonFile, armature, animation, getAxisMappingMatrix())

        bpy.context.scene.frame_set(originalFrame)
        armature.animation_data.action = originalAnimation
        setArmaturePosition(armature, originalArmaturePosition)
        return {'FINISHED'}

class ExportPanel(bpy.types.Panel):
    bl_label = "Export"
    bl_idname = "OBJECT_PT_layout"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"
    
    def draw(self, context):
        self.layout.prop(context.scene.exportProperties, "meshPath")
        self.layout.prop(context.scene.exportProperties, "skeletonPath")
        self.layout.prop(context.scene.exportProperties, "forwardAxis")
        self.layout.prop(context.scene.exportProperties, "upAxis")
        self.layout.operator('object.export_mesh')
        self.layout.operator('object.export_skeleton')

def register():
    bpy.utils.register_class(ExportProperties)
    bpy.utils.register_class(ExportMeshOperator)
    bpy.utils.register_class(ExportSkeletonOperator)
    bpy.utils.register_class(ExportPanel)
    bpy.types.Scene.exportProperties = bpy.props.PointerProperty(type=ExportProperties)

def unregister():
    bpy.utils.unregister_class(ExportProperties)
    bpy.utils.unregister_class(ExportMeshOperator)
    bpy.utils.unregister_class(ExportSkeletonOperator)
    bpy.utils.unregister_class(ExportPanel)
    del bpy.types.Scene.exportProperties

if __name__ == "__main__":
    register()