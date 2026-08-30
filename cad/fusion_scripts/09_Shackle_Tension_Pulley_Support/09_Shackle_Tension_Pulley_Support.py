import adsk.core
import adsk.fusion
import traceback
import math


COMP_PREFIX = '09_Shackle_Tension_Pulley_Support'
LOCK_PREFIX = '02_Padlock_Reference'
BASE_PREFIXES = ['13_Main_Base_Plate']

PULLEY_OD_MM = 10.0
PULLEY_BORE_MM = 3.0
PULLEY_WIDTH_MM = 4.0
PULLEY_SIDE_CLEAR_MM = 0.7
PULLEY_X_FROM_SHACKLE_TOP_MM = 25.0
PULLEY_SIDE_SIGN = 1.0

V_GROOVE_ANGLE_DEG = 90.0
V_GROOVE_MOUTH_WIDTH_MM = 3.0
V_GROOVE_ROOT_WIDTH_MM = 1.63
V_GROOVE_TOP_DROP_MM = 0.5

SHAFT_D_MM = 3.0
SHAFT_CLEAR_D_MM = 3.25
SHAFT_EXTRA_OUTSIDE_MM = 2.0

SUPPORT_TOP_D_MM = 10.0
SUPPORT_CHEEK_T_MM = 2.5
LOWER_BRIDGE_CLEAR_MM = 1.0
SUPPORT_TILT_DEG = 45.0
UPPER_PLATFORM_ANGLE_DEG = 45.0
UPPER_PLATFORM_LEN_MM = SUPPORT_TOP_D_MM
SPRING_ANCHOR_PLATE_T_MM = 4.0
SPRING_ANCHOR_PLATE_W_MM = 2.0
SPRING_ANCHOR_HOLE_D_MM = 2.5
SPRING_ANCHOR_HOLE_COUNT = 3
SPRING_ANCHOR_HOLE_SPACING_MM = 4.5
SPRING_ANCHOR_HOLE_EDGE_MARGIN_MM = 2.5


def mm(v):
    return v / 10.0


def to_mm(v):
    return v * 10.0


def v_groove_outer_radius():
    return PULLEY_OD_MM / 2.0


def v_groove_mouth_radius():
    return v_groove_outer_radius() - V_GROOVE_TOP_DROP_MM


def v_groove_root_radius():
    half_delta_w = (V_GROOVE_MOUTH_WIDTH_MM - V_GROOVE_ROOT_WIDTH_MM) / 2.0
    angle_half = math.radians(V_GROOVE_ANGLE_DEG / 2.0)

    if angle_half <= 1e-6:
        raise RuntimeError('V groove angle is not valid.')

    radial_drop = half_delta_w / math.tan(angle_half)
    r = v_groove_mouth_radius() - radial_drop
    min_r = PULLEY_BORE_MM / 2.0 + 0.8

    if r < min_r:
        r = min_r

    return r


def v_groove_root_diameter():
    return v_groove_root_radius() * 2.0


def clean_existing(root, prefixes):
    if isinstance(prefixes, str):
        prefixes = [prefixes]

    targets = []

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


def find_occ(root, prefixes):
    if isinstance(prefixes, str):
        prefixes = [prefixes]

    occs = root.allOccurrences

    for i in range(occs.count):
        occ = occs.item(i)
        if not occ.component:
            continue

        for p in prefixes:
            if occ.component.name.startswith(p) or occ.name.startswith(p):
                return occ

    return None


def new_comp(root, name):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = name
    return occ, comp


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


def find_body_bbox_by_keywords(occ, keywords):
    keys = [k.lower() for k in keywords]

    for i in range(occ.component.bRepBodies.count):
        body = occ.component.bRepBodies.item(i)
        name = body.name.lower()

        for key in keys:
            if key in name:
                return body_world_bbox(occ, body)

    return None


def get_base_top_z(root):
    base_occ = find_occ(root, BASE_PREFIXES)

    if not base_occ:
        return 0.0

    return base_occ.boundingBox.maxPoint.z


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


def ring_profile(sk):
    for i in range(sk.profiles.count):
        prof = sk.profiles.item(i)

        try:
            if prof.profileLoops.count > 1:
                return prof
        except Exception:
            pass

    return largest_profile(sk)


def make_box_min(comp, name, x0, x1, y0, y1, z0, z1):
    if x1 <= x0 or y1 <= y0 or z1 <= z0:
        return None

    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + '_sk'

    sk.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(x0, y0, 0),
        adsk.core.Point3D.create(x1, y1, 0)
    )

    prof = sk.profiles.item(sk.profiles.count - 1)

    ei = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ei.setDistanceExtent(False, adsk.core.ValueInput.createByReal(z1 - z0))

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, 0, z0)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def slanted_profile_points(cx, axis_z, base_z, outer_d, side):
    r = outer_d / 2.0
    angle = math.radians(SUPPORT_TILT_DEG)

    ux = side * math.cos(angle)
    uz = math.sin(angle)

    if uz <= 1e-6:
        raise RuntimeError('Support tilt angle is not valid.')

    nx = -uz
    nz = ux

    cap_a = (cx + nx * r, axis_z + nz * r)
    cap_b = (cx - nx * r, axis_z - nz * r)
    cap_top = (cx + ux * r, axis_z + uz * r)

    def to_base(p):
        t = (p[1] - base_z) / uz
        return (p[0] - ux * t, base_z)

    base_a = to_base(cap_a)
    base_b = to_base(cap_b)

    return {
        'cap_a': cap_a,
        'cap_b': cap_b,
        'cap_top': cap_top,
        'base_a': base_a,
        'base_b': base_b,
        'u': (ux, uz),
        'r': r
    }


def make_slanted_round_top_plate_y(comp, name, cx, cy, base_z, axis_z, outer_d, thick_y, side):
    if axis_z <= base_z:
        raise RuntimeError('Slanted round-top support is too low.')

    pts = slanted_profile_points(cx, axis_z, base_z, outer_d, side)

    sk = comp.sketches.add(comp.xZConstructionPlane)
    sk.name = name + '_sk'

    def sp(p):
        return sk.modelToSketchSpace(adsk.core.Point3D.create(p[0], 0, p[1]))

    lines = sk.sketchCurves.sketchLines
    arcs = sk.sketchCurves.sketchArcs

    p_base_a = sp(pts['base_a'])
    p_cap_a = sp(pts['cap_a'])
    p_top = sp(pts['cap_top'])
    p_cap_b = sp(pts['cap_b'])
    p_base_b = sp(pts['base_b'])

    lines.addByTwoPoints(p_base_a, p_cap_a)
    arcs.addByThreePoints(p_cap_a, p_top, p_cap_b)
    lines.addByTwoPoints(p_cap_b, p_base_b)
    lines.addByTwoPoints(p_base_b, p_base_a)

    prof = largest_profile(sk)
    if not prof:
        raise RuntimeError('No profile found for ' + name)

    ei = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ei.setSymmetricExtent(adsk.core.ValueInput.createByReal(thick_y), True)

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, cy, 0)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def make_slanted_lower_web_y(comp, name, cx, cy, base_z, axis_z, outer_d, thick_y, top_z, side):
    pts = slanted_profile_points(cx, axis_z, base_z, outer_d, side)
    ux, uz = pts['u']

    if top_z <= base_z + mm(0.8):
        return None

    if top_z >= axis_z:
        top_z = axis_z - mm(0.5)

    def point_at_z(cap_point, z):
        t = (cap_point[1] - z) / uz
        return (cap_point[0] - ux * t, z)

    raw_top_a = point_at_z(pts['cap_a'], top_z)
    raw_top_b = point_at_z(pts['cap_b'], top_z)

    top_mid_x = (raw_top_a[0] + raw_top_b[0]) / 2.0
    top_mid_z = (raw_top_a[1] + raw_top_b[1]) / 2.0

    top_len = mm(UPPER_PLATFORM_LEN_MM)
    top_half_len = top_len / 2.0

    support_angle = math.radians(UPPER_PLATFORM_ANGLE_DEG)
    support_dir_x = side * math.cos(support_angle)
    support_dir_z = math.sin(support_angle)

    # Platform normal follows the support direction, so the platform edge
    # itself must lie perpendicular to the support direction in the XZ profile.
    top_dir_x = -support_dir_z
    top_dir_z = support_dir_x

    top_p1 = (
        top_mid_x - top_dir_x * top_half_len,
        top_mid_z - top_dir_z * top_half_len
    )
    top_p2 = (
        top_mid_x + top_dir_x * top_half_len,
        top_mid_z + top_dir_z * top_half_len
    )

    if top_p1[0] <= top_p2[0]:
        left_top = top_p1
        right_top = top_p2
    else:
        left_top = top_p2
        right_top = top_p1

    if pts['base_a'][0] <= pts['base_b'][0]:
        left_base = pts['base_a']
        right_base = pts['base_b']
    else:
        left_base = pts['base_b']
        right_base = pts['base_a']

    sk = comp.sketches.add(comp.xZConstructionPlane)
    sk.name = name + '_sk'

    def sp(p):
        return sk.modelToSketchSpace(adsk.core.Point3D.create(p[0], 0, p[1]))

    lines = sk.sketchCurves.sketchLines

    p_base_a = sp(left_base)
    p_top_a = sp(left_top)
    p_top_b = sp(right_top)
    p_base_b = sp(right_base)

    lines.addByTwoPoints(p_base_a, p_top_a)
    lines.addByTwoPoints(p_top_a, p_top_b)
    lines.addByTwoPoints(p_top_b, p_base_b)
    lines.addByTwoPoints(p_base_b, p_base_a)

    prof = largest_profile(sk)
    if not prof:
        raise RuntimeError('No profile found for ' + name)

    ei = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ei.setSymmetricExtent(adsk.core.ValueInput.createByReal(thick_y), True)

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, cy, 0)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def make_cyl_y(comp, name, cx, cy, cz, r, length):
    sk = comp.sketches.add(comp.xZConstructionPlane)
    sk.name = name + '_sk'

    centre = sk.modelToSketchSpace(adsk.core.Point3D.create(cx, 0, cz))
    sk.sketchCurves.sketchCircles.addByCenterRadius(centre, r)

    prof = sk.profiles.item(sk.profiles.count - 1)

    ei = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ei.setSymmetricExtent(adsk.core.ValueInput.createByReal(length), True)

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, cy, 0)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def make_cyl_z(comp, name, cx, cy, z0, r, height):
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + '_sk'

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(cx, cy, 0),
        r
    )

    prof = largest_profile(sk)
    if not prof:
        raise RuntimeError('No profile found for ' + name)

    ei = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ei.setDistanceExtent(False, adsk.core.ValueInput.createByReal(height))

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, 0, z0)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def add_spring_anchor_plate(comp, data):
    px = data['pulley_x']
    py = data['pulley_y']
    base_top = data['base_top_z']
    side = data['side']

    plate_t = mm(SPRING_ANCHOR_PLATE_T_MM)
    plate_w = mm(SPRING_ANCHOR_PLATE_W_MM)
    hole_d = mm(SPRING_ANCHOR_HOLE_D_MM)
    hole_spacing = mm(SPRING_ANCHOR_HOLE_SPACING_MM)
    edge_margin = mm(SPRING_ANCHOR_HOLE_EDGE_MARGIN_MM)

    hole_positions = []
    for i in range(SPRING_ANCHOR_HOLE_COUNT):
        hole_positions.append(px + side * hole_spacing * i)

    min_hx = min(hole_positions)
    max_hx = max(hole_positions)

    plate_x0 = min_hx - edge_margin
    plate_x1 = max_hx + edge_margin
    plate_y0 = py - plate_w / 2.0
    plate_y1 = py + plate_w / 2.0
    plate_z0 = base_top
    plate_z1 = base_top + plate_t

    plate = make_box_min(
        comp,
        '09_spring_anchor_plate_flat_on_base',
        plate_x0,
        plate_x1,
        plate_y0,
        plate_y1,
        plate_z0,
        plate_z1
    )

    if not plate:
        return None

    hole_z = plate_z0 + plate_t / 2.0

    cut_tools = []
    for i, hx in enumerate(hole_positions):
        cut_tools.append(
            make_cyl_y(
                comp,
                'cut_09_Side_Facing_Spring_Anchor_Hole_' + str(i + 1),
                hx,
                py,
                hole_z,
                hole_d / 2.0,
                plate_w + mm(1.0)
            )
        )

    combine_cut(comp, plate, cut_tools)

    data['spring_hole_positions_x'] = hole_positions
    data['spring_plate_x0'] = plate_x0
    data['spring_plate_x1'] = plate_x1
    return plate


def offset_y_plane(comp, y_off):
    planes = comp.constructionPlanes
    pi = planes.createInput()
    pi.setByOffset(
        comp.xZConstructionPlane,
        adsk.core.ValueInput.createByReal(y_off)
    )
    return planes.add(pi)


def circle_profile_on_y_plane(comp, plane, cx, cz, r, name):
    sk = comp.sketches.add(plane)
    sk.name = name + '_sk'

    centre = sk.modelToSketchSpace(adsk.core.Point3D.create(cx, 0, cz))
    sk.sketchCurves.sketchCircles.addByCenterRadius(centre, r)

    prof = largest_profile(sk)
    if not prof:
        raise RuntimeError('No circle profile found for ' + name)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return prof


def make_v_bearing_y(comp, name, cx, cy, cz, outer_d, bore_d, width):
    outer_r = outer_d / 2.0
    bore_r = bore_d / 2.0

    face_half_w = width / 2.0
    mouth_half_w = mm(V_GROOVE_MOUTH_WIDTH_MM / 2.0)
    root_half_w = mm(V_GROOVE_ROOT_WIDTH_MM / 2.0)

    mouth_r = mm(v_groove_mouth_radius())
    root_r = mm(v_groove_root_radius())

    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + '_revolve_sk'

    axis = sk.sketchCurves.sketchLines.addByTwoPoints(
        adsk.core.Point3D.create(cx, cy - face_half_w - mm(0.5), 0),
        adsk.core.Point3D.create(cx, cy + face_half_w + mm(0.5), 0)
    )
    axis.isConstruction = True

    pts = [
        adsk.core.Point3D.create(cx, cy - face_half_w, 0),
        adsk.core.Point3D.create(cx + outer_r, cy - face_half_w, 0),
        adsk.core.Point3D.create(cx + mouth_r, cy - mouth_half_w, 0),
        adsk.core.Point3D.create(cx + root_r, cy - root_half_w, 0),
        adsk.core.Point3D.create(cx + root_r, cy + root_half_w, 0),
        adsk.core.Point3D.create(cx + mouth_r, cy + mouth_half_w, 0),
        adsk.core.Point3D.create(cx + outer_r, cy + face_half_w, 0),
        adsk.core.Point3D.create(cx, cy + face_half_w, 0)
    ]

    lines = sk.sketchCurves.sketchLines
    for i in range(len(pts)):
        lines.addByTwoPoints(pts[i], pts[(i + 1) % len(pts)])

    prof = largest_profile(sk)
    if not prof:
        raise RuntimeError('No revolve profile found for ' + name)

    ri = comp.features.revolveFeatures.createInput(
        prof,
        axis,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ri.setAngleExtent(
        False,
        adsk.core.ValueInput.createByString('360 deg')
    )

    rev = comp.features.revolveFeatures.add(ri)
    body = rev.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, 0, cz)

    bore = make_cyl_y(
        comp,
        'cut_' + name + '_3mm_bore',
        cx,
        cy,
        cz,
        bore_r,
        width + mm(1.0)
    )
    combine_cut(comp, body, [bore])
    body.name = name

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def make_ring_y(comp, name, cx, cy, cz, outer_r, inner_r, width):
    sk = comp.sketches.add(comp.xZConstructionPlane)
    sk.name = name + '_sk'

    centre = sk.modelToSketchSpace(adsk.core.Point3D.create(cx, 0, cz))

    sk.sketchCurves.sketchCircles.addByCenterRadius(centre, outer_r)
    sk.sketchCurves.sketchCircles.addByCenterRadius(centre, inner_r)

    prof = ring_profile(sk)

    ei = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ei.setSymmetricExtent(adsk.core.ValueInput.createByReal(width), True)

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, cy, 0)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def combine_join(comp, target, tools):
    objs = adsk.core.ObjectCollection.create()

    for body in tools:
        if body:
            objs.add(body)

    if objs.count == 0:
        return target

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)
    return target


def combine_cut(comp, target, tools):
    objs = adsk.core.ObjectCollection.create()

    for body in tools:
        if body:
            objs.add(body)

    if objs.count == 0:
        return target

    ci = comp.features.combineFeatures.createInput(target, objs)
    ci.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)
    return target


def add_support(comp, data):
    px = data['pulley_x']
    py = data['pulley_y']
    pz = data['pulley_z']
    base_top = data['base_top_z']

    cheek_t = mm(SUPPORT_CHEEK_T_MM)
    side_clear = mm(PULLEY_SIDE_CLEAR_MM)
    pulley_w = mm(PULLEY_WIDTH_MM)
    support_d = mm(SUPPORT_TOP_D_MM)
    pulley_r = mm(PULLEY_OD_MM / 2.0)

    inner_gap = pulley_w + 2.0 * side_clear
    total_y = inner_gap + 2.0 * cheek_t

    left_cy = py - inner_gap / 2.0 - cheek_t / 2.0
    right_cy = py + inner_gap / 2.0 + cheek_t / 2.0

    side = data['side']

    left = make_slanted_round_top_plate_y(
        comp,
        '09_left_slanted_round_top_support_cheek',
        px,
        left_cy,
        base_top,
        pz,
        support_d,
        cheek_t,
        side
    )

    right = make_slanted_round_top_plate_y(
        comp,
        '09_right_slanted_round_top_support_cheek',
        px,
        right_cy,
        base_top,
        pz,
        support_d,
        cheek_t,
        side
    )

    bridge_z1 = pz - pulley_r - mm(LOWER_BRIDGE_CLEAR_MM)

    bridge = make_slanted_lower_web_y(
        comp,
        '09_slanted_lower_web_between_cheeks_no_base_plate',
        px,
        py,
        base_top,
        pz,
        support_d,
        inner_gap,
        bridge_z1,
        side
    )

    bracket = combine_join(comp, left, [right, bridge])
    bracket.name = '09_PRINT_Shackle_Tension_Pulley_Support'

    shaft_cut = make_cyl_y(
        comp,
        'cut_09_Shaft_Hole_3p25mm_Through_Round_Top',
        px,
        py,
        pz,
        mm(SHAFT_CLEAR_D_MM / 2.0),
        total_y + mm(2.0)
    )

    combine_cut(comp, bracket, [shaft_cut])

    data['total_y'] = total_y
    return bracket


def add_reference_parts(comp, data):
    px = data['pulley_x']
    py = data['pulley_y']
    pz = data['pulley_z']
    total_y = data['total_y']

    shaft_len = total_y + mm(2.0 * SHAFT_EXTRA_OUTSIDE_MM)

    make_cyl_y(
        comp,
        '09_3mm_shaft_ref',
        px,
        py,
        pz,
        mm(SHAFT_D_MM / 2.0),
        shaft_len
    )

    make_v_bearing_y(
        comp,
        '09_v_groove_bearing_ref_OD10_ID3_W4_90deg',
        px,
        py,
        pz,
        mm(PULLEY_OD_MM),
        mm(PULLEY_BORE_MM),
        mm(PULLEY_WIDTH_MM)
    )


def get_layout_data(root):
    lock_occ = find_occ(root, LOCK_PREFIX)

    if not lock_occ:
        raise RuntimeError('02_Padlock_Reference not found. Run 02 padlock script first.')

    shackle_bb = find_body_bbox_by_keywords(
        lock_occ,
        [
            '02_shackle_round_u',
            'shackle_round',
            'shackle'
        ]
    )

    if not shackle_bb:
        raise RuntimeError('Cannot find shackle body in 02_Padlock_Reference.')

    shackle_c = bbox_center(shackle_bb)
    base_top = get_base_top_z(root)

    side = 1.0 if PULLEY_SIDE_SIGN >= 0 else -1.0

    pulley_r = mm(PULLEY_OD_MM / 2.0)
    line_r = mm(v_groove_root_radius())
    line_z = shackle_bb.maxPoint.z
    pulley_z = line_z - line_r

    if pulley_z <= base_top + mm(2.0):
        raise RuntimeError(
            'Pulley axis is too low. Shackle top line height is {:.2f} mm.'.format(
                to_mm(line_z)
            )
        )

    if side > 0:
        shackle_top_x = shackle_bb.maxPoint.x
        pulley_x = shackle_top_x + mm(PULLEY_X_FROM_SHACKLE_TOP_MM)
    else:
        shackle_top_x = shackle_bb.minPoint.x
        pulley_x = shackle_top_x - mm(PULLEY_X_FROM_SHACKLE_TOP_MM)

    return {
        'base_top_z': base_top,
        'shackle_top_x': shackle_top_x,
        'shackle_y': shackle_c.y,
        'line_z': line_z,
        'pulley_x': pulley_x,
        'pulley_y': shackle_c.y,
        'pulley_z': pulley_z,
        'pulley_r': pulley_r,
        'line_r': line_r,
        'side': side
    }


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

        clean_existing(root, COMP_PREFIX)

        occ, comp = new_comp(root, COMP_PREFIX)

        data = get_layout_data(root)
        add_support(comp, data)
        add_reference_parts(comp, data)
        add_spring_anchor_plate(comp, data)

        try:
            design.snapshots.add()
        except Exception:
            pass

        app.activeViewport.fit()

        ui.messageBox(
            '09 shackle tension pulley support created.\n\n'
            'No separate base plate. Bottom of support sits on the existing base top.\n'
            'No fishing line reference. A separate flat spring anchor plate is added on the base with side-facing holes.\n'
            'Support side profile is a tilted rectangle with a semicircular top.\n'
            'Support width equals top circle diameter.\n'
            'The centre web remains full width and joined to both support cheeks.\n'
            'Upper platform length is fixed to SUPPORT_TOP_D_MM.\n'
            'The support axis remains 45 deg.\n\n'
            'V-groove bearing: OD 10 / bore 3 / width 4 mm.\n'
            'Supplier-based groove data: 90 deg, mouth width 3.00 mm, root width 1.63 mm, top drop 0.50 mm.\n'
            'Pulley X offset from shackle top: 25.00 mm.\n'
            'Groove root line Z: {:.2f} mm.\n'
            'Bearing outer top Z: {:.2f} mm.\n'
            'Shackle top Z: {:.2f} mm.\n'
            'Pulley centre XYZ: {:.2f}, {:.2f}, {:.2f} mm.\n'
            'Support top diameter: {:.2f} mm.\n'
            'Tilt angle: {:.2f} deg.\n'
            'Upper platform angle: {:.2f} deg.\n'
            'Upper platform length: {:.2f} mm.\n'
            'Centre web width: full inner gap between fork cheeks.\n'
            'Spring anchor plate: flat on base, below the outer side of the bearing.\n'
            'Three side-facing holes are at the same height from the base and arranged progressively away from the support base.\n'
            'Hole 1 is directly below the bearing centre; all holes cut through the plate side-to-side.\n'
            'Spring anchor hole diameter: {:.2f} mm. Hole spacing: {:.2f} mm.\n'
            'Groove root diameter: {:.2f} mm.'.format(
                to_mm(data['pulley_z'] + data['line_r']),
                to_mm(data['pulley_z'] + data['pulley_r']),
                to_mm(data['line_z']),
                to_mm(data['pulley_x']),
                to_mm(data['pulley_y']),
                to_mm(data['pulley_z']),
                SUPPORT_TOP_D_MM,
                SUPPORT_TILT_DEG,
                UPPER_PLATFORM_ANGLE_DEG,
                UPPER_PLATFORM_LEN_MM,
                SPRING_ANCHOR_HOLE_D_MM,
                SPRING_ANCHOR_HOLE_SPACING_MM,
                v_groove_root_diameter()
            )
        )

    except Exception:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
