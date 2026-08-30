# Print-layout source dependencies

`15_Print_Layout` reconstructs the minimum assembly needed to generate the printable moving-base geometry before copying bodies into the print layout.

Generation order:

1. `00_Lock_Parameters.py`
2. `01_Passive_Shaft_Support.py`
3. `02_Padlock_Reference.py`
4. `03_Drive_Head.py`
5. `04_X_Axis_Linear_Rail.py`
6. `05_MG92B_Servo_Reference.py`
7. `07_Drive_Head_Mounting_Base_and_Limiters.py`
8. `10_O_Ring_Press_Wheel_Hub.py`
9. `11_Swing_Arm.py`

The 02/03/04/05/07/10/11 modules remain the local snapshots used by the print-layout workflow. P7.5 adds canonical 00 parameters and the passive support because the previous print-only path started directly at the padlock reference and could therefore use stale fallback dimensions. The only adaptation in the added 00/01 copies is routing status/error messages through the parent script's silent-message hook.
