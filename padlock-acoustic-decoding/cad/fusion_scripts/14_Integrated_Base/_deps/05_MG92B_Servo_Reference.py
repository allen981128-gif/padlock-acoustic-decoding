import adsk.core
import adsk.fusion
import traceback
import math


def silent_message_box(*args, **kwargs):
    return 0


BAFFLE_GAP_MM = 3.0
SERVO_EXTRA_Z_LIFT_MM = 1.5

DRIVE_ROLLER_LOCAL_X_MM = 4.25
DRIVE_ROLLER_LOCAL_Y_MM = 50.0
DRIVE_ROLLER_LOCAL_Z_MM = 0.0

MOTOR_BODY_NAME = "03_01_motor_body_28p5x28p2x28p2"


def mm(v):
    return v / 10.0


def clean_existing(root, prefixes):
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


def new_comp(root, name):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = name
    return occ, comp


def get_occ_transform(occ):
    try:
        return occ.transform2.copy()
    except Exception:
        return occ.transform.copy()


def local_to_world_mm(occ, x, y, z):
    p = adsk.core.Point3D.create(mm(x), mm(y), mm(z))
    mat = get_occ_transform(occ)
    p.transformBy(mat)
    return p


def move_bodies(comp, bodies, dx, dy, dz):
    if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
        return

    objs = adsk.core.ObjectCollection.create()
    for b in bodies:
        objs.add(b)

    mat = adsk.core.Matrix3D.create()
    mat.translation = adsk.core.Vector3D.create(dx, dy, dz)

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def move_occurrence(occ, dx, dy, dz):
    if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
        return

    try:
        occ.isGrounded = False
    except Exception:
        pass

    mat = get_occ_transform(occ)
    t = mat.translation

    mat.translation = adsk.core.Vector3D.create(
        t.x + dx,
        t.y + dy,
        t.z + dz
    )

    try:
        occ.transform2 = mat
    except Exception:
        occ.transform = mat


def rotate_bodies(comp, bodies, angle_deg, axis, point):
    if abs(angle_deg) < 1e-9:
        return

    objs = adsk.core.ObjectCollection.create()
    for b in bodies:
        objs.add(b)

    mat = adsk.core.Matrix3D.create()
    mat.setToRotation(math.radians(angle_deg), axis, point)

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def add_box(comp, name, cx, cy, z0, sx, sy, sz):
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + "_sk"

    p1 = adsk.core.Point3D.create(mm(cx - sx / 2), mm(cy - sy / 2), 0)
    p2 = adsk.core.Point3D.create(mm(cx + sx / 2), mm(cy + sy / 2), 0)

    sk.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)

    prof = sk.profiles.item(sk.profiles.count - 1)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(sz)))

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, 0, mm(z0))

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def add_cyl_z(comp, name, cx, cy, z0, r, h):
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + "_sk"

    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(mm(cx), mm(cy), 0),
        mm(r)
    )

    prof = sk.profiles.item(sk.profiles.count - 1)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(h)))

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, 0, mm(z0))

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def cut_cyl_z(comp, target, cx, cy, z0, r, h):
    tool = add_cyl_z(comp, "cut_tool", cx, cy, z0, r, h)

    tools = adsk.core.ObjectCollection.create()
    tools.add(tool)

    ci = comp.features.combineFeatures.createInput(target, tools)
    ci.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    ci.isKeepToolBodies = False

    comp.features.combineFeatures.add(ci)


def get_all_bodies(comp):
    bodies = []
    for i in range(comp.bRepBodies.count):
        bodies.append(comp.bRepBodies.item(i))
    return bodies


def bbox_center(bb):
    return adsk.core.Point3D.create(
        (bb.minPoint.x + bb.maxPoint.x) / 2,
        (bb.minPoint.y + bb.maxPoint.y) / 2,
        (bb.minPoint.z + bb.maxPoint.z) / 2
    )


def get_body_center(comp):
    bodies = get_all_bodies(comp)

    min_x = None
    min_y = None
    min_z = None
    max_x = None
    max_y = None
    max_z = None

    for b in bodies:
        bb = b.boundingBox

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

    return adsk.core.Point3D.create(
        (min_x + max_x) / 2,
        (min_y + max_y) / 2,
        (min_z + max_z) / 2
    )


def body_world_bbox(occ, body):
    try:
        proxy = body.createForAssemblyContext(occ)
        return proxy.boundingBox
    except Exception:
        return body.boundingBox


def body_world_center(occ, body):
    return bbox_center(body_world_bbox(occ, body))


def union_world_bbox_for_names(occ, names):
    names = [n.lower() for n in names]

    min_x = None
    min_y = None
    min_z = None
    max_x = None
    max_y = None
    max_z = None

    for i in range(occ.component.bRepBodies.count):
        b = occ.component.bRepBodies.item(i)
        bn = b.name.lower()

        use_body = False
        for n in names:
            if n in bn:
                use_body = True
                break

        if not use_body:
            continue

        bb = body_world_bbox(occ, b)

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
        return occ.boundingBox

    return adsk.core.BoundingBox3D.create(
        adsk.core.Point3D.create(min_x, min_y, min_z),
        adsk.core.Point3D.create(max_x, max_y, max_z)
    )


def lift_to_z0(comp):
    bodies = get_all_bodies(comp)
    if not bodies:
        return

    min_z = None

    for b in bodies:
        bb = b.boundingBox
        if min_z is None or bb.minPoint.z < min_z:
            min_z = bb.minPoint.z

    if min_z is not None:
        move_bodies(comp, bodies, 0, 0, -min_z)


def find_occ(root, prefix):
    occs = root.allOccurrences

    for i in range(occs.count):
        occ = occs.item(i)

        if occ.component and occ.component.name.startswith(prefix):
            return occ

        if occ.name.startswith(prefix):
            return occ

    return None


def get_motor_body_bbox(drive_occ):
    for i in range(drive_occ.component.bRepBodies.count):
        b = drive_occ.component.bRepBodies.item(i)
        if b.name == MOTOR_BODY_NAME:
            return body_world_bbox(drive_occ, b)

    for i in range(drive_occ.component.bRepBodies.count):
        b = drive_occ.component.bRepBodies.item(i)
        if "motor_body" in b.name.lower():
            return body_world_bbox(drive_occ, b)

    raise RuntimeError("Cannot find 07 motor body.")


def get_rubber_roller_center(drive_occ):
    return local_to_world_mm(
        drive_occ,
        DRIVE_ROLLER_LOCAL_X_MM,
        DRIVE_ROLLER_LOCAL_Y_MM,
        DRIVE_ROLLER_LOCAL_Z_MM
    )


def get_servo_main_body_bbox(servo_occ):
    return union_world_bbox_for_names(
        servo_occ,
        [
            "servo_bottom_case",
            "servo_main_case",
            "servo_top_case"
        ]
    )


def servo_output_center(comp, occ):
    names = [
        "servo_output_shaft_ref",
        "servo_output_boss"
    ]

    for key in names:
        for i in range(comp.bRepBodies.count):
            b = comp.bRepBodies.item(i)
            if key in b.name.lower():
                return body_world_center(occ, b)

    return bbox_center(occ.boundingBox)


def position_servo_to_motor_edge(root, servo_occ, servo_comp):
    drive_occ = find_occ(root, "03_Drive_Head")

    if not drive_occ:
        raise RuntimeError("03_Drive_Head not found.")

    motor_bb = get_motor_body_bbox(drive_occ)
    motor_c = bbox_center(motor_bb)
    rubber_c = get_rubber_roller_center(drive_occ)

    y_sign = 1.0
    if rubber_c.y < motor_c.y:
        y_sign = -1.0

    # Z: main body bottom aligns with motor body bottom.
    servo_main_bb = get_servo_main_body_bbox(servo_occ)
    dz = motor_bb.minPoint.z - servo_main_bb.minPoint.z
    move_occurrence(servo_occ, 0, 0, dz)

    # X: output shaft / lift wheel line aligns with rubber roller centre.
    shaft_c = servo_output_center(servo_comp, servo_occ)
    dx = rubber_c.x - shaft_c.x
    move_occurrence(servo_occ, dx, 0, 0)

    # Y: main body face sits outside motor body with baffle gap.
    servo_main_bb = get_servo_main_body_bbox(servo_occ)

    if y_sign > 0:
        dy = motor_bb.maxPoint.y + mm(BAFFLE_GAP_MM) - servo_main_bb.minPoint.y
    else:
        dy = motor_bb.minPoint.y - mm(BAFFLE_GAP_MM) - servo_main_bb.maxPoint.y

    move_occurrence(servo_occ, 0, dy, 0)


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

        clean_existing(root, [
            "05_MG92B_Servo_Reference"
        ])

        occ, comp = new_comp(root, "05_MG92B_Servo_Reference")

        body_x = 22.6
        body_y = 12.0

        lug_bottom_z = 21.0
        lug_t = 2.1
        lug_to_top = 2.0
        body_z = lug_bottom_z + lug_t + lug_to_top

        ear_x = 4.8
        overall_x = body_x + 2 * ear_x
        ear_cx = body_x / 2 + ear_x / 2

        lug_z = lug_bottom_z
        hole_pitch_x = body_x + ear_x

        screw_r = 1.2

        shaft_x = -body_x / 2 + 7.2
        shaft_y = 0.0

        boss_r = 4.2
        boss_h = 2.0
        shaft_r = 2.2
        shaft_h = 4.2

        bottom_cap_h = 2.0
        middle_h = 18.5
        top_cap_h = body_z - bottom_cap_h - middle_h

        side_rotation_deg = 90.0
        vertical_rotation_deg = 180.0

        add_box(
            comp,
            "servo_bottom_case",
            0,
            0,
            0,
            body_x,
            body_y,
            bottom_cap_h
        )

        add_box(
            comp,
            "servo_main_case",
            0,
            0,
            bottom_cap_h,
            body_x,
            body_y,
            middle_h
        )

        add_box(
            comp,
            "servo_top_case",
            0,
            0,
            bottom_cap_h + middle_h,
            body_x,
            body_y,
            top_cap_h
        )

        left_ear = add_box(
            comp,
            "servo_left_mounting_ear",
            -ear_cx,
            0,
            lug_z,
            ear_x,
            body_y,
            lug_t
        )

        right_ear = add_box(
            comp,
            "servo_right_mounting_ear",
            ear_cx,
            0,
            lug_z,
            ear_x,
            body_y,
            lug_t
        )

        cut_cyl_z(
            comp,
            left_ear,
            -hole_pitch_x / 2,
            0,
            lug_z - 0.5,
            screw_r,
            lug_t + 1.0
        )

        cut_cyl_z(
            comp,
            right_ear,
            hole_pitch_x / 2,
            0,
            lug_z - 0.5,
            screw_r,
            lug_t + 1.0
        )

        add_box(
            comp,
            "servo_top_raised_block",
            shaft_x,
            0,
            body_z,
            13.0,
            body_y,
            1.4
        )

        add_cyl_z(
            comp,
            "servo_output_boss",
            shaft_x,
            shaft_y,
            body_z + 0.8,
            boss_r,
            boss_h
        )

        add_cyl_z(
            comp,
            "servo_output_shaft_ref",
            shaft_x,
            shaft_y,
            body_z + 2.4,
            shaft_r,
            shaft_h
        )

        bodies = get_all_bodies(comp)

        rotate_bodies(
            comp,
            bodies,
            side_rotation_deg,
            adsk.core.Vector3D.create(0, 1, 0),
            adsk.core.Point3D.create(0, 0, 0)
        )

        lift_to_z0(comp)

        bodies = get_all_bodies(comp)
        center = get_body_center(comp)

        rotate_bodies(
            comp,
            bodies,
            vertical_rotation_deg,
            adsk.core.Vector3D.create(0, 0, 1),
            center
        )

        position_servo_to_motor_edge(root, occ, comp)

        # Extra lift after normal alignment.
        move_occurrence(occ, 0, 0, mm(SERVO_EXTRA_Z_LIFT_MM))

        try:
            design.snapshots.add()
        except Exception:
            pass

        app.activeViewport.fit()

        silent_message_box("05 MG92B servo reference generated, aligned and lifted 1.5 mm.")

    except Exception:
        if ui:
            silent_message_box(traceback.format_exc())