import adsk.core
import adsk.fusion
import traceback


def silent_message_box(*args, **kwargs):
    return 0


def mm(v):
    return v / 10.0


def move_body(comp, body, dx, dy, dz):
    objs = adsk.core.ObjectCollection.create()
    objs.add(body)

    mat = adsk.core.Matrix3D.create()
    mat.translation = adsk.core.Vector3D.create(mm(dx), mm(dy), mm(dz))

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def create_cylinder_x(comp, name, cx, cy, cz, dia, length):
    sk = comp.sketches.add(comp.yZConstructionPlane)

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(0, mm(cy), mm(cz)),
        mm(dia / 2)
    )

    prof = sk.profiles.item(0)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(length)))

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, cx - length / 2, 0, 0)
    return body


def create_cylinder_y(comp, name, cx, cy, cz, dia, length):
    sk = comp.sketches.add(comp.xZConstructionPlane)

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(mm(cx), mm(cz), 0),
        mm(dia / 2)
    )

    prof = sk.profiles.item(0)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(length)))

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, 0, cy - length / 2, 0)
    return body


def create_box_center(comp, name, cx, cy, cz, sx, sy, sz):
    sk = comp.sketches.add(comp.xYConstructionPlane)

    sk.sketchCurves.sketchLines.addCenterPointRectangle(
        adsk.core.Point3D.create(mm(cx), mm(cy), 0),
        adsk.core.Point3D.create(mm(cx + sx / 2), mm(cy + sy / 2), 0)
    )

    prof = sk.profiles.item(0)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(sz)))

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, 0, 0, cz - sz / 2)
    return body


def combine_join(comp, target, tools):
    objs = adsk.core.ObjectCollection.create()
    for t in tools:
        objs.add(t)

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)

    return target


def combine_cut(comp, target, tools):
    objs = adsk.core.ObjectCollection.create()
    for t in tools:
        objs.add(t)

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)

    return target


def run(context):
    ui = None

    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = app.activeProduct

        if not isinstance(design, adsk.fusion.Design):
            silent_message_box("请先打开 Fusion 设计文件。")
            return

        root = design.rootComponent

        occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        comp = occ.component
        comp.name = "10_O_Ring_Press_Wheel_Hub"

        # Axis = X
        # Flat rubber strip: 4mm width, 1mm thickness; groove depth 0.6mm

        hub_width = 6.0
        bore_dia = 3.2

        flange_dia = 18.0
        groove_root_dia = 16.8
        groove_width = 4.0
        flange_width = (hub_width - groove_width) / 2.0

        screw_hole_dia = 2.4
        screw_hole_len = 17.0

        # M2 nut: AF 4.0mm, thickness 1.6mm; added print clearance
        nut_slot_sx = hub_width + 1.0
        nut_slot_sy = 1.9
        nut_slot_sz = 4.3

        nut_slot_y_top = 3.7
        nut_slot_y_bottom = -3.7

        # Both M2 nut slots pass fully through the 6mm wheel width in X
        nut_slot_x_top = 0.0
        nut_slot_x_bottom = 0.0

        core = create_cylinder_x(
            comp,
            "Groove_Root_16p8mm",
            0,
            0,
            0,
            groove_root_dia,
            hub_width
        )

        left_flange = create_cylinder_x(
            comp,
            "Left_Flange_18mm",
            -(hub_width / 2 - flange_width / 2),
            0,
            0,
            flange_dia,
            flange_width
        )

        right_flange = create_cylinder_x(
            comp,
            "Right_Flange_18mm",
            (hub_width / 2 - flange_width / 2),
            0,
            0,
            flange_dia,
            flange_width
        )

        hub = combine_join(comp, core, [left_flange, right_flange])
        hub.name = "O_Ring_Hub_Base"

        bore = create_cylinder_x(
            comp,
            "Cut_3p2mm_Centre_Bore",
            0,
            0,
            0,
            bore_dia,
            hub_width + 2
        )

        screw_hole = create_cylinder_y(
            comp,
            "Cut_Dual_M2_Set_Screw_Hole",
            0,
            0,
            0,
            screw_hole_dia,
            screw_hole_len
        )

        nut_slot_top = create_box_center(
            comp,
            "Cut_Top_M2_Nut_Through_Slot_X",
            nut_slot_x_top,
            nut_slot_y_top,
            0,
            nut_slot_sx,
            nut_slot_sy,
            nut_slot_sz
        )

        nut_slot_bottom = create_box_center(
            comp,
            "Cut_Bottom_M2_Nut_Through_Slot_X",
            nut_slot_x_bottom,
            nut_slot_y_bottom,
            0,
            nut_slot_sx,
            nut_slot_sy,
            nut_slot_sz
        )

        hub = combine_cut(
            comp,
            hub,
            [bore, screw_hole, nut_slot_top, nut_slot_bottom]
        )

        hub.name = "10_PRINT_O_Ring_Hub"

        silent_message_box(
            "10 O-ring press wheel hub generated.\n\n"
            "Export only:\n"
            "10_PRINT_O_Ring_Hub\n\n"
            "Hub OD: 18mm\n"
            "Width: 6mm\n"
            "Centre bore: 3.2mm\n"
            "Flat rubber groove: 4.0mm wide x 0.6mm deep\n"
            "Hardware: 2x M2 hex nuts + 2x M2x6 cup point grub screws\n"
            "M2 nut through-slot: 7.0 x 1.9 x 4.3mm; slot centre Y +/-3.7mm"
        )

    except Exception:
        if ui:
            silent_message_box("Failed:\\n{}".format(traceback.format_exc()))