import adsk.core
import adsk.fusion
import traceback
import math


OUT_PREFIX = '14_Integrated_Base'
OUT_COMP_NAME = '14_Integrated_Base'

BASE_COMP_PREFIX = '13_Main_Base_Plate'

INCLUDE_FOR_BASE_FOOTPRINT = [
    '01_Passive_Shaft_Support',
    '02_Padlock_Reference',
    '03_Drive_Head',
    '04_X_Axis_Linear_Rail',
    '05_MG92B_Servo_Reference',
    '06_Servo_Lift_Arm',
    '07_Drive_Head_Mounting_Base_and_Limiters',
    '08_Lock_Locator_and_Limiters',
    '09_Shackle_Tension_Pulley_Support',
]

RAIL_PREFIXES = [
    '04_X_Axis_Linear_Rail',
]

RAIL_BASE_BODY_KEYS = [
    '04_03_rail_base',
    'base_185'
]

BASE_MARGIN_MM = 12.0
BASE_THICKNESS_MM = 6.0

OUTER_MOUNT_HOLE_D_MM = 4.2
OUTER_MOUNT_HOLE_EDGE_OFFSET_MM = 12.0

RAIL_MOUNT_THROUGH_D_MM = 3.77
RAIL_MOUNT_X_FROM_LIMIT_EDGE_MM = 35.15
RAIL_MOUNT_Y_FROM_SIDE_MM = 6.15

M3_NUT_AF_MM = 5.5
M3_NUT_POCKET_DEPTH_MM = 2.5
M3_NUT_POCKET_CLEAR_MM = 0.15

PASSIVE_SUPPORT_SHAFT_CLEAR_D_MM = 3.30
PASSIVE_SUPPORT_TOP_TO_SHAFT_MM = 3.2

CORNER_FILLET_MM = 1.2

HIDE_SOURCE_COMPONENTS = True
SILENT_SUCCESS_MESSAGES = True


SOURCE_FILES = [
    '01_Passive_Shaft_Support.py',
    '02_Padlock_Reference.py',
    '03_Drive_Head.py',
    '04_X_Axis_Linear_Rail.py',
    '05_MG92B_Servo_Reference.py',
    '06_Servo_Lift_Arm.py',
    '07_Drive_Head_Mounting_Base_and_Limiters.py',
    '08_Lock_Locator_and_Limiters.py',
    '09_Shackle_Tension_Pulley_Support.py',
]


def mm(v):
    return v / 10.0


def to_mm(v):
    return v * 10.0


def add_user_parameter_if_missing(design, name, value_mm):
    p = design.userParameters.itemByName(name)
    if p:
        return

    design.userParameters.add(
        name,
        adsk.core.ValueInput.createByString(str(value_mm) + ' mm'),
        'mm',
        ''
    )


def ensure_default_user_parameters(design):
    defaults = {
        'lock_width': 47.14,
        'lock_height': 49.85,
        'lock_thickness': 14.32,
        'lock_top_z': 24.925,

        'lock_edge_fillet': 1.2,
        'fillet_small': 0.8,

        'shell_top_z': 23.6,
        'shell_top_height': 2.0,
        'shell_depth': 14.5,
        'shell_right_x': 22.6,
        'shell_right_width': 2.6,
        'shell_left_x': -22.6,
        'shell_left_width': 2.6,
        'shell_radius': 1.0,

        'dial_window_x': 0.0,
        'dial_1_z': -12.72,
        'dial_2_z': -4.24,
        'dial_3_z': 4.24,
        'dial_4_z': 12.72,
        'dial_pitch': 8.48,
        'dial_body_radius': 9.4,

        'dial_window_width': 14.14,
        'dial_window_height': 4.5,
        'dial_window_depth': 2.3,
        'dial_visible_width': 11.69,
        'dial_visible_height': 3.98,
        'dial_window_corner': 0.6,

        'front_window_y': -7.2,
        'back_window_y': 7.2,
        'front_dial_face_y': -8.4,
        'back_dial_face_y': 8.4,
        'dial_front_projection': 0.8,
        'dial_back_projection': 0.8,

        'shackle_left_x': -8.0,
        'shackle_right_x': 8.0,
        'shackle_center_y': 0.0,
        'shackle_rod_radius': 1.8,
        'shackle_visible_height': 14.0,

        'mic_max_diameter': 36.22,
        'mic_end_diameter': 27.51,
        'mic_thickness': 15.13,
        'mic_center_z_from_bottom': 32.34,
        'mic_center_x_from_right': 6.0
    }

    for name, value_mm in defaults.items():
        add_user_parameter_if_missing(design, name, value_mm)


def silent_message_box(*args, **kwargs):
    return 0


def _load_source_module(filename):
    import importlib.util
    import os

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_deps', filename)
    module_name = '_padlock_fusion_' + ''.join(c if c.isalnum() else '_' for c in filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError('Unable to load Fusion source module: ' + filename)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.silent_message_box = silent_message_box
    return module

def run_source(filename, context):
    module = _load_source_module(filename)
    if not hasattr(module, 'run'):
        raise RuntimeError('Source module has no run(context): ' + filename)
    module.run(context)


def run_sources(context):
    ran = []
    for filename in SOURCE_FILES:
        run_source(filename, context)
        ran.append(filename)
    return ran



def occ_name(occ):
    if occ.component:
        return occ.component.name
    return occ.name


def starts_with_any(name, prefixes):
    for p in prefixes:
        if name.startswith(p):
            return True
    return False


def clean_existing(root, prefixes):
    if isinstance(prefixes, str):
        prefixes = [prefixes]

    targets = []

    for i in range(root.occurrences.count):
        occ = root.occurrences.item(i)
        name = occ_name(occ)

        for p in prefixes:
            if name.startswith(p):
                targets.append(occ)
                break

    for occ in targets:
        try:
            occ.deleteMe()
        except Exception:
            pass


def find_occurrences(root, prefixes):
    if isinstance(prefixes, str):
        prefixes = [prefixes]

    found = []
    occs = root.allOccurrences

    for i in range(occs.count):
        occ = occs.item(i)
        name = occ_name(occ)

        for p in prefixes:
            if name.startswith(p):
                found.append(occ)
                break

    return found


def find_occ(root, prefixes):
    found = find_occurrences(root, prefixes)
    if found:
        return found[0]
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

    for b in bodies:
        if b:
            objs.add(b)

    if objs.count == 0:
        return

    mat = adsk.core.Matrix3D.create()
    mat.translation = adsk.core.Vector3D.create(dx, dy, dz)

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def lift_component_bodies_to_z0(comp):
    bodies = []
    min_z = None

    for i in range(comp.bRepBodies.count):
        body = comp.bRepBodies.item(i)
        bodies.append(body)
        bb = body.boundingBox

        if min_z is None or bb.minPoint.z < min_z:
            min_z = bb.minPoint.z

    if not bodies or min_z is None:
        return

    if abs(min_z) < 1e-9:
        return

    move_bodies(comp, bodies, 0, 0, -min_z)


def body_world_bbox(occ, body):
    try:
        proxy = body.createForAssemblyContext(occ)
        return proxy.boundingBox
    except Exception:
        return body.boundingBox


def find_body_bbox_by_keywords(occ, keywords):
    keys = [k.lower() for k in keywords]

    for i in range(occ.component.bRepBodies.count):
        body = occ.component.bRepBodies.item(i)
        name = body.name.lower()

        for key in keys:
            if key in name:
                return body_world_bbox(occ, body)

    return None


def find_old_base_top(root):
    top_z = None

    for i in range(root.occurrences.count):
        occ = root.occurrences.item(i)
        name = occ_name(occ)

        if name.startswith(BASE_COMP_PREFIX):
            bb = occ.boundingBox
            if top_z is None or bb.maxPoint.z > top_z:
                top_z = bb.maxPoint.z

    if top_z is None:
        return 0.0

    return top_z


def make_box_min(comp, name, x0, x1, y0, y1, z0, z1):
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


def make_cyl_z(comp, name, cx, cy, cz, r, length):
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + '_sk'

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(cx, cy, 0),
        r
    )

    prof = sk.profiles.item(sk.profiles.count - 1)

    ei = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ei.setSymmetricExtent(adsk.core.ValueInput.createByReal(length), True)

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, 0, cz)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def make_cyl_x(comp, name, cx, cy, cz, r, length):
    sk = comp.sketches.add(comp.yZConstructionPlane)
    sk.name = name + '_sk'

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(0, cy, cz),
        r
    )

    prof = sk.profiles.item(sk.profiles.count - 1)

    ei = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ei.setSymmetricExtent(adsk.core.ValueInput.createByReal(length), True)

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], cx, 0, 0)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def make_hex_prism_z(comp, name, cx, cy, z0, flat_to_flat, height):
    r = flat_to_flat / math.sqrt(3.0)

    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + '_sk'

    pts = []
    for i in range(6):
        a = math.radians(30.0 + 60.0 * i)
        pts.append(
            adsk.core.Point3D.create(
                cx + r * math.cos(a),
                cy + r * math.sin(a),
                0
            )
        )

    lines = sk.sketchCurves.sketchLines
    for i in range(6):
        lines.addByTwoPoints(pts[i], pts[(i + 1) % 6])

    prof = sk.profiles.item(sk.profiles.count - 1)

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


def fillet_body(comp, body, r):
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


def collect_footprint_bbox(root):
    min_x = None
    min_y = None
    max_x = None
    max_y = None

    used_names = []

    for i in range(root.occurrences.count):
        occ = root.occurrences.item(i)
        name = occ_name(occ)

        if name.startswith(BASE_COMP_PREFIX):
            continue

        if name.startswith(OUT_PREFIX):
            continue

        if not starts_with_any(name, INCLUDE_FOR_BASE_FOOTPRINT):
            continue

        bb = occ.boundingBox

        if min_x is None:
            min_x = bb.minPoint.x
            min_y = bb.minPoint.y
            max_x = bb.maxPoint.x
            max_y = bb.maxPoint.y
        else:
            min_x = min(min_x, bb.minPoint.x)
            min_y = min(min_y, bb.minPoint.y)
            max_x = max(max_x, bb.maxPoint.x)
            max_y = max(max_y, bb.maxPoint.y)

        used_names.append(name)

    if min_x is None:
        raise RuntimeError('No target components found after source module generation.')

    return min_x, max_x, min_y, max_y, used_names


def make_outer_mount_holes(comp, plate, x0, x1, y0, y1, z0, z1):
    offset = mm(OUTER_MOUNT_HOLE_EDGE_OFFSET_MM)
    r = mm(OUTER_MOUNT_HOLE_D_MM / 2.0)
    zc = (z0 + z1) / 2.0
    length = (z1 - z0) + mm(2.0)

    cx = (x0 + x1) / 2.0
    sx = x1 - x0

    pts = [
        (x0 + offset, y0 + offset),
        (x1 - offset, y0 + offset),
        (x0 + offset, y1 - offset),
        (x1 - offset, y1 - offset)
    ]

    if sx > mm(160.0):
        pts.append((cx, y0 + offset))
        pts.append((cx, y1 - offset))

    tools = []

    for i, (hx, hy) in enumerate(pts):
        tools.append(
            make_cyl_z(
                comp,
                'cut_14_Outer_Mount_Hole_' + str(i + 1),
                hx,
                hy,
                zc,
                r,
                length
            )
        )

    combine_cut(comp, plate, tools)


def get_rail_mount_points(root):
    rail_occ = find_occ(root, RAIL_PREFIXES)
    if not rail_occ:
        return []

    rail_base_bb = find_body_bbox_by_keywords(rail_occ, RAIL_BASE_BODY_KEYS)

    if not rail_base_bb:
        rail_base_bb = rail_occ.boundingBox

    x_off = mm(RAIL_MOUNT_X_FROM_LIMIT_EDGE_MM)
    y_off = mm(RAIL_MOUNT_Y_FROM_SIDE_MM)

    x0 = rail_base_bb.minPoint.x
    x1 = rail_base_bb.maxPoint.x
    y0 = rail_base_bb.minPoint.y
    y1 = rail_base_bb.maxPoint.y

    if (x1 - x0) <= 2.0 * x_off:
        raise RuntimeError('Rail base X length is too short for the 35.15 mm hole offset.')

    if (y1 - y0) <= 2.0 * y_off:
        raise RuntimeError('Rail base Y width is too short for the 6.15 mm hole offset.')

    return [
        (x0 + x_off, y0 + y_off),
        (x0 + x_off, y1 - y_off),
        (x1 - x_off, y0 + y_off),
        (x1 - x_off, y1 - y_off)
    ]


def make_rail_mount_holes_and_nut_pockets(comp, plate, points, z0, z1):
    if not points:
        return

    through_r = mm(RAIL_MOUNT_THROUGH_D_MM / 2.0)
    through_zc = (z0 + z1) / 2.0
    through_len = (z1 - z0) + mm(2.0)

    hex_af = mm(M3_NUT_AF_MM + M3_NUT_POCKET_CLEAR_MM)
    pocket_depth = mm(M3_NUT_POCKET_DEPTH_MM)
    pocket_z0 = z0 - mm(0.05)
    pocket_h = pocket_depth + mm(0.05)

    tools = []

    for i, (hx, hy) in enumerate(points):
        tools.append(
            make_cyl_z(
                comp,
                'cut_14_Rail_M3_Through_Hole_' + str(i + 1),
                hx,
                hy,
                through_zc,
                through_r,
                through_len
            )
        )

        tools.append(
            make_hex_prism_z(
                comp,
                'cut_14_Rail_M3_Hex_Nut_Pocket_Back_' + str(i + 1),
                hx,
                hy,
                pocket_z0,
                hex_af,
                pocket_h
            )
        )

    combine_cut(comp, plate, tools)


def is_passive_support_print_body(body):
    name = body.name.lower()
    return name.startswith('01_support_base')


def is_lock_limiter_print_body(body):
    name = body.name.lower()
    if name.startswith('cut_'):
        return False
    return True


def is_shackle_support_print_body(body):
    name = body.name.lower()

    if 'shaft_ref' in name:
        return False
    if 'bearing_ref' in name:
        return False
    if 'v_groove' in name:
        return False
    if name.startswith('cut_'):
        return False

    return (
        name.startswith('09_print')
        or name.startswith('09_spring_anchor_plate')
    )


def fixed_body_filter(occ, body):
    on = occ_name(occ).lower()

    if on.startswith('01_passive_shaft_support'):
        return is_passive_support_print_body(body)

    if on.startswith('08_lock_locator_and_limiters'):
        return is_lock_limiter_print_body(body)

    if on.startswith('09_shackle_tension_pulley_support'):
        return is_shackle_support_print_body(body)

    return False


def copy_body_to_target(src_occ, body, target_occ):
    target_comp = target_occ.component
    before = target_comp.bRepBodies.count

    try:
        proxy = body.createForAssemblyContext(src_occ)
    except Exception:
        proxy = body

    proxy.copyToComponent(target_occ)

    copied = []
    after = target_comp.bRepBodies.count

    for i in range(before, after):
        copied.append(target_comp.bRepBodies.item(i))

    return copied


def expand_passive_support_shaft_clearance(comp, body):
    bb = body.boundingBox

    cx = (bb.minPoint.x + bb.maxPoint.x) / 2.0
    cy = (bb.minPoint.y + bb.maxPoint.y) / 2.0
    cz = bb.maxPoint.z - mm(PASSIVE_SUPPORT_TOP_TO_SHAFT_MM)

    length = (bb.maxPoint.x - bb.minPoint.x) + mm(2.0)
    r = mm(PASSIVE_SUPPORT_SHAFT_CLEAR_D_MM / 2.0)

    cut = make_cyl_x(
        comp,
        'cut_14_Passive_Support_Shaft_Clearance_3p3mm',
        cx,
        cy,
        cz,
        r,
        length
    )

    combine_cut(comp, body, [cut])


def copy_fixed_bodies(root, target_occ):
    copied = []
    source_occs = []

    prefixes = [
        '01_Passive_Shaft_Support',
        '08_Lock_Locator_and_Limiters',
        '09_Shackle_Tension_Pulley_Support',
    ]

    for occ in find_occurrences(root, prefixes):
        source_occs.append(occ)

        for i in range(occ.component.bRepBodies.count):
            body = occ.component.bRepBodies.item(i)

            if not fixed_body_filter(occ, body):
                continue

            new_bodies = copy_body_to_target(occ, body, target_occ)

            for nb in new_bodies:
                if occ_name(occ).lower().startswith('01_passive_shaft_support'):
                    expand_passive_support_shaft_clearance(target_occ.component, nb)

            copied.extend(new_bodies)

    if HIDE_SOURCE_COMPONENTS:
        for occ in source_occs:
            try:
                occ.isLightBulbOn = False
            except Exception:
                pass

    return copied


def join_print_bodies(comp, base_body, bodies):
    joined = []
    failed = []

    for body in bodies:
        try:
            name = body.name
            combine_join(comp, base_body, [body])
            joined.append(name)
        except Exception:
            failed.append(body.name)

    base_body.name = '14_PRINT_Integrated_Base'
    return joined, failed


def delete_source_components(root):
    prefixes = [
        '01_Passive_Shaft_Support',
        '02_Padlock_Reference',
        '03_Drive_Head',
        '04_X_Axis_Linear_Rail',
        '05_MG92B_Servo_Reference',
        '06_Servo_Lift_Arm',
        '07_Drive_Head_Mounting_Base_and_Limiters',
        '08_Lock_Locator_and_Limiters',
        '09_Shackle_Tension_Pulley_Support',
    ]

    targets = find_occurrences(root, prefixes)

    for occ in targets:
        try:
            occ.deleteMe()
        except Exception:
            try:
                occ.isLightBulbOn = False
            except Exception:
                pass


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

        clean_existing(root, [OUT_PREFIX, '14_Integrated_Base'])
        try:
            delete_source_components(root)
        except Exception:
            pass
        ensure_default_user_parameters(design)

        ran_sources = run_sources(context)

        base_top_z = find_old_base_top(root)
        min_x, max_x, min_y, max_y, used_names = collect_footprint_bbox(root)
        rail_points = get_rail_mount_points(root)

        margin = mm(BASE_MARGIN_MM)
        t = mm(BASE_THICKNESS_MM)

        x0 = min_x - margin
        x1 = max_x + margin
        y0 = min_y - margin
        y1 = max_y + margin

        z1 = base_top_z
        z0 = base_top_z - t

        target_occ, comp = new_comp(root, OUT_COMP_NAME)

        base = make_box_min(
            comp,
            '14_base_before_join',
            x0,
            x1,
            y0,
            y1,
            z0,
            z1
        )

        fillet_body(comp, base, mm(CORNER_FILLET_MM))
        make_outer_mount_holes(comp, base, x0, x1, y0, y1, z0, z1)
        make_rail_mount_holes_and_nut_pockets(comp, base, rail_points, z0, z1)

        copied_bodies = copy_fixed_bodies(root, target_occ)
        joined, failed = join_print_bodies(comp, base, copied_bodies)
        lift_component_bodies_to_z0(comp)
        delete_source_components(root)

        try:
            design.snapshots.add()
        except Exception:
            pass

        app.activeViewport.fit()

        msg = (
            'Self-contained integrated print base created.\\n\\n'
            'Source modules run: {}\\n'
            'Base size X/Y: {:.2f} x {:.2f} mm\\n'
            'Base thickness: {:.2f} mm\\n'
            'Copied fixed bodies: {}\\n'
            'Joined bodies: {}\\n'
            'Unjoined bodies left separate: {}\\n'
            'Rail holes: {} x {:.2f} mm\\n'
            'Rail nut pockets: AF {:.2f} mm, depth {:.2f} mm\\n'
            '03 shaft clearance: {:.2f} mm\n'
            'Final bottom Z: 0.00 mm'
        ).format(
            len(ran_sources),
            to_mm(x1 - x0),
            to_mm(y1 - y0),
            BASE_THICKNESS_MM,
            len(copied_bodies),
            len(joined),
            len(failed),
            len(rail_points),
            RAIL_MOUNT_THROUGH_D_MM,
            M3_NUT_AF_MM + M3_NUT_POCKET_CLEAR_MM,
            M3_NUT_POCKET_DEPTH_MM,
            PASSIVE_SUPPORT_SHAFT_CLEAR_D_MM
        )

        if failed:
            msg += '\\n\\nSome copied bodies did not join. They remain in the same component.'

        if not SILENT_SUCCESS_MESSAGES:
            ui.messageBox(msg)
        else:
            try:
                app.log(msg)
            except Exception:
                pass

    except Exception:
        if ui:
            ui.messageBox('Failed:\\n{}'.format(traceback.format_exc()))
