import adsk.core
import adsk.fusion
import traceback
import math


TARGET_WHEEL_NO = 2
# 1, 2, 3, 4 = specific wheel
# 0 = wheel stack centre

ROLLER_LOCAL_Y_MM = 50.0
ROLLER_LOCAL_Z_MM = 0.0

RUBBER_ROLLER_RADIUS_MM = 10.0
CONTACT_PRELOAD_MM = 0.20

MOTOR_HALF_Y_MM = 14.1

# Upper spring hooks on swing arms.
SPRING_UPPER_TO_LOWER_HOLE_MM = 18.0
SPRING_UPPER_HOLE_D_MM = 2.5
SPRING_UPPER_HOLE_SPACING_MM = 6.5
SPRING_UPPER_TAB_T_Z_MM = 3.0
SPRING_UPPER_TAB_Y_MARGIN_MM = 3.5
SPRING_UPPER_TAB_X_MARGIN_MM = 3.0
SPRING_UPPER_RISER_X_OVERLAP_MM = 0.6
SPRING_UPPER_RISER_Z_OVERLAP_MM = 0.08

# Must match 11 movable base spring plate logic.
SPRING_LOWER_PLATE_X_T_MM = 2.0
SPRING_LOWER_PLATE_H_MM = 6.6
SPRING_LOWER_HOLE_D_MM = 2.5
SPRING_LOWER_HOLE_SPACING_MM = 6.5
SPRING_LOWER_FORWARD_GAP_MM = 1.5
SPRING_LOWER_EDGE_GAP_MM = 1.5
SPRING_LOWER_TOP_CLEAR_MM = 2.0
SPRING_SUPPORT_CHEEK_T_MM = 2.2
SPRING_SUPPORT_SIDE_CLEAR_MM = 0.8
SPRING_SUPPORT_Y_HALF_MM = 4.5


def mm(v):
    return v / 10.0


def to_mm(v):
    return v * 10.0


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


def clean_existing(root, prefixes):
    occs = []

    for i in range(root.occurrences.count):
        occ = root.occurrences.item(i)
        if not occ.component:
            continue

        for prefix in prefixes:
            if occ.component.name.startswith(prefix):
                occs.append(occ)
                break

    for occ in occs:
        occ.deleteMe()


def find_occ(root, prefix):
    occs = root.allOccurrences

    for i in range(occs.count):
        occ = occs.item(i)

        if occ.component and occ.component.name.startswith(prefix):
            return occ

        if occ.name.startswith(prefix):
            return occ

    return None


def get_occ_transform(occ):
    try:
        return occ.transform2.copy()
    except Exception:
        return occ.transform.copy()


def local_to_world(occ, x, y, z):
    p = adsk.core.Point3D.create(x, y, z)
    mat = get_occ_transform(occ)
    p.transformBy(mat)
    return p


def get_target_wheel_world_point(design, root):
    lock_occ = find_occ(root, '02_Padlock_Reference')

    if not lock_occ:
        raise RuntimeError('02_Padlock_Reference not found. Run 02 first.')

    dial_x = v(design, 'dial_window_x')

    dial_zs = [
        v(design, 'dial_1_z'),
        v(design, 'dial_2_z'),
        v(design, 'dial_3_z'),
        v(design, 'dial_4_z')
    ]

    if TARGET_WHEEL_NO in [1, 2, 3, 4]:
        target_z = dial_zs[TARGET_WHEEL_NO - 1]
    else:
        target_z = sum(dial_zs) / 4.0

    return local_to_world(
        lock_occ,
        dial_x,
        0.0,
        target_z
    )


def place_drive_head_to_lock_wheel(design, root, drive_occ, roller_local_x_mm):
    wheel_pt = get_target_wheel_world_point(design, root)

    wheel_r = vp(design, 'dial_body_radius', 9.4)
    roller_r = mm(RUBBER_ROLLER_RADIUS_MM)
    preload = mm(CONTACT_PRELOAD_MM)

    target_x = wheel_pt.x
    target_y = wheel_pt.y
    target_z = wheel_pt.z + wheel_r + roller_r - preload

    dx = target_x - mm(roller_local_x_mm)
    dy = target_y - mm(ROLLER_LOCAL_Y_MM)
    dz = target_z - mm(ROLLER_LOCAL_Z_MM)

    mat = adsk.core.Matrix3D.create()
    mat.translation = adsk.core.Vector3D.create(dx, dy, dz)

    try:
        drive_occ.isGrounded = False
    except Exception:
        pass

    try:
        drive_occ.transform2 = mat
    except Exception:
        drive_occ.transform = mat

    motor_near_edge_y = dy + mm(MOTOR_HALF_Y_MM)
    motor_to_wheel_center_y = abs(target_y - motor_near_edge_y)

    return {
        'wheel_x': wheel_pt.x,
        'wheel_y': wheel_pt.y,
        'wheel_z': wheel_pt.z,
        'roller_x': target_x,
        'roller_y': target_y,
        'roller_z': target_z,
        'dx': dx,
        'dy': dy,
        'dz': dz,
        'motor_to_wheel_center_y': motor_to_wheel_center_y
    }


def move_body(comp, body, dx, dy, dz):
    if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
        return

    objs = adsk.core.ObjectCollection.create()
    objs.add(body)

    mat = adsk.core.Matrix3D.create()
    mat.translation = adsk.core.Vector3D.create(mm(dx), mm(dy), mm(dz))

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def rotate_body(comp, body, angle_deg, axis, point):
    objs = adsk.core.ObjectCollection.create()
    objs.add(body)

    mat = adsk.core.Matrix3D.create()
    mat.setToRotation(math.radians(angle_deg), axis, point)

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def create_cylinder_x_center_safe(comp, name, cx, cy, cz, dia, length):
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + '_sk'

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(mm(cx), mm(cy), 0),
        mm(dia / 2.0)
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

    move_body(comp, body, 0, 0, cz - length / 2.0)

    rotate_body(
        comp,
        body,
        90.0,
        adsk.core.Vector3D.create(0, 1, 0),
        adsk.core.Point3D.create(mm(cx), mm(cy), mm(cz))
    )

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def create_box_min(comp, name, x0, x1, y0, y1, z0, z1):
    sk = comp.sketches.add(comp.xYConstructionPlane)

    sk.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(mm(x0), mm(y0), 0),
        adsk.core.Point3D.create(mm(x1), mm(y1), 0)
    )

    prof = sk.profiles.item(0)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(z1 - z0)))

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, 0, 0, z0)
    return body


def create_box_center(comp, name, cx, cy, cz, sx, sy, sz):
    return create_box_min(
        comp,
        name,
        cx - sx / 2,
        cx + sx / 2,
        cy - sy / 2,
        cy + sy / 2,
        cz - sz / 2,
        cz + sz / 2
    )


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


def create_xy_plate_with_z_holes(comp, name, x0, x1, y0, y1, z0, z1, hole_x, hole_ys, hole_r):
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + '_sk'

    sk.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(mm(x0), mm(y0), 0),
        adsk.core.Point3D.create(mm(x1), mm(y1), 0)
    )

    for hy in hole_ys:
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(mm(hole_x), mm(hy), 0),
            mm(hole_r)
        )

    prof = largest_profile(sk)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(z1 - z0)))

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_body(comp, body, 0, 0, z0)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def add_upper_spring_tab(comp, arm, prefix, arm_cx, free_y, pivot_y, centre_z, arm_t, web_width_z):
    side_sign = -1.0 if 'left' in prefix.lower() else 1.0

    bearing_w_x = 4.0
    support_half_x = (
        (bearing_w_x + SPRING_SUPPORT_SIDE_CLEAR_MM) / 2.0
        + SPRING_SUPPORT_CHEEK_T_MM
    )

    lower_hole_x = arm_cx + side_sign * (
        support_half_x
        + SPRING_LOWER_EDGE_GAP_MM
        + SPRING_LOWER_PLATE_X_T_MM / 2.0
    )

    dir_y = 1.0 if pivot_y >= free_y else -1.0
    front_y = free_y + dir_y * SPRING_SUPPORT_Y_HALF_MM

    if dir_y > 0:
        lower_plate_y0 = front_y + SPRING_LOWER_FORWARD_GAP_MM
        lower_plate_y1 = lower_plate_y0 + 23.0
    else:
        lower_plate_y1 = front_y - SPRING_LOWER_FORWARD_GAP_MM
        lower_plate_y0 = lower_plate_y1 - 23.0

    lower_cy = (lower_plate_y0 + lower_plate_y1) / 2.0
    hole_ys = [
        lower_cy - SPRING_UPPER_HOLE_SPACING_MM,
        lower_cy,
        lower_cy + SPRING_UPPER_HOLE_SPACING_MM
    ]

    motor_body_bottom_z = -14.1
    arm_top_z = centre_z + web_width_z / 2.0
    arm_bottom_z = centre_z - web_width_z / 2.0

    lower_z0 = motor_body_bottom_z
    lower_base_z1 = min(
        lower_z0 + SPRING_LOWER_PLATE_H_MM,
        arm_bottom_z - SPRING_LOWER_TOP_CLEAR_MM
    )

    min_lower_h = SPRING_LOWER_HOLE_D_MM + 1.0
    if lower_base_z1 <= lower_z0 + min_lower_h:
        lower_base_z1 = lower_z0 + min_lower_h

    lower_hole_z = (lower_z0 + lower_base_z1) / 2.0
    upper_hole_z = lower_hole_z + SPRING_UPPER_TO_LOWER_HOLE_MM

    tab_z0 = upper_hole_z - SPRING_UPPER_TAB_T_Z_MM / 2.0
    tab_z1 = upper_hole_z + SPRING_UPPER_TAB_T_Z_MM / 2.0

    if tab_z0 > arm_top_z:
        tab_z0 = arm_top_z - 0.05
        tab_z1 = max(tab_z1, tab_z0 + SPRING_UPPER_TAB_T_Z_MM)

    y0 = min(hole_ys) - SPRING_UPPER_TAB_Y_MARGIN_MM
    y1 = max(hole_ys) + SPRING_UPPER_TAB_Y_MARGIN_MM

    # Extend the tab across the full arm width so it is not only touching the arm edge.
    if side_sign < 0:
        inner_x = arm_cx + arm_t / 2.0
    else:
        inner_x = arm_cx - arm_t / 2.0

    outer_x = lower_hole_x + side_sign * SPRING_UPPER_TAB_X_MARGIN_MM

    x0 = min(inner_x, outer_x)
    x1 = max(inner_x, outer_x)

    tab = create_xy_plate_with_z_holes(
        comp,
        prefix + '_upper_spring_hook_tab_3x2p5_holes_20mm_above_lower',
        x0,
        x1,
        y0,
        y1,
        tab_z0,
        tab_z1,
        lower_hole_x,
        hole_ys,
        SPRING_UPPER_HOLE_D_MM / 2.0
    )

    tools = [tab]

    # If the 20 mm target puts the tab above the arm, add a vertical riser.
    # The riser sits over the arm body only, so it does not block the spring holes.
    if tab_z0 > arm_top_z - SPRING_UPPER_RISER_Z_OVERLAP_MM:
        riser_z0 = arm_top_z - SPRING_UPPER_RISER_Z_OVERLAP_MM
        riser_z1 = tab_z0 + SPRING_UPPER_RISER_Z_OVERLAP_MM

        riser_x0 = arm_cx - arm_t / 2.0 - SPRING_UPPER_RISER_X_OVERLAP_MM
        riser_x1 = arm_cx + arm_t / 2.0 + SPRING_UPPER_RISER_X_OVERLAP_MM

        riser = create_box_center(
            comp,
            prefix + '_upper_spring_hook_riser_to_arm',
            arm_cx,
            (y0 + y1) / 2.0,
            (riser_z0 + riser_z1) / 2.0,
            riser_x1 - riser_x0,
            y1 - y0,
            riser_z1 - riser_z0
        )
        tools.append(riser)

    arm = combine_join(comp, arm, tools)
    arm.name = prefix + '_swing_arm_base_with_bridge_lug_and_upper_spring_hook_connected'

    return arm


def create_cylinder_x_center(comp, name, cx, cy, cz, dia, length):
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


def create_cylinder_x_start(comp, name, x_start, cy, cz, dia, length):
    return create_cylinder_x_center(
        comp,
        name,
        x_start + length / 2,
        cy,
        cz,
        dia,
        length
    )


def create_cylinder_y_center(comp, name, cx, cy, cz, dia, length):
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


def combine_join(comp, target, tools):
    objs = adsk.core.ObjectCollection.create()

    for tool in tools:
        objs.add(tool)

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    ci.isKeepToolBodies = False

    comp.features.combineFeatures.add(ci)
    return target


def combine_cut(comp, target, tools):
    objs = adsk.core.ObjectCollection.create()

    for tool in tools:
        objs.add(tool)

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    ci.isKeepToolBodies = False

    comp.features.combineFeatures.add(ci)
    return target


def create_ring_x(comp, name, cx, cy, cz, outer_dia, inner_dia, width):
    outer = create_cylinder_x_center(
        comp,
        name + '_outer',
        cx,
        cy,
        cz,
        outer_dia,
        width
    )

    inner = create_cylinder_x_center(
        comp,
        name + '_inner_cut',
        cx,
        cy,
        cz,
        inner_dia,
        width + 1.0
    )

    combine_cut(comp, outer, [inner])
    outer.name = name
    return outer


def create_shaft_collar(comp, name, cx, cy, cz):
    collar_od = 8.0
    collar_bore = 3.05
    collar_w = 4.0

    collar = create_cylinder_x_center(
        comp,
        name,
        cx,
        cy,
        cz,
        collar_od,
        collar_w
    )

    bore = create_cylinder_x_center(
        comp,
        name + '_cut_3p05_bore',
        cx,
        cy,
        cz,
        collar_bore,
        collar_w + 1.0
    )

    combine_cut(comp, collar, [bore])
    collar.name = name
    return collar


def create_nema11_motor(comp):
    x0 = 0.0
    cy = 0.0
    cz = 0.0

    face_size = 28.2
    body_len = 28.5

    shaft_len = 20.0
    shaft_d = 5.0
    shaft_flat = 4.5

    pilot_d = 22.0
    pilot_h = 2.0

    hole_pitch = 23.0
    hole_d = 2.5
    hole_depth = 2.5

    wire_len = 25.0
    wire_d = 0.9
    wire_gap = 3.0

    half_face = face_size / 2
    body_y0 = cy - half_face
    body_y1 = cy + half_face
    body_z0 = cz - half_face
    body_z1 = cz + half_face

    body = create_box_min(
        comp,
        '03_01_motor_body_28p5x28p2x28p2',
        x0,
        x0 + body_len,
        body_y0,
        body_y1,
        body_z0,
        body_z1
    )

    create_cylinder_x_start(
        comp,
        '03_02_front_pilot_d22x2',
        x0 - pilot_h,
        cy,
        cz,
        pilot_d,
        pilot_h
    )

    shaft = create_cylinder_x_start(
        comp,
        '03_03_output_shaft_d5x20',
        x0 - shaft_len,
        cy,
        cz,
        shaft_d,
        shaft_len
    )

    shaft_r = shaft_d / 2
    flat_z = cz - shaft_r + shaft_flat

    flat_tool = create_box_min(
        comp,
        'cut_motor_shaft_d_flat',
        x0 - shaft_len - 0.2,
        x0 + 0.2,
        cy - shaft_r - 1.0,
        cy + shaft_r + 1.0,
        flat_z,
        flat_z + shaft_d
    )
    combine_cut(comp, shaft, [flat_tool])

    half_pitch = hole_pitch / 2

    for dy in [-half_pitch, half_pitch]:
        for dz in [-half_pitch, half_pitch]:
            hole_tool = create_cylinder_x_start(
                comp,
                'cut_motor_m2p5_mount_hole',
                x0 - 0.1,
                cy + dy,
                cz + dz,
                hole_d,
                hole_depth + 0.2
            )
            combine_cut(comp, body, [hole_tool])

    conn_t = 2.7
    conn_x_len = 6.0
    conn_z_len = 15.0

    conn_x0 = x0 + body_len - conn_x_len
    conn_x1 = x0 + body_len

    conn_y0 = body_y0 - conn_t
    conn_y1 = body_y0

    conn_z0 = cz - conn_z_len / 2
    conn_z1 = cz + conn_z_len / 2

    create_box_min(
        comp,
        '03_04_side_flat_connector_15x6x2p7',
        conn_x0,
        conn_x1,
        conn_y0,
        conn_y1,
        conn_z0,
        conn_z1
    )

    wire_x = (conn_x0 + conn_x1) / 2
    wire_y0 = conn_y0 - wire_len
    wire_y1 = conn_y0

    wire_zs = [
        cz + 1.5 * wire_gap,
        cz + 0.5 * wire_gap,
        cz - 0.5 * wire_gap,
        cz - 1.5 * wire_gap
    ]

    for i, wz in enumerate(wire_zs):
        create_box_min(
            comp,
            '03_05_side_wire_reference_' + str(i + 1),
            wire_x - wire_d / 2,
            wire_x + wire_d / 2,
            wire_y0,
            wire_y1,
            wz - wire_d / 2,
            wz + wire_d / 2
        )


def create_gt2_pulley(comp, prefix, x_start, cy, cz, bore_d):
    total_len = 16.0
    flange_d = 16.0
    belt_land_d = 12.0

    front_flange_t = 1.4
    belt_land_w = 7.2
    rear_len = total_len - front_flange_t - belt_land_w

    front = create_cylinder_x_start(
        comp,
        prefix + '_front_flange_d16',
        x_start,
        cy,
        cz,
        flange_d,
        front_flange_t
    )

    land = create_cylinder_x_start(
        comp,
        prefix + '_belt_land_d12',
        x_start + front_flange_t,
        cy,
        cz,
        belt_land_d,
        belt_land_w
    )

    rear = create_cylinder_x_start(
        comp,
        prefix + '_rear_body_d16',
        x_start + front_flange_t + belt_land_w,
        cy,
        cz,
        flange_d,
        rear_len
    )

    sections = [
        (front, x_start, front_flange_t),
        (land, x_start + front_flange_t, belt_land_w),
        (rear, x_start + front_flange_t + belt_land_w, rear_len)
    ]

    for body, sx, length in sections:
        bore = create_cylinder_x_start(
            comp,
            'cut_' + prefix + '_bore',
            sx - 0.2,
            cy,
            cz,
            bore_d,
            length + 0.4
        )
        combine_cut(comp, body, [bore])


def create_gt2_belt(comp):
    belt_x = -18.0
    belt_width = 6.0

    left_y = 0.0
    right_y = 50.0
    center_z = 0.0

    pitch = 2.0
    pulley_teeth = 20
    belt_thickness = 1.4

    pitch_radius = pulley_teeth * pitch / (2 * math.pi)
    inner_r = pitch_radius - belt_thickness / 2
    outer_r = pitch_radius + belt_thickness / 2

    outer_middle = create_box_min(
        comp,
        '03_08_gt2_belt_outer_straight',
        belt_x,
        belt_x + belt_width,
        left_y,
        right_y,
        center_z - outer_r,
        center_z + outer_r
    )

    outer_left = create_cylinder_x_start(
        comp,
        '03_09_gt2_belt_outer_left_round',
        belt_x,
        left_y,
        center_z,
        outer_r * 2,
        belt_width
    )

    outer_right = create_cylinder_x_start(
        comp,
        '03_10_gt2_belt_outer_right_round',
        belt_x,
        right_y,
        center_z,
        outer_r * 2,
        belt_width
    )

    belt = combine_join(comp, outer_middle, [outer_left, outer_right])
    belt.name = '03_11_GT2_140_belt_reference'

    inner_middle = create_box_min(
        comp,
        'cut_gt2_belt_inner_straight',
        belt_x - 0.2,
        belt_x + belt_width + 0.2,
        left_y,
        right_y,
        center_z - inner_r,
        center_z + inner_r
    )
    combine_cut(comp, belt, [inner_middle])

    inner_left = create_cylinder_x_start(
        comp,
        'cut_gt2_belt_inner_left_round',
        belt_x - 0.2,
        left_y,
        center_z,
        inner_r * 2,
        belt_width + 0.4
    )
    combine_cut(comp, belt, [inner_left])

    inner_right = create_cylinder_x_start(
        comp,
        'cut_gt2_belt_inner_right_round',
        belt_x - 0.2,
        right_y,
        center_z,
        inner_r * 2,
        belt_width + 0.4
    )
    combine_cut(comp, belt, [inner_right])


def create_o_ring_roller(comp, center_x, center_y, center_z):
    hub_width = 6.0
    bore_dia = 3.2

    flange_dia = 18.0
    groove_root_dia = 14.7
    groove_width = 3.2
    flange_width = (hub_width - groove_width) / 2.0

    screw_hole_dia = 2.4
    screw_hole_len = 17.0

    nut_slot_sx = 5.4
    nut_slot_sy = 1.9
    nut_slot_sz = 4.3

    nut_slot_y_top = 4.7
    nut_slot_y_bottom = -4.7

    nut_slot_x_top = 0.3
    nut_slot_x_bottom = -0.3

    o_ring_od = 20.0
    o_ring_id = 14.0
    o_ring_width = 3.0

    collar_w = 4.0
    collar_gap = 0.2

    core = create_cylinder_x_center(
        comp,
        '03_15_roller_hub_groove_root_14p7',
        center_x,
        center_y,
        center_z,
        groove_root_dia,
        hub_width
    )

    left_flange = create_cylinder_x_center(
        comp,
        '03_16_roller_hub_left_flange_18',
        center_x - (hub_width / 2 - flange_width / 2),
        center_y,
        center_z,
        flange_dia,
        flange_width
    )

    right_flange = create_cylinder_x_center(
        comp,
        '03_17_roller_hub_right_flange_18',
        center_x + (hub_width / 2 - flange_width / 2),
        center_y,
        center_z,
        flange_dia,
        flange_width
    )

    hub = combine_join(comp, core, [left_flange, right_flange])
    hub.name = '03_18_printed_o_ring_hub_reference'

    bore = create_cylinder_x_center(
        comp,
        'cut_roller_hub_3p2_bore',
        center_x,
        center_y,
        center_z,
        bore_dia,
        hub_width + 2.0
    )

    screw_hole = create_cylinder_y_center(
        comp,
        'cut_roller_dual_m2_set_screw_hole',
        center_x,
        center_y,
        center_z,
        screw_hole_dia,
        screw_hole_len
    )

    nut_slot_top = create_box_center(
        comp,
        'cut_roller_top_m2_nut_slot',
        center_x + nut_slot_x_top,
        center_y + nut_slot_y_top,
        center_z,
        nut_slot_sx,
        nut_slot_sy,
        nut_slot_sz
    )

    nut_slot_bottom = create_box_center(
        comp,
        'cut_roller_bottom_m2_nut_slot',
        center_x + nut_slot_x_bottom,
        center_y + nut_slot_y_bottom,
        center_z,
        nut_slot_sx,
        nut_slot_sy,
        nut_slot_sz
    )

    combine_cut(comp, hub, [bore, screw_hole, nut_slot_top, nut_slot_bottom])
    hub.name = '03_19_printed_o_ring_hub_cut_reference'

    create_ring_x(
        comp,
        '03_20_o_ring_20od_14id_3w',
        center_x,
        center_y,
        center_z,
        o_ring_od,
        o_ring_id,
        o_ring_width
    )

    left_collar_cx = center_x - hub_width / 2 - collar_gap - collar_w / 2
    right_collar_cx = center_x + hub_width / 2 + collar_gap + collar_w / 2

    create_shaft_collar(
        comp,
        '03_21_roller_left_shaft_collar',
        left_collar_cx,
        center_y,
        center_z
    )

    create_shaft_collar(
        comp,
        '03_22_roller_right_shaft_collar',
        right_collar_cx,
        center_y,
        center_z
    )


def add_bearing_seat_cutters(comp, cutters, arm_cx, y_pos, z_pos, arm_t):
    bearing_body_dia = 8.2
    flange_pocket_dia = 9.8
    flange_pocket_depth = 0.8

    cutters.append(create_cylinder_x_center(
        comp,
        'cut_bearing_body_8p2',
        arm_cx,
        y_pos,
        z_pos,
        bearing_body_dia,
        arm_t + 2.0
    ))

    cutters.append(create_cylinder_x_center(
        comp,
        'cut_flange_pocket_pos_x',
        arm_cx + arm_t / 2 - flange_pocket_depth / 2,
        y_pos,
        z_pos,
        flange_pocket_dia,
        flange_pocket_depth + 0.1
    ))

    cutters.append(create_cylinder_x_center(
        comp,
        'cut_flange_pocket_neg_x',
        arm_cx - arm_t / 2 + flange_pocket_depth / 2,
        y_pos,
        z_pos,
        flange_pocket_dia,
        flange_pocket_depth + 0.1
    ))


def create_f693zz_bearing(comp, name, cx, cy, cz):
    bearing_width = 4.0
    bearing_od = 8.0
    bearing_id = 3.0
    flange_od = 9.5
    flange_depth = 0.8

    body = create_cylinder_x_center(
        comp,
        name + '_body_8od_4w',
        cx,
        cy,
        cz,
        bearing_od,
        bearing_width
    )

    flange_pos = create_cylinder_x_center(
        comp,
        name + '_flange_pos_x_9p5od',
        cx + bearing_width / 2 - flange_depth / 2,
        cy,
        cz,
        flange_od,
        flange_depth
    )

    flange_neg = create_cylinder_x_center(
        comp,
        name + '_flange_neg_x_9p5od',
        cx - bearing_width / 2 + flange_depth / 2,
        cy,
        cz,
        flange_od,
        flange_depth
    )

    bearing = combine_join(comp, body, [flange_pos, flange_neg])
    bearing.name = name + '_F693ZZ_reference'

    bore = create_cylinder_x_center(
        comp,
        'cut_' + name + '_3mm_bore',
        cx,
        cy,
        cz,
        bearing_id,
        bearing_width + 1.0
    )

    combine_cut(comp, bearing, [bore])
    bearing.name = name + '_F693ZZ_reference'
    return bearing


def create_swing_arm(comp, prefix, arm_cx, shaft_y, shaft_z):
    arm_t = 4.0
    centre_dist = 50.0

    end_dia = 18.0
    web_width_z = 14.0

    bridge_y = 35.10
    bridge_z = 9.70
    bridge_hole_dia = 3.4

    bridge_lug_y_size = 8.0
    bridge_lug_top_wall = 1.5

    pivot_y = shaft_y
    free_y = shaft_y - centre_dist
    centre_z = shaft_z

    pivot_end = create_cylinder_x_center(
        comp,
        prefix + '_pivot_round_end',
        arm_cx,
        pivot_y,
        centre_z,
        end_dia,
        arm_t
    )

    free_end = create_cylinder_x_center(
        comp,
        prefix + '_free_round_end',
        arm_cx,
        free_y,
        centre_z,
        end_dia,
        arm_t
    )

    web = create_box_center(
        comp,
        prefix + '_middle_web',
        arm_cx,
        shaft_y - centre_dist / 2.0,
        centre_z,
        arm_t,
        centre_dist,
        web_width_z
    )

    arm = combine_join(comp, pivot_end, [free_end, web])
    arm.name = prefix + '_swing_arm_base'

    arm_top_z = centre_z + web_width_z / 2.0
    lug_base_z = arm_top_z
    lug_top_z = bridge_z + bridge_hole_dia / 2.0 + bridge_lug_top_wall
    lug_h = lug_top_z - lug_base_z

    if lug_h <= 0:
        raise ValueError(prefix + ' bridge lug height is not valid.')

    bridge_lug = create_box_center(
        comp,
        prefix + '_bridge_hanger_lug',
        arm_cx,
        bridge_y,
        lug_base_z + lug_h / 2.0,
        arm_t,
        bridge_lug_y_size,
        lug_h
    )

    lug_hole_cut = create_cylinder_x_center_safe(
        comp,
        'cut_' + prefix + '_bridge_lug_3p4_hole_before_join',
        arm_cx,
        bridge_y,
        bridge_z,
        bridge_hole_dia,
        arm_t + 8.0
    )

    combine_cut(comp, bridge_lug, [lug_hole_cut])
    bridge_lug.name = prefix + '_bridge_hanger_lug_3p4_hole'

    arm = combine_join(comp, arm, [bridge_lug])
    arm.name = prefix + '_swing_arm_base_with_bridge_lug'

    arm = add_upper_spring_tab(
        comp,
        arm,
        prefix,
        arm_cx,
        free_y,
        pivot_y,
        centre_z,
        arm_t,
        web_width_z
    )

    cutters = []

    add_bearing_seat_cutters(
        comp,
        cutters,
        arm_cx,
        pivot_y,
        centre_z,
        arm_t
    )

    add_bearing_seat_cutters(
        comp,
        cutters,
        arm_cx,
        free_y,
        centre_z,
        arm_t
    )

    combine_cut(comp, arm, cutters)

    final_bridge_cut = create_cylinder_x_center_safe(
        comp,
        'cut_' + prefix + '_bridge_lug_3p4_hole_after_join',
        arm_cx,
        bridge_y,
        bridge_z,
        bridge_hole_dia,
        arm_t + 8.0
    )

    combine_cut(comp, arm, [final_bridge_cut])
    arm.name = prefix + '_Swing_Arm_Print_Body'

    create_f693zz_bearing(
        comp,
        prefix + '_pivot',
        arm_cx,
        pivot_y,
        centre_z
    )

    create_f693zz_bearing(
        comp,
        prefix + '_free',
        arm_cx,
        free_y,
        centre_z
    )


def create_pivot_short_shaft_set(comp, prefix, arm_cx, pivot_y, pivot_z):
    shaft_len = 18.0
    shaft_dia = 3.0

    collar_w = 4.0

    shaft_left_x = arm_cx - shaft_len / 2.0
    shaft_right_x = arm_cx + shaft_len / 2.0

    left_collar_cx = shaft_left_x + collar_w / 2.0
    right_collar_cx = shaft_right_x - collar_w / 2.0

    create_cylinder_x_center(
        comp,
        prefix + '_pivot_short_shaft_d3_len18',
        arm_cx,
        pivot_y,
        pivot_z,
        shaft_dia,
        shaft_len
    )

    create_shaft_collar(
        comp,
        prefix + '_left_pivot_shaft_collar_edge_flush',
        left_collar_cx,
        pivot_y,
        pivot_z
    )

    create_shaft_collar(
        comp,
        prefix + '_right_pivot_shaft_collar_edge_flush',
        right_collar_cx,
        pivot_y,
        pivot_z
    )


def create_swing_arm_groups(comp):
    shaft_y = 50.0
    shaft_z = 0.0

    shaft_left_x = -45.75
    shaft_right_x = 54.25

    layout_shaft_left_x = -33.25
    layout_shaft_right_x = 41.75

    structure_left_x = -20.0
    structure_right_x = 28.5

    collar_w = 4.0
    arm_t = 4.0
    side_gap = 0.2

    arm_out_offset = 8.0

    exposed_left_len = structure_left_x - layout_shaft_left_x
    exposed_right_len = layout_shaft_right_x - structure_right_x

    occupied_side_len = collar_w + side_gap + arm_t + side_gap + collar_w

    left_edge_clear = (exposed_left_len - occupied_side_len) / 2.0
    right_edge_clear = (exposed_right_len - occupied_side_len) / 2.0

    if left_edge_clear < 0 or right_edge_clear < 0:
        raise ValueError('Original arm layout does not have enough shaft space.')

    left_outer_cx = layout_shaft_left_x + left_edge_clear + collar_w / 2.0
    left_arm_cx = left_outer_cx + collar_w / 2.0 + side_gap + arm_t / 2.0
    left_inner_cx = left_arm_cx + arm_t / 2.0 + side_gap + collar_w / 2.0

    right_inner_cx = structure_right_x + right_edge_clear + collar_w / 2.0
    right_arm_cx = right_inner_cx + collar_w / 2.0 + side_gap + arm_t / 2.0
    right_outer_cx = right_arm_cx + arm_t / 2.0 + side_gap + collar_w / 2.0

    left_outer_cx -= arm_out_offset
    left_arm_cx -= arm_out_offset
    left_inner_cx -= arm_out_offset

    right_inner_cx += arm_out_offset
    right_arm_cx += arm_out_offset
    right_outer_cx += arm_out_offset

    left_group_min = left_outer_cx - collar_w / 2.0
    right_group_max = right_outer_cx + collar_w / 2.0

    if left_group_min < shaft_left_x or right_group_max > shaft_right_x:
        raise ValueError('Moved arm groups exceed the 100 mm shaft range.')

    create_shaft_collar(
        comp,
        '03_23_left_outer_main_shaft_collar',
        left_outer_cx,
        shaft_y,
        shaft_z
    )

    create_shaft_collar(
        comp,
        '03_24_left_inner_main_shaft_collar',
        left_inner_cx,
        shaft_y,
        shaft_z
    )

    create_shaft_collar(
        comp,
        '03_25_right_inner_main_shaft_collar',
        right_inner_cx,
        shaft_y,
        shaft_z
    )

    create_shaft_collar(
        comp,
        '03_26_right_outer_main_shaft_collar',
        right_outer_cx,
        shaft_y,
        shaft_z
    )

    create_swing_arm(
        comp,
        '03_27_left',
        left_arm_cx,
        shaft_y,
        shaft_z
    )

    create_swing_arm(
        comp,
        '03_28_right',
        right_arm_cx,
        shaft_y,
        shaft_z
    )

    pivot_y = 0.0
    pivot_z = shaft_z

    create_pivot_short_shaft_set(
        comp,
        '03_29_left',
        left_arm_cx,
        pivot_y,
        pivot_z
    )

    create_pivot_short_shaft_set(
        comp,
        '03_30_right',
        right_arm_cx,
        pivot_y,
        pivot_z
    )

    return left_arm_cx, right_arm_cx


def create_driven_shaft_and_roller(comp):
    belt_x = -18.0
    belt_width = 6.0

    shaft_y = 50.0
    shaft_z = 0.0

    shaft_len = 100.0
    shaft_dia = 3.0

    idler_front_flange_t = 1.4
    idler_belt_land_w = 7.2

    idler_x_start = (
        belt_x
        - idler_front_flange_t
        - (idler_belt_land_w - belt_width) / 2.0
    )

    structure_left_x = idler_x_start
    structure_right_x = 28.5

    structure_width = structure_right_x - structure_left_x
    exposed_each_side = (shaft_len - structure_width) / 2.0

    shaft_x_start = structure_left_x - exposed_each_side
    shaft_x_end = structure_right_x + exposed_each_side
    shaft_cx = (shaft_x_start + shaft_x_end) / 2.0

    create_cylinder_x_center(
        comp,
        '03_12_driven_shaft_d3_len100',
        shaft_cx,
        shaft_y,
        shaft_z,
        shaft_dia,
        shaft_len
    )

    create_gt2_pulley(
        comp,
        '03_13_driven_gt2_20t_3mm',
        idler_x_start,
        shaft_y,
        shaft_z,
        3.0
    )

    create_o_ring_roller(
        comp,
        shaft_cx,
        shaft_y,
        shaft_z
    )

    return shaft_x_start, shaft_x_end, shaft_cx


def run(context):
    ui = None

    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = app.activeProduct

        if not isinstance(design, adsk.fusion.Design):
            ui.messageBox('Open a Fusion design first.')
            return

        root = design.rootComponent

        clean_existing(root, ['03_Drive_Head'])

        occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        comp = occ.component
        comp.name = '03_Drive_Head'

        create_nema11_motor(comp)

        create_gt2_pulley(
            comp,
            '03_06_motor_gt2_20t_5mm',
            -20.0,
            0.0,
            0.0,
            5.0
        )

        create_gt2_belt(comp)

        shaft_x_start, shaft_x_end, shaft_cx = create_driven_shaft_and_roller(comp)

        left_arm_cx, right_arm_cx = create_swing_arm_groups(comp)

        info = place_drive_head_to_lock_wheel(
            design,
            root,
            occ,
            shaft_cx
        )

        try:
            design.snapshots.add()
        except Exception:
            pass

        app.activeViewport.fit()

        ui.messageBox(
            '03 drive head generated and aligned.\n\n'
            'Target wheel: {}\n'
            'Wheel centre XYZ: {:.2f}, {:.2f}, {:.2f} mm\n'
            'Roller axis XYZ: {:.2f}, {:.2f}, {:.2f} mm\n'
            'Drive head translation XYZ: {:.2f}, {:.2f}, {:.2f} mm\n\n'
            'Motor near edge to wheel centre in Y: {:.2f} mm\n\n'
            'Driven shaft X range: {:.2f} to {:.2f}\n'
            'Driven shaft centre X: {:.2f}\n'
            'Left arm centre X: {:.3f}\n'
            'Right arm centre X: {:.3f}\n'
            'Bridge hanger hole Y/Z: 35.10 / 9.70 mm\n'
            'Bridge lug was cut before joining to arm.\n'
            'arm_out_offset: 8.0 mm\n'
            'Upper spring hook: 3 holes, aligned to lower spring plate, 20 mm vertical distance'.format(
                TARGET_WHEEL_NO,
                to_mm(info['wheel_x']),
                to_mm(info['wheel_y']),
                to_mm(info['wheel_z']),
                to_mm(info['roller_x']),
                to_mm(info['roller_y']),
                to_mm(info['roller_z']),
                to_mm(info['dx']),
                to_mm(info['dy']),
                to_mm(info['dz']),
                to_mm(info['motor_to_wheel_center_y']),
                shaft_x_start,
                shaft_x_end,
                shaft_cx,
                left_arm_cx,
                right_arm_cx
            )
        )

    except Exception:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))