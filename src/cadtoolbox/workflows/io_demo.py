"""Independent analytic reference: cm DXF semicircle -> mm solid -> STEP."""
from pathlib import Path
from math import pi
import cadtoolbox.geometry  # Scope caches before loading external backends.
import cadquery as cq
import ezdxf
from ..contracts import ShapeExpectation, ShapeKind
from ..geometry.io import export_step, load_dxf
from ..geometry.quality import GeometryError


def run_io_demo(directory: Path) -> dict:
    directory = Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    dxf = directory/'semicircle-cm.dxf'
    step = directory/'semicircle-prism.step'
    if dxf.exists() or step.exists():
        raise GeometryError('output_exists','demo requires a new output directory')
    doc = ezdxf.new('R2010')
    doc.units = 5  # centimetres; radius 1 cm becomes 10 mm.
    msp = doc.modelspace()
    msp.add_arc((0,0),1,0,180)
    msp.add_line((-1,0),(1,0))
    doc.saveas(dxf)
    profile = load_dxf(dxf)
    solid = cq.Solid.extrudeLinear(profile.wires[0],[],(0,0,8))
    reference_volume = pi*10**2/2*8
    reference_error = abs(solid.Volume()-reference_volume)
    if reference_error > 1e-6:
        raise GeometryError('reference_mismatch','DXF prism disagrees with analytic reference')
    io = export_step(solid,step,ShapeExpectation(ShapeKind.SOLID,1))
    return {'success':True,'profile':profile.report,'step':io,'reference':{
        'formula':'pi * (10 mm)^2 / 2 * 8 mm','volume_mm3':reference_volume,
        'actual_volume_mm3':solid.Volume(),'absolute_error_mm3':reference_error}}
