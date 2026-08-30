import adsk.core
import adsk.fusion
import traceback


def silent_message_box(*args, **kwargs):
    return 0


def v(design, name):
    p = design.userParameters.itemByName(name)
    if not p:
        raise RuntimeError('Missing parameter: ' + name)
    return p.value


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
    return occ, comp


def move_body(comp, body, dx, dy, dz):
    if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
        return

    objs = adsk.core.ObjectCollection.create()
    objs.add(body)

    mat = adsk.core.Matrix3D.create()
    mat.translation = adsk.core.Vector3D.create(dx, dy, dz)

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def box(comp, name, cx, cy, cz, sx, sy, sz):
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
    ei.setDistanceExtent(False, adsk.core.ValueInput.createByReal(sz))

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, 0, 0, cz - sz / 2)
    sk.isVisible = False
    return body


def cyl(comp, name, cx, cy, cz, r, length, axis):
    if axis == 'X':
        sk = comp.sketches.add(comp.yZConstructionPlane)
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(cy, cz, 0),
            r
        )
        dx, dy, dz = cx, 0, 0

    elif axis == 'Y':
        sk = comp.sketches.add(comp.xZConstructionPlane)
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(cx, cz, 0),
            r
        )
        dx, dy, dz = 0, cy, 0

    else:
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(cx, cy, 0),
            r
        )
        dx, dy, dz = 0, 0, cz

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

    move_body(comp, body, dx, dy, dz)
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


def join_bodies(comp, target, tools, name):
    objs = adsk.core.ObjectCollection.create()

    for b in tools:
        objs.add(b)

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    ci.isKeepToolBodies = False

    comp.features.combineFeatures.add(ci)
    target.name = name
    return target


def offset_plane(comp, base, dist):
    planes = comp.constructionPlanes
    pi = planes.createInput()
    pi.setByOffset(base, adsk.core.ValueInput.createByReal(dist))
    return planes.add(pi)


def circle_profile_xz(comp, x, y, z, r):
    plane = offset_plane(comp, comp.xZConstructionPlane, y)
    sk = comp.sketches.add(plane)

    centre = sk.modelToSketchSpace(
        adsk.core.Point3D.create(x, y, z)
    )

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        centre,
        r
    )

    prof = sk.profiles.item(0)
    sk.isVisible = False

    return prof


def add_ad35_mic(comp, design):
    lw = v(design, 'lock_width')
    lh = v(design, 'lock_height')
    lt = v(design, 'lock_thickness')

    max_d = vp(design, 'mic_max_diameter', 36.22)
    end_d = vp(design, 'mic_end_diameter', 27.51)
    t = vp(design, 'mic_thickness', 15.13)

    z_from_bottom = vp(design, 'mic_center_z_from_bottom', 32.34)
    x_from_back_right = vp(design, 'mic_center_x_from_right', 6.0)

    r_max = max_d / 2
    r_end = end_d / 2
    r_shoulder = r_end + (r_max - r_end) * 0.72

    x = -lw / 2 + x_from_back_right
    z = -lh / 2 + z_from_bottom

    back_hint = v(design, 'back_window_y')
    side = 1 if back_hint > 0 else -1

    y0 = side * lt / 2
    y1 = y0 + side * t * 0.20
    y2 = y0 + side * t * 0.50
    y3 = y0 + side * t * 0.80
    y4 = y0 + side * t

    p0 = circle_profile_xz(comp, x, y0, z, r_end)
    p1 = circle_profile_xz(comp, x, y1, z, r_shoulder)
    p2 = circle_profile_xz(comp, x, y2, z, r_max)
    p3 = circle_profile_xz(comp, x, y3, z, r_shoulder)
    p4 = circle_profile_xz(comp, x, y4, z, r_end)

    li = comp.features.loftFeatures.createInput(
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )

    li.loftSections.add(p0)
    li.loftSections.add(p1)
    li.loftSections.add(p2)
    li.loftSections.add(p3)
    li.loftSections.add(p4)

    loft = comp.features.loftFeatures.add(li)
    body = loft.bodies.item(0)
    body.name = '02_AD35_Mic'

    fillet(comp, body, v(design, 'fillet_small') * 0.2)


def add_body(comp, design):
    lw = v(design, 'lock_width')
    lh = v(design, 'lock_height')
    lt = v(design, 'lock_thickness')
    edge = v(design, 'lock_edge_fillet')

    body = box(comp, '02_Body_Silver', 0, 0, 0, lw, lt, lh)
    fillet(comp, body, edge)

    top = box(
        comp,
        '02_Lip_Red_Top',
        0,
        0,
        v(design, 'shell_top_z'),
        lw,
        v(design, 'shell_depth'),
        v(design, 'shell_top_height')
    )
    fillet(comp, top, v(design, 'shell_radius') * 0.25)

    right = box(
        comp,
        '02_Lip_Red_Right',
        v(design, 'shell_right_x'),
        0,
        0,
        v(design, 'shell_right_width'),
        v(design, 'shell_depth'),
        lh
    )
    fillet(comp, right, v(design, 'shell_radius') * 0.25)

    left = box(
        comp,
        '02_Lip_Red_Left',
        v(design, 'shell_left_x'),
        0,
        0,
        v(design, 'shell_left_width'),
        v(design, 'shell_depth'),
        lh
    )
    fillet(comp, left, v(design, 'shell_radius') * 0.2)


def add_window_set(comp, design, side, y_frame, y_wheel, depth):
    x = v(design, 'dial_window_x')

    ww = v(design, 'dial_window_width')
    wh = v(design, 'dial_window_height')
    wd = v(design, 'dial_window_depth')

    fw = v(design, 'dial_visible_width')
    fh = v(design, 'dial_visible_height')

    zs = [
        v(design, 'dial_1_z'),
        v(design, 'dial_2_z'),
        v(design, 'dial_3_z'),
        v(design, 'dial_4_z')
    ]

    for i, z in enumerate(zs):
        frame = box(
            comp,
            f'02_{side}_Window_{i + 1}',
            x,
            y_frame,
            z,
            ww,
            wd,
            wh
        )

        wheel = box(
            comp,
            f'02_{side}_Wheel_Face_{i + 1}',
            x,
            y_wheel,
            z,
            fw,
            depth,
            fh
        )

        fillet(comp, frame, v(design, 'dial_window_corner'))
        fillet(comp, wheel, v(design, 'fillet_small') * 0.25)


def add_shackle(comp, design):
    r = v(design, 'shackle_rod_radius')
    lx = v(design, 'shackle_left_x')
    rx = v(design, 'shackle_right_x')
    y = v(design, 'shackle_center_y')

    body_top_z = v(design, 'lock_top_z')

    R = (rx - lx) / 2
    joint_z = body_top_z + v(design, 'shackle_visible_height') - R

    rod_bottom_z = body_top_z
    rod_top_z = joint_z
    rod_len = rod_top_z - rod_bottom_z
    rod_cz = (rod_top_z + rod_bottom_z) / 2

    left = cyl(
        comp,
        '02_Shackle_Left_Rod',
        lx,
        y,
        rod_cz,
        r,
        rod_len,
        'Z'
    )

    right = cyl(
        comp,
        '02_Shackle_Right_Rod',
        rx,
        y,
        rod_cz,
        r,
        rod_len,
        'Z'
    )

    sk = comp.sketches.add(comp.xYConstructionPlane)

    axis = sk.sketchCurves.sketchLines.addByTwoPoints(
        adsk.core.Point3D.create(0, -20, 0),
        adsk.core.Point3D.create(0, 20, 0)
    )

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(R, 0, 0),
        r
    )

    prof = sk.profiles.item(0)

    ri = comp.features.revolveFeatures.createInput(
        prof,
        axis,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )

    ri.setAngleExtent(
        False,
        adsk.core.ValueInput.createByString('180 deg')
    )

    rev = comp.features.revolveFeatures.add(ri)
    arc = rev.bodies.item(0)
    arc.name = '02_Shackle_Top_Arc'

    move_body(comp, arc, 0, y, joint_z)
    sk.isVisible = False

    shackle = join_bodies(
        comp,
        arc,
        [left, right],
        '02_Shackle_Round_U'
    )

    fillet(comp, shackle, v(design, 'fillet_small') * 0.08)


def align_lock_to_passive_rollers(design, lock_occ):
    try:
        lock_occ.isGrounded = False
    except Exception:
        pass

    dial_x = v(design, 'dial_window_x')

    dial_zs = [
        v(design, 'dial_1_z'),
        v(design, 'dial_2_z'),
        v(design, 'dial_3_z'),
        v(design, 'dial_4_z')
    ]

    dial_stack_center_z = sum(dial_zs) / 4

    wheel_r = vp(design, 'dial_body_radius', 9.4)
    bearing_r = mm(4.0)

    mic_t = vp(design, 'mic_thickness', 15.13)
    mic_clearance = mm(4.8)

    support_h = mic_t + mic_clearance
    top_to_shaft = mm(3.2)

    shaft_z = support_h - top_to_shaft
    bearing_top_z = shaft_z + bearing_r

    preload = mm(0.10)

    wheel_center_z = bearing_top_z + wheel_r - preload

    tx = -dial_stack_center_z
    ty = dial_x
    tz = wheel_center_z

    mat = adsk.core.Matrix3D.create()

    origin = adsk.core.Point3D.create(
        tx,
        ty,
        tz
    )

    x_axis = adsk.core.Vector3D.create(0, -1, 0)
    y_axis = adsk.core.Vector3D.create(0, 0, -1)
    z_axis = adsk.core.Vector3D.create(1, 0, 0)

    mat.setWithCoordinateSystem(
        origin,
        x_axis,
        y_axis,
        z_axis
    )

    try:
        lock_occ.transform2 = mat
    except Exception:
        lock_occ.transform = mat

    try:
        design.snapshots.add()
    except Exception:
        pass


def run(context):
    ui = None

    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)

        if not design:
            silent_message_box('Open a Fusion design first.')
            return

        lock_occ, c = new_comp(
            design.rootComponent,
            '02_Padlock_Reference'
        )

        add_body(c, design)

        add_window_set(
            c,
            design,
            'Front',
            v(design, 'front_window_y'),
            v(design, 'front_dial_face_y'),
            v(design, 'dial_front_projection')
        )

        add_window_set(
            c,
            design,
            'Back',
            v(design, 'back_window_y'),
            v(design, 'back_dial_face_y'),
            v(design, 'dial_back_projection')
        )

        add_shackle(c, design)
        add_ad35_mic(c, design)

        align_lock_to_passive_rollers(design, lock_occ)

        silent_message_box('02 padlock reference created and aligned.')

    except Exception:
        if ui:
            silent_message_box(traceback.format_exc())