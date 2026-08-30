import adsk.core
import adsk.fusion
import traceback
import math


def silent_message_box(*args, **kwargs):
    return 0


# Upper spring hooks.
SPRING_UPPER_TO_LOWER_HOLE_MM = 18.0
SPRING_UPPER_HOLE_D_MM = 2.5
SPRING_UPPER_HOLE_SPACING_MM = 6.5
SPRING_UPPER_TAB_T_Z_MM = 3.0
SPRING_UPPER_TAB_Y_MARGIN_MM = 3.5
SPRING_UPPER_TAB_X_MARGIN_MM = 3.0
SPRING_UPPER_RISER_X_OVERLAP_MM = 0.6
SPRING_UPPER_RISER_Z_OVERLAP_MM = 0.08

# Must match current 11 base spring plates.
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
    if abs(angle_deg) < 1e-9:
        return

    objs = adsk.core.ObjectCollection.create()
    objs.add(body)

    mat = adsk.core.Matrix3D.create()
    mat.setToRotation(math.radians(angle_deg), axis, point)

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

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def create_cylinder_x_safe(comp, name, cx, cy, cz, dia, length):
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + '_sk'

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(mm(cx), mm(cy), 0),
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

    move_body(comp, body, 0, 0, cz - length / 2)

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

    try:
        sk.isVisible = False
    except Exception:
        pass

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

    if side_sign < 0:
        inner_x = arm_cx + arm_t / 2.0
    else:
        inner_x = arm_cx - arm_t / 2.0

    outer_x = lower_hole_x + side_sign * SPRING_UPPER_TAB_X_MARGIN_MM

    x0 = min(inner_x, outer_x)
    x1 = max(inner_x, outer_x)

    tab = create_xy_plate_with_z_holes(
        comp,
        prefix + '_upper_spring_hook_tab_3x2p5_holes_18mm_above_lower',
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
    arm.name = prefix + '_swing_arm_base_with_bridge_lug_and_upper_spring_hook_18mm'

    return arm


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


def add_bearing_seat_cutters(comp, cutters, arm_cx, y_pos, z_pos, arm_t, body_dia, flange_dia, flange_depth):
    cut_len_x = arm_t + 2.0

    cutters.append(create_cylinder_x(
        comp,
        "cut_bearing_body_8p2",
        arm_cx,
        y_pos,
        z_pos,
        body_dia,
        cut_len_x
    ))

    cutters.append(create_cylinder_x(
        comp,
        "cut_flange_pocket_pos_x",
        arm_cx + arm_t / 2 - flange_depth / 2,
        y_pos,
        z_pos,
        flange_dia,
        flange_depth + 0.1
    ))

    cutters.append(create_cylinder_x(
        comp,
        "cut_flange_pocket_neg_x",
        arm_cx - arm_t / 2 + flange_depth / 2,
        y_pos,
        z_pos,
        flange_dia,
        flange_depth + 0.1
    ))


def create_swing_arm_with_bridge_lug(comp, prefix, arm_cx):
    arm_t = 4.0
    centre_dist = 50.0

    end_dia = 18.0
    web_width_z = 14.0

    bearing_body_dia = 8.2
    flange_pocket_dia = 9.8
    flange_pocket_depth = 0.8

    rear_y = 0.0
    front_y = centre_dist
    centre_z = 0.0

    bridge_y = 35.10
    bridge_z = 9.70
    bridge_hole_dia = 3.4

    bridge_lug_y_size = 8.0
    bridge_lug_top_wall = 1.5

    rear_end = create_cylinder_x(
        comp,
        prefix + "_rear_round_end",
        arm_cx,
        rear_y,
        centre_z,
        end_dia,
        arm_t
    )

    front_end = create_cylinder_x(
        comp,
        prefix + "_front_round_end",
        arm_cx,
        front_y,
        centre_z,
        end_dia,
        arm_t
    )

    web = create_box_center(
        comp,
        prefix + "_middle_web",
        arm_cx,
        centre_dist / 2,
        centre_z,
        arm_t,
        centre_dist,
        web_width_z
    )

    arm = combine_join(comp, rear_end, [front_end, web])
    arm.name = prefix + "_swing_arm_base"

    arm_top_z = centre_z + web_width_z / 2.0
    lug_base_z = arm_top_z
    lug_top_z = bridge_z + bridge_hole_dia / 2.0 + bridge_lug_top_wall
    lug_h = lug_top_z - lug_base_z

    if lug_h <= 0:
        raise ValueError(prefix + " bridge lug height is not valid.")

    bridge_lug = create_box_center(
        comp,
        prefix + "_bridge_hanger_lug",
        arm_cx,
        bridge_y,
        lug_base_z + lug_h / 2.0,
        arm_t,
        bridge_lug_y_size,
        lug_h
    )

    lug_hole_cut = create_cylinder_x_safe(
        comp,
        "cut_" + prefix + "_bridge_lug_3p4_hole_before_join",
        arm_cx,
        bridge_y,
        bridge_z,
        bridge_hole_dia,
        arm_t + 8.0
    )

    combine_cut(comp, bridge_lug, [lug_hole_cut])
    bridge_lug.name = prefix + "_bridge_hanger_lug_3p4_hole"

    arm = combine_join(comp, arm, [bridge_lug])
    arm.name = prefix + "_swing_arm_base_with_bridge_lug"

    cutters = []

    add_bearing_seat_cutters(
        comp,
        cutters,
        arm_cx,
        rear_y,
        centre_z,
        arm_t,
        bearing_body_dia,
        flange_pocket_dia,
        flange_pocket_depth
    )

    add_bearing_seat_cutters(
        comp,
        cutters,
        arm_cx,
        front_y,
        centre_z,
        arm_t,
        bearing_body_dia,
        flange_pocket_dia,
        flange_pocket_depth
    )

    combine_cut(comp, arm, cutters)

    final_bridge_cut = create_cylinder_x_safe(
        comp,
        "cut_" + prefix + "_bridge_lug_3p4_hole_after_join",
        arm_cx,
        bridge_y,
        bridge_z,
        bridge_hole_dia,
        arm_t + 8.0
    )

    combine_cut(comp, arm, [final_bridge_cut])

    arm = add_upper_spring_tab(
        comp,
        arm,
        prefix,
        arm_cx,
        rear_y,
        front_y,
        centre_z,
        arm_t,
        web_width_z
    )

    arm.name = "11_PRINT_" + prefix.capitalize() + "_Swing_Arm"

    return arm


def run(context):
    ui = None

    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = app.activeProduct

        if not isinstance(design, adsk.fusion.Design):
            silent_message_box("Open a Fusion design first.")
            return

        root = design.rootComponent

        occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        comp = occ.component
        comp.name = "11_Swing_Arm"

        create_swing_arm_with_bridge_lug(comp, "left", -8.0)
        create_swing_arm_with_bridge_lug(comp, "right", 8.0)

        try:
            design.snapshots.add()
        except Exception:
            pass

        app.activeViewport.fit()

        silent_message_box(
            "Two printable swing arms with upper spring hooks generated.\n\n"
            "Bridge lug relative position:\n"
            "Lug centre Y: 35.10 mm from rear bearing centre\n"
            "Lug centre Z: 9.45 mm\n"
            "Lug bottom Z: 7.00 mm\n"
            "Lug top Z: 11.90 mm\n"
            "Lug size: 4.0 X x 8.0 Y x 4.9 Z mm\n"
            "Hole centre Y/Z: 35.10 / 8.70 mm\n"
            "Hole dia: 3.4 mm, X-direction through-hole\n\n"
            "Export bodies:\n"
            "11_PRINT_Left_Swing_Arm\n"
            "11_PRINT_Right_Swing_Arm"
        )

    except Exception:
        if ui:
            silent_message_box("Failed:\n{}".format(traceback.format_exc()))
