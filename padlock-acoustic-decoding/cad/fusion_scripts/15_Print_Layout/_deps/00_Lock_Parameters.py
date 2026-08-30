import adsk.core
import adsk.fusion
import traceback


def set_param(design, name, expr, unit='', comment=''):
    p = design.userParameters.itemByName(name)
    v = adsk.core.ValueInput.createByString(expr)

    if p:
        p.expression = expr
        p.comment = comment
        return p

    return design.userParameters.add(name, v, unit, comment)


def run(context):
    ui = None

    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)

        if not design:
            silent_message_box('Open a Fusion design first.')
            return

        params = [
            # General
            ('clear_fit', '0.3 mm', 'mm', 'Fit clearance'),
            ('clear_general', '0.5 mm', 'mm', 'General clearance'),
            ('clear_large', '1.0 mm', 'mm', 'Large clearance'),
            ('wall_min', '2.5 mm', 'mm', 'Minimum wall'),
            ('fillet_small', '0.6 mm', 'mm', 'Small fillet'),
            ('fillet_medium', '1.2 mm', 'mm', 'Medium fillet'),
            ('fillet_large', '3.0 mm', 'mm', 'Large fillet'),

            # Lock body
            ('lock_width', '47.14 mm', 'mm', 'Body width'),
            ('lock_height', '49.85 mm', 'mm', 'Body height'),
            ('lock_thickness', '14.5 mm', 'mm', 'Body thickness'),
            ('lock_edge_fillet', '1.0 mm', 'mm', 'Body edge fillet'),
            ('lock_body_fillet', '1.4 mm', 'mm', 'Body corner fillet'),

            ('lock_top_z', 'lock_height / 2', 'mm', 'Body top Z'),
            ('lock_bottom_z', '-lock_height / 2', 'mm', 'Body bottom Z'),
            ('lock_left_x', '-lock_width / 2', 'mm', 'Body left X'),
            ('lock_right_x', 'lock_width / 2', 'mm', 'Body right X'),
            ('lock_front_y', '-lock_thickness / 2', 'mm', 'Body front Y'),
            ('lock_back_y', 'lock_thickness / 2', 'mm', 'Body back Y'),

            # Metal faces
            ('front_plate_thickness', '0.8 mm', 'mm', 'Front plate thickness'),
            ('back_plate_thickness', '0.8 mm', 'mm', 'Back plate thickness'),
            ('front_plate_y', 'lock_front_y - front_plate_thickness / 2', 'mm', 'Front plate Y'),
            ('back_plate_y', 'lock_back_y + back_plate_thickness / 2', 'mm', 'Back plate Y'),

            # Red shell
            ('shell_right_width', '2.3 mm', 'mm', 'Right red lip width'),
            ('shell_left_width', '2.23 mm', 'mm', 'Left red lip width'),
            ('shell_top_height', '2.59 mm', 'mm', 'Top red lip height'),
            ('shell_depth', 'lock_thickness + 1.6 mm', 'mm', 'Shell depth'),
            ('shell_radius', '2.0 mm', 'mm', 'Shell edge radius'),

            ('shell_right_x', 'lock_right_x - shell_right_width / 2', 'mm', 'Right shell X'),
            ('shell_left_x', 'lock_left_x + shell_left_width / 2', 'mm', 'Left shell X'),
            ('shell_top_z', 'lock_top_z - shell_top_height / 2', 'mm', 'Top shell Z'),
            ('shell_center_y', '0 mm', 'mm', 'Shell centre Y'),

            # Logo panel
            ('logo_panel_width', '21 mm', 'mm', 'Logo panel width'),
            ('logo_panel_height', '34 mm', 'mm', 'Logo panel height'),
            ('logo_panel_depth', '0.35 mm', 'mm', 'Logo panel depth'),
            ('logo_panel_corner', '0.7 mm', 'mm', 'Logo panel corner'),

            ('logo_panel_x', 'lock_left_x + 16.5 mm', 'mm', 'Logo panel X'),
            ('logo_panel_y', 'front_plate_y - 0.15 mm', 'mm', 'Logo panel Y'),
            ('logo_panel_z', '-1.0 mm', 'mm', 'Logo panel Z'),

            # Dial stack
            ('dial_count', '4', '', 'Dial count'),
            ('dial_body_diameter', '18.8 mm', 'mm', 'Wheel diameter'),
            ('dial_body_radius', 'dial_body_diameter / 2', 'mm', 'Wheel radius'),
            ('dial_body_width', 'lock_thickness', 'mm', 'Wheel inner width'),

            ('dial_window_width', '14.14 mm', 'mm', 'Front window width'),
            ('dial_window_height', '3.98 mm', 'mm', 'Front window height'),
            ('dial_window_gap', '4.5 mm', 'mm', 'Window gap'),
            ('dial_pitch', 'dial_window_height + dial_window_gap', 'mm', 'Window pitch'),

            ('dial_window_x_offset_right', '12.45 mm', 'mm', 'Window centre from right edge'),
            ('dial_window_x', 'lock_right_x - dial_window_x_offset_right', 'mm', 'Window centre X'),

            ('dial_top_offset', '11.69 mm', 'mm', 'Top window centre from body top'),
            ('dial_1_z', 'lock_top_z - dial_top_offset', 'mm', 'Top window Z'),
            ('dial_2_z', 'dial_1_z - dial_pitch', 'mm', 'Second window Z'),
            ('dial_3_z', 'dial_2_z - dial_pitch', 'mm', 'Third window Z'),
            ('dial_4_z', 'dial_3_z - dial_pitch', 'mm', 'Bottom window Z'),
            ('dial_stack_center_z', '(dial_1_z + dial_4_z) / 2', 'mm', 'Dial stack centre Z'),

            ('dial_center_x', 'dial_window_x', 'mm', 'Dial centre X'),
            ('dial_center_y', '0 mm', 'mm', 'Dial centre Y'),

            # Wheel exposure
            ('dial_projection', '(dial_body_diameter - lock_thickness) / 2', 'mm', 'Wheel projection each side'),
            ('dial_front_projection', 'dial_projection', 'mm', 'Front wheel projection'),
            ('dial_back_projection', 'dial_projection', 'mm', 'Back wheel projection'),

            # Front and back dial windows
            ('dial_window_depth', '0.55 mm', 'mm', 'Window recess depth'),
            ('dial_window_corner', '0.5 mm', 'mm', 'Window corner'),

            ('dial_visible_width', '13.2 mm', 'mm', 'Visible wheel width'),
            ('dial_visible_height', '4.4 mm', 'mm', 'Visible wheel height'),

            ('front_window_y', 'front_plate_y - dial_window_depth / 2', 'mm', 'Front window Y'),
            ('back_window_y', 'back_plate_y + dial_window_depth / 2', 'mm', 'Back window Y'),

            ('front_dial_face_y', 'lock_front_y - dial_front_projection / 2', 'mm', 'Front wheel face Y'),
            ('back_dial_face_y', 'lock_back_y + dial_back_projection / 2', 'mm', 'Back wheel face Y'),

            # Side windows
            ('side_window_diameter', '4.4 mm', 'mm', 'Side window diameter'),
            ('side_window_radius', 'side_window_diameter / 2', 'mm', 'Side window radius'),
            ('side_window_depth', '0.5 mm', 'mm', 'Side window depth'),

            ('side_window_x', 'lock_right_x - shell_right_width / 2', 'mm', 'Side window X'),
            ('side_window_y', '0 mm', 'mm', 'Side window Y'),

            ('side_dial_visible_diameter', '3.6 mm', 'mm', 'Visible side dial diameter'),
            ('side_dial_visible_radius', 'side_dial_visible_diameter / 2', 'mm', 'Visible side dial radius'),
            ('side_dial_projection', '0.5 mm', 'mm', 'Side dial projection'),
            ('side_dial_x', 'lock_right_x + side_dial_projection / 2', 'mm', 'Side visible dial X'),

            # Shackle
            ('shackle_rod_diameter', '6.16 mm', 'mm', 'Rod diameter'),
            ('shackle_rod_radius', 'shackle_rod_diameter / 2', 'mm', 'Rod radius'),
            ('shackle_leg_spacing', '25.76 mm', 'mm', 'Leg spacing'),
            ('shackle_visible_height', '31.8 mm', 'mm', 'Visible shackle height'),
            ('shackle_arc_radius', 'shackle_leg_spacing / 2', 'mm', 'Top bend radius'),
            ('shackle_leg_length', 'shackle_visible_height - shackle_arc_radius', 'mm', 'Straight leg length'),

            ('shackle_left_x', '-shackle_leg_spacing / 2', 'mm', 'Left leg X'),
            ('shackle_right_x', 'shackle_leg_spacing / 2', 'mm', 'Right leg X'),
            ('shackle_center_y', '0 mm', 'mm', 'Shackle centre Y'),
            ('shackle_insert_z', 'lock_top_z - 1.0 mm', 'mm', 'Insert Z'),
            ('shackle_arc_center_z', 'lock_top_z + shackle_leg_length', 'mm', 'Arc centre Z'),
            ('shackle_top_z', 'lock_top_z + shackle_visible_height', 'mm', 'Top Z'),

            ('shackle_hole_diameter', 'shackle_rod_diameter + 0.8 mm', 'mm', 'Hole diameter'),
            ('shackle_hole_radius', 'shackle_hole_diameter / 2', 'mm', 'Hole radius'),

            # Screws
            ('screw_diameter', '5.0 mm', 'mm', 'Screw diameter'),
            ('screw_radius', 'screw_diameter / 2', 'mm', 'Screw radius'),
            ('screw_depth', '0.35 mm', 'mm', 'Screw depth'),
            ('screw_z', 'lock_bottom_z + 6.0 mm', 'mm', 'Screw Z'),
            ('screw_left_x', 'lock_right_x - 20.5 mm', 'mm', 'Left screw X'),
            ('screw_right_x', 'lock_right_x - 8.0 mm', 'mm', 'Right screw X'),

            # Base
            ('base_length_x', '125 mm', 'mm', 'Base length X'),
            ('base_width_y', '95 mm', 'mm', 'Base width Y'),
            ('base_thickness', '6 mm', 'mm', 'Base thickness'),
            ('base_top_z', 'lock_bottom_z - clear_large', 'mm', 'Base top Z'),
            ('base_bottom_z', 'base_top_z - base_thickness', 'mm', 'Base bottom Z'),
            ('base_corner_radius', '3 mm', 'mm', 'Base corner radius'),

            # Holder
            ('holder_back_thickness', '5 mm', 'mm', 'Back wall thickness'),
            ('holder_side_thickness', '5 mm', 'mm', 'Side wall thickness'),
            ('holder_bottom_lip_height', '5 mm', 'mm', 'Bottom lip height'),
            ('holder_clamp_height', 'lock_height + 8 mm', 'mm', 'Clamp height'),

            ('holder_inner_width', 'lock_width + clear_large', 'mm', 'Inner width'),
            ('holder_inner_thickness', 'lock_thickness + 2 * dial_projection + clear_large', 'mm', 'Inner thickness'),
            ('holder_outer_width', 'holder_inner_width + 2 * holder_side_thickness', 'mm', 'Outer width'),
            ('holder_back_y', 'lock_back_y + dial_projection + holder_back_thickness / 2 + clear_fit', 'mm', 'Back wall Y'),

            # Drive head
            ('drive_wheel_diameter', '6 mm', 'mm', 'Drive wheel diameter'),
            ('drive_wheel_radius', 'drive_wheel_diameter / 2', 'mm', 'Drive wheel radius'),
            ('drive_wheel_width', '3 mm', 'mm', 'Drive wheel width'),
            ('drive_contact_depth', '0.8 mm', 'mm', 'Contact depth'),

            ('drive_motor_width', '28 mm', 'mm', 'Motor width'),
            ('drive_motor_depth', '28 mm', 'mm', 'Motor depth'),
            ('drive_motor_length', '35 mm', 'mm', 'Motor length'),

            ('drive_center_x', 'lock_right_x + drive_wheel_radius - drive_contact_depth', 'mm', 'Drive centre X'),
            ('drive_center_y', 'side_window_y', 'mm', 'Drive centre Y'),
            ('drive_center_z', 'dial_stack_center_z', 'mm', 'Drive centre Z'),

            ('drive_carriage_width', '36 mm', 'mm', 'Carriage width'),
            ('drive_carriage_depth', '18 mm', 'mm', 'Carriage depth'),
            ('drive_carriage_height', '22 mm', 'mm', 'Carriage height'),

            # Vertical rail
            ('rail_height', 'dial_pitch * 3 + 35 mm', 'mm', 'Rail height'),
            ('rail_width', '12 mm', 'mm', 'Rail width'),
            ('rail_depth', '10 mm', 'mm', 'Rail depth'),
            ('rail_center_x', 'drive_center_x + 28 mm', 'mm', 'Rail centre X'),
            ('rail_center_y', 'drive_center_y', 'mm', 'Rail centre Y'),
            ('rail_center_z', 'dial_stack_center_z', 'mm', 'Rail centre Z'),

            # Microphone
            ('mic_diameter', '36.44 mm', 'mm', 'Mic diameter'),
            ('mic_radius', 'mic_diameter / 2', 'mm', 'Mic radius'),
            ('mic_thickness', '15.13 mm', 'mm', 'Mic thickness'),
            ('mic_pad_diameter', 'mic_diameter + 4 mm', 'mm', 'Mic pad diameter'),
            ('mic_pad_thickness', '3 mm', 'mm', 'Mic pad thickness'),

            ('mic_center_x', 'lock_right_x - 12 mm', 'mm', 'Mic centre X'),
            ('mic_center_y', 'back_plate_y + dial_projection + mic_thickness / 2', 'mm', 'Mic centre Y'),
            ('mic_center_z', '6 mm', 'mm', 'Mic centre Z'),

            ('mic_arm_width', '20 mm', 'mm', 'Mic arm width'),
            ('mic_arm_thickness', '4 mm', 'mm', 'Mic arm thickness'),

            # Tension frame
            ('tension_frame_height', 'shackle_top_z + 20 mm', 'mm', 'Frame height'),
            ('tension_frame_width', 'lock_width + 55 mm', 'mm', 'Frame width'),
            ('tension_post_width', '8 mm', 'mm', 'Post width'),
            ('tension_crossbar_height', '8 mm', 'mm', 'Crossbar height'),
            ('tension_hook_diameter', '4 mm', 'mm', 'Hook diameter'),

            ('tension_center_x', '0 mm', 'mm', 'Tension X'),
            ('tension_center_y', '0 mm', 'mm', 'Tension Y'),
            ('tension_hook_z', 'shackle_top_z - 5 mm', 'mm', 'Hook Z'),

            # AD-35 mic
            ('mic_max_diameter', '36.22 mm', 'mm', 'AD35 max diameter'),
            ('mic_end_diameter', '27.51 mm', 'mm', 'AD35 end diameter'),
            ('mic_thickness', '15.13 mm', 'mm', 'AD35 thickness'),

            ('mic_center_z_from_bottom', '32.34 mm', 'mm', 'AD35 centre from lock bottom'),
            ('mic_center_x_from_right', '6 mm', 'mm', 'AD35 centre from right edge'),

            ('mic_max_radius', 'mic_max_diameter / 2', 'mm', 'AD35 max radius'),
            ('mic_end_radius', 'mic_end_diameter / 2', 'mm', 'AD35 end radius'),

            ('mic_center_z', '-lock_height / 2 + mic_center_z_from_bottom', 'mm', 'AD35 centre Z'),
            ('mic_center_x', 'lock_width / 2 - mic_center_x_from_right', 'mm', 'AD35 centre X'),

            ('mic_inner_y', 'lock_thickness / 2', 'mm', 'AD35 inner face Y'),
            ('mic_outer_y', 'lock_thickness / 2 + mic_thickness', 'mm', 'AD35 outer face Y'),
            ('mic_mid_y', 'lock_thickness / 2 + mic_thickness / 2', 'mm', 'AD35 max diameter Y'),
        ]

        for name, expr, unit, comment in params:
            set_param(design, name, expr, unit, comment)

        silent_message_box('00 parameters updated.')

    except Exception:
        if ui:
            silent_message_box(traceback.format_exc())