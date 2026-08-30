import adsk.core
import adsk.fusion
import traceback
import math


def silent_message_box(*args, **kwargs):
    return 0


def mm(v):
    return v / 10.0


def vp(design, name, default_mm):
    p = design.userParameters.itemByName(name)
    if p:
        return p.value

    p = design.userParameters.add(
        name,
        adsk.core.ValueInput.createByString(str(default_mm) + ' mm'),
        'mm',
        ''
    )
    return p.value


def clean_existing(root, prefix):
    occs = []

    for i in range(root.occurrences.count):
        occ = root.occurrences.item(i)
        if occ.component.name.startswith(prefix):
            occs.append(occ)

    for occ in occs:
        occ.deleteMe()


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


def rotate_body(comp, body, angle_deg, axis):
    objs = adsk.core.ObjectCollection.create()
    objs.add(body)

    mat = adsk.core.Matrix3D.create()
    mat.setToRotation(
        math.radians(angle_deg),
        axis,
        adsk.core.Point3D.create(0, 0, 0)
    )

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def make_box(comp, name, x, y, z, sx, sy, sz):
    sketch = comp.sketches.add(comp.xYConstructionPlane)

    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(x, y, 0),
        adsk.core.Point3D.create(x + sx, y + sy, 0)
    )

    prof = sketch.profiles.item(0)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByReal(sz)
    )

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, 0, 0, z)
    return body


def make_cyl_z(comp, name, cx, cy, z, r, h):
    sketch = comp.sketches.add(comp.xYConstructionPlane)

    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(cx, cy, 0),
        r
    )

    prof = sketch.profiles.item(0)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByReal(h)
    )

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, 0, 0, z)
    return body


def make_cyl_x(comp, name, x, cy, cz, r, length):
    body = make_cyl_z(comp, name, 0, 0, 0, r, length)

    rotate_body(
        comp,
        body,
        90,
        adsk.core.Vector3D.create(0, 1, 0)
    )

    move_body(comp, body, x, cy, cz)
    return body


def largest_profile(sketch):
    best = None
    best_area = -1

    for i in range(sketch.profiles.count):
        prof = sketch.profiles.item(i)
        area = prof.areaProperties().area

        if area > best_area:
            best = prof
            best_area = area

    return best


def make_slider_with_holes(comp, name, x, y, z, sx, sy, sz, hole_space, hole_r):
    sketch = comp.sketches.add(comp.xYConstructionPlane)
    lines = sketch.sketchCurves.sketchLines
    circles = sketch.sketchCurves.sketchCircles

    lines.addTwoPointRectangle(
        adsk.core.Point3D.create(x, y, 0),
        adsk.core.Point3D.create(x + sx, y + sy, 0)
    )

    cx = x + sx / 2
    cy = y + sy / 2
    half = hole_space / 2

    for dx in [-half, half]:
        for dy in [-half, half]:
            circles.addByCenterRadius(
                adsk.core.Point3D.create(cx + dx, cy + dy, 0),
                hole_r
            )

    prof = largest_profile(sketch)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByReal(sz)
    )

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, 0, 0, z)
    return body


def make_appearance(app, design, name, r, g, b):
    old = design.appearances.itemByName(name)
    if old:
        return old

    base = None

    for i in range(app.materialLibraries.count):
        lib = app.materialLibraries.item(i)
        if lib.appearances.count > 0:
            base = lib.appearances.item(0)
            break

    if not base:
        return None

    ap = design.appearances.addByCopy(base, name)

    try:
        color = adsk.core.Color.create(r, g, b, 255)
        props = ap.appearanceProperties

        for i in range(props.count):
            prop = props.item(i)
            cp = adsk.core.ColorProperty.cast(prop)
            if cp:
                cp.value = color
    except Exception:
        pass

    return ap


def apply_ap(body, ap):
    if ap:
        body.appearance = ap


def combine_cut(comp, target, tools):
    objs = adsk.core.ObjectCollection.create()

    for tool in tools:
        if tool:
            objs.add(tool)

    if objs.count == 0:
        return target

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)
    return target


def place_point_xy(x, y, pivot_x, pivot_y):
    if not FLIP_RAIL_180_ABOUT_SLIDER:
        return x, y

    return (
        2 * pivot_x - x,
        2 * pivot_y - y
    )


def add_rail_mount_holes(comp, base, base_x, right_plate_x, y0, rail_w, z0, base_h, pivot_x, pivot_y):
    hole_r = mm(RAIL_MOUNT_HOLE_D_MM / 2.0)
    x_offset = mm(RAIL_MOUNT_X_FROM_LIMIT_EDGE_MM)
    y_offset = mm(RAIL_MOUNT_Y_FROM_SIDE_MM)

    raw_xs = [
        base_x + x_offset,
        right_plate_x - x_offset
    ]

    raw_ys = [
        y0 + y_offset,
        y0 + rail_w - y_offset
    ]

    tools = []
    cut_z = z0 - mm(0.5)
    cut_h = base_h + mm(1.0)

    n = 1
    for raw_x in raw_xs:
        for raw_y in raw_ys:
            hx, hy = place_point_xy(raw_x, raw_y, pivot_x, pivot_y)
            tools.append(
                make_cyl_z(
                    comp,
                    'cut_04_Rail_Mount_Hole_' + str(n),
                    hx,
                    hy,
                    cut_z,
                    hole_r,
                    cut_h
                )
            )
            n += 1

    combine_cut(comp, base, tools)


def find_occ(root, prefixes):
    if isinstance(prefixes, str):
        prefixes = [prefixes]

    occs = root.allOccurrences

    for i in range(occs.count):
        occ = occs.item(i)

        for prefix in prefixes:
            if occ.component and occ.component.name.startswith(prefix):
                return occ

            if occ.name.startswith(prefix):
                return occ

    return None


def bbox_center(bb):
    return adsk.core.Point3D.create(
        (bb.minPoint.x + bb.maxPoint.x) / 2,
        (bb.minPoint.y + bb.maxPoint.y) / 2,
        (bb.minPoint.z + bb.maxPoint.z) / 2
    )


def body_world_bbox(occ, body):
    try:
        proxy = body.createForAssemblyContext(occ)
        return proxy.boundingBox
    except Exception:
        return body.boundingBox


def get_body_bbox_by_keywords(occ, keywords):
    keywords = [k.lower() for k in keywords]

    for i in range(occ.component.bRepBodies.count):
        body = occ.component.bRepBodies.item(i)
        name = body.name.lower()

        for key in keywords:
            if key in name:
                return body_world_bbox(occ, body)

    return occ.boundingBox


def get_base_top_z(root):
    base_occ = find_occ(root, '13_Main_Base_Plate')

    if not base_occ:
        return 0.0

    return base_occ.boundingBox.maxPoint.z


def get_position_from_model(root, total_len, rail_w):
    lock_occ = find_occ(root, '02_Padlock_Reference')
    if not lock_occ:
        raise RuntimeError('02_Padlock_Reference not found. Run 01 first.')

    drive_occ = find_occ(root, '03_Drive_Head')
    if not drive_occ:
        raise RuntimeError('03_Drive_Head not found. Run 07 first.')

    lock_bb = get_body_bbox_by_keywords(
        lock_occ,
        [
            '02_body_silver',
            'body_silver'
        ]
    )

    motor_bb = get_body_bbox_by_keywords(
        drive_occ,
        [
            '03_01_motor_body_28p5x28p2x28p2',
            'motor_body'
        ]
    )

    lock_c = bbox_center(lock_bb)
    motor_c = bbox_center(motor_bb)
    base_top_z = get_base_top_z(root)

    x0 = lock_c.x - total_len / 2
    y0 = motor_c.y - rail_w / 2
    z0 = base_top_z

    return x0, y0, z0, lock_c, motor_c, base_top_z




FLIP_RAIL_180_ABOUT_SLIDER = True

RAIL_MOUNT_HOLE_D_MM = 3.77
RAIL_MOUNT_X_FROM_LIMIT_EDGE_MM = 35.15
RAIL_MOUNT_Y_FROM_SIDE_MM = 6.15


def place_box_xy(x, y, sx, sy, pivot_x, pivot_y):
    if not FLIP_RAIL_180_ABOUT_SLIDER:
        return x, y

    return (
        2 * pivot_x - (x + sx),
        2 * pivot_y - (y + sy)
    )


def place_cyl_x_start(x, y, length, pivot_x, pivot_y):
    if not FLIP_RAIL_180_ABOUT_SLIDER:
        return x, y

    return (
        2 * pivot_x - (x + length),
        2 * pivot_y - y
    )

def run(context):
    ui = None

    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent

        clean_existing(root, '04_X_Axis_Linear_Rail')

        comp = new_comp(root, '04_X_Axis_Linear_Rail')

        # Default material only. No custom appearances assigned.

        # Main dimensions
        total_len = vp(design, 'lr06v8_total_len', 225)
        rail_w = vp(design, 'lr06v8_rail_w', 30)

        # Position only
        x0, y0, z0, lock_c, motor_c, base_top_z = get_position_from_model(
            root,
            total_len,
            rail_w
        )

        motor_len = vp(design, 'lr06v8_motor_len', 30)
        motor_w = vp(design, 'lr06v8_motor_w', 28)
        motor_h = vp(design, 'lr06v8_motor_h', 28)
        motor_lift_z = vp(design, 'lr06v8_motor_lift_z', 6)

        plate_t = vp(design, 'lr06v8_plate_t', 5)
        left_plate_h = vp(design, 'lr06v8_left_plate_h', 34)
        right_plate_h = vp(design, 'lr06v8_right_plate_h', 28)

        base_h = vp(design, 'lr06v8_base_h', 13)

        slider_len = vp(design, 'lr06v8_slider_len', 32)
        slider_w = vp(design, 'lr06v8_slider_w', 30)
        slider_gap_z = vp(design, 'lr06v8_slider_gap_z', 3)
        slider_cx = vp(design, 'lr06v8_slider_cx', 127.5)

        shaft_r = vp(design, 'lr06v8_shaft_r', 1.8)
        shaft_z = vp(design, 'lr06v8_shaft_z', 20)

        m3_r = vp(design, 'lr06v8_m3_r', 1.6)
        m3_space = vp(design, 'lr06v8_m3_space', 20)

        # Derived
        motor_x = x0
        motor_y = y0 + (rail_w - motor_w) / 2
        motor_z = z0 + motor_lift_z

        left_plate_x = x0 + motor_len
        base_x = x0 + motor_len + plate_t
        right_plate_x = x0 + total_len - plate_t

        base_len = total_len - motor_len - plate_t - plate_t

        slider_z = z0 + base_h + slider_gap_z
        slider_h = right_plate_h - base_h - slider_gap_z

        cy = y0 + rail_w / 2

        pivot_x = x0 + slider_cx
        pivot_y = cy

        # 1. Motor box
        motor_px, motor_py = place_box_xy(
            motor_x, motor_y, motor_len, motor_w, pivot_x, pivot_y
        )
        motor = make_box(
            comp,
            '04_01_Motor_Box_30x28x28_Lifted_6mm',
            motor_px,
            motor_py,
            motor_z,
            motor_len,
            motor_w,
            motor_h
        )

        # 2. Left plate
        left_plate_px, left_plate_py = place_box_xy(
            left_plate_x, y0, plate_t, rail_w, pivot_x, pivot_y
        )
        left_plate = make_box(
            comp,
            '04_02_Left_Plate_5x30x34',
            left_plate_px,
            left_plate_py,
            z0,
            plate_t,
            rail_w,
            left_plate_h
        )

        # 3. Main base
        base_px, base_py = place_box_xy(
            base_x, y0, base_len, rail_w, pivot_x, pivot_y
        )
        base = make_box(
            comp,
            '04_03_Rail_Base_185x30x13_with_4x_M3_Mount_Holes',
            base_px,
            base_py,
            z0,
            base_len,
            rail_w,
            base_h
        )

        add_rail_mount_holes(
            comp,
            base,
            base_x,
            right_plate_x,
            y0,
            rail_w,
            z0,
            base_h,
            pivot_x,
            pivot_y
        )


        # 4. Right plate
        right_plate_px, right_plate_py = place_box_xy(
            right_plate_x, y0, plate_t, rail_w, pivot_x, pivot_y
        )
        right_plate = make_box(
            comp,
            '04_04_Right_Plate_5x30x28',
            right_plate_px,
            right_plate_py,
            z0,
            plate_t,
            rail_w,
            right_plate_h
        )

        # 5. Central shaft
        shaft_x, shaft_y = place_cyl_x_start(
            base_x, cy, base_len, pivot_x, pivot_y
        )
        shaft = make_cyl_x(
            comp,
            '04_05_Central_Shaft',
            shaft_x,
            shaft_y,
            z0 + shaft_z,
            shaft_r,
            base_len
        )

        # 6. Slider platform
        slider_raw_x = x0 + slider_cx - slider_len / 2
        slider_px, slider_py = place_box_xy(
            slider_raw_x, y0, slider_len, slider_w, pivot_x, pivot_y
        )
        slider = make_slider_with_holes(
            comp,
            '04_06_Slider_Platform_32x30_Top_Flush',
            slider_px,
            slider_py,
            slider_z,
            slider_len,
            slider_w,
            slider_h,
            m3_space,
            m3_r
        )

        app.activeViewport.fit()

        silent_message_box(
            '04 X-axis linear rail generated with 4 rail mount holes.\n\n'
            'Slider platform centre is kept fixed.\n'
            'Rail is rotated 180 deg in XY when FLIP_RAIL_180_ABOUT_SLIDER is True.\n'
            'Rail bottom Z aligned to base plate top.\n'
            '4 rail mounting holes are cut on the rail base.\n'
            'Hole diameter: {:.2f} mm, X offset from each limit edge: {:.2f} mm, Y offset from each side: {:.2f} mm.\n\n'
            'x0/y0/z0: {:.2f}, {:.2f}, {:.2f} mm'.format(
                RAIL_MOUNT_HOLE_D_MM,
                RAIL_MOUNT_X_FROM_LIMIT_EDGE_MM,
                RAIL_MOUNT_Y_FROM_SIDE_MM,
                x0 * 10,
                y0 * 10,
                z0 * 10
            )
        )

    except Exception:
        if ui:
            silent_message_box('Failed:\n{}'.format(traceback.format_exc()))