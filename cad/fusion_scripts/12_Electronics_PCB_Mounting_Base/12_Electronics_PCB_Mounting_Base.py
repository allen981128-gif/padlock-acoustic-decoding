import adsk.core
import adsk.fusion
import traceback
import math


COMP_NAME = '12_Electronics_PCB_Mounting_Base'


BASE_W_MM = 145.0
BASE_D_MM = 155.0
BASE_T_MM = 6.0

POST_H_MM = 6.0
POST_D_MM = 7.5

M3_THROUGH_D_MM = 3.4
M3_NUT_AF_MM = 5.5
M3_NUT_CLEAR_MM = 0.15
M3_NUT_POCKET_DEPTH_MM = 2.5

BREADBOARD_W_MM = 55.6
BREADBOARD_D_MM = 83.4
BREADBOARD_X_MM = 81.4
BREADBOARD_Y_MM = 58.02
BREADBOARD_CLEARANCE_MM = 0.4
BREADBOARD_RECESS_DEPTH_MM = 1.0

TMC_SIZE_MM = 42.72
TMC_HOLE_PITCH_MM = 35.27
TMC_X_MM = 16.81
TMC_UPPER_Y_MM = 103.72
TMC_LOWER_Y_MM = 53.0

BUCK_W_MM = 60.34
BUCK_D_MM = 37.0
BUCK_HOLE_PITCH_X_MM = 53.22
BUCK_HOLE_PITCH_Y_MM = 30.5
BUCK_X_MM = 8.0
BUCK_Y_MM = 8.0


def mm(value):
    return value / 10.0


def new_component(root, name):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = name
    return comp


def move_body(comp, body, dx, dy, dz):
    objs = adsk.core.ObjectCollection.create()
    objs.add(body)

    mat = adsk.core.Matrix3D.create()
    mat.translation = adsk.core.Vector3D.create(dx, dy, dz)

    move_input = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(move_input)


def make_box(comp, name, x0, x1, y0, y1, z0, z1):
    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.name = name + '_Sketch'

    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(x0, y0, 0),
        adsk.core.Point3D.create(x1, y1, 0)
    )

    profile = sketch.profiles.item(sketch.profiles.count - 1)

    ext_input = comp.features.extrudeFeatures.createInput(
        profile,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_input.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByReal(z1 - z0)
    )

    feature = comp.features.extrudeFeatures.add(ext_input)
    body = feature.bodies.item(0)
    body.name = name

    if abs(z0) > 1e-9:
        move_body(comp, body, 0, 0, z0)

    sketch.isVisible = False
    return body


def make_cylinder(comp, name, cx, cy, z0, diameter, height):
    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.name = name + '_Sketch'

    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(cx, cy, 0),
        diameter / 2.0
    )

    profile = sketch.profiles.item(sketch.profiles.count - 1)

    ext_input = comp.features.extrudeFeatures.createInput(
        profile,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_input.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByReal(height)
    )

    feature = comp.features.extrudeFeatures.add(ext_input)
    body = feature.bodies.item(0)
    body.name = name

    if abs(z0) > 1e-9:
        move_body(comp, body, 0, 0, z0)

    sketch.isVisible = False
    return body


def make_hex_prism(comp, name, cx, cy, z0, flat_to_flat, height):
    radius = flat_to_flat / math.sqrt(3.0)

    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.name = name + '_Sketch'

    points = []
    for i in range(6):
        angle = math.radians(30.0 + 60.0 * i)
        points.append(
            adsk.core.Point3D.create(
                cx + radius * math.cos(angle),
                cy + radius * math.sin(angle),
                0
            )
        )

    lines = sketch.sketchCurves.sketchLines
    for i in range(6):
        lines.addByTwoPoints(points[i], points[(i + 1) % 6])

    profile = sketch.profiles.item(sketch.profiles.count - 1)

    ext_input = comp.features.extrudeFeatures.createInput(
        profile,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_input.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByReal(height)
    )

    feature = comp.features.extrudeFeatures.add(ext_input)
    body = feature.bodies.item(0)
    body.name = name

    if abs(z0) > 1e-9:
        move_body(comp, body, 0, 0, z0)

    sketch.isVisible = False
    return body


def combine(comp, target, tools, operation):
    collection = adsk.core.ObjectCollection.create()

    for tool in tools:
        if tool:
            collection.add(tool)

    if collection.count == 0:
        return target

    combine_input = comp.features.combineFeatures.createInput(
        target,
        collection
    )
    combine_input.operation = operation
    combine_input.isKeepToolBodies = False
    comp.features.combineFeatures.add(combine_input)

    return target


def board_hole_centres(x, y, width, depth, pitch_x, pitch_y):
    edge_x = (width - pitch_x) / 2.0
    edge_y = (depth - pitch_y) / 2.0

    return [
        (x + edge_x, y + edge_y),
        (x + edge_x + pitch_x, y + edge_y),
        (x + edge_x, y + edge_y + pitch_y),
        (x + edge_x + pitch_x, y + edge_y + pitch_y)
    ]


def add_posts(comp, plate, prefix, centres):
    tools = []
    total_h = mm(BASE_T_MM + POST_H_MM)

    for index, (cx_mm, cy_mm) in enumerate(centres, start=1):
        tools.append(
            make_cylinder(
                comp,
                '{}_Post_{:02d}'.format(prefix, index),
                mm(cx_mm),
                mm(cy_mm),
                0,
                mm(POST_D_MM),
                total_h
            )
        )

    combine(
        comp,
        plate,
        tools,
        adsk.fusion.FeatureOperations.JoinFeatureOperation
    )


def add_m3_holes_and_nut_pockets(comp, plate, prefix, centres):
    tools = []

    total_h_mm = BASE_T_MM + POST_H_MM
    through_z0_mm = -0.5
    through_h_mm = total_h_mm + 1.0

    pocket_af_mm = M3_NUT_AF_MM + M3_NUT_CLEAR_MM
    pocket_z0_mm = -0.05
    pocket_h_mm = M3_NUT_POCKET_DEPTH_MM + 0.05

    for index, (cx_mm, cy_mm) in enumerate(centres, start=1):
        tools.append(
            make_cylinder(
                comp,
                '{}_Through_{:02d}'.format(prefix, index),
                mm(cx_mm),
                mm(cy_mm),
                mm(through_z0_mm),
                mm(M3_THROUGH_D_MM),
                mm(through_h_mm)
            )
        )

        tools.append(
            make_hex_prism(
                comp,
                '{}_Nut_Pocket_Back_{:02d}'.format(prefix, index),
                mm(cx_mm),
                mm(cy_mm),
                mm(pocket_z0_mm),
                mm(pocket_af_mm),
                mm(pocket_h_mm)
            )
        )

    combine(
        comp,
        plate,
        tools,
        adsk.fusion.FeatureOperations.CutFeatureOperation
    )


def add_breadboard_recess(comp, plate):
    clearance = BREADBOARD_CLEARANCE_MM
    depth = BREADBOARD_RECESS_DEPTH_MM

    x0 = BREADBOARD_X_MM - clearance
    x1 = BREADBOARD_X_MM + BREADBOARD_W_MM + clearance
    y0 = BREADBOARD_Y_MM - clearance
    y1 = BREADBOARD_Y_MM + BREADBOARD_D_MM + clearance

    tool = make_box(
        comp,
        'Breadboard_Recess_Cut',
        mm(x0),
        mm(x1),
        mm(y0),
        mm(y1),
        mm(BASE_T_MM - depth),
        mm(BASE_T_MM + 0.1)
    )

    combine(
        comp,
        plate,
        [tool],
        adsk.fusion.FeatureOperations.CutFeatureOperation
    )


def run(context):
    ui = None

    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)

        if not design:
            ui.messageBox('Open a Fusion design first.')
            return

        root = design.rootComponent
        comp = new_component(root, COMP_NAME)

        plate = make_box(
            comp,
            '12_PRINT_Electronics_PCB_Mounting_Base',
            0,
            mm(BASE_W_MM),
            0,
            mm(BASE_D_MM),
            0,
            mm(BASE_T_MM)
        )

        add_breadboard_recess(comp, plate)

        tmc_upper_centres = board_hole_centres(
            TMC_X_MM,
            TMC_UPPER_Y_MM,
            TMC_SIZE_MM,
            TMC_SIZE_MM,
            TMC_HOLE_PITCH_MM,
            TMC_HOLE_PITCH_MM
        )

        tmc_lower_centres = board_hole_centres(
            TMC_X_MM,
            TMC_LOWER_Y_MM,
            TMC_SIZE_MM,
            TMC_SIZE_MM,
            TMC_HOLE_PITCH_MM,
            TMC_HOLE_PITCH_MM
        )

        buck_centres = board_hole_centres(
            BUCK_X_MM,
            BUCK_Y_MM,
            BUCK_W_MM,
            BUCK_D_MM,
            BUCK_HOLE_PITCH_X_MM,
            BUCK_HOLE_PITCH_Y_MM
        )

        add_posts(comp, plate, 'TMC2209_Upper', tmc_upper_centres)
        add_posts(comp, plate, 'TMC2209_Lower', tmc_lower_centres)
        add_posts(comp, plate, 'Buck_Converter', buck_centres)

        add_m3_holes_and_nut_pockets(
            comp,
            plate,
            'TMC2209_Upper',
            tmc_upper_centres
        )
        add_m3_holes_and_nut_pockets(
            comp,
            plate,
            'TMC2209_Lower',
            tmc_lower_centres
        )
        add_m3_holes_and_nut_pockets(
            comp,
            plate,
            'Buck_Converter',
            buck_centres
        )

        try:
            design.snapshots.add()
        except Exception:
            pass

        app.activeViewport.fit()

        ui.messageBox(
            '12 electronics PCB mounting base created.\n\n'
            'Base: 145 x 155 x 6 mm\n'
            'Breadboard: recessed on the upper-right, vertically aligned to the midpoint between both TMC2209 boards\n'
            'TMC2209 boards: upper and middle left\n'
            'Buck converter: lower left\n'
            'M3 nut pockets: AF 5.65 mm, depth 2.50 mm\n'
            'No outer corner mounting holes'
        )

    except Exception:
        if ui:
            ui.messageBox(
                'Failed:\n{}'.format(traceback.format_exc())
            )
