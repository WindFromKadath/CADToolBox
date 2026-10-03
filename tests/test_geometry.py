from math import pi
from pathlib import Path
import json
import subprocess
import sys
import cadtoolbox.geometry
import cadquery as cq
import ezdxf
import pytest
from cadtoolbox.contracts import Axis,ShapeExpectation,ShapeKind,Unit,QualityPolicy
from cadtoolbox.geometry import io
from cadtoolbox.geometry.io import load_step,export_step,load_dxf
from cadtoolbox.geometry.measure import measure,axis_candidates
from cadtoolbox.geometry.quality import GeometryError,GeometryResult,topology,validate_shape
from cadtoolbox.workflows.io_demo import run_io_demo

ONE = ShapeExpectation(ShapeKind.SOLID,1)


def save_dxf(directory, builder, units=4):
    doc=ezdxf.new('R2010');doc.units=units
    builder(doc.modelspace())
    path=directory/'input.dxf';doc.saveas(path)
    return path


def test_tilted_cylinder_exact_axis_and_radius():
    axis=Axis((12,-7,3),(1,2,3))
    shape=cq.Solid.makeCylinder(12.345,7.89,axis.origin_mm,axis.direction)
    report=measure(shape,axis)
    assert report['axial_length_mm'] == pytest.approx(7.89,abs=1e-6)
    assert report['diameter_candidates_mm'] == pytest.approx([24.69])
    assert report['volume_mm3'] == pytest.approx(pi*12.345**2*7.89,rel=1e-10)
    assert report['axial_min_mm'] == pytest.approx(0,abs=1e-6)
    assert report['axis_source'] == 'explicit argument'
    assert len(axis_candidates(shape)) == 1
    assert measure(shape)['axial_length_mm'] == pytest.approx(7.89,abs=1e-6)


def test_axis_detection_does_not_guess_box():
    box=cq.Workplane().box(2,3,4).val()
    with pytest.raises(GeometryError,match='supply an explicit axis'):
        measure(box)
    assert measure(box,Axis(direction=(0,0,1)))['axial_length_mm'] == pytest.approx(4)


def test_solid_face_and_legitimate_degenerate_edges():
    sphere=cq.Solid.makeSphere(5,angleDegrees1=-90)
    assert validate_shape(sphere,ONE)['success']
    assert topology(sphere)['degenerated_edge_count'] > 0
    with pytest.raises(GeometryError):
        validate_shape(sphere,ONE,QualityPolicy(reject_degenerated_edges=True))
    face=cq.Face.makePlane(4,5)
    assert validate_shape(face,ShapeExpectation(ShapeKind.FACE))['success']
    with pytest.raises(GeometryError):
        validate_shape(face,ONE)
    with pytest.raises(GeometryError,match='no vertices'):
        topology(cq.Compound.makeCompound([]))
    assert topology(cq.Vertex.makeVertex(0,0,0))['minimum_edge_length_mm'] is None


def test_compound_roundtrip_preserves_every_component(case_dir):
    a=cq.Workplane().box(2,3,4).val()
    b=cq.Solid.makeCylinder(2,5,(10,0,0))
    shape=cq.Compound.makeCompound([a,b])
    expected=ShapeExpectation(ShapeKind.COMPOUND,2)
    out=case_dir/'two.stp'
    report=export_step(shape,out,expected)
    assert report['success']
    loaded=load_step(out,expected)
    assert len(loaded.shape.Solids()) == 2
    assert sorted(s.Volume() for s in loaded.shape.Solids()) == pytest.approx(sorted([24,20*pi]))
    with pytest.raises(GeometryError):
        load_step(out,ONE)
    with pytest.raises(GeometryError):
        validate_shape(cq.Compound.makeCompound([a,cq.Face.makePlane(1,1)]),ShapeExpectation(ShapeKind.COMPOUND,1))
    with pytest.raises(GeometryError,match='overwrite'):
        export_step(shape,out,expected)


def test_step_header_units_and_bad_input(case_dir):
    solid=cq.Workplane().box(12,23,34).val()
    path=case_dir/'cm.step'
    cq.exporters.export(solid,str(path),exportType='STEP',unit='MM',outputUnit='CM')
    loaded=load_step(path,ONE)
    assert loaded.shape.Volume() == pytest.approx(12*23*34,rel=1e-9)
    with pytest.raises(GeometryError,match='not found'):
        load_step(case_dir/'missing.step')
    bad=case_dir/'bad.step';bad.write_text('invalid STEP',encoding='utf-8')
    with pytest.raises(GeometryError):
        load_step(bad)


@pytest.mark.parametrize('mode',['volume','bounds'])
def test_failed_roundtrip_is_not_published(case_dir,monkeypatch,mode):
    solid=cq.Workplane().box(2,3,4).val()
    original=io.load_step
    def changed(path,expected):
        result=original(path,expected)
        result.shape=result.shape.scale(2) if mode=='volume' else result.shape.translate((1,0,0))
        return result
    monkeypatch.setattr(io,'load_step',changed)
    out=case_dir/'rejected.step'
    with pytest.raises(GeometryError) as error:
        export_step(solid,out,ONE)
    assert error.value.code == 'roundtrip_mismatch'
    assert not out.exists()
    assert Path(error.value.report['failure_artifact']).is_file()


def test_dxf_circle_preserves_curve_and_scales_units(case_dir):
    path=save_dxf(case_dir,lambda m:m.add_circle((0,0),1),units=5)
    result=load_dxf(path)
    assert result.report['curve_types'] == {'CIRCLE':1}
    assert result.report['input_unit'] == 'cm'
    assert cq.Face.makeFromWires(result.wires[0]).Area() == pytest.approx(100*pi,rel=1e-10)
    with pytest.raises(GeometryError) as error:
        load_dxf(path,input_unit=Unit.MM)
    assert error.value.code == 'unit_conflict'


def test_dxf_bulge_is_not_polygonized(case_dir):
    path=save_dxf(case_dir,lambda m:m.add_lwpolyline([(-1,0,1),(1,0,1)],format='xyb',close=True))
    result=load_dxf(path)
    assert result.report['curve_types'] == {'CIRCLE':2}
    assert cq.Face.makeFromWires(result.wires[0]).Area() == pytest.approx(pi,rel=1e-10)


def test_dxf_bspline_preserved(case_dir):
    def builder(m):
        m.add_open_spline([(0,0,0),(1,0,0),(2,0,0),(3,0,0)],degree=3)
        m.add_line((3,0),(3,2));m.add_line((3,2),(0,2));m.add_line((0,2),(0,0))
    path=save_dxf(case_dir,builder)
    result=load_dxf(path)
    assert result.report['curve_types']['BSPLINE'] == 1
    assert cq.Face.makeFromWires(result.wires[0]).Area() == pytest.approx(6,abs=1e-6)


def test_dxf_ellipse_preserved(case_dir):
    path=save_dxf(case_dir,lambda m:m.add_ellipse((0,0),major_axis=(2,0,0),ratio=0.5))
    result=load_dxf(path)
    assert result.report['curve_types'] == {'ELLIPSE':1}
    assert cq.Face.makeFromWires(result.wires[0]).Area() == pytest.approx(2*pi,rel=1e-10)


def test_dxf_unsupported_entity_layer_selection_and_open_wire(case_dir):
    def builder(m):
        m.doc.layers.new('PROFILE');m.doc.layers.new('NOTES')
        m.add_circle((0,0),2,dxfattribs={'layer':'PROFILE'})
        m.add_text('not a profile',dxfattribs={'layer':'NOTES'})
    path=save_dxf(case_dir,builder)
    with pytest.raises(GeometryError) as error:
        load_dxf(path)
    assert error.value.code == 'unsupported_entity'
    assert load_dxf(path,include_layers=['profile']).report['wire_count'] == 1
    with pytest.raises(GeometryError):
        load_dxf(path,include_layers=['missing'])
    path=save_dxf(case_dir,lambda m:m.add_line((0,0),(1,0)))
    with pytest.raises(GeometryError) as error:
        load_dxf(path)
    assert error.value.code == 'open_profile'


def test_dxf_unitless_malformed_and_nonplanar(case_dir):
    path=save_dxf(case_dir,lambda m:m.add_circle((0,0),2),units=0)
    with pytest.raises(GeometryError) as error:
        load_dxf(path)
    assert error.value.code == 'unit_missing'
    assert load_dxf(path,input_unit=Unit.INCH).report['scale_to_mm'] == 25.4
    path=save_dxf(case_dir,lambda m:m.add_line((0,0),(0,0)))
    with pytest.raises(GeometryError) as error:
        load_dxf(path)
    assert error.value.code == 'dxf_conversion'
    path=save_dxf(case_dir,lambda m:m.add_circle((0,0,2),2))
    with pytest.raises(GeometryError) as error:
        load_dxf(path)
    assert error.value.code == 'dxf_plane'


def test_demo_independent_reference_and_cli_failures(case_dir):
    report=run_io_demo(case_dir/'demo')
    assert report['success'] and report['reference']['absolute_error_mm3'] < 1e-6
    assert report['profile']['curve_types'] == {'CIRCLE':1,'LINE':1}
    with pytest.raises(GeometryError):
        run_io_demo(case_dir/'demo')
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,'-m','cadtoolbox','inspect-step',str(case_dir/'missing.step')],cwd=root,capture_output=True,text=True,encoding='utf-8')
    assert result.returncode == 2
    assert json.loads(result.stdout)['code'] == 'missing_input'
    result=subprocess.run([sys.executable,'-m','cadtoolbox','demo-io','--output',str(root.parent/'outside-demo')],cwd=root,capture_output=True,text=True,encoding='utf-8')
    assert result.returncode == 2 and 'inside CADToolbox' in result.stderr


def test_face_step_roundtrip_does_not_require_volume(case_dir):
    face=cq.Face.makePlane(2,3)
    report=export_step(face,case_dir/'face.step',ShapeExpectation(ShapeKind.FACE))
    assert report['roundtrip_quality']['volume_mm3'] == 0
    assert report['roundtrip_quality']['area_mm2'] == pytest.approx(6)
