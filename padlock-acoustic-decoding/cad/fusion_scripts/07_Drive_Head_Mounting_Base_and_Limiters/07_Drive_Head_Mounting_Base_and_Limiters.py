import adsk.core
import adsk.fusion
import traceback
import math


BASE_PREFIX = "07_Drive_Head_Mounting_Base_and_Limiters"

SLIDER_OCC_PREFIX = "04_X_Axis_Linear_Rail"
DRIVE_OCC_PREFIX = "03_Drive_Head"
SERVO_OCC_PREFIX = "05_MG92B_Servo_Reference"
LIMITER_OCC_PREFIX = "08_Lock_Locator_and_Limiters"
LOCK_OCC_PREFIX = "02_Padlock_Reference"

SLIDER_BODY_KEY = "04_06_slider_platform"
MOTOR_BODY_KEY = "motor_body"
MOTOR_SHAFT_KEY = "03_03_output_shaft"
MOTOR_PILOT_KEY = "03_02_front_pilot"

LEFT_SUPPORT_KEY = "03_27_left_free"
RIGHT_SUPPORT_KEY = "03_28_right_free"
LEFT_PIVOT_KEY = "03_27_left_pivot"
RIGHT_PIVOT_KEY = "03_28_right_pivot"
LEFT_ARM_KEY = "03_27_left_swing_arm_print_body"
RIGHT_ARM_KEY = "03_28_right_swing_arm_print_body"

LOCK_LIMIT_CLEAR_MM = 6.0
BASE_MARGIN_MM = 2.0
REQUIRED_MARGIN_MM = 0.5

SLIDER_MOUNT_HOLE_D_MM = 3.3
SLIDER_COUNTERBORE_D_MM = 6.0
SLIDER_COUNTERBORE_DEPTH_MM = 3.0

SPRING_HOOK_HOLE_COUNT = 3
SPRING_HOOK_PLATE_X_T_MM = 2.0
SPRING_HOOK_PLATE_Y_LEN_MM = 23.0
SPRING_HOOK_PLATE_H_MM = 6.6
SPRING_HOOK_TOP_EXTRA_MM = 1.5
SPRING_HOOK_HOLE_D_MM = 2.5
SPRING_HOOK_HOLE_SPACING_MM = 6.5
SPRING_HOOK_FORWARD_GAP_MM = 1.5
SPRING_HOOK_EDGE_GAP_MM = 1.5
SPRING_HOOK_TOP_CLEAR_MM = 2.0
SPRING_HOOK_END_MARGIN_MM = 2.0

SUPPORT_CHEEK_T_MM = 2.2
SUPPORT_SIDE_CLEAR_MM = 0.8
SUPPORT_Y_HALF_MM = 4.5
SUPPORT_TOP_CLEAR_MM = 6.0
SUPPORT_SHAFT_HOLE_D_MM = 3.0

LIMIT_WALL_T_MM = 2.0
LIMIT_WALL_CLEAR_MM = 0.4
LIMIT_OUTPUT_CORNER_OVERLAP_MM = 0.25
SERVO_OUTPUT_WALL_H_MM = 7.0
MOTOR_PILOT_CLEAR_MM = 0.6
SERVO_OUTPUT_KEYS = [
    "servo_output_shaft_ref",
    "servo_output_boss"
]

SERVO_STEP_MARGIN_MM = 0.8
SERVO_EAR_SLOT_CLEAR_MM = 0.35
SERVO_MAIN_KEYS = [
    "servo_bottom_case",
    "servo_main_case",
    "servo_top_case"
]
SERVO_EAR_KEYS = [
    "servo_left_mounting_ear",
    "servo_right_mounting_ear"
]


def mm(v):
    return v / 10.0


def to_mm(v):
    return v * 10.0


def clean_existing(root, prefixes):
    targets = []

    if isinstance(prefixes, str):
        prefixes = [prefixes]

    for i in range(root.occurrences.count):
        occ = root.occurrences.item(i)
        if not occ.component:
            continue

        for p in prefixes:
            if occ.component.name.startswith(p) or occ.name.startswith(p):
                targets.append(occ)
                break

    for occ in targets:
        try:
            occ.deleteMe()
        except Exception:
            pass


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
    return occ, comp


def body_world_bbox(occ, body):
    try:
        proxy = body.createForAssemblyContext(occ)
        return proxy.boundingBox
    except Exception:
        return body.boundingBox


def bbox_center(bb):
    return adsk.core.Point3D.create(
        (bb.minPoint.x + bb.maxPoint.x) / 2.0,
        (bb.minPoint.y + bb.maxPoint.y) / 2.0,
        (bb.minPoint.z + bb.maxPoint.z) / 2.0
    )


def find_body_bbox(occ, key):
    key = key.lower()

    for i in range(occ.component.bRepBodies.count):
        body = occ.component.bRepBodies.item(i)
        if key in body.name.lower():
            return body_world_bbox(occ, body)

    raise RuntimeError("Body not found: " + key)


def try_find_body_bbox(occ, key):
    try:
        return find_body_bbox(occ, key)
    except Exception:
        return None


def find_body_bboxes_for_keys(occ, keys):
    keys = [k.lower() for k in keys]
    boxes = []

    for i in range(occ.component.bRepBodies.count):
        body = occ.component.bRepBodies.item(i)
        name = body.name.lower()

        for key in keys:
            if key in name:
                boxes.append(body_world_bbox(occ, body))
                break

    return boxes


def union_bbox_for_keys(occ, keys):
    keys = [k.lower() for k in keys]

    min_x = None
    min_y = None
    min_z = None
    max_x = None
    max_y = None
    max_z = None

    for i in range(occ.component.bRepBodies.count):
        body = occ.component.bRepBodies.item(i)
        name = body.name.lower()

        use_body = False
        for key in keys:
            if key in name:
                use_body = True
                break

        if not use_body:
            continue

        bb = body_world_bbox(occ, body)

        if min_x is None:
            min_x = bb.minPoint.x
            min_y = bb.minPoint.y
            min_z = bb.minPoint.z
            max_x = bb.maxPoint.x
            max_y = bb.maxPoint.y
            max_z = bb.maxPoint.z
        else:
            min_x = min(min_x, bb.minPoint.x)
            min_y = min(min_y, bb.minPoint.y)
            min_z = min(min_z, bb.minPoint.z)
            max_x = max(max_x, bb.maxPoint.x)
            max_y = max(max_y, bb.maxPoint.y)
            max_z = max(max_z, bb.maxPoint.z)

    if min_x is None:
        raise RuntimeError("Bodies not found for keys: " + str(keys))

    return adsk.core.BoundingBox3D.create(
        adsk.core.Point3D.create(min_x, min_y, min_z),
        adsk.core.Point3D.create(max_x, max_y, max_z)
    )


def union_occ_bbox(root, prefixes):
    if isinstance(prefixes, str):
        prefixes = [prefixes]

    min_x = None
    min_y = None
    min_z = None
    max_x = None
    max_y = None
    max_z = None

    occs = root.allOccurrences

    for i in range(occs.count):
        occ = occs.item(i)
        if not occ.component:
            continue

        use_occ = False
        for prefix in prefixes:
            if occ.component.name.startswith(prefix) or occ.name.startswith(prefix):
                use_occ = True
                break

        if not use_occ:
            continue

        bb = occ.boundingBox

        if min_x is None:
            min_x = bb.minPoint.x
            min_y = bb.minPoint.y
            min_z = bb.minPoint.z
            max_x = bb.maxPoint.x
            max_y = bb.maxPoint.y
            max_z = bb.maxPoint.z
        else:
            min_x = min(min_x, bb.minPoint.x)
            min_y = min(min_y, bb.minPoint.y)
            min_z = min(min_z, bb.minPoint.z)
            max_x = max(max_x, bb.maxPoint.x)
            max_y = max(max_y, bb.maxPoint.y)
            max_z = max(max_z, bb.maxPoint.z)

    if min_x is None:
        return None

    return adsk.core.BoundingBox3D.create(
        adsk.core.Point3D.create(min_x, min_y, min_z),
        adsk.core.Point3D.create(max_x, max_y, max_z)
    )


def move_bodies(comp, bodies, dx, dy, dz):
    if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
        return

    objs = adsk.core.ObjectCollection.create()
    for body in bodies:
        if body:
            objs.add(body)

    if objs.count == 0:
        return

    mat = adsk.core.Matrix3D.create()
    mat.translation = adsk.core.Vector3D.create(dx, dy, dz)

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def make_box_min(comp, name, x0, x1, y0, y1, z0, z1):
    if x1 <= x0 or y1 <= y0 or z1 <= z0:
        return None

    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + "_sk"

    sk.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(x0, y0, 0),
        adsk.core.Point3D.create(x1, y1, 0)
    )

    prof = sk.profiles.item(sk.profiles.count - 1)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(z1 - z0))

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, 0, z0)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def make_box_center(comp, name, cx, cy, cz, sx, sy, sz):
    return make_box_min(
        comp,
        name,
        cx - sx / 2.0,
        cx + sx / 2.0,
        cy - sy / 2.0,
        cy + sy / 2.0,
        cz - sz / 2.0,
        cz + sz / 2.0
    )


def make_cyl_x(comp, name, cx, cy, cz, r, length):
    sk = comp.sketches.add(comp.yZConstructionPlane)
    sk.name = name + "_sk"

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(0, cy, cz),
        r
    )

    prof = sk.profiles.item(sk.profiles.count - 1)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setSymmetricExtent(
        adsk.core.ValueInput.createByReal(length),
        True
    )

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], cx, 0, 0)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def make_cyl_z(comp, name, cx, cy, cz, r, length):
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + "_sk"

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(cx, cy, 0),
        r
    )

    prof = sk.profiles.item(sk.profiles.count - 1)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setSymmetricExtent(
        adsk.core.ValueInput.createByReal(length),
        True
    )

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, 0, cz)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def offset_x_plane(comp, x):
    planes = comp.constructionPlanes
    pi = planes.createInput()
    pi.setByOffset(
        comp.yZConstructionPlane,
        adsk.core.ValueInput.createByReal(x)
    )
    return planes.add(pi)


def make_box_yz_at_x(comp, name, x_center, x_thick, y0, y1, z0, z1):
    if x_thick <= 0 or y1 <= y0 or z1 <= z0:
        return None

    plane = offset_x_plane(comp, x_center)
    sk = comp.sketches.add(plane)
    sk.name = name + "_sk"

    p1 = sk.modelToSketchSpace(
        adsk.core.Point3D.create(x_center, y0, z0)
    )
    p2 = sk.modelToSketchSpace(
        adsk.core.Point3D.create(x_center, y1, z1)
    )

    sk.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)

    prof = sk.profiles.item(sk.profiles.count - 1)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setSymmetricExtent(
        adsk.core.ValueInput.createByReal(x_thick),
        True
    )

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body



def largest_profile(sk):
    best = None
    best_area = -1.0

    for i in range(sk.profiles.count):
        prof = sk.profiles.item(i)
        try:
            area = prof.areaProperties().area
        except Exception:
            area = 0.0

        if area > best_area:
            best = prof
            best_area = area

    return best


def make_box_yz_at_x_with_hole(comp, name, x_center, x_thick, y0, y1, z0, z1, hole_y, hole_z, hole_r):
    if x_thick <= 0 or y1 <= y0 or z1 <= z0:
        return None

    plane = offset_x_plane(comp, x_center)
    sk = comp.sketches.add(plane)
    sk.name = name + "_sk"

    p1 = sk.modelToSketchSpace(
        adsk.core.Point3D.create(x_center, y0, z0)
    )
    p2 = sk.modelToSketchSpace(
        adsk.core.Point3D.create(x_center, y1, z1)
    )

    sk.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)

    hc = sk.modelToSketchSpace(
        adsk.core.Point3D.create(x_center, hole_y, hole_z)
    )
    sk.sketchCurves.sketchCircles.addByCenterRadius(hc, hole_r)

    prof = largest_profile(sk)
    if not prof:
        raise RuntimeError("No profile found for " + name)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setSymmetricExtent(
        adsk.core.ValueInput.createByReal(x_thick),
        True
    )

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def make_cyl_x_at_final(comp, name, cx, cy, cz, r, length):
    if length <= 0 or r <= 0:
        return None

    plane = offset_x_plane(comp, cx)
    sk = comp.sketches.add(plane)
    sk.name = name + "_sk"

    center = sk.modelToSketchSpace(
        adsk.core.Point3D.create(cx, cy, cz)
    )

    sk.sketchCurves.sketchCircles.addByCenterRadius(center, r)

    prof = sk.profiles.item(sk.profiles.count - 1)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setSymmetricExtent(
        adsk.core.ValueInput.createByReal(length),
        True
    )

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def combine_join(comp, target, tools):
    objs = adsk.core.ObjectCollection.create()

    for tool in tools:
        if tool:
            objs.add(tool)

    if objs.count == 0:
        return target

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)
    return target


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


def add_rect(rects, x0, x1, y0, y1):
    rects.append((x0, x1, y0, y1))


def rect_union(rects, margin):
    x0 = min(r[0] for r in rects) - margin
    x1 = max(r[1] for r in rects) + margin
    y0 = min(r[2] for r in rects) - margin
    y1 = max(r[3] for r in rects) + margin
    return x0, x1, y0, y1


def rects_overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def trim_against_limiter(base_rect, required_rect, limiter_bb, clear):
    base_x0, base_x1, base_y0, base_y1 = base_rect
    req_x0, req_x1, req_y0, req_y1 = required_rect

    keep_margin = mm(REQUIRED_MARGIN_MM)

    base_cx = (base_x0 + base_x1) / 2.0
    base_cy = (base_y0 + base_y1) / 2.0
    lim_c = bbox_center(limiter_bb)

    if rects_overlap(base_y0, base_y1, limiter_bb.minPoint.y, limiter_bb.maxPoint.y):
        if lim_c.x < base_cx:
            target = limiter_bb.maxPoint.x + clear
            max_x0 = req_x0 - keep_margin
            if target > base_x0:
                base_x0 = min(target, max_x0)
        else:
            target = limiter_bb.minPoint.x - clear
            min_x1 = req_x1 + keep_margin
            if target < base_x1:
                base_x1 = max(target, min_x1)

    if rects_overlap(base_x0, base_x1, limiter_bb.minPoint.x, limiter_bb.maxPoint.x):
        if lim_c.y < base_cy:
            target = limiter_bb.maxPoint.y + clear
            max_y0 = req_y0 - keep_margin
            if target > base_y0:
                base_y0 = min(target, max_y0)
        else:
            target = limiter_bb.minPoint.y - clear
            min_y1 = req_y1 + keep_margin
            if target < base_y1:
                base_y1 = max(target, min_y1)

    return base_x0, base_x1, base_y0, base_y1


def add_slider_mount_rect(rects, slider_bb):
    cx = (slider_bb.minPoint.x + slider_bb.maxPoint.x) / 2.0
    cy = (slider_bb.minPoint.y + slider_bb.maxPoint.y) / 2.0

    hole_space = mm(20.0)
    margin = mm(5.0)

    add_rect(
        rects,
        cx - hole_space / 2.0 - margin,
        cx + hole_space / 2.0 + margin,
        cy - hole_space / 2.0 - margin,
        cy + hole_space / 2.0 + margin
    )


def add_slider_mount_holes(comp, target, slider_bb, z0, z1):
    cx = (slider_bb.minPoint.x + slider_bb.maxPoint.x) / 2.0
    cy = (slider_bb.minPoint.y + slider_bb.maxPoint.y) / 2.0

    hole_space = mm(20.0)
    hole_r = mm(SLIDER_MOUNT_HOLE_D_MM / 2.0)
    counterbore_r = mm(SLIDER_COUNTERBORE_D_MM / 2.0)
    counterbore_depth = mm(SLIDER_COUNTERBORE_DEPTH_MM)

    if z1 - z0 <= counterbore_depth:
        raise RuntimeError("Base is too thin for 3 mm slider screw counterbores.")

    # The mounting base has limit walls / raised features above z1.  A cutter that
    # stops at the base top leaves those features across the screw holes, which
    # blocks the M3 head and makes the openings appear as partial circles.
    # Keep the 20 x 20 mm hole centres unchanged, but provide a vertical access
    # path through any geometry above the base.
    access_top_z = target.boundingBox.maxPoint.z + mm(1.0)

    through_bottom_z = z0 - mm(1.5)
    through_len = access_top_z - through_bottom_z
    through_z = (through_bottom_z + access_top_z) / 2.0

    counterbore_bottom_z = z1 - counterbore_depth
    counterbore_len = access_top_z - counterbore_bottom_z
    counterbore_z = (counterbore_bottom_z + access_top_z) / 2.0

    cutters = []

    for dx in [-hole_space / 2.0, hole_space / 2.0]:
        for dy in [-hole_space / 2.0, hole_space / 2.0]:
            hx = cx + dx
            hy = cy + dy

            cutters.append(make_cyl_z(
                comp,
                "cut_07_Slider_M3_Through_Hole",
                hx,
                hy,
                through_z,
                hole_r,
                through_len
            ))

            cutters.append(make_cyl_z(
                comp,
                "cut_07_Slider_M3_Head_Counterbore_6x3",
                hx,
                hy,
                counterbore_z,
                counterbore_r,
                counterbore_len
            ))

    combine_cut(comp, target, cutters)


def add_body_footprint(rects, bb, margin):
    add_rect(
        rects,
        bb.minPoint.x - margin,
        bb.maxPoint.x + margin,
        bb.minPoint.y - margin,
        bb.maxPoint.y + margin
    )


def swing_support_spec(support_bb, base_top_z, motor_axis_c=None):
    c0 = bbox_center(support_bb)

    if motor_axis_c:
        c = adsk.core.Point3D.create(c0.x, motor_axis_c.y, motor_axis_c.z)
    else:
        c = c0

    cheek_t = mm(SUPPORT_CHEEK_T_MM)
    side_clear = mm(SUPPORT_SIDE_CLEAR_MM)
    y_half = mm(SUPPORT_Y_HALF_MM)
    top_clear = mm(SUPPORT_TOP_CLEAR_MM)

    bearing_w_x = support_bb.maxPoint.x - support_bb.minPoint.x
    gap_x = bearing_w_x + side_clear

    z0 = base_top_z
    z1 = max(c.z + top_clear, base_top_z + mm(6.5))

    left_x0 = c.x - gap_x / 2.0 - cheek_t
    left_x1 = c.x - gap_x / 2.0
    right_x0 = c.x + gap_x / 2.0
    right_x1 = c.x + gap_x / 2.0 + cheek_t

    y0 = c.y - y_half
    y1 = c.y + y_half

    return {
        "center": c,
        "left": (left_x0, left_x1, y0, y1, z0, z1),
        "right": (right_x0, right_x1, y0, y1, z0, z1),
        "rect": (left_x0, right_x1, y0, y1),
        "hole_len": (right_x1 - left_x0) + mm(0.8)
    }


def make_swing_support(comp, prefix, spec, hole_cutters=None):
    left_x0, left_x1, y0, y1, z0, z1 = spec["left"]
    right_x0, right_x1, y0, y1, z0, z1 = spec["right"]
    c = spec["center"]

    hole_r = mm(SUPPORT_SHAFT_HOLE_D_MM / 2.0)

    left = make_box_yz_at_x_with_hole(
        comp,
        prefix + "_left_fork_cheek_3mm_motor_axis_hole",
        (left_x0 + left_x1) / 2.0,
        left_x1 - left_x0,
        y0,
        y1,
        z0,
        z1,
        c.y,
        c.z,
        hole_r
    )

    right = make_box_yz_at_x_with_hole(
        comp,
        prefix + "_right_fork_cheek_3mm_motor_axis_hole",
        (right_x0 + right_x1) / 2.0,
        right_x1 - right_x0,
        y0,
        y1,
        z0,
        z1,
        c.y,
        c.z,
        hole_r
    )

    return [left, right]


def spring_plate_spec(support_spec, support_bb, pivot_bb, arm_bb, slider_bb, base_top_z, name_prefix):
    c = support_spec["center"]
    pc = bbox_center(pivot_bb)
    dir_y = 1.0 if pc.y >= c.y else -1.0

    plate_x_t = mm(SPRING_HOOK_PLATE_X_T_MM)
    plate_y_len = mm(SPRING_HOOK_PLATE_Y_LEN_MM)
    hole_r = mm(SPRING_HOOK_HOLE_D_MM / 2.0)
    hole_spacing = mm(SPRING_HOOK_HOLE_SPACING_MM)
    forward_gap = mm(SPRING_HOOK_FORWARD_GAP_MM)
    end_margin = mm(SPRING_HOOK_END_MARGIN_MM)

    slider_cx = (slider_bb.minPoint.x + slider_bb.maxPoint.x) / 2.0
    edge_gap = mm(SPRING_HOOK_EDGE_GAP_MM)

    if c.x <= slider_cx:
        x1 = support_spec["rect"][0] - edge_gap
        x0 = x1 - plate_x_t
    else:
        x0 = support_spec["rect"][1] + edge_gap
        x1 = x0 + plate_x_t

    sy0 = support_spec["rect"][2]
    sy1 = support_spec["rect"][3]
    front_y = sy1 if dir_y > 0 else sy0

    if dir_y > 0:
        y0 = front_y + forward_gap
        y1 = y0 + plate_y_len
    else:
        y1 = front_y - forward_gap
        y0 = y1 - plate_y_len

    arm_bottom_z = support_bb.minPoint.z
    if arm_bb:
        arm_bottom_z = min(arm_bottom_z, arm_bb.minPoint.z)

    z0 = base_top_z
    plate_h = mm(SPRING_HOOK_PLATE_H_MM)
    top_extra = mm(SPRING_HOOK_TOP_EXTRA_MM)
    base_z1 = min(base_top_z + plate_h, arm_bottom_z - mm(SPRING_HOOK_TOP_CLEAR_MM))

    min_plate_h = mm(SPRING_HOOK_HOLE_D_MM + 1.0)
    if base_z1 <= z0 + min_plate_h:
        base_z1 = z0 + min_plate_h

    hole_z = (z0 + base_z1) / 2.0
    z1 = base_z1 + top_extra

    cy = (y0 + y1) / 2.0
    hole_ys = [cy - hole_spacing, cy, cy + hole_spacing]
    if dir_y < 0:
        hole_ys = sorted(hole_ys, reverse=False)

    # Shift hole group inside plate ends if needed.
    min_h = min(hole_ys)
    max_h = max(hole_ys)
    if min_h < y0 + hole_r + end_margin:
        shift = (y0 + hole_r + end_margin) - min_h
        hole_ys = [y + shift for y in hole_ys]
    if max(hole_ys) > y1 - hole_r - end_margin:
        shift = max(hole_ys) - (y1 - hole_r - end_margin)
        hole_ys = [y - shift for y in hole_ys]

    return {
        "name_prefix": name_prefix,
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y1,
        "z0": z0,
        "z1": z1,
        "cx": (x0 + x1) / 2.0,
        "hole_z": hole_z,
        "hole_ys": sorted(hole_ys),
        "hole_r": hole_r,
        "rect": (x0, x1, y0, y1)
    }


def make_spring_plate(comp, spec):
    plate = make_box_yz_at_x(
        comp,
        spec["name_prefix"] + "_spring_plate_solid_before_holes",
        spec["cx"],
        spec["x1"] - spec["x0"],
        spec["y0"],
        spec["y1"],
        spec["z0"],
        spec["z1"]
    )

    cutters = []
    cut_len = (spec["x1"] - spec["x0"]) + mm(1.0)

    for i, hy in enumerate(spec["hole_ys"]):
        cutters.append(make_cyl_x_at_final(
            comp,
            "cut_" + spec["name_prefix"] + "_spring_plate_hole_" + str(i + 1),
            spec["cx"],
            hy,
            spec["hole_z"],
            spec["hole_r"],
            cut_len
        ))

    combine_cut(comp, plate, cutters)
    plate.name = spec["name_prefix"] + "_spring_plate_3x_2p5mm_holes"
    return plate



def bbox_union_from_list(boxes):
    if not boxes:
        return None

    min_x = boxes[0].minPoint.x
    min_y = boxes[0].minPoint.y
    min_z = boxes[0].minPoint.z
    max_x = boxes[0].maxPoint.x
    max_y = boxes[0].maxPoint.y
    max_z = boxes[0].maxPoint.z

    for bb in boxes[1:]:
        min_x = min(min_x, bb.minPoint.x)
        min_y = min(min_y, bb.minPoint.y)
        min_z = min(min_z, bb.minPoint.z)
        max_x = max(max_x, bb.maxPoint.x)
        max_y = max(max_y, bb.maxPoint.y)
        max_z = max(max_z, bb.maxPoint.z)

    return adsk.core.BoundingBox3D.create(
        adsk.core.Point3D.create(min_x, min_y, min_z),
        adsk.core.Point3D.create(max_x, max_y, max_z)
    )


def limit_wall_output_side(body_bb, output_bb):
    if not output_bb:
        return None

    bc = bbox_center(body_bb)
    oc = bbox_center(output_bb)

    dx = oc.x - bc.x
    dy = oc.y - bc.y

    if abs(dx) >= abs(dy):
        if dx < 0:
            return "x_min"
        return "x_max"

    if dy < 0:
        return "y_min"
    return "y_max"


def limit_wall_height(body_bb, base_top_z, ratio=None):
    return body_bb.maxPoint.z


def make_wall_spec(name, x0, x1, y0, y1, z0, z1, kind="box", hole=None):
    return {
        "name": name,
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y1,
        "z0": z0,
        "z1": z1,
        "kind": kind,
        "hole": hole,
        "rect": (x0, x1, y0, y1)
    }


def box_limit_wall_specs(name_prefix, body_bb, base_top_z, output_side, output_h=None, output_hole=None):
    t = mm(LIMIT_WALL_T_MM)
    c = mm(LIMIT_WALL_CLEAR_MM)

    bx0 = body_bb.minPoint.x - c
    bx1 = body_bb.maxPoint.x + c
    by0 = body_bb.minPoint.y - c
    by1 = body_bb.maxPoint.y + c

    z0 = base_top_z
    z1 = limit_wall_height(body_bb, base_top_z)

    if output_h is None:
        output_z1 = z1
    else:
        output_z1 = base_top_z + output_h

    specs = []

    # X-min side
    x0 = bx0 - t
    x1 = bx0
    if output_side == "x_min":
        specs.append(make_wall_spec(
            name_prefix + "_x_min_output_limit_wall",
            x0, x1, by0, by1, z0, output_z1,
            "x_wall_with_hole" if output_hole else "box",
            output_hole
        ))
    else:
        specs.append(make_wall_spec(
            name_prefix + "_x_min_limit_wall",
            x0, x1, by0, by1, z0, z1
        ))

    # X-max side
    x0 = bx1
    x1 = bx1 + t
    if output_side == "x_max":
        specs.append(make_wall_spec(
            name_prefix + "_x_max_output_limit_wall",
            x0, x1, by0, by1, z0, output_z1,
            "x_wall_with_hole" if output_hole else "box",
            output_hole
        ))
    else:
        specs.append(make_wall_spec(
            name_prefix + "_x_max_limit_wall",
            x0, x1, by0, by1, z0, z1
        ))

    # Y-min side
    y0 = by0 - t
    y1 = by0
    if output_side == "y_min":
        specs.append(make_wall_spec(
            name_prefix + "_y_min_output_limit_wall",
            bx0 - t, bx1 + t, y0, y1, z0, output_z1,
            "box",
            None
        ))
    else:
        specs.append(make_wall_spec(
            name_prefix + "_y_min_limit_wall",
            bx0 - t, bx1 + t, y0, y1, z0, z1
        ))

    # Y-max side
    y0 = by1
    y1 = by1 + t
    if output_side == "y_max":
        specs.append(make_wall_spec(
            name_prefix + "_y_max_output_limit_wall",
            bx0 - t, bx1 + t, y0, y1, z0, output_z1,
            "box",
            None
        ))
    else:
        specs.append(make_wall_spec(
            name_prefix + "_y_max_limit_wall",
            bx0 - t, bx1 + t, y0, y1, z0, z1
        ))

    return specs


def motor_pilot_hole_spec(motor_pilot_bb, motor_axis_c):
    if not motor_pilot_bb or not motor_axis_c:
        return None

    r_y = (motor_pilot_bb.maxPoint.y - motor_pilot_bb.minPoint.y) / 2.0
    r_z = (motor_pilot_bb.maxPoint.z - motor_pilot_bb.minPoint.z) / 2.0
    r = max(r_y, r_z) + mm(MOTOR_PILOT_CLEAR_MM)

    return {
        "cy": motor_axis_c.y,
        "cz": motor_axis_c.z,
        "r": r
    }


def fit_rect_from_bbox(bb):
    c = mm(LIMIT_WALL_CLEAR_MM)
    return {
        "x0": bb.minPoint.x - c,
        "x1": bb.maxPoint.x + c,
        "y0": bb.minPoint.y - c,
        "y1": bb.maxPoint.y + c
    }


def wall_range_x_for_y_wall(fit, shared_side):
    t = mm(LIMIT_WALL_T_MM)

    if shared_side == "x_max":
        return fit["x0"] - t, fit["x1"]

    if shared_side == "x_min":
        return fit["x0"], fit["x1"] + t

    return fit["x0"] - t, fit["x1"] + t


def wall_range_y_for_x_wall(fit, shared_side):
    t = mm(LIMIT_WALL_T_MM)

    if shared_side == "y_max":
        return fit["y0"] - t, fit["y1"]

    if shared_side == "y_min":
        return fit["y0"], fit["y1"] + t

    return fit["y0"] - t, fit["y1"] + t


def wall_spec_for_side(prefix, fit, side, z0, z1, shared_side=None, output_side=None, output_z1=None, output_hole=None):
    t = mm(LIMIT_WALL_T_MM)
    kind = "box"
    hole = None
    wall_z1 = z1

    if side == output_side:
        if output_z1 is not None:
            wall_z1 = output_z1
        if output_hole and side in ["x_min", "x_max"]:
            kind = "x_wall_with_hole"
            hole = output_hole

    y0_for_x, y1_for_x = wall_range_y_for_x_wall(fit, shared_side)
    x0_for_y, x1_for_y = wall_range_x_for_y_wall(fit, shared_side)

    # On the output-shaft side, the front wall is not a full closed wall.
    # Trim adjacent side walls so they do not create useless protruding tabs.
    if output_side == "x_min":
        x0_for_y = max(x0_for_y, fit["x0"])
    elif output_side == "x_max":
        x1_for_y = min(x1_for_y, fit["x1"])
    elif output_side == "y_min":
        y0_for_x = max(y0_for_x, fit["y0"])
    elif output_side == "y_max":
        y1_for_x = min(y1_for_x, fit["y1"])

    if side == "x_min":
        return make_wall_spec(
            prefix + "_x_min_limit_wall",
            fit["x0"] - t,
            fit["x0"],
            y0_for_x,
            y1_for_x,
            z0,
            wall_z1,
            kind,
            hole
        )

    if side == "x_max":
        return make_wall_spec(
            prefix + "_x_max_limit_wall",
            fit["x1"],
            fit["x1"] + t,
            y0_for_x,
            y1_for_x,
            z0,
            wall_z1,
            kind,
            hole
        )

    if side == "y_min":
        return make_wall_spec(
            prefix + "_y_min_limit_wall",
            x0_for_y,
            x1_for_y,
            fit["y0"] - t,
            fit["y0"],
            z0,
            wall_z1,
            "box",
            None
        )

    if side == "y_max":
        return make_wall_spec(
            prefix + "_y_max_limit_wall",
            x0_for_y,
            x1_for_y,
            fit["y1"],
            fit["y1"] + t,
            z0,
            wall_z1,
            "box",
            None
        )

    raise RuntimeError("Unknown wall side: " + side)


def shared_side_between(a_bb, b_bb):
    ac = bbox_center(a_bb)
    bc = bbox_center(b_bb)

    if abs(ac.x - bc.x) >= abs(ac.y - bc.y):
        if ac.x < bc.x:
            return "x_max", "x_min", "x"
        return "x_min", "x_max", "x"

    if ac.y < bc.y:
        return "y_max", "y_min", "y"
    return "y_min", "y_max", "y"



def add_shared_output_corner_connectors(specs, name_prefix, fit, output_side, axis, gap0, gap1, base_top_z, output_z1):
    if not output_side or output_z1 <= base_top_z:
        return

    t = mm(LIMIT_WALL_T_MM)
    overlap = mm(LIMIT_OUTPUT_CORNER_OVERLAP_MM)

    if axis == "x":
        # Shared wall is vertical in the gap between motor and servo, running along Y.
        # Add only a low connector at the output end, so the output face joins the shared wall
        # without extending a full-height useless tab.
        if output_side == "y_min":
            specs.append(make_wall_spec(
                name_prefix + "_shared_output_corner_y_min_connector",
                gap0,
                gap1,
                fit["y0"] - t,
                fit["y0"] + overlap,
                base_top_z,
                output_z1
            ))
        elif output_side == "y_max":
            specs.append(make_wall_spec(
                name_prefix + "_shared_output_corner_y_max_connector",
                gap0,
                gap1,
                fit["y1"] - overlap,
                fit["y1"] + t,
                base_top_z,
                output_z1
            ))

    else:
        # Shared wall runs along X.
        if output_side == "x_min":
            specs.append(make_wall_spec(
                name_prefix + "_shared_output_corner_x_min_connector",
                fit["x0"] - t,
                fit["x0"] + overlap,
                gap0,
                gap1,
                base_top_z,
                output_z1
            ))
        elif output_side == "x_max":
            specs.append(make_wall_spec(
                name_prefix + "_shared_output_corner_x_max_connector",
                fit["x1"] - overlap,
                fit["x1"] + t,
                gap0,
                gap1,
                base_top_z,
                output_z1
            ))

def opposite_side(side):
    if side == "x_min":
        return "x_max"
    if side == "x_max":
        return "x_min"
    if side == "y_min":
        return "y_max"
    if side == "y_max":
        return "y_min"
    return None


def servo_outer_edge_coord(motor_bb, servo_bb):
    servo_fit = fit_rect_from_bbox(servo_bb)
    t = mm(LIMIT_WALL_T_MM)
    motor_shared, servo_shared, axis = shared_side_between(motor_bb, servo_bb)
    side = opposite_side(servo_shared)

    if side == "x_min":
        return side, servo_fit["x0"] - t
    if side == "x_max":
        return side, servo_fit["x1"] + t
    if side == "y_min":
        return side, servo_fit["y0"] - t
    if side == "y_max":
        return side, servo_fit["y1"] + t

    return None, None


def force_base_to_servo_outer_edge(base_rect, motor_bb, servo_bb):
    base_x0, base_x1, base_y0, base_y1 = base_rect
    side, coord = servo_outer_edge_coord(motor_bb, servo_bb)

    if side == "x_min":
        base_x0 = coord
    elif side == "x_max":
        base_x1 = coord
    elif side == "y_min":
        base_y0 = coord
    elif side == "y_max":
        base_y1 = coord

    return base_x0, base_x1, base_y0, base_y1


def combined_limit_wall_specs(motor_bb, servo_bb, motor_shaft_bb, motor_pilot_bb, servo_output_bb, base_top_z):
    motor_fit = fit_rect_from_bbox(motor_bb)
    servo_fit = fit_rect_from_bbox(servo_bb)

    motor_output_side = limit_wall_output_side(motor_bb, motor_shaft_bb)
    servo_output_side = limit_wall_output_side(servo_bb, servo_output_bb)

    motor_axis_c = bbox_center(motor_shaft_bb) if motor_shaft_bb else bbox_center(motor_bb)
    motor_pilot_hole = motor_pilot_hole_spec(motor_pilot_bb, motor_axis_c)

    # Motor front wall is only up to the centreline of the 22 mm pilot.
    motor_output_z1 = motor_axis_c.z
    servo_output_z1 = base_top_z + mm(SERVO_OUTPUT_WALL_H_MM)

    motor_shared, servo_shared, axis = shared_side_between(motor_bb, servo_bb)
    sides = ["x_min", "x_max", "y_min", "y_max"]

    specs = []

    for side in sides:
        if side != motor_shared:
            specs.append(wall_spec_for_side(
                "07_motor",
                motor_fit,
                side,
                base_top_z,
                motor_bb.maxPoint.z,
                motor_shared,
                motor_output_side,
                motor_output_z1,
                motor_pilot_hole
            ))

    for side in sides:
        if side != servo_shared:
            specs.append(wall_spec_for_side(
                "07_servo",
                servo_fit,
                side,
                base_top_z,
                servo_bb.maxPoint.z,
                servo_shared,
                servo_output_side,
                servo_output_z1,
                None
            ))

    t = mm(LIMIT_WALL_T_MM)
    shared_z1 = max(motor_bb.maxPoint.z, servo_bb.maxPoint.z)
    motor_z1 = motor_bb.maxPoint.z
    servo_z1 = servo_bb.maxPoint.z

    if axis == "x":
        if motor_shared == "x_max":
            gap0 = motor_fit["x1"]
            gap1 = servo_fit["x0"]
        else:
            gap0 = servo_fit["x1"]
            gap1 = motor_fit["x0"]

        if gap1 <= gap0:
            mid = (gap0 + gap1) / 2.0
            gap0 = mid - t / 2.0
            gap1 = mid + t / 2.0

        overlap_y0 = max(motor_fit["y0"], servo_fit["y0"]) - t
        overlap_y1 = min(motor_fit["y1"], servo_fit["y1"]) + t

        # Trim the shared wall on output-shaft sides as well. The front wall is open/partial,
        # so a shared-wall tab extending beyond that side has no locating function and can hit the mechanism.
        if motor_output_side == "y_min":
            overlap_y0 = max(overlap_y0, motor_fit["y0"])
        if servo_output_side == "y_min":
            overlap_y0 = max(overlap_y0, servo_fit["y0"])
        if motor_output_side == "y_max":
            overlap_y1 = min(overlap_y1, motor_fit["y1"])
        if servo_output_side == "y_max":
            overlap_y1 = min(overlap_y1, servo_fit["y1"])

        if overlap_y1 <= overlap_y0:
            overlap_y0 = min(motor_fit["y0"], servo_fit["y0"])
            overlap_y1 = max(motor_fit["y1"], servo_fit["y1"])

        specs.append(make_wall_spec(
            "07_shared_motor_servo_smooth_limit_wall_core",
            gap0,
            gap1,
            overlap_y0,
            overlap_y1,
            base_top_z,
            shared_z1
        ))

        if motor_fit["y0"] < servo_fit["y0"] - 1e-9:
            y0 = motor_fit["y0"] if motor_output_side == "y_min" else motor_fit["y0"] - t
            y1 = servo_fit["y0"]
            if y1 > y0:
                specs.append(make_wall_spec(
                    "07_shared_motor_servo_extra_min_y",
                    gap0,
                    gap1,
                    y0,
                    y1,
                    base_top_z,
                    motor_z1
                ))
        elif servo_fit["y0"] < motor_fit["y0"] - 1e-9:
            y0 = servo_fit["y0"] if servo_output_side == "y_min" else servo_fit["y0"] - t
            y1 = motor_fit["y0"]
            if y1 > y0:
                specs.append(make_wall_spec(
                    "07_shared_motor_servo_extra_min_y",
                    gap0,
                    gap1,
                    y0,
                    y1,
                    base_top_z,
                    servo_z1
                ))

        if motor_fit["y1"] > servo_fit["y1"] + 1e-9:
            y0 = servo_fit["y1"]
            y1 = motor_fit["y1"] if motor_output_side == "y_max" else motor_fit["y1"] + t
            if y1 > y0:
                specs.append(make_wall_spec(
                    "07_shared_motor_servo_extra_max_y",
                    gap0,
                    gap1,
                    y0,
                    y1,
                    base_top_z,
                    motor_z1
                ))
        elif servo_fit["y1"] > motor_fit["y1"] + 1e-9:
            y0 = motor_fit["y1"]
            y1 = servo_fit["y1"] if servo_output_side == "y_max" else servo_fit["y1"] + t
            if y1 > y0:
                specs.append(make_wall_spec(
                    "07_shared_motor_servo_extra_max_y",
                    gap0,
                    gap1,
                    y0,
                    y1,
                    base_top_z,
                    servo_z1
                ))
    else:
        if motor_shared == "y_max":
            gap0 = motor_fit["y1"]
            gap1 = servo_fit["y0"]
        else:
            gap0 = servo_fit["y1"]
            gap1 = motor_fit["y0"]

        if gap1 <= gap0:
            mid = (gap0 + gap1) / 2.0
            gap0 = mid - t / 2.0
            gap1 = mid + t / 2.0

        overlap_x0 = max(motor_fit["x0"], servo_fit["x0"]) - t
        overlap_x1 = min(motor_fit["x1"], servo_fit["x1"]) + t

        # Same output-side trim for the case where the shared wall runs in X.
        if motor_output_side == "x_min":
            overlap_x0 = max(overlap_x0, motor_fit["x0"])
        if servo_output_side == "x_min":
            overlap_x0 = max(overlap_x0, servo_fit["x0"])
        if motor_output_side == "x_max":
            overlap_x1 = min(overlap_x1, motor_fit["x1"])
        if servo_output_side == "x_max":
            overlap_x1 = min(overlap_x1, servo_fit["x1"])

        if overlap_x1 <= overlap_x0:
            overlap_x0 = min(motor_fit["x0"], servo_fit["x0"])
            overlap_x1 = max(motor_fit["x1"], servo_fit["x1"])

        specs.append(make_wall_spec(
            "07_shared_motor_servo_smooth_limit_wall_core",
            overlap_x0,
            overlap_x1,
            gap0,
            gap1,
            base_top_z,
            shared_z1
        ))

        if motor_fit["x0"] < servo_fit["x0"] - 1e-9:
            x0 = motor_fit["x0"] if motor_output_side == "x_min" else motor_fit["x0"] - t
            x1 = servo_fit["x0"]
            if x1 > x0:
                specs.append(make_wall_spec(
                    "07_shared_motor_servo_extra_min_x",
                    x0,
                    x1,
                    gap0,
                    gap1,
                    base_top_z,
                    motor_z1
                ))
        elif servo_fit["x0"] < motor_fit["x0"] - 1e-9:
            x0 = servo_fit["x0"] if servo_output_side == "x_min" else servo_fit["x0"] - t
            x1 = motor_fit["x0"]
            if x1 > x0:
                specs.append(make_wall_spec(
                    "07_shared_motor_servo_extra_min_x",
                    x0,
                    x1,
                    gap0,
                    gap1,
                    base_top_z,
                    servo_z1
                ))

        if motor_fit["x1"] > servo_fit["x1"] + 1e-9:
            x0 = servo_fit["x1"]
            x1 = motor_fit["x1"] if motor_output_side == "x_max" else motor_fit["x1"] + t
            if x1 > x0:
                specs.append(make_wall_spec(
                    "07_shared_motor_servo_extra_max_x",
                    x0,
                    x1,
                    gap0,
                    gap1,
                    base_top_z,
                    motor_z1
                ))
        elif servo_fit["x1"] > motor_fit["x1"] + 1e-9:
            x0 = motor_fit["x1"]
            x1 = servo_fit["x1"] if servo_output_side == "x_max" else servo_fit["x1"] + t
            if x1 > x0:
                specs.append(make_wall_spec(
                    "07_shared_motor_servo_extra_max_x",
                    x0,
                    x1,
                    gap0,
                    gap1,
                    base_top_z,
                    servo_z1
                ))

    add_shared_output_corner_connectors(
        specs,
        "07_motor",
        motor_fit,
        motor_output_side,
        axis,
        gap0,
        gap1,
        base_top_z,
        motor_output_z1
    )

    add_shared_output_corner_connectors(
        specs,
        "07_servo",
        servo_fit,
        servo_output_side,
        axis,
        gap0,
        gap1,
        base_top_z,
        servo_output_z1
    )

    return merge_box_wall_specs(specs)


def merge_box_wall_specs(specs):
    # Merge only simple rectangular box walls. Special walls with holes stay separate.
    boxes = []
    specials = []

    for spec in specs:
        name = spec.get("name", "")

        # Shared motor/servo walls are deliberately segmented by height.
        # Do not merge them back into one tall wall.
        if name.startswith("07_shared_motor_servo") or "shared_output_corner" in name:
            specials.append(spec)
        elif spec.get("kind") == "box":
            boxes.append(spec)
        else:
            specials.append(spec)

    used = [False] * len(boxes)
    merged = []
    tol = mm(0.05)

    for i, a in enumerate(boxes):
        if used[i]:
            continue

        cur = dict(a)
        used[i] = True
        changed = True

        while changed:
            changed = False
            for j, b in enumerate(boxes):
                if used[j]:
                    continue

                same_x_band = abs(cur["x0"] - b["x0"]) < tol and abs(cur["x1"] - b["x1"]) < tol
                y_touch = not (cur["y1"] < b["y0"] - tol or b["y1"] < cur["y0"] - tol)

                same_y_band = abs(cur["y0"] - b["y0"]) < tol and abs(cur["y1"] - b["y1"]) < tol
                x_touch = not (cur["x1"] < b["x0"] - tol or b["x1"] < cur["x0"] - tol)

                if same_x_band and y_touch:
                    cur["y0"] = min(cur["y0"], b["y0"])
                    cur["y1"] = max(cur["y1"], b["y1"])
                    cur["z0"] = min(cur["z0"], b["z0"])
                    cur["z1"] = max(cur["z1"], b["z1"])
                    cur["rect"] = (cur["x0"], cur["x1"], cur["y0"], cur["y1"])
                    used[j] = True
                    changed = True

                elif same_y_band and x_touch:
                    cur["x0"] = min(cur["x0"], b["x0"])
                    cur["x1"] = max(cur["x1"], b["x1"])
                    cur["z0"] = min(cur["z0"], b["z0"])
                    cur["z1"] = max(cur["z1"], b["z1"])
                    cur["rect"] = (cur["x0"], cur["x1"], cur["y0"], cur["y1"])
                    used[j] = True
                    changed = True

        cur["name"] = cur["name"] + "_merged"
        merged.append(cur)

    return merged + specials


def make_limit_walls(comp, specs):
    bodies = []

    for spec in specs:
        body = None

        if spec.get("kind") == "x_wall_with_hole" and spec.get("hole"):
            x_center = (spec["x0"] + spec["x1"]) / 2.0
            x_thick = spec["x1"] - spec["x0"]
            body = make_box_yz_at_x_with_hole(
                comp,
                spec["name"],
                x_center,
                x_thick,
                spec["y0"],
                spec["y1"],
                spec["z0"],
                spec["z1"],
                spec["hole"]["cy"],
                spec["hole"]["cz"],
                spec["hole"]["r"]
            )
        else:
            body = make_box_min(
                comp,
                spec["name"],
                spec["x0"],
                spec["x1"],
                spec["y0"],
                spec["y1"],
                spec["z0"],
                spec["z1"]
            )

        if body:
            bodies.append(body)

    return bodies


def servo_step_spec(servo_main_bb, base_top_z):
    margin = mm(SERVO_STEP_MARGIN_MM)
    step_z0 = base_top_z
    step_z1 = servo_main_bb.minPoint.z

    if step_z1 <= step_z0:
        return None

    return {
        "x0": servo_main_bb.minPoint.x - margin,
        "x1": servo_main_bb.maxPoint.x + margin,
        "y0": servo_main_bb.minPoint.y - margin,
        "y1": servo_main_bb.maxPoint.y + margin,
        "z0": step_z0,
        "z1": step_z1,
        "rect": (
            servo_main_bb.minPoint.x - margin,
            servo_main_bb.maxPoint.x + margin,
            servo_main_bb.minPoint.y - margin,
            servo_main_bb.maxPoint.y + margin
        )
    }


def make_servo_step(comp, spec):
    if not spec:
        return None

    return make_box_min(
        comp,
        "07_servo_1p5mm_raise_step_only_under_body",
        spec["x0"],
        spec["x1"],
        spec["y0"],
        spec["y1"],
        spec["z0"],
        spec["z1"]
    )


def make_servo_ear_slot_cutters(comp, ear_bbs, base_z0, base_top_z, step_top_z):
    cutters = []
    clear = mm(SERVO_EAR_SLOT_CLEAR_MM)

    for i, bb in enumerate(ear_bbs):
        if bb.minPoint.z >= step_top_z + clear:
            continue

        if bb.maxPoint.z <= base_z0 - clear:
            continue

        cut_z0 = max(base_z0 - clear, bb.minPoint.z - clear)
        cut_z1 = step_top_z + clear

        if cut_z1 <= cut_z0:
            continue

        cutters.append(make_box_min(
            comp,
            "cut_07_Servo_Mounting_Ear_Slot_" + str(i + 1),
            bb.minPoint.x - clear,
            bb.maxPoint.x + clear,
            bb.minPoint.y - clear,
            bb.maxPoint.y + clear,
            cut_z0,
            cut_z1
        ))

    return cutters


def run(context):
    ui = None

    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = app.activeProduct

        if not isinstance(design, adsk.fusion.Design):
            ui.messageBox("Open a Fusion design first.")
            return

        root = design.rootComponent

        slider_occ = find_occ(root, SLIDER_OCC_PREFIX)
        drive_occ = find_occ(root, DRIVE_OCC_PREFIX)
        servo_occ = find_occ(root, SERVO_OCC_PREFIX)

        if not slider_occ:
            raise RuntimeError("04_X_Axis_Linear_Rail not found. Run 04 first.")

        if not drive_occ:
            raise RuntimeError("03_Drive_Head not found. Run 03 first.")

        if not servo_occ:
            raise RuntimeError("05_MG92B_Servo_Reference not found. Run 05 first.")

        clean_existing(root, BASE_PREFIX)

        occ, comp = new_comp(root, BASE_PREFIX)

        slider_bb = find_body_bbox(slider_occ, SLIDER_BODY_KEY)
        motor_bb = find_body_bbox(drive_occ, MOTOR_BODY_KEY)

        motor_shaft_bb = try_find_body_bbox(drive_occ, MOTOR_SHAFT_KEY)
        motor_pilot_bb = try_find_body_bbox(drive_occ, MOTOR_PILOT_KEY)
        if motor_shaft_bb:
            motor_axis_c = bbox_center(motor_shaft_bb)
        else:
            motor_axis_c = None

        servo_main_bb = union_bbox_for_keys(
            servo_occ,
            SERVO_MAIN_KEYS
        )

        servo_all_bb = union_bbox_for_keys(
            servo_occ,
            SERVO_MAIN_KEYS + SERVO_EAR_KEYS
        )

        servo_ear_bbs = find_body_bboxes_for_keys(
            servo_occ,
            SERVO_EAR_KEYS
        )

        servo_output_bb = bbox_union_from_list(
            find_body_bboxes_for_keys(
                servo_occ,
                SERVO_OUTPUT_KEYS
            )
        )

        left_support_bb = find_body_bbox(drive_occ, LEFT_SUPPORT_KEY)
        right_support_bb = find_body_bbox(drive_occ, RIGHT_SUPPORT_KEY)
        left_pivot_bb = find_body_bbox(drive_occ, LEFT_PIVOT_KEY)
        right_pivot_bb = find_body_bbox(drive_occ, RIGHT_PIVOT_KEY)
        left_arm_bb = try_find_body_bbox(drive_occ, LEFT_ARM_KEY)
        right_arm_bb = try_find_body_bbox(drive_occ, RIGHT_ARM_KEY)

        base_z0 = slider_bb.maxPoint.z
        base_z1 = motor_bb.minPoint.z

        if base_z1 <= base_z0 + mm(1.0):
            raise RuntimeError(
                "Motor bottom is too close to the slider top. "
                "Cannot make a usable uniform base thickness."
            )

        margin = mm(BASE_MARGIN_MM)
        rects = []

        # The rest of the footprint is driven by actual functional features. Do not
        # add the complete motor/servo body footprints plus margin, otherwise the base
        # grows beyond the outer limit walls and spring hooks.
        servo_step = servo_step_spec(servo_main_bb, base_z1)
        if servo_step:
            add_rect(rects, *servo_step["rect"])

        all_wall_specs = combined_limit_wall_specs(
            motor_bb,
            servo_main_bb,
            motor_shaft_bb,
            motor_pilot_bb,
            servo_output_bb,
            base_z1
        )

        for wall_spec in all_wall_specs:
            add_rect(rects, *wall_spec["rect"])

        left_support_spec = swing_support_spec(left_support_bb, base_z1, motor_axis_c)
        right_support_spec = swing_support_spec(right_support_bb, base_z1, motor_axis_c)

        add_rect(rects, *left_support_spec["rect"])
        add_rect(rects, *right_support_spec["rect"])

        left_plate_spec = spring_plate_spec(
            left_support_spec,
            left_support_bb,
            left_pivot_bb,
            left_arm_bb,
            slider_bb,
            base_z1,
            "07_left"
        )
        right_plate_spec = spring_plate_spec(
            right_support_spec,
            right_support_bb,
            right_pivot_bb,
            right_arm_bb,
            slider_bb,
            base_z1,
            "07_right"
        )
        add_rect(rects, *left_plate_spec["rect"])
        add_rect(rects, *right_plate_spec["rect"])

        req_x0, req_x1, req_y0, req_y1 = rect_union(rects, 0)
        base_x0, base_x1, base_y0, base_y1 = rect_union(rects, 0)

        limiter_bb = union_occ_bbox(root, LIMITER_OCC_PREFIX)
        if not limiter_bb:
            limiter_bb = union_occ_bbox(root, LOCK_OCC_PREFIX)

        if limiter_bb:
            base_x0, base_x1, base_y0, base_y1 = trim_against_limiter(
                (base_x0, base_x1, base_y0, base_y1),
                (req_x0, req_x1, req_y0, req_y1),
                limiter_bb,
                mm(LOCK_LIMIT_CLEAR_MM)
            )

        base_x0, base_x1, base_y0, base_y1 = force_base_to_servo_outer_edge(
            (base_x0, base_x1, base_y0, base_y1),
            motor_bb,
            servo_main_bb
        )

        base = make_box_min(
            comp,
            "07_uniform_thickness_rectangular_base",
            base_x0,
            base_x1,
            base_y0,
            base_y1,
            base_z0,
            base_z1
        )

        tools = []
        hole_cutters = []

        servo_step_body = make_servo_step(comp, servo_step)
        if servo_step_body:
            tools.append(servo_step_body)

        tools.extend(make_limit_walls(comp, all_wall_specs))

        tools.extend(make_swing_support(
            comp,
            "07_left_swing_arm_motor_end_support",
            left_support_spec,
            hole_cutters
        ))

        tools.extend(make_swing_support(
            comp,
            "07_right_swing_arm_motor_end_support",
            right_support_spec,
            hole_cutters
        ))

        tools.append(make_spring_plate(
            comp,
            left_plate_spec
        ))
        tools.append(make_spring_plate(
            comp,
            right_plate_spec
        ))

        base = combine_join(comp, base, tools)
        base.name = "07_PRINT_Drive_Head_Mounting_Base"

        if servo_step:
            hole_cutters.extend(make_servo_ear_slot_cutters(
                comp,
                servo_ear_bbs,
                base_z0,
                base_z1,
                servo_step["z1"]
            ))

        combine_cut(comp, base, hole_cutters)
        add_slider_mount_holes(comp, base, slider_bb, base_z0, base_z1)

        try:
            design.snapshots.add()
        except Exception:
            pass

        app.activeViewport.fit()

        ui.messageBox(
            "07 drive-head mounting base and limiters generated.\n\n"
            "Base bottom: slider platform top.\n"
            "Base top: 03 drive-head motor body bottom.\n"
            "Servo step: only under servo main body.\n"
            "Servo mounting-ear slots are cut from the base/step.\n"
            "Two low spring plates are made at final coordinates and cut before joining.\n"
            "Output-shaft side adjacent walls are trimmed so useless front-side protrusions are removed. The shared motor/servo wall remains segmented and excluded from merging.\n"
            "No material or appearance is assigned.\n\n"
            "Base thickness: {:.2f} mm\n"
            "Servo step height: {:.2f} mm\n"
            "Base size X/Y: {:.2f} x {:.2f} mm\n"
            "Left spring plate centre X/Y/Z: {:.2f}, {:.2f}, {:.2f} mm\n"
            "Right spring plate centre X/Y/Z: {:.2f}, {:.2f}, {:.2f} mm".format(
                to_mm(base_z1 - base_z0),
                to_mm(servo_step["z1"] - servo_step["z0"]) if servo_step else 0.0,
                to_mm(base_x1 - base_x0),
                to_mm(base_y1 - base_y0),
                to_mm((left_plate_spec["x0"] + left_plate_spec["x1"]) / 2.0),
                to_mm((left_plate_spec["y0"] + left_plate_spec["y1"]) / 2.0),
                to_mm(left_plate_spec["hole_z"]),
                to_mm((right_plate_spec["x0"] + right_plate_spec["x1"]) / 2.0),
                to_mm((right_plate_spec["y0"] + right_plate_spec["y1"]) / 2.0),
                to_mm(right_plate_spec["hole_z"])
            )
        )

    except Exception:
        if ui:
            ui.messageBox("Failed:\n{}".format(traceback.format_exc()))
