"""UV boundaries, independent analytic solids, explicit failures and fallback."""
from math import pi,sin,cos,dist
import json
from pathlib import Path
import pytest
import cadtoolbox.geometry
import cadquery as cq
from cadtoolbox.contracts import Axis,Frame,ContractError,ShapeExpectation,ShapeKind
from cadtoolbox.geometry.quality import GeometryError,integrated_volume
from cadtoolbox.geometry.parametric import RectangularBase,CoonsBase,edge_point
from cadtoolbox.geometry.theta_fields import FormulaField,SampleField,EndField,GridField,build_field
from cadtoolbox.geometry.surface_fit import FitConfig,fit_surface,rotate_point,independent_uv
from cadtoolbox.geometry.twisted_solid import SewConfig,build_twisted_solid,validate_solid_target
from cadtoolbox.geometry.io import export_step,load_step
from cadtoolbox.workflows.surfaces import run_surface_blade
FRAME=Frame(Axis());SMALL=FitConfig(initial_u=6,initial_v=8,max_u=12,max_v=16)

def base(frame=FRAME):return RectangularBase(frame,(0,10),(5,20))
def samples(a,b):return [{'v':0,'value':a},{'v':1,'value':b}]


def test_true_curved_coons_boundaries_and_permutation():
    points=[(0,5,0),(10,5,0),(10,20,0),(0,20,0)]
    edges=[cq.Edge.makeLine(points[0],points[1]),cq.Edge.makeLine(points[1],points[2]),
           cq.Edge.makeThreePointArc(points[2],(5,21,0),points[3]),cq.Edge.makeSpline([cq.Vector(*points[3]),cq.Vector(-.5,12.5,0),cq.Vector(*points[0])])]
    curve=CoonsBase([edges[2],cq.Edge(edges[0].wrapped.Reversed()),edges[3],edges[1]],FRAME,start_mm=points[0],next_mm=points[1])
    assert curve.evaluate(.5,1)==pytest.approx((5,21,0),abs=1e-9)
    assert curve.evaluate(0,.5)[0]==pytest.approx(-.5,abs=1e-8)
    assert curve.build_face().Area()>150
    assert set(curve.report['curve_types'])=={'LINE','CIRCLE','BSPLINE'}
    for u,v in [(0,.3),(1,.7),(.4,0),(.6,1)]:
        assert cq.Vertex.makeVertex(*curve.evaluate(u,v)).distance(curve.build_face())<1e-7
    with pytest.raises(GeometryError):CoonsBase(edges,FRAME,start_mm=(1,5,0),next_mm=points[1])


def test_coons_affine_uv_and_arbitrary_frame():
    frame=Frame(Axis((3,-4,7),(1,2,3)),(0,1,0))
    points=[(0,5,0),(10,6,0),(12,20,0),(1,19,0)]
    edges=[cq.Edge.makeLine(points[i],points[(i+1)%4]) for i in range(4)]
    curve=CoonsBase(edges,frame,start_mm=points[0],next_mm=points[1])
    u,v=.3,.7
    local=tuple((1-u)*(1-v)*points[0][k]+u*(1-v)*points[1][k]+u*v*points[2][k]+(1-u)*v*points[3][k] for k in range(3))
    assert curve.evaluate(u,v)==pytest.approx(frame.to_world(local))


def test_field_units_nodes_unwrap_and_gradients():
    b=base();a=FormulaField('10+2*u+3*v',b,Axis(),'degree');r=FormulaField('(10+2*u+3*v)*pi/180',b,Axis(),'radian')
    for u,v in [(0,0),(.2,.8),(1,1)]:
        assert a.evaluate(u,v)==pytest.approx(r.evaluate(u,v))
        assert a.gradient(u,v)==pytest.approx((2*pi/180,3*pi/180),abs=1e-9)
    s=SampleField([{'v':x,'value':10+3*x} for x in [0,.1,.3,1]],'degree')
    for v in [0,.1,.25,.3,.7,1]:assert s.evaluate(.5,v)==pytest.approx((10+3*v)*pi/180,abs=1e-10)
    phase=SampleField(samples(179,-179),'degree')
    assert phase.evaluate(0,1)==pytest.approx(181*pi/180)
    assert phase.evaluate(0,.5)==pytest.approx(pi)
    end=EndField(samples(10,20),samples(14,24),'degree','smoothstep')
    assert end.evaluate(.25,.4)==pytest.approx((14+4*(.25**2)*(3-2*.25))*pi/180)
    assert end.gradient(0,.4)[0]<1e-5
    assert end.evaluate(1,.4)==pytest.approx(18*pi/180)


def test_nonuniform_grid_exact_nodes_and_c1():
    us=[0,.35,1];vs=[0,.25,.6,1];values=[[7.625,9.96875,13.25,17],[6.825,9.56875,12.85,16.3],[5.625,7.96875,10.875,15]]
    field=GridField(us,vs,values)
    for i,u in enumerate(us):
        for j,v in enumerate(vs):assert field.evaluate(u,v)==pytest.approx(values[i][j]*pi/180)
    assert field.gradient(.35-1e-5,.4)[0]==pytest.approx(field.gradient(.35+1e-5,.4)[0],abs=1e-5)
    assert field.gradient(.4,.6-1e-5)[1]==pytest.approx(field.gradient(.4,.6+1e-5)[1],abs=1e-5)


@pytest.mark.parametrize('expression',["__import__('os')",'math.__dict__','u.__class__','1e309','[u,v]'])
def test_formula_rejects_unrelated_access(expression):
    with pytest.raises(ContractError):FormulaField(expression,base(),Axis())


def test_formula_failure_and_field_contracts():
    with pytest.raises(ContractError):FormulaField('1/0',base(),Axis()).evaluate(0,0)
    with pytest.raises(ContractError):SampleField(samples(1,float('nan')))
    with pytest.raises(ContractError):SampleField([{'v':0,'value':1},{'v':0,'value':2},{'v':1,'value':3}])
    with pytest.raises(ContractError):GridField([0,1],[0,1],[[1,2]])
    with pytest.raises(ContractError):GridField([0,1],[0,1],[[1,2],[3,True]])
    with pytest.raises(ContractError):FormulaField('10',base(),Axis(),'unspecified')
    with pytest.raises(ContractError):SampleField(samples(1,2)).evaluate(-.1,.5)
    with pytest.raises(ContractError):build_field({'mode':'unavailable'},base(),Axis())
    assert SampleField(samples(1,1e12)).evaluate(0,1)<4
    with pytest.raises(ContractError):SewConfig(tolerances_mm=(True,))


def test_arbitrary_axis_rotation_independent_vectors():
    axis=Axis((2,3,4),(1,1,0));p=(2,3,9);t=.3
    # Axis is (1/sqrt(2),1/sqrt(2),0); z cross rotation is (a_y,-a_x,0).
    expected=(2+5*sin(t)/2**.5,3-5*sin(t)/2**.5,4+5*cos(t))
    assert rotate_point(p,axis,t)==pytest.approx(expected)
    assert dist(rotate_point(p,axis,t),axis.origin_mm)==pytest.approx(5)


def test_validation_samples_do_not_alias_fit_inputs():
    for nu,nv in [(81,161),(160,320)]:
        pts=independent_uv(nu,nv,40,80)[:40*80]
        for u,v in pts:
            assert abs(u*(nu-1)-round(u*(nu-1)))>.4
            assert abs(v*(nv-1)-round(v*(nv-1)))>.4


def test_fit_budget_is_not_relaxed():
    b=base();field=FormulaField('10+5*sin(7*pi*v)',b,Axis())
    config=FitConfig(initial_u=4,initial_v=4,max_u=4,max_v=4,max_error_mm=1e-6,rms_error_mm=1e-7,boundary_error_mm=1e-6)
    with pytest.raises(GeometryError,match='budget') as error:fit_surface(b,field,Axis(),config)
    assert error.value.code=='surface_fit_budget'
    assert error.value.report['attempts'][-1]['limits']['max_error_mm']==1e-6


@pytest.mark.parametrize('angle,tilted',[(10,False),(-10,False),(10,True)])
def test_shared_faces_analytic_volume_step_and_frame(tmp_path,angle,tilted):
    frame=Frame(Axis((3,-4,7),(1,2,3)),(0,1,0)) if tilted else FRAME
    b=base(frame);field=FormulaField(str(angle),b,frame.axis)
    result=build_twisted_solid(b,field,frame.axis,SMALL)
    # Source constructs straight corner connectors, so a chordal trapezoid
    # yields sin(theta), rather than circular-sector area proportional to theta.
    expected=10*(20**2-5**2)*abs(sin(angle*pi/180))/2
    assert integrated_volume(result.shape)==pytest.approx(expected,rel=1e-8)
    assert result.report['quality']['free_edge_count']==0
    assert result.report['quality']['degenerated_edge_count']==0
    assert result.report['construction_method']=='six_shared_faces'
    expected_shape=ShapeExpectation(ShapeKind.SOLID,1)
    exported=export_step(result.shape,tmp_path/'solid.step',expected_shape)
    assert exported['success']
    reread=load_step(tmp_path/'solid.step',expected_shape)
    assert integrated_volume(reread.shape)==pytest.approx(expected,rel=1e-8)
    assert validate_solid_target(reread.shape,b,field,frame.axis,SMALL)['success']


def test_radius_theta_and_collapsed_faces_fail():
    b=base()
    for expr in ['0','-1+2*v','181']:
        with pytest.raises(GeometryError):build_twisted_solid(b,FormulaField(expr,b,Axis()),Axis(),SMALL)
    with pytest.raises(GeometryError):build_twisted_solid(b,FormulaField('10',b,Axis()),Axis(),SMALL,min_axis_radius_mm=6)
    with pytest.raises(ContractError):FitConfig(initial_u=3)
    with pytest.raises(ContractError):SewConfig(tolerances_mm=(.01,),max_tolerance_mm=.001)
    with pytest.raises(ContractError):build_twisted_solid(b,FormulaField('10',b,Axis()),Axis(),SMALL,allow_loft_fallback='true')


def test_actual_faces_validation_detects_wrong_solid():
    b=base();field=FormulaField('10',b,Axis());result=build_twisted_solid(b,field,Axis(),SMALL)
    with pytest.raises(GeometryError,match='budget'):validate_solid_target(result.shape.translate((0,0,2)),b,field,Axis(),SMALL)


def test_loft_requires_permission_and_uses_every_u(monkeypatch):
    import cadtoolbox.geometry.twisted_solid as mod
    b=base();field=FormulaField('10+u+v',b,Axis())
    def failed(*args,**kwargs):raise GeometryError('forced_shared_face_failure','explicit failure fixture')
    monkeypatch.setattr(mod,'build_all_side_faces',failed)
    with pytest.raises(GeometryError,match='not permitted'):build_twisted_solid(b,field,Axis(),SMALL)
    result=build_twisted_solid(b,field,Axis(),SMALL,SewConfig(loft_sections=9,loft_curve_samples=31),allow_loft_fallback=True)
    assert result.report['construction_method']=='multi_section_loft_fallback'
    assert result.report['geometry_changed_by_fallback'] is True
    assert result.report['construction_failures'][0]['code']=='forced_shared_face_failure'
    assert result.report['constructed_target_validation']['success']
    # u=1 is one degree different from u=0; reusing only the end law would
    # miss target faces by much more than the configured .001 mm budget.
    assert abs(field.evaluate(1,.5)-field.evaluate(0,.5))==pytest.approx(pi/180)


def test_unsupported_step_base_retains_failure(tmp_path):
    config={'schema_version':1,'unit':'mm','frame':{'axis':{'origin_mm':[0,0,0],'direction':[1,0,0]},'radial_reference':[0,1,0]},'base':{'mode':'step_face'}}
    path=tmp_path/'config.json';path.write_text(json.dumps(config),encoding='utf-8')
    with pytest.raises(GeometryError) as error:run_surface_blade(path,tmp_path/'output')
    assert error.value.code=='unsupported_step_base'
    report=json.loads((tmp_path/'output/report.json').read_text(encoding='utf-8'))
    assert report['success'] is False
    assert report['failure']['code']=='unsupported_step_base'


def test_curved_coons_solid_preserves_actual_base(tmp_path):
    points=[(0,5,0),(10,5,0),(10,20,0),(0,20,0)]
    edges=[cq.Edge.makeLine(points[0],points[1]),cq.Edge.makeLine(points[1],points[2]),cq.Edge.makeThreePointArc(points[2],(5,21,0),points[3]),cq.Edge.makeLine(points[3],points[0])]
    b=CoonsBase(edges,FRAME,start_mm=points[0],next_mm=points[1]);field=FormulaField('10',b,Axis())
    result=build_twisted_solid(b,field,Axis(),FitConfig(initial_u=12,initial_v=8,max_u=24,max_v=16))
    assert result.report['quality']['valid']
    assert result.report['quality']['free_edge_count']==0
    assert 'CIRCLE' in result.report['quality']['curve_types']
    assert cq.Vertex.makeVertex(5,21,0).distance(result.shape)<1e-7
    exported=export_step(result.shape,tmp_path/'curved.step',ShapeExpectation(ShapeKind.SOLID,1))
    assert exported['success']
