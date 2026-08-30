import adsk.core
import adsk.fusion
import traceback
import math


def silent_message_box(*args, **kwargs):
    return 0


def mm(v):
    return v / 10.0


def to_mm(v):
    return v * 10.0


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

    p1 = adsk.core.Point3D.create(mm(cx - sx / 2.0), mm(cy - sy / 2.0), 0)
    p2 = adsk.core.Point3D.create(mm(cx + sx / 2.0), mm(cy + sy / 2.0), 0)

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


def add_cyl_x(comp, name, cx, cy, cz, r, length):
    body = add_cyl_z(
        comp,
        name,
        cx,
        cy,
        cz - length / 2.0,
        r,
        length
    )

    rotate_bodies(
        comp,
        [body],
        90.0,
        adsk.core.Vector3D.create(0, 1, 0),
        adsk.core.Point3D.create(mm(cx), mm(cy), mm(cz))
    )

    return body


def add_ring_z(comp, name, cx, cy, cz, outer_r, inner_r, h):
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.name = name + "_sk"

    center = adsk.core.Point3D.create(mm(cx), mm(cy), 0)

    sk.sketchCurves.sketchCircles.addByCenterRadius(center, mm(outer_r))
    sk.sketchCurves.sketchCircles.addByCenterRadius(center, mm(inner_r))

    prof = None

    for i in range(sk.profiles.count):
        p = sk.profiles.item(i)
        try:
            if p.profileLoops.count > 1:
                prof = p
                break
        except Exception:
            pass

    if prof is None:
        prof = sk.profiles.item(sk.profiles.count - 1)

    ext_in = comp.features.extrudeFeatures.createInput(
        prof,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(h)))

    ext = comp.features.extrudeFeatures.add(ext_in)
    body = ext.bodies.item(0)
    body.name = name

    move_bodies(comp, [body], 0, 0, mm(cz - h / 2.0))

    try:
        sk.isVisible = False
    except Exception:
        pass

    return body


def add_ring_x(comp, name, cx, cy, cz, outer_r, inner_r, length):
    body = add_ring_z(
        comp,
        name,
        cx,
        cy,
        cz,
        outer_r,
        inner_r,
        length
    )

    rotate_bodies(
        comp,
        [body],
        90.0,
        adsk.core.Vector3D.create(0, 1, 0),
        adsk.core.Point3D.create(mm(cx), mm(cy), mm(cz))
    )

    return body


def bbox_center(bb):
    return adsk.core.Point3D.create(
        (bb.minPoint.x + bb.maxPoint.x) / 2.0,
        (bb.minPoint.y + bb.maxPoint.y) / 2.0,
        (bb.minPoint.z + bb.maxPoint.z) / 2.0
    )


def body_world_bbox(occ, body):
    try:
        proxy = body.createForAssemblyContext(occ)
        return proxy.boundingBox
    except Exception:
        return body.boundingBox


def find_occ(root, prefix):
    occs = root.allOccurrences

    for i in range(occs.count):
        occ = occs.item(i)

        if occ.component and occ.component.name.startswith(prefix):
            return occ

        if occ.name.startswith(prefix):
            return occ

    return None


def servo_output_ref_mm(servo_occ):
    keys = [
        "servo_output_shaft_ref",
        "servo_output_boss"
    ]

    for key in keys:
        for i in range(servo_occ.component.bRepBodies.count):
            b = servo_occ.component.bRepBodies.item(i)

            if key in b.name.lower():
                bb = body_world_bbox(servo_occ, b)
                c = bbox_center(bb)

                output_w_x = to_mm(bb.maxPoint.x - bb.minPoint.x)
                if output_w_x < 0.5:
                    output_w_x = 4.2

                return to_mm(c.x), to_mm(c.y), to_mm(c.z), output_w_x

    c = bbox_center(servo_occ.boundingBox)
    return to_mm(c.x), to_mm(c.y), to_mm(c.z), 4.2


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

        servo_occ = find_occ(root, "05_MG92B_Servo_Reference")
        if not servo_occ:
            raise RuntimeError("05_MG92B_Servo_Reference not found. Run 05 servo script first.")

        clean_existing(root, [
            "06_Servo_Lift_Arm"
        ])

        occ, comp = new_comp(root, "06_Servo_Lift_Arm")

        servo_x, servo_y, servo_z, output_w_x = servo_output_ref_mm(servo_occ)

        # Main parameters
        ARM_DIR_Y = 1.0

        arm_len_y = 15.0
        arm_w_x = output_w_x
        arm_t_z = 3.0

        bearing_od = 10.0
        bearing_id = 3.0
        bearing_w_x = 4.0
        bearing_lift_extra_z = 0.5

        bearing_from_arm_end = 3.0

        bridge_len_x = 100.0
        bridge_r = bearing_id / 2.0

        # Arm from servo output wheel
        arm_start_y = servo_y
        arm_end_y = servo_y + ARM_DIR_Y * arm_len_y

        arm_center_x = servo_x
        arm_center_y = servo_y + ARM_DIR_Y * arm_len_y / 2.0
        arm_center_z = servo_z

        arm_z0 = arm_center_z - arm_t_z / 2.0
        arm_top_z = arm_z0 + arm_t_z

        arm = add_box(
            comp,
            "Lift_Arm_15mm",
            arm_center_x,
            arm_center_y,
            arm_z0,
            arm_w_x,
            arm_len_y,
            arm_t_z
        )

        # Bearing from arm coordinates
        bearing_cx = arm_center_x
        bearing_cy = arm_end_y - ARM_DIR_Y * bearing_from_arm_end
        bearing_cz = arm_top_z + bearing_od / 2.0 + bearing_lift_extra_z

        bearing = add_ring_x(
            comp,
            "Bearing_623ZZ_ID3_OD10_W4_Lift1mm",
            bearing_cx,
            bearing_cy,
            bearing_cz,
            bearing_od / 2.0,
            bearing_id / 2.0,
            bearing_w_x
        )

        # Bridge is the 100mm rod through the bearing
        bridge = add_cyl_x(
            comp,
            "Bridge_Rod_100mm_Through_Bearing",
            bearing_cx,
            bearing_cy,
            bearing_cz,
            bridge_r,
            bridge_len_x
        )

        try:
            design.snapshots.add()
        except Exception:
            pass

        app.activeViewport.fit()

        silent_message_box("10 lift arm with 623ZZ bearing, 1mm lift and 100mm bridge rod generated.")

    except Exception:
        if ui:
            silent_message_box(traceback.format_exc())