SOURCE_FILES = [
    '00_Lock_Parameters.py',
    '01_Passive_Shaft_Support.py',
    '02_Padlock_Reference.py',
    '03_Drive_Head.py',
    '04_X_Axis_Linear_Rail.py',
    '05_MG92B_Servo_Reference.py',
    '07_Drive_Head_Mounting_Base_and_Limiters.py',
    '10_O_Ring_Press_Wheel_Hub.py',
    '11_Swing_Arm.py',
]


import adsk.core
import adsk.fusion
import traceback
import math


OUT_PREFIX = "15_Print_Layout"
OUT_COMP_NAME = "15_Print_Layout"

PRINT_GAP_MM = 18.0
QUANTITY_PER_PRINT_BODY = 2
PARTS_PER_ROW = 4
DELETE_TEMP_COMPONENTS = True
SHOW_SUCCESS_MESSAGE = False

TEMP_COMPONENT_PREFIXES = [
    '01_Passive_Shaft_Support',
    '02_Padlock_Reference',
    '03_Drive_Head',
    '04_X_Axis_Linear_Rail',
    '05_MG92B_Servo_Reference',
    '07_Drive_Head_Mounting_Base_and_Limiters',
    '10_O_Ring_Press_Wheel_Hub',
    '11_Swing_Arm',
]


def mm(v):
    return v / 10.0


def occ_name(occ):
    if occ.component:
        return occ.component.name
    return occ.name


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
            try:
                occ.isLightBulbOn = False
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


def new_comp(root, name):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = name
    return occ, comp


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


def rotate_bodies(comp, bodies, angle_deg, axis, point):
    objs = adsk.core.ObjectCollection.create()
    for b in bodies:
        if b:
            objs.add(b)

    if objs.count == 0:
        return

    mat = adsk.core.Matrix3D.create()
    mat.setToRotation(math.radians(angle_deg), axis, point)

    mi = comp.features.moveFeatures.createInput(objs, mat)
    comp.features.moveFeatures.add(mi)


def body_center(body):
    bb = body.boundingBox
    return adsk.core.Point3D.create(
        (bb.minPoint.x + bb.maxPoint.x) / 2.0,
        (bb.minPoint.y + bb.maxPoint.y) / 2.0,
        (bb.minPoint.z + bb.maxPoint.z) / 2.0
    )


def copy_body_to_target(src_occ, body, target_occ):
    comp = target_occ.component
    before = comp.bRepBodies.count

    try:
        proxy = body.createForAssemblyContext(src_occ)
    except Exception:
        proxy = body

    proxy.copyToComponent(target_occ)

    copied = []
    after = comp.bRepBodies.count
    for i in range(before, after):
        copied.append(comp.bRepBodies.item(i))

    return copied


SILENT_MESSAGES = []


def silent_message_box(*args, **kwargs):
    if args:
        try:
            SILENT_MESSAGES.append(str(args[0]))
        except Exception:
            pass
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

    message_start = len(SILENT_MESSAGES)
    module.run(context)

    for message in SILENT_MESSAGES[message_start:]:
        text = str(message).strip()
        if text.startswith('Failed:') or 'Traceback (most recent call last)' in text:
            raise RuntimeError(filename + ' failed:\n' + text)


def run_sources(context):
    ran = []
    for filename in SOURCE_FILES:
        run_source(filename, context)
        ran.append(filename)
    return ran



def is_print_body(occ, body):
    n = body.name.lower()
    on = occ_name(occ).lower()

    if on.startswith("10_o_ring_press_wheel_hub"):
        return n.startswith("10_print_o_ring")

    if on.startswith("11_swing_arm"):
        return n.startswith("11_print_left_swing_arm") or n.startswith("11_print_right_swing_arm")

    if on.startswith("07_drive_head_mounting_base_and_limiters"):
        return n.startswith("07_print") or n.startswith("print_this_slider") or n.startswith("slider_platform")

    return False


def part_kind(body):
    n = body.name.lower()

    if "o_ring" in n or "oring" in n:
        return "oring"

    if "left_swing_arm" in n:
        return "left_arm"

    if "right_swing_arm" in n:
        return "right_arm"

    if "07_print" in n or "slider" in n or "uniform_base" in n:
        return "slider_platform"

    return "other"


def sort_key(item):
    occ, body = item
    order = {
        "oring": 0,
        "left_arm": 1,
        "right_arm": 2,
        "slider_platform": 3,
        "other": 9,
    }
    return order.get(part_kind(body), 9)


def collect_print_bodies(root):
    prefixes = [
        "10_O_Ring_Press_Wheel_Hub",
        "11_Swing_Arm",
        "07_Drive_Head_Mounting_Base_and_Limiters"
    ]

    items = []
    for occ in find_occurrences(root, prefixes):
        for i in range(occ.component.bRepBodies.count):
            body = occ.component.bRepBodies.item(i)
            if is_print_body(occ, body):
                items.append((occ, body))

    items.sort(key=sort_key)
    return items


def orient_for_print(comp, body):
    k = part_kind(body)

    # O-ring hub: put the X-axis cylinder flat on the print bed.
    if k == "oring":
        rotate_bodies(
            comp,
            [body],
            90.0,
            adsk.core.Vector3D.create(0, 1, 0),
            adsk.core.Point3D.create(0, 0, 0)
        )
        return

    # Swing arms: do not first flatten both in the same direction.
    # Lay them flat by rotating around Y in opposite directions.
    if k == "left_arm":
        rotate_bodies(
            comp,
            [body],
            90.0,
            adsk.core.Vector3D.create(0, 1, 0),
            adsk.core.Point3D.create(0, 0, 0)
        )
        return

    if k == "right_arm":
        rotate_bodies(
            comp,
            [body],
            -90.0,
            adsk.core.Vector3D.create(0, 1, 0),
            adsk.core.Point3D.create(0, 0, 0)
        )
        return


def place_body_at(comp, body, x0_target, y0_target):
    bb = body.boundingBox
    dx = x0_target - bb.minPoint.x
    dy = y0_target - bb.minPoint.y
    dz = -bb.minPoint.z

    move_bodies(comp, [body], dx, dy, dz)

    bb2 = body.boundingBox
    return bb2


def layout_copied_bodies(target_occ, copied):
    comp = target_occ.component
    gap = mm(PRINT_GAP_MM)
    current_x = 0.0
    current_y = 0.0
    row_max_y = 0.0
    row_count = 0

    laid_out = []

    for body in copied:
        original = body.name
        orient_for_print(comp, body)
        bb = place_body_at(comp, body, current_x, current_y)

        current_x = bb.maxPoint.x + gap
        row_max_y = max(row_max_y, bb.maxPoint.y)
        row_count += 1

        body.name = "PRINT_LAYOUT_" + original
        laid_out.append(body.name)

        if row_count >= PARTS_PER_ROW:
            current_x = 0.0
            current_y = row_max_y + gap
            row_max_y = current_y
            row_count = 0

    return laid_out


def cleanup_temp_components(root):
    if not DELETE_TEMP_COMPONENTS:
        return

    clean_existing(root, TEMP_COMPONENT_PREFIXES)


def log_message(app, msg):
    try:
        app.log(msg)
    except Exception:
        pass


def validate_expected(found_kinds):
    missing = []
    for k in ["oring", "left_arm", "right_arm", "slider_platform"]:
        if k not in found_kinds:
            missing.append(k)
    return missing


def run(context):
    ui = None

    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)

        if not design:
            ui.messageBox("Open a Fusion design first.")
            return

        root = design.rootComponent

        clean_existing(root, OUT_PREFIX)
        clean_existing(root, TEMP_COMPONENT_PREFIXES)

        # Run the canonical parameter script first, then build the passive support
        # before aligning the padlock reference.  This matches the manual assembly
        # dependency chain and prevents the print-only workflow from using stale
        # fallback lock dimensions.
        ran_sources = run_sources(context)

        source_items = collect_print_bodies(root)
        if not source_items:
            raise RuntimeError(
                "No printable bodies found. Expected O-ring hub, swing arms, and slider platform."
            )

        target_occ, comp = new_comp(root, OUT_COMP_NAME)

        copied = []
        found_kinds = []

        for copy_no in range(QUANTITY_PER_PRINT_BODY):
            for occ, body in source_items:
                kind = part_kind(body)
                found_kinds.append(kind)
                new_bodies = copy_body_to_target(occ, body, target_occ)
                for nb in new_bodies:
                    nb.name = nb.name + "_copy" + str(copy_no + 1)
                copied.extend(new_bodies)

        laid_out = layout_copied_bodies(target_occ, copied)
        missing = validate_expected(sorted(set(found_kinds)))

        cleanup_temp_components(root)

        try:
            design.snapshots.add()
        except Exception:
            pass

        app.activeViewport.fit()

        msg = (
            "Print layout generated.\n"
            "Bodies laid out: " + str(len(laid_out)) + "\n"
            "Quantity per printable body: " + str(QUANTITY_PER_PRINT_BODY) + "\n"
            "Found: " + ", ".join(sorted(set(found_kinds))) + "\n"
            "Source modules run: " + str(len(ran_sources)) + "\n"
            "Swing arms flattened by opposite Y rotations: left +90 deg, right -90 deg."
        )

        if missing:
            msg += "\n\nMissing: " + ", ".join(missing)
            ui.messageBox(msg)
        elif SHOW_SUCCESS_MESSAGE:
            ui.messageBox(msg)
        else:
            log_message(app, msg)

    except Exception:
        if ui:
            ui.messageBox("Failed:\n" + traceback.format_exc())
