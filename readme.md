# Blender Export Scripting Guide
Everyone would like to have "the .png of 3D file formats," but such a thing doesn't exist. 3D data is too complex and every rendering engine needs a different set of information. Formats that try to support everything take a lot of work to parse. Even the code to integrate a library in your engine can become quite large for generic formats.

Say you use an OBJ loading library for your project, and later you decide you want to support skeleton animations. OBJ doesn't support skeletons, so now you have to find a new library to load a new format and redo your integration code from scratch.

If you're in control of all models you will need to load (most games, for example), making your own format and exporter that does only what you need cuts down on complexity and work. You can have Blender output a simple, predictable binary format that's easy for the engine to parse. If you need more data later, you can extend your existing exporter.

Blender makes it easy enough to get the data you're interested in, though where to find it in Blender's Python API can be hard to figure out. I was able to write my own exporter thanks to [IQM](https://github.com/lsalzman/iqm) having the most readable blender export scripts I've seen by far. I recommend referencing those in addition to this guide. 

This repo includes a complete export script that produces files for meshes and skeleton animations. The file format has no name, and looks like this:
```
Vertex {
	f32 positions[3]
	f32 UVs[2]
	f32 normals[3]
	u8 bone_indeces[4] (if hasJointBindings)
	f32 bone_weights[4] (if hasJointBindings)
}

file: Mesh {
	u32 faceCount
	u32 vertexCount
	bool8 hasUVs
	bool8 hasNormals
	bool8 hasJointBindings
	u16 faces[3 * faceCount]
	Vertex vertices[vertexCount]
}

SkeletonJoint {
	u32 parent index
	f32 model_space_inverse_bind_pose_matrix[16]
}

AnimationJoint {
	f32 position[3]
	f32 rotationQuaternion[4]
	f32 scale[3]
}

AnimationFrame {
	AnimationJoint joints[skeletonJointCount]
}

Animation {
	uint32 frameCount
	uint32 nameLength
	char8 name[nameLength]
	Frame frames[frameCount]
}

file: Skeleton {
	u32 skeletonJointCount
	SkeletonJoint joints[skeletonJointCount]
	u32 animation_count
	Animation animations[animationCount]
}
```
The example code in this text omits some lines from the complete export script in order to focus on one topic at a time. When comparing your implementation to this one, reference the complete script.

# Export UI
You could make a proper export dialog, but making it a panel allows for one-click export and is very nice for rapid iterating, so that's what this guide will show you how to do.

## Making the Panel
Metadata about the script and where its UI is located is defined by a magic `bl_info` dictionary
```python
bl_info = {
    "name": "Game Asset Exporter",
    "author": "Your Name",
    "version": (2022, 7, 18),
    "blender": (3, 2, 1),
    "location": "Properties > Object > Export",
    "description": "One-click export game asset files.",
    "category": "Export"}
```
A Property Group stores configuration for the exporter. A button to do an action is connected to an Operator class. A Panel class's draw method defines the order in which configuration UI and operator buttons are displayed.

This exporter's properties are the mesh file path, skeleton and animations file path, and drop-down boxes to redefine Forward and Up axes.
```python
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
		# Do stuff...
		return {'FINISHED'}

class ExportSkeletonOperator(bpy.types.Operator):
	bl_idname = "object.export_skeleton"
	bl_label = "Export Skeleton and Animations"
	def execute(self, context):
		# Do stuff...
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
```

Finally, you need to register these classes with Blender, and tell it how to clean up if the user disables this export plugin.
```python
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
```

# Working with Objects

## Getting Selected Objects
Artists may have a lot of objects on the side they created while making the final mesh, or multiple game objects in the file. Many exporters have an option for only exporting the selected meshes.
```python
meshList = []
for object in bpy.context.selected_objects:
	if object.type == "MESH":
		meshList.append(object)
```
You can access an [object's](https://docs.blender.org/api/current/bpy.types.Object.html) mesh with `object.to_mesh()`, but objects contain data we'll need that the mesh doesn't, so we'll leave it as-is for now.

To get armatures, check if `object.type == "ARMATURE"` instead.

## Applying Modifiers
Get the evaluated dependency graph
```python
sceneWithAppliedModifiers = bpy.context.evaluated_depsgraph_get()
```
Use it to make a copy of the object's mesh with modifiers applied
```python
mesh = object.evaluated_get(sceneWithAppliedModifiers).to_mesh(preserve_all_data_layers=True, depsgraph=bpy.context.evaluated_depsgraph_get())
```

## Reorienting Meshes
Blender's Forward, Right, and Up axes may not match the game engine's. Exporters allow you to remap these axes by selecting positive or negative X, Y, or Z axes for Forward and Up, then deriving Right from them.
Use Blender's built-in [axis_conversion](https://docs.blender.org/api/current/bpy_extras.io_utils.html#bpy_extras.io_utils.axis_conversion) function to get the final matrix
```python
return axis_conversion("-Y", "Z", bpy.context.scene.exportProperties.forwardAxis, bpy.context.scene.exportProperties.upAxis).to_4x4()
```

Apply the transformation to the mesh with matrix multiplication, which is `@` in Python
```python
mesh.transform(transformMatrix @ object.matrix_world)
```

# BMeshes
[BMesh](https://docs.blender.org/api/current/bmesh.html) allows you to do operations on a mesh in Python scripts. You can convert a regular mesh to a BMesh, modify it, then convert back.
```python
bm = bmesh.new()
bm.from_mesh(mesh)
# Do operations to the geometry...
bm.to_mesh(mesh)
```

## Triangulating Meshes
Graphics cards don't deal with quads or n-gons, only triangles. Convert all faces with more than 3 sides to triangles with a BMesh
```python
bmesh.ops.triangulate(bm, faces=bm.faces)
```

# Extracting Mesh Data
The faces of a [mesh](https://docs.blender.org/api/current/bpy.types.Mesh.html) are stored in the `polygon` property. [Polygons](https://docs.blender.org/api/current/bpy.types.MeshPolygon.html) are made up of vertices, a.k.a polygon corners, a.k.a. [loops](https://docs.blender.org/api/current/bpy.types.MeshLoops.html). Each polygon has a list of loop indices which can be used to look up vertex data. While a polygon has a list of vertex indices, these are not very useful by themselves. Loop indices allow you to associate vertex position, uv, normal, and bone bindings.
```python
for polygon in mesh.polygons:
	if len(polygon.loop_indices) == 3:
		for loopIndex in polygon.loop_indices:
			loop = mesh.loops[loopIndex]
			position = mesh.vertices[loop.vertex_index].undeformed_co
			uv = mesh.uv_layers.active.data[loop.index].uv
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
```

## Merging Duplicate Vertices
Multiple triangles may connect at the same vertex position. That doesn't mean the vertex has the same UVs (it may be on a seam) or the same normals (it may be on a sharp edge). You need to gather all the vertex data together to determine if it's a true duplicate and can be removed. Blender has a loop for every polygon vertex, whether or not it's a duplicate.

To avoid duplicate vertices, we can make a dictionary of vertices instead of an array, with the key as the vertex and value as the index. As we add faces, they are re-mapped to this de-duplicated dictionary.
```python
vertex = Vertex(position, uv, normal, jointIndices, normalizeJointWeights(jointWeights))
if vertices.get(vertex) == None:
	vertices[vertex] = len(vertices)
faceIndices.append(vertices[vertex])
```
Convert them to an array with
```python
vertices.keys()
```
Dictionaries maintain order since Python 3.7.

## Changing to Rest Position
If the mesh has an armature modifier, the current pose will be applied to vertices. Change the armature to rest pose before extracting vertex data.
```python
originalArmaturePosition = "REST"
if armature:
	originalArmaturePosition = armature.data.pose_position
	setArmaturePosition(armature, "REST")
```
After getting all the mesh data, change the armature back to the previous pose. You could just set it to "POSE", but it may have been in "REST" position already.
```python
if armature:
	setArmaturePosition(armature, originalArmaturePosition)
```

# Armature Data
An armature is a skeleton containing [bones](https://docs.blender.org/api/current/bpy.types.Bone.html). More specifically, an armature is a set of joints that are linked together. Each joint is a transform, and the joints form a tree. Animations apply additional transforms to joints over time.

My setup is to have one armature per file, and animations are made up of Blender's Actions (in the dopesheet panel, change to Action Editor). We can extract animation data by just playing the animation and getting each bone's final transform at different times.

## Extracting Bone Rest Positions
Games tend to be interested in the inverse model-space pose, since you only need the rest positions of bones when building the skinning matrix. `bone.matrix_local` is unaffected by animations.
```python
for bone in armature.data.bones:
	parentIndex = armature.data.bones.find(bone.parent.name) if bone.parent else 0
	modelSpacePose = transform @ bone.matrix_local
	inverseModelSpacePose = modelSpacePose.inverted()
```

## Setting up Animations
Iterate through the actions one at a time, and each frame in the action one at a time. I haven't seen other exporters encode the interpolation styles; they just export the current state at each frame. You could optimize this by skipping transforms that don't change.
```python
for animation in bpy.data.actions:
	armature.animation_data.action = animation
	startFrame = int(animation.frame_range.x)
	endFrame = int(animation.frame_range.y)
	for frame in range(startFrame, endFrame+1):
		bpy.context.scene.frame_set(frame)
```
Save the current frame when the script is ran and restore it when finished.

## Extracting Animation Data
`bone.matrix` contains the bone's pose with animation transforms applied. Transform each bone into a space relative to the parent (with animation transforms applied). Transform the root bone by the axis remapping matrix.
```python
for bone in armature.pose.bones:
	parentSpacePose = bone.matrix
	if bone.parent:
		parentSpacePose = bone.parent.matrix.inverted() @ bone.matrix
	else:
		parentSpacePose = axisRemapping @ bone.matrix
	translation = parentSpacePose.to_translation()
	rotation = parentSpacePose.to_quaternion()
	# Does not support negative scales
	scale = parentSpacePose.to_scale()
```

# Learning More
The easiest way to explore data Blender makes available is to open a Python Console panel and start with
```python
bpy.context.selected_objects[0]
```
To see what it contains, write
```python
dir(bpy.context.selected_objects[0])
```
Pick one that sounds interesting and keep digging.
