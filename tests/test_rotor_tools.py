from math import pi,sqrt,sin,hypot
import json,subprocess,sys
from pathlib import Path
import pytest
import cadtoolbox.geometry
import cadquery as cq
from cadtoolbox.contracts import Axis,Frame,Thickness,ContractError
from cadtoolbox.geometry.quality import GeometryError
from cadtoolbox.geometry.blades import CircleLaw,ThetaLaw,build_radial_blade,extreme_chord_thickness
from cadtoolbox.geometry.domains import (closed_profile,axisymmetric_channel,projected_channel,material_domain,trim_solid,trim_bspline_face)
from cadtoolbox.geometry.assembly import (Component,fuse_components,circular_pattern,assemble_unique,fillet_two_end_rotor,extract_rounded_blade)
from cadtoolbox.geometry.transforms import transform_shape

FRAME=Frame(Axis())


def test_circle_intersection_and_handedness():
    for r in [105.95,153,200]:
        positive=CircleLaw(155.8,68.4,1).point(r)
        negative=CircleLaw(155.8,68.4,-1).point(r)
        assert hypot(*positive)==pytest.approx(r)
        assert hypot(positive[0],positive[1]-68.4)==pytest.approx(155.8)
        assert negative==pytest.approx((-positive[0],positive[1]))
    with pytest.raises(ContractError):CircleLaw(155.8,68.4,1).point(5)


@pytest.mark.parametrize('args',[(10,0,1),(10,2,True),(float('nan'),2,1)])
def test_invalid_circle_law(args):
    with pytest.raises(ContractError):CircleLaw(*args)


@pytest.mark.parametrize('kind',['chord','arc_length'])
def test_chord_arc_and_analytic_prism_volume(kind):
    thickness=Thickness(6,kind)
    law=ThetaLaw(10,20,0,0)
    blade=build_radial_blade(FRAME,(0,5),(10,20),thickness,law)
    actual=extreme_chord_thickness(blade.solid,FRAME)
    for label,r in [('inner',10),('outer',20)]:
        expected=6 if kind=='chord' else 2*r*sin(6/(2*r))
        assert actual[label]['chord_mm']==pytest.approx(expected,abs=1e-6)
    if kind=='chord':
        assert blade.report['side_construction']=='exact constant-theta chord lines'
        # Constant chord and zero theta produces two straight parallel sides.
        independent=6*(sqrt(20**2-3**2)-sqrt(10**2-3**2))*5
        assert blade.solid.Volume()==pytest.approx(independent,rel=1e-8)


def test_theta_interpolation_clamping_and_bad_inputs():
    law=ThetaLaw(10,20,0.2,0.8,exponent=2,linear_blend=0.5)
    assert law.theta(15)==pytest.approx(0.2+0.6*(0.5*0.5+0.5*0.5**2))
    assert law.theta(5)==0.2 and law.theta(30)==pytest.approx(0.8)
    with pytest.raises(ContractError):ThetaLaw(10,9,0,1)
    with pytest.raises(ContractError):ThetaLaw(10,20,0,1,linear_blend=1.1)
    with pytest.raises(ContractError):build_radial_blade(FRAME,(0,5),(10,20),Thickness(2,'normal'),law)
    with pytest.raises(ContractError):build_radial_blade(FRAME,(0,5),(10,20),Thickness(20,'chord'),law)
    with pytest.raises(ContractError):build_radial_blade(FRAME,(0,5),(10,20),Thickness(2,'chord'),law,samples=True)


def test_fit_limit_is_not_silently_relaxed():
    with pytest.raises(GeometryError) as error:
        build_radial_blade(FRAME,(0,5),(95.95,210),Thickness(10,'chord'),CircleLaw(155.8,68.4,1),samples=4,fit_tolerance_mm=1e-8)
    assert error.value.code=='blade_fit'


def test_frame_rotation_preserves_blade_dimensions():
    tilted=Frame(Axis((7,-3,2),(1,2,3)),(0,1,0))
    law=ThetaLaw(10,20,-0.3,0.5)
    base=build_radial_blade(FRAME,(2,7),(10,20),Thickness(2,'chord'),law)
    moved=build_radial_blade(tilted,(2,7),(10,20),Thickness(2,'chord'),law)
    assert moved.solid.Volume()==pytest.approx(base.solid.Volume(),rel=1e-9)
    assert extreme_chord_thickness(moved.solid,tilted)['inner']['chord_mm']==pytest.approx(2,abs=1e-6)
    restored=transform_shape(transform_shape(base.solid,tilted),tilted,to_local=True)
    assert restored.distance(base.solid)<1e-8


def test_revolve_annulus_and_exact_projected_circle():
    profile=closed_profile([(0,2),(5,2),(5,4),(0,4)],mode='polyline')
    domain=axisymmetric_channel(profile,FRAME,source='analytic annulus')
    assert domain.shape.Volume()==pytest.approx(pi*(4**2-2**2)*5,rel=1e-10)
    circle=cq.Wire.assembleEdges([cq.Edge.makeCircle(2,dir=(1,0,0))])
    tilted=Frame(Axis((7,-3,2),(1,2,3)),(0,1,0))
    extrusion=projected_channel(circle,(1,7),tilted,source='analytic circle')
    assert extrusion.shape.Volume()==pytest.approx(pi*2**2*6,rel=1e-10)
    assert extrusion.spec.kind.value=='projected_extrusion'
    assert domain.spec.kind.value=='axisymmetric_meridional'


def test_periodic_profile_and_invalid_ordered_inputs():
    wire=closed_profile([(0,2),(2,3),(0,4),(-2,3)])
    assert wire.IsClosed() and wire.Edges()[0].geomType()=='BSPLINE'
    assert axisymmetric_channel(wire,FRAME,source='periodic profile').shape.Volume()>0
    for points in [[(0,0),(0,0),(1,1)],[(0,0),(1,float('nan')),(2,2)]]:
        with pytest.raises(ContractError):closed_profile(points)
    with pytest.raises(ContractError):axisymmetric_channel(closed_profile([(0,-2),(3,-2),(3,-1),(0,-1)],mode='polyline'),FRAME,source='negative radius')
    xy=cq.Wire.assembleEdges([cq.Edge.makeCircle(2)])
    with pytest.raises(ContractError):projected_channel(xy,(0,5),FRAME,source='wrong plane')


def test_trim_retains_all_solids_and_reports_empty():
    source=cq.Workplane().box(10,4,4).val()
    boxes=[cq.Workplane().box(2,2,2).val().translate((x,0,0)) for x in [-3,3]]
    domain=material_domain(cq.Compound.makeCompound(boxes),FRAME,source='two disjoint boxes')
    result=trim_solid(source,domain)
    assert len(result.parts)==2
    assert sorted(s.Volume() for s in result.parts)==pytest.approx([8,8])
    assert all(item['outside_measure']==0 for item in result.report['parts'])
    with pytest.raises(GeometryError):result.require_one()
    far=material_domain(boxes[0].translate((100,0,0)),FRAME,source='no overlap')
    empty=trim_solid(source,far)
    assert empty.report['status']=='empty' and empty.parts==()
    with pytest.raises(GeometryError):empty.require_one()


def test_bspline_supporting_surface_and_all_components():
    face=cq.Face.makeSplineApprox([[cq.Vector(x,y,0.02*x*y) for y in [-3,0,3]] for x in [-5,0,5]],tol=1e-6)
    boxes=[cq.Workplane().box(2,2,4).val().translate((x,0,0)) for x in [-3,3]]
    domain=material_domain(cq.Compound.makeCompound(boxes),FRAME,source='two windows')
    result=trim_bspline_face(face,domain)
    assert len(result.parts)==2 and all(p.geomType()=='BSPLINE' for p in result.parts)
    assert all(item['outside_measure']<1e-8 for item in result.report['parts'])
    with pytest.raises(ContractError):trim_bspline_face(cq.Face.makePlane(3,3),domain)


def test_pattern_arbitrary_axis_count_one_and_interference():
    frame=Frame(Axis((7,-3,2),(1,2,3)),(0,1,0))
    block=transform_shape(cq.Workplane().box(1,1,1).val().translate((0,5,0)),frame)
    copies,report=circular_pattern(block,frame.axis,4)
    assert report['count']==4 and len(report['relative_pitch_distances_mm'])==3
    for copy in copies:
        _,y,z=frame.to_local(copy.Center().toTuple())
        assert hypot(y,z)==pytest.approx(5,abs=1e-8)
        assert copy.Volume()==pytest.approx(1)
    _,one=circular_pattern(block,frame.axis,1)
    assert one['relative_pitch_distances_mm']==[]
    with pytest.raises(ContractError):circular_pattern(block,frame.axis,0)
    with pytest.raises(ContractError):circular_pattern(block,frame.axis,True)
    with pytest.raises(GeometryError) as error:circular_pattern(cq.Workplane().box(1,1,1).val(),Axis(),4)
    assert error.value.code=='pattern_interference'


def test_union_independent_volume_and_partial_fusion():
    a=cq.Workplane().box(2,2,2).val().translate((-0.5,0,0))
    b=cq.Workplane().box(2,2,2).val().translate((0.5,0,0))
    result=fuse_components([Component('A','shell',a),Component('B','blade',b)])
    assert result.shape.Volume()==pytest.approx(12)
    assert result.report['overlap_volume_mm3']==pytest.approx(4)
    with pytest.raises(GeometryError) as error:
        fuse_components([Component('A','shell',a),Component('B','blade',b.translate((10,0,0)))])
    assert error.value.code=='partial_fusion' and error.value.report['status']=='partial'
    assert error.value.report['result_solid_count']==2


def test_duplicate_components_missing_contact_and_unsupported_fillet():
    a=cq.Workplane().box(2,2,2).val()
    with pytest.raises(ContractError):fuse_components([Component('A','shell',a),Component('A','blade',a.copy())])
    with pytest.raises(ContractError):fuse_components([Component('A','shell',a),Component('B','blade',a)])
    with pytest.raises(GeometryError):assemble_unique([Component('A','shell',a),Component('B','blade',a.translate((10,0,0)))])
    with pytest.raises(GeometryError) as error:
        fillet_two_end_rotor(a,FRAME,low_radius_mm=1,high_radius_mm=1,expected_semantic_candidates=12,expected_low_edges=4,expected_high_edges=4)
    assert error.value.code=='rotor_fillet'
    shell=cq.Workplane().box(0.5,3,3).val()
    with pytest.raises(GeometryError):extract_rounded_blade(a,[shell])


def test_rotor_cli_output_scope(case_dir):
    root=Path(__file__).resolve().parents[1]
    p=subprocess.run([sys.executable,'-m','cadtoolbox','build-rotor',str(root/'configs/rotor-case.json'),'--output',str(root.parent/'outside-rotor')],capture_output=True,text=True,encoding='utf-8')
    assert p.returncode==2 and 'inside CADToolbox' in p.stderr


def test_adaptive_mass_analytic_sphere_and_face():
    from cadtoolbox.geometry.quality import integrated_volume,integrated_area,topology
    sphere=cq.Workplane().sphere(2).val()
    assert integrated_volume(sphere)==pytest.approx(4*pi*2**3/3,rel=1e-11)
    assert integrated_area(sphere)==pytest.approx(4*pi*2**2,rel=1e-11)
    face=cq.Face.makeFromWires(cq.Wire.assembleEdges([cq.Edge.makeCircle(2)]))
    assert topology(face)['volume_mm3']==0 and integrated_area(face)==pytest.approx(pi*4)
    with pytest.raises(GeometryError):integrated_volume(face)


def test_checkpoint_scope_and_strict_audit_remain_separate(case_dir,monkeypatch):
    from cadtoolbox.workflows.checkpoints import export_checkpoint
    from cadtoolbox.geometry.io import export_step
    from cadtoolbox.contracts import ShapeExpectation,ShapeKind
    expected=ShapeExpectation(ShapeKind.SOLID,1)
    source=cq.Workplane().box(2,2,2).val()
    # Export a structurally valid but differently sized shape. Source checkpoint
    # structure and generic metric equality have intentionally distinct scopes.
    original=cq.exporters.export
    def changed(shape,path,**kw):return original(cq.Workplane().box(3,3,3).val(),path,**kw)
    monkeypatch.setattr(cq.exporters,'export',changed)
    checkpoint=export_checkpoint(source,case_dir/'source-checkpoint.step',expected,source_policy=True)
    assert checkpoint.report['success'] is True
    assert checkpoint.report['generic_strict_io_audit']['success'] is False
    assert checkpoint.shape.Volume()==pytest.approx(27)
    with pytest.raises(GeometryError) as error:export_step(source,case_dir/'generic-strict.step',expected)
    assert error.value.code=='roundtrip_mismatch'
    with pytest.raises(GeometryError):export_checkpoint(source,case_dir/'implicit.step',expected)
    with pytest.raises(GeometryError):export_checkpoint(source,case_dir/'source-checkpoint.step',expected,source_policy=True)


def test_axis_cylinder_face_count_and_explicit_grouped_union():
    from cadtoolbox.geometry.measure import count_axis_cylinder_faces
    frame=Frame(Axis((7,-3,2),(1,2,3)),(0,1,0))
    cylinder=transform_shape(cq.Solid.makeCylinder(2,5,dir=(1,0,0)),frame)
    assert count_axis_cylinder_faces(cylinder,frame.axis,2)['face_count']==1
    assert count_axis_cylinder_faces(cylinder,Axis(),2)['face_count']==0
    a=cq.Workplane().box(2,2,2).val().translate((-0.5,0,0))
    b=cq.Workplane().box(2,2,2).val().translate((0.5,0,0))
    result=fuse_components([Component('A','shell',a),Component('B','blade',b)],base_role='shell',unify_tolerance_mm=None)
    assert result.report['fused_volume_mm3']==pytest.approx(12)
    assert result.report['base_role']=='shell' and result.report['unify_tolerance_mm'] is None


def test_periodic_cylinder_seam_is_not_a_thickness_side():
    domain=axisymmetric_channel(closed_profile([(1,5),(3,5),(3,15),(1,15)],mode='polyline'),FRAME,source='annular channel with periodic seams')
    blank=build_radial_blade(FRAME,(0,4),(4,16),Thickness(2,'chord'),ThetaLaw(5,15,0,0))
    trimmed=trim_solid(blank.solid,domain).require_one()
    measurement=extreme_chord_thickness(trimmed,FRAME)
    for name,r in [('inner',5),('outer',15)]:
        assert measurement[name]['radius_mm']==pytest.approx(r,abs=1e-6)
        assert measurement[name]['chord_mm']==pytest.approx(2,abs=1e-6)
        assert measurement[name]['method']=='axial side-face endpoints'


def test_explicit_mass_policy_is_validated_and_default_preserved():
    a=cq.Workplane().box(2,2,2).val()
    items=[Component('A','shell',a)]
    assert fuse_components(items).report['volume_relative_tolerance']==1e-8
    assert fuse_components(items,volume_rel=1e-7,unify_volume_rel=1e-7).report['unify_volume_relative_tolerance']==1e-7
    for value in [0,-1,float('nan'),True]:
        with pytest.raises(ContractError):fuse_components(items,volume_rel=value)
