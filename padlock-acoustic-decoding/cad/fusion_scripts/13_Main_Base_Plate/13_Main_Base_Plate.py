import adsk.core
import adsk.fusion
import traceback
import math


BASE_COMP_PREFIX = '13_Main_Base_Plate'
NEW_BASE_NAME = '13_Main_Base_Plate'

# Include these top-level components in the footprint calculation.
# Missing components are ignored.
INCLUDE_PREFIXES = [
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

# Outer base mounting holes.
MOUNT_HOLE_D_MM = 4.2
MOUNT_HOLE_EDGE_OFFSET_MM = 12.0

# Linear rail mounting holes.
RAIL_MOUNT_THROUGH_D_MM = 3.77
RAIL_MOUNT_X_FROM_LIMIT_EDGE_MM = 35.15
RAIL_MOUNT_Y_FROM_SIDE_MM = 6.15

# M3 hex nut pocket on the underside of the base.
M3_NUT_AF_MM = 5.5
M3_NUT_POCKET_DEPTH_MM = 2.5
M3_NUT_POCKET_CLEAR_MM = 0.15

CORNER_FILLET_MM = 1.2


def mm(v):
    return v / 10.0


def to_mm(v):
    return v * 10.0


def occ_name(occ):
    if occ.component:
        return occ.component.name
    return occ.name


def starts_with_any(name, prefixes):
    for p in prefixes:
        if name.startswith(p):
            return True
    return False


def find_occ(root, prefixes):
    if isinstance(prefixes, str):
        prefixes = [prefixes]

    occs = root.allOccurrences

    for i in range(occs.count):
        occ = occs.item(i)
        name = occ_name(occ)

        for p in prefixes:
            if name.startswith(p):
                return occ

    return None


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


def clean_existing_base(root):
    targets = []

    for i in range(root.occurrences.count):
        occ = root.occurrences.item(i)
        name = occ_name(occ)

        if name.startswith(BASE_COMP_PREFIX):
            targets.append(occ)

    for occ in targets:
        try:
            occ.deleteMe()
        except Exception:
            pass


def new_comp(root, name):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = name
    return comp


def move_bodies(comp, bodies, dx, dy, dz):
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
    ei.setSymmetricExtent(
        adsk.core.ValueInput.createByReal(length),
        True
    )

    ext = comp.features.extrudeFeatures.add(ei)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, 0, cz)

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def make_hex_prism_z(comp, name, cx, cy, z0, flat_to_flat, height):
    # For a regular hexagon, AF = sqrt(3) * circumradius.
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

        if not starts_with_any(name, INCLUDE_PREFIXES):
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
        raise RuntimeError(
            'No target components found. Run the assembly scripts first, then run this base plate script.'
        )

    return min_x, max_x, min_y, max_y, used_names


def make_outer_mount_holes(comp, plate, x0, x1, y0, y1, z0, z1):
    offset = mm(MOUNT_HOLE_EDGE_OFFSET_MM)
    r = mm(MOUNT_HOLE_D_MM / 2.0)
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
                'cut_13_Outer_Mount_Hole_' + str(i + 1),
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

    rail_base_bb = find_body_bbox_by_keywords(
        rail_occ,
        RAIL_BASE_BODY_KEYS
    )

    if not rail_base_bb:
        rail_base_bb = rail_occ.boundingBox

    x_off = mm(RAIL_MOUNT_X_FROM_LIMIT_EDGE_MM)
    y_off = mm(RAIL_MOUNT_Y_FROM_SIDE_MM)

    x0 = rail_base_bb.minPoint.x
    x1 = rail_base_bb.maxPoint.x
    y0 = rail_base_bb.minPoint.y
    y1 = rail_base_bb.maxPoint.y

    if (x1 - x0) <= 2.0 * x_off:
        raise RuntimeError('Rail base X length is too short for the requested 35.15 mm hole offset.')

    if (y1 - y0) <= 2.0 * y_off:
        raise RuntimeError('Rail base Y width is too short for the requested 6.15 mm hole offset.')

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
                'cut_13_Rail_M3_Through_Hole_' + str(i + 1),
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
                'cut_13_Rail_M3_Hex_Nut_Pocket_Back_' + str(i + 1),
                hx,
                hy,
                pocket_z0,
                hex_af,
                pocket_h
            )
        )

    combine_cut(comp, plate, tools)


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

        clean_existing_base(root)

        comp = new_comp(root, NEW_BASE_NAME)

        plate = make_box_min(
            comp,
            '13_PRINT_Main_Base_Plate',
            x0,
            x1,
            y0,
            y1,
            z0,
            z1
        )

        fillet_body(comp, plate, mm(CORNER_FILLET_MM))
        make_outer_mount_holes(comp, plate, x0, x1, y0, y1, z0, z1)
        make_rail_mount_holes_and_nut_pockets(comp, plate, rail_points, z0, z1)

        try:
            design.snapshots.add()
        except Exception:
            pass

        app.activeViewport.fit()

        ui.messageBox(
            '13 main base plate created.\\n\\n'
            'Included components: {}\\n'
            'Base top Z kept at: {:.2f} mm\\n'
            'Base size X/Y: {:.2f} x {:.2f} mm\\n'
            'Base thickness: {:.2f} mm\\n'
            'Margin: {:.2f} mm\\n'
            'Outer mount holes: {:.2f} mm diameter.\\n'
            'Rail mount holes: {} x {:.2f} mm diameter.\\n'
            'Rail nut pockets on underside: AF {:.2f} mm, depth {:.2f} mm.'.format(
                len(used_names),
                to_mm(base_top_z),
                to_mm(x1 - x0),
                to_mm(y1 - y0),
                BASE_THICKNESS_MM,
                BASE_MARGIN_MM,
                MOUNT_HOLE_D_MM,
                len(rail_points),
                RAIL_MOUNT_THROUGH_D_MM,
                M3_NUT_AF_MM + M3_NUT_POCKET_CLEAR_MM,
                M3_NUT_POCKET_DEPTH_MM
            )
        )

    except Exception:
        if ui:
            ui.messageBox('Failed:\\n{}'.format(traceback.format_exc()))
