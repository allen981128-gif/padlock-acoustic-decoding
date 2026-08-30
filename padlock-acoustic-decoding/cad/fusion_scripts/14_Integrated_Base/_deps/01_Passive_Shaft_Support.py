import adsk.core
import adsk.fusion
import traceback


def silent_message_box(*args, **kwargs):
    return 0


def mm(value):
    return value / 10.0


def vp(design, name, default_mm):
    p = design.userParameters.itemByName(name)
    if p:
        return p.value
    return mm(default_mm)


def new_comp(root, name):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = name
    return comp


def move_body(comp, body, dx, dy, dz):
    if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
        return

    objs = adsk.core.ObjectCollection.create()
    objs.add(body)

    mat = adsk.core.Matrix3D.create()
    mat.translation = adsk.core.Vector3D.create(dx, dy, dz)

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def box_z(comp, name, cx, cy, bottom_z, sx, sy, sz):
    sk = comp.sketches.add(comp.xYConstructionPlane)

    sk.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(cx - sx / 2, cy - sy / 2, 0),
        adsk.core.Point3D.create(cx + sx / 2, cy + sy / 2, 0)
    )

    prof = sk.profiles.item(0)

    ei = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )

    ei.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByReal(sz)
    )

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, 0, 0, bottom_z)
    sk.isVisible = False

    return body


def cyl_x(comp, name, cx, cy, cz, r, length):
    sk = comp.sketches.add(comp.yZConstructionPlane)

    centre = sk.modelToSketchSpace(
        adsk.core.Point3D.create(0, cy, cz)
    )

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        centre,
        r
    )

    prof = sk.profiles.item(0)

    ei = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )

    ei.setSymmetricExtent(
        adsk.core.ValueInput.createByReal(length),
        True
    )

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, cx, 0, 0)
    sk.isVisible = False

    return body


def fillet(comp, body, r):
    edges = adsk.core.ObjectCollection.create()

    for e in body.edges:
        edges.add(e)

    if edges.count == 0:
        return

    try:
        fi = comp.features.filletFeatures.createInput()
        fi.addConstantRadiusEdgeSet(
            edges,
            adsk.core.ValueInput.createByReal(r),
            True
        )
        comp.features.filletFeatures.add(fi)
    except Exception:
        pass


def cut_one(comp, target, cutter):
    objs = adsk.core.ObjectCollection.create()
    objs.add(cutter)

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)


def ring_x(comp, name, cx, cy, cz, outer_r, inner_r, width):
    outer = cyl_x(
        comp,
        name,
        cx,
        cy,
        cz,
        outer_r,
        width
    )

    inner = cyl_x(
        comp,
        'cut_' + name + '_Inner',
        cx,
        cy,
        cz,
        inner_r,
        width + mm(1.0)
    )

    cut_one(comp, outer, inner)
    outer.name = name

    fillet(comp, outer, mm(0.06))
    return outer


def add_support_base(comp, design):
    pitch = vp(design, 'dial_pitch', 8.48)

    bearing_width = mm(4.0)
    bearing_od = mm(8.0)
    bearing_radius = bearing_od / 2

    shim_clear_each_side = mm(0.6)
    end_margin = mm(5.0)

    mic_thickness = vp(design, 'mic_thickness', 15.13)
    mic_clearance = mm(4.8)

    length_x = 3 * pitch + bearing_width + 2 * end_margin
    width_y = mm(12.0)
    height_z = mic_thickness + mic_clearance

    window_width_x = bearing_width + 2 * shim_clear_each_side
    window_length_y = bearing_od + mm(1.6)
    window_depth_z = bearing_od + mm(1.2)

    window_bottom_z = height_z - window_depth_z

    top_to_shaft = mm(3.2)
    shaft_z = height_z - top_to_shaft

    if top_to_shaft >= bearing_radius:
        raise RuntimeError('Shaft hole is too low.')

    shaft_hole_radius = mm(1.55)

    bearing_xs = [
        -1.5 * pitch,
        -0.5 * pitch,
        0.5 * pitch,
        1.5 * pitch
    ]

    base = box_z(
        comp,
        '01_Support_Base',
        0,
        0,
        0,
        length_x,
        width_y,
        height_z
    )

    fillet(comp, base, mm(0.35))

    shaft_hole = cyl_x(
        comp,
        'cut_01_Shaft_Hole_3p1mm',
        0,
        0,
        shaft_z,
        shaft_hole_radius,
        length_x + mm(2.0)
    )

    cut_one(comp, base, shaft_hole)

    for i, x in enumerate(bearing_xs):
        window = box_z(
            comp,
            f'cut_01_Top_Window_{i + 1}',
            x,
            0,
            window_bottom_z,
            window_width_x,
            window_length_y,
            window_depth_z + mm(0.5)
        )

        cut_one(comp, base, window)

    return {
        'pitch': pitch,
        'bearing_xs': bearing_xs,
        'shaft_z': shaft_z,
        'length_x': length_x
    }


def add_shaft_bearings_and_spacers(comp, data):
    shaft_z = data['shaft_z']
    bearing_xs = data['bearing_xs']
    pitch = data['pitch']

    shaft_len = mm(75.0)
    shaft_r = mm(1.5)

    bearing_outer_r = mm(4.0)
    bearing_inner_r = mm(1.55)
    bearing_width = mm(4.0)

    shim_thick = mm(0.3)
    shim_outer_r = mm(2.55)
    shim_inner_r = mm(1.55)

    spacer_outer_r = mm(2.55)
    spacer_inner_r = mm(1.55)

    shaft = cyl_x(
        comp,
        '01_Shaft_3mm_Reference',
        0,
        0,
        shaft_z,
        shaft_r,
        shaft_len
    )

    fillet(comp, shaft, mm(0.03))

    for i, x in enumerate(bearing_xs):
        ring_x(
            comp,
            f'01_693ZZ_Bearing_Reference_{i + 1}',
            x,
            0,
            shaft_z,
            bearing_outer_r,
            bearing_inner_r,
            bearing_width
        )

        left_shim_x = x - bearing_width / 2 - shim_thick / 2
        right_shim_x = x + bearing_width / 2 + shim_thick / 2

        ring_x(
            comp,
            f'01_Left_Shim_Reference_{i + 1}',
            left_shim_x,
            0,
            shaft_z,
            shim_outer_r,
            shim_inner_r,
            shim_thick
        )

        ring_x(
            comp,
            f'01_Right_Shim_Reference_{i + 1}',
            right_shim_x,
            0,
            shaft_z,
            shim_outer_r,
            shim_inner_r,
            shim_thick
        )

    for i in range(3):
        x0 = bearing_xs[i]
        x1 = bearing_xs[i + 1]

        gap_start = x0 + bearing_width / 2 + shim_thick
        gap_end = x1 - bearing_width / 2 - shim_thick

        spacer_len = gap_end - gap_start
        spacer_x = (gap_start + gap_end) / 2

        if spacer_len > mm(0.5):
            ring_x(
                comp,
                f'01_Spacer_Reference_{i + 1}',
                spacer_x,
                0,
                shaft_z,
                spacer_outer_r,
                spacer_inner_r,
                spacer_len
            )


def run(context):
    ui = None

    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)

        if not design:
            silent_message_box('Open a Fusion design first.')
            return

        comp = new_comp(
            design.rootComponent,
            '01_Passive_Shaft_Support'
        )

        data = add_support_base(comp, design)
        add_shaft_bearings_and_spacers(comp, data)

        silent_message_box('01 passive shaft support created.')

    except Exception:
        if ui:
            silent_message_box(traceback.format_exc())