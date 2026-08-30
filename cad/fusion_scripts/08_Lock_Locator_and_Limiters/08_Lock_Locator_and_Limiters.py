import adsk.core
import adsk.fusion
import traceback


def mm(value):
    return value / 10.0


def v(design, name):
    p = design.userParameters.itemByName(name)
    if not p:
        raise RuntimeError('Missing parameter: ' + name)
    return p.value


def vp(design, name, default_mm):
    p = design.userParameters.itemByName(name)
    if p:
        return p.value
    return mm(default_mm)


def find_occ(root, prefix):
    occs = root.allOccurrences

    for i in range(occs.count):
        occ = occs.item(i)

        if occ.component and occ.component.name.startswith(prefix):
            return occ

        if occ.name.startswith(prefix):
            return occ

    return None


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


def join_bodies(comp, target, tools):
    objs = adsk.core.ObjectCollection.create()

    for body in tools:
        objs.add(body)

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)


def cut_one(comp, target, cutter):
    objs = adsk.core.ObjectCollection.create()
    objs.add(cutter)

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)


def get_limiter_params():
    return {
        'gap': mm(0.3),

        'bottom_t_z': mm(1.6),
        'bottom_gap_z': mm(0.3),
        'bottom_depth_x': mm(8.0),
        'bottom_depth_y': mm(10.0),

        'shaft_hole_r': mm(2.10),
        'shaft_cut_extra_x': mm(2.0),

        'top_gap_z': mm(0.3),

        'front_t_x': mm(4.0),
        'front_depth_y': mm(10.0),

        'side_t_y': mm(4.0),
        'side_depth_x': mm(8.0),

        'extension_y': mm(15.0),
        'extension_overlap': mm(0.05)
    }


def get_shared_lock_data(design, root):
    lw = v(design, 'lock_width')
    lh = v(design, 'lock_height')
    lt = v(design, 'lock_thickness')

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

    lock_cx = -dial_stack_center_z
    lock_cy = dial_x
    lock_cz = wheel_center_z

    x_min = lock_cx - lh / 2
    x_max = lock_cx + lh / 2

    y_min = lock_cy - lw / 2
    y_max = lock_cy + lw / 2

    z_min = lock_cz - lt / 2
    z_max = lock_cz + lt / 2

    mic_x_from_right = vp(design, 'mic_center_x_from_right', 6.0)
    mic_local_x = -lw / 2 + mic_x_from_right
    mic_global_y = lock_cy - mic_local_x

    shackle_y_a = lock_cy - v(design, 'shackle_left_x')
    shackle_y_b = lock_cy - v(design, 'shackle_right_x')
    shackle_z = lock_cz - v(design, 'shackle_center_y')

    base_occ = find_occ(root, '13_Main_Base_Plate')

    if base_occ:
        base_top_z = base_occ.boundingBox.maxPoint.z
    else:
        base_top_z = 0

    support_occ = find_occ(root, '01_Passive_Shaft_Support')

    shaft_y = 0.0
    support_shaft_z = shaft_z

    if support_occ:
        bb = support_occ.boundingBox
        shaft_y = (bb.minPoint.y + bb.maxPoint.y) / 2
        support_shaft_z = bb.minPoint.z + shaft_z

    mic_on_positive_y = mic_global_y > lock_cy
    noad35_positive_y = not mic_on_positive_y

    return {
        'x_min': x_min,
        'x_max': x_max,
        'y_min': y_min,
        'y_max': y_max,
        'z_min': z_min,
        'z_max': z_max,
        'lock_cy': lock_cy,
        'shaft_z': shaft_z,
        'shaft_y': shaft_y,
        'support_shaft_z': support_shaft_z,
        'base_top_z': base_top_z,
        'mic_global_y': mic_global_y,
        'noad35_positive_y': noad35_positive_y,
        'shackle_y_a': shackle_y_a,
        'shackle_y_b': shackle_y_b,
        'shackle_z': shackle_z
    }


def choose_bottom_lip_y_range(root, y_min, y_max):
    support_occ = find_occ(root, '01_Passive_Shaft_Support')

    y_margin = mm(0.8)
    clearance = mm(1.0)

    full_y0 = y_min - y_margin
    full_y1 = y_max + y_margin

    prefer_positive_y = True

    if not support_occ:
        mid = (full_y0 + full_y1) / 2

        if prefer_positive_y:
            return mid, full_y1

        return full_y0, mid

    sbb = support_occ.boundingBox

    neg_y0 = full_y0
    neg_y1 = min(full_y1, sbb.minPoint.y - clearance)

    pos_y0 = max(full_y0, sbb.maxPoint.y + clearance)
    pos_y1 = full_y1

    neg_len = neg_y1 - neg_y0
    pos_len = pos_y1 - pos_y0

    if prefer_positive_y and pos_len > mm(2.0):
        return pos_y0, pos_y1

    if not prefer_positive_y and neg_len > mm(2.0):
        return neg_y0, neg_y1

    if pos_len >= neg_len and pos_len > mm(2.0):
        return pos_y0, pos_y1

    if neg_len > mm(2.0):
        return neg_y0, neg_y1

    mid = (full_y0 + full_y1) / 2
    return mid, full_y1


def add_04_wrap_limit(comp, root, ctx, p):
    x_min = ctx['x_min']
    y_min = ctx['y_min']
    y_max = ctx['y_max']
    z_min = ctx['z_min']
    z_max = ctx['z_max']

    base_top_z = ctx['base_top_z']
    shaft_y = ctx['shaft_y']
    shaft_z = ctx['support_shaft_z']

    wall_t = mm(4.0)
    wall_gap = mm(0.15)
    y_margin = mm(0.8)

    wall_x0 = x_min - wall_gap - wall_t
    wall_x1 = x_min - wall_gap

    wall_y0 = y_min - y_margin
    wall_y1 = y_max + y_margin

    top_lip_thickness_z = mm(1.4)
    top_lip_depth_x = mm(3.2)

    top_lip_x0 = wall_x0
    top_lip_x1 = x_min + top_lip_depth_x

    top_lip_z0 = z_max + p['top_gap_z']
    top_lip_z1 = top_lip_z0 + top_lip_thickness_z

    wall_z0 = base_top_z
    wall_z1 = top_lip_z1

    front_is_negative_y = True

    front_gap_y = p['gap']
    front_plate_t_y = mm(4.0)

    front_x0 = wall_x0
    front_x1 = top_lip_x1

    if front_is_negative_y:
        front_y0 = y_min - front_gap_y - front_plate_t_y
        front_y1 = y_min - front_gap_y

        top_lip_y0 = front_y0
        top_lip_y1 = y_max + y_margin
    else:
        front_y0 = y_max + front_gap_y
        front_y1 = y_max + front_gap_y + front_plate_t_y

        top_lip_y0 = y_min - y_margin
        top_lip_y1 = front_y1

    front_z0 = base_top_z
    front_z1 = top_lip_z1

    wall = box_z(
        comp,
        '08_No_Shackle_Side_Wall_Rect',
        (wall_x0 + wall_x1) / 2,
        (wall_y0 + wall_y1) / 2,
        wall_z0,
        wall_x1 - wall_x0,
        wall_y1 - wall_y0,
        wall_z1 - wall_z0
    )

    top_lip = box_z(
        comp,
        '08_Top_Retainer_Lip',
        (top_lip_x0 + top_lip_x1) / 2,
        (top_lip_y0 + top_lip_y1) / 2,
        top_lip_z0,
        top_lip_x1 - top_lip_x0,
        top_lip_y1 - top_lip_y0,
        top_lip_z1 - top_lip_z0
    )

    front_plate = box_z(
        comp,
        '08_Front_End_Limiter_Plate',
        (front_x0 + front_x1) / 2,
        (front_y0 + front_y1) / 2,
        front_z0,
        front_x1 - front_x0,
        front_y1 - front_y0,
        front_z1 - front_z0
    )

    corner_fill = box_z(
        comp,
        '08_Side_Front_Corner_Fill',
        (wall_x0 + wall_x1) / 2,
        (front_y0 + front_y1) / 2,
        base_top_z,
        wall_x1 - wall_x0,
        front_y1 - front_y0,
        top_lip_z1 - base_top_z
    )

    bottom_lip_x0 = wall_x1
    bottom_lip_x1 = x_min + p['bottom_depth_x']

    bottom_lip_y0, bottom_lip_y1 = choose_bottom_lip_y_range(
        root,
        y_min,
        y_max
    )

    bottom_lip_z1 = z_min - p['bottom_gap_z']
    bottom_lip_z0 = bottom_lip_z1 - p['bottom_t_z']

    bottom_lip = box_z(
        comp,
        '08_Bottom_Half_Limit_Ledge',
        (bottom_lip_x0 + bottom_lip_x1) / 2,
        (bottom_lip_y0 + bottom_lip_y1) / 2,
        bottom_lip_z0,
        bottom_lip_x1 - bottom_lip_x0,
        bottom_lip_y1 - bottom_lip_y0,
        bottom_lip_z1 - bottom_lip_z0
    )

    rib_t_x = mm(2.5)
    rib_z0 = base_top_z
    rib_z1 = bottom_lip_z1

    tools = [
        top_lip,
        front_plate,
        corner_fill,
        bottom_lip
    ]

    if rib_z1 > rib_z0:
        outer_rib_x1 = bottom_lip_x1
        outer_rib_x0 = outer_rib_x1 - rib_t_x

        outer_rib = box_z(
            comp,
            '08_Bottom_Ledge_Outer_Rib_FullWidth',
            (outer_rib_x0 + outer_rib_x1) / 2,
            (bottom_lip_y0 + bottom_lip_y1) / 2,
            rib_z0,
            outer_rib_x1 - outer_rib_x0,
            bottom_lip_y1 - bottom_lip_y0,
            rib_z1 - rib_z0
        )

        tools.append(outer_rib)

    join_bodies(comp, wall, tools)

    shaft_opening = cyl_x(
        comp,
        'cut_08_Shaft_Clearance_Opening',
        (wall_x0 + bottom_lip_x1) / 2,
        shaft_y,
        shaft_z,
        p['shaft_hole_r'],
        bottom_lip_x1 - wall_x0 + p['shaft_cut_extra_x']
    )

    cut_one(comp, wall, shaft_opening)

    wall.name = '08_Combined_Wrap_Limiter'

    return wall


def add_05_corner_support(comp, design, ctx, p):
    x_max = ctx['x_max']
    y_min = ctx['y_min']
    y_max = ctx['y_max']
    z_min = ctx['z_min']
    z_max = ctx['z_max']

    base_top_z = ctx['base_top_z']
    shaft_z = ctx['shaft_z']
    support_shaft_y = ctx['shaft_y']
    support_shaft_z = ctx['support_shaft_z']

    shackle_y_a = ctx['shackle_y_a']
    shackle_y_b = ctx['shackle_y_b']
    shackle_z = ctx['shackle_z']

    noad35_positive_y = ctx['noad35_positive_y']

    front_t_x = p['front_t_x']
    side_t_y = p['side_t_y']
    top_t_z = mm(1.8)
    bottom_t_z = p['bottom_t_z']

    front_depth_y = p['front_depth_y']
    side_depth_x = p['side_depth_x']

    top_depth_x = mm(8.0)
    top_depth_y = mm(10.0)

    bottom_depth_x = p['bottom_depth_x']
    bottom_depth_y = p['bottom_depth_y']

    front_x0 = x_max + p['gap']
    front_x1 = front_x0 + front_t_x

    side_x0 = x_max - side_depth_x
    side_x1 = front_x1

    top_x0 = x_max - top_depth_x
    top_x1 = front_x1

    bottom_x0 = x_max - bottom_depth_x
    bottom_x1 = front_x1

    if noad35_positive_y:
        y_face = y_max

        side_y0 = y_max + p['gap']
        side_y1 = side_y0 + side_t_y

        front_y0 = y_max - front_depth_y
        front_y1 = side_y1

        top_y0 = y_max - top_depth_y
        top_y1 = side_y1

        bottom_y0 = y_max - bottom_depth_y
        bottom_y1 = side_y1

        ext_y0 = front_y0 - p['extension_y']
        ext_y1 = front_y0 + p['extension_overlap']

        bottom_ext_y0 = bottom_y0 - p['extension_y']
        bottom_ext_y1 = bottom_y0 + p['extension_overlap']

    else:
        y_face = y_min

        side_y1 = y_min - p['gap']
        side_y0 = side_y1 - side_t_y

        front_y0 = side_y0
        front_y1 = y_min + front_depth_y

        top_y0 = side_y0
        top_y1 = y_min + top_depth_y

        bottom_y0 = side_y0
        bottom_y1 = y_min + bottom_depth_y

        ext_y0 = front_y1 - p['extension_overlap']
        ext_y1 = front_y1 + p['extension_y']

        bottom_ext_y0 = bottom_y1 - p['extension_overlap']
        bottom_ext_y1 = bottom_y1 + p['extension_y']

    z0 = base_top_z
    z1 = z_max + p['top_gap_z'] + top_t_z

    top_z0 = z_max + p['top_gap_z']
    top_z1 = top_z0 + top_t_z

    bottom_z1 = z_min - p['bottom_gap_z']
    bottom_z0 = bottom_z1 - bottom_t_z

    front_plate = box_z(
        comp,
        '08_Shackle_Front_Limit_Plate',
        (front_x0 + front_x1) / 2,
        (front_y0 + front_y1) / 2,
        z0,
        front_x1 - front_x0,
        front_y1 - front_y0,
        z1 - z0
    )

    side_plate = box_z(
        comp,
        '08_Shackle_Side_Limit_Plate',
        (side_x0 + side_x1) / 2,
        (side_y0 + side_y1) / 2,
        z0,
        side_x1 - side_x0,
        side_y1 - side_y0,
        z1 - z0
    )

    top_plate = box_z(
        comp,
        '08_Shackle_Top_Limit_Plate',
        (top_x0 + top_x1) / 2,
        (top_y0 + top_y1) / 2,
        top_z0,
        top_x1 - top_x0,
        top_y1 - top_y0,
        top_z1 - top_z0
    )

    bottom_plate = box_z(
        comp,
        '08_Shackle_Bottom_Limit_Plate',
        (bottom_x0 + bottom_x1) / 2,
        (bottom_y0 + bottom_y1) / 2,
        bottom_z0,
        bottom_x1 - bottom_x0,
        bottom_y1 - bottom_y0,
        bottom_z1 - bottom_z0
    )

    if abs(shackle_y_a - y_face) <= abs(shackle_y_b - y_face):
        shackle_y = shackle_y_a
    else:
        shackle_y = shackle_y_b

    rod_r = v(design, 'shackle_rod_radius')

    notch_r = rod_r + mm(1.6)
    max_safe_r = shackle_z - shaft_z - mm(0.8)

    if max_safe_r > rod_r + mm(0.5):
        notch_r = min(notch_r, max_safe_r)
    else:
        notch_r = rod_r + mm(0.6)

    notch_bottom_z = shackle_z - notch_r

    front_extension = box_z(
        comp,
        '08_Shackle_Front_Edge_Extension_Plate',
        (front_x0 + front_x1) / 2,
        (ext_y0 + ext_y1) / 2,
        z0,
        front_x1 - front_x0,
        ext_y1 - ext_y0,
        notch_bottom_z - z0
    )

    bottom_extension = box_z(
        comp,
        '08_Shackle_Bottom_Limit_Extension_Plate',
        (bottom_x0 + bottom_x1) / 2,
        (bottom_ext_y0 + bottom_ext_y1) / 2,
        bottom_z0,
        bottom_x1 - bottom_x0,
        bottom_ext_y1 - bottom_ext_y0,
        bottom_z1 - bottom_z0
    )

    side_notch = cyl_x(
        comp,
        'cut_08_Shackle_Clearance_Side',
        (side_x0 + side_x1) / 2,
        shackle_y,
        shackle_z,
        notch_r,
        side_x1 - side_x0 + p['shaft_cut_extra_x']
    )

    cut_one(comp, side_plate, side_notch)

    front_notch = cyl_x(
        comp,
        'cut_08_Shackle_Clearance_Front',
        (front_x0 + front_x1) / 2,
        shackle_y,
        shackle_z,
        notch_r,
        front_x1 - front_x0 + p['shaft_cut_extra_x']
    )

    cut_one(comp, front_plate, front_notch)

    join_bodies(
        comp,
        front_extension,
        [
            bottom_extension
        ]
    )

    shaft_cut = cyl_x(
        comp,
        'cut_08_Extension_Shaft_Clearance',
        (front_x0 + front_x1) / 2,
        support_shaft_y,
        support_shaft_z,
        p['shaft_hole_r'],
        front_x1 - front_x0 + p['shaft_cut_extra_x']
    )

    cut_one(comp, front_extension, shaft_cut)

    join_bodies(
        comp,
        front_plate,
        [
            side_plate,
            top_plate,
            bottom_plate,
            front_extension
        ]
    )

    front_plate.name = '08_Shackle_Corner_Limiter'

    return front_plate


def add_04_05_limiters(comp, design, root):
    p = get_limiter_params()
    ctx = get_shared_lock_data(design, root)

    add_04_wrap_limit(comp, root, ctx, p)
    add_05_corner_support(comp, design, ctx, p)


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

        comp = new_comp(
            root,
            '08_Lock_Locator_and_Limiters'
        )

        add_04_05_limiters(comp, design, root)

        ui.messageBox('08 lock locator and limiters created.')

    except Exception:
        if ui:
            ui.messageBox(traceback.format_exc())