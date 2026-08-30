# CAD and Fusion 360 source

`fusion_scripts/` contains the parameterised Fusion 360 project scripts. The numbering records geometric dependency rather than an arbitrary file list.

A typical rebuild starts with `00_Lock_Parameters` and then executes only the components required by the target assembly or print layout. Integrated scripts under `14_Integrated_Base` and `15_Print_Layout` include dependency copies required by those workflows.

`Mechanical_system_geometry.f3d` is the archived integrated Fusion design supplied with the dissertation source materials.

The `3D_print/` directory contains exported STL files supplied with the final CAD archive.
