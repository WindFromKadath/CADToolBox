"""Real native DOF/status, parameter driving, isolation and independent CAD."""
from copy import deepcopy
from math import pi,dist
from pathlib import Path
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
import cadtoolbox.geometry
from cadtoolbox.contracts import ContractError,Axis,Frame
from cadtoolbox.solver.model import normalize_sketch,drive_dimensions
from cadtoolbox.solver.sketch import solve_sketch
from cadtoolbox.workflows.solved_profile import build_profile,run_solved_profile
from cadtoolbox.geometry.quality import GeometryError,integrated_volume
from cadtoolbox.geometry.io import load_dxf
ROOT=Path(__file__).resolve().parents[1]

def config(name='case'):return json.loads((ROOT/('configs/solver-'+name+'.json')).read_text(encoding='utf-8'))
def parameter(name,value,unit='mm'):return {'name':name,'value':value,'unit':unit,'source':'independent solver test dimension','status':'derived'}


def test_real_fully_determined_rectangle_moves_seed():
    c=config();result=solve_sketch(c['sketch'])
    assert result['success'] and result['geometry_eligible']
    assert result['status']=='fully_determined'
    assert result['raw_result']=={'result':0,'dof':0,'nbad':0}
    assert result['solved_points_mm']=={'BL':[0,0],'BR':[100,0],'TR':[100,60],'TL':[0,60]}
    assert result['solved_points_mm']['BR']!=c['sketch']['points'][1]['initial_mm']
    assert result['residuals']['max_error_mm']<1e-9
    assert result['isolation']['reference_entity_types']=={'origin':50000,'normal':60000,'workplane':80000}
    face,solid,report=build_profile(result,c['geometry'])
    assert face.Area()==pytest.approx(6000)
    assert integrated_volume(solid)==pytest.approx(48000)
    assert report['outline_points_mm'][1]==[100,0]


def test_under_constrained_returns_real_dof_and_blocks_geometry():
    c=config('under-case');result=solve_sketch(c['sketch'])
    assert result['raw_result']['result']==0
    assert result['raw_result']['dof']==1
    assert result['status']=='under_constrained'
    assert result['success'] is False
    with pytest.raises(GeometryError,match='fully determined'):build_profile(result,c['geometry'])


def test_inconsistent_native_handles_map_to_source_constraint_ids():
    c=config('conflict-case');result=solve_sketch(c['sketch'])
    assert result['raw_result']['result']==1
    assert result['status']=='inconsistent'
    assert result['raw_result']['nbad']==2
    assert set(result['failed_constraint_ids'])=={'width','conflicting-width'}
    assert result['geometry_eligible'] is False
    with pytest.raises(GeometryError):build_profile(result,c['geometry'])


def test_redundant_is_explicit_and_does_not_publish():
    c=config();duplicate=deepcopy(c['sketch']['constraints'][-2]);duplicate['id']='duplicate-width'
    c['sketch']['constraints'].append(duplicate);r=solve_sketch(c['sketch'])
    assert r['backend_result_name']=='REDUNDANT_OKAY'
    assert r['raw_result']['dof']==0
    assert r['status']=='redundant' and not r['geometry_eligible']
    assert set(r['failed_constraint_ids'])=={'width','duplicate-width'}


def test_driving_dimensions_changes_constraints_not_initial_guesses():
    c=config();s=drive_dimensions(c['sketch'],{'width':parameter('width',150),'height':parameter('height',80)})
    assert s['points']==c['sketch']['points']
    assert c['sketch']['constraints'][-2]['parameter']['value']==100
    r=solve_sketch(s)
    assert r['success'] and r['solved_points_mm']['TR']==pytest.approx([150,80])
    _,solid,_=build_profile(r,c['geometry'])
    assert integrated_volume(solid)==pytest.approx(150*80*8)
    with pytest.raises(ContractError):drive_dimensions(s,{'origin':parameter('datum',2)})


def test_dimension_unit_conversion_has_same_physical_geometry():
    s=drive_dimensions(config()['sketch'],{'width':parameter('width',12,'cm'),'height':parameter('height',.08,'m')})
    r=solve_sketch(s)
    assert r['success'] and r['solved_points_mm']['TR']==pytest.approx([120,80])


def test_real_circle_parameters_and_disjoint_hole_volume():
    c=config('hole-case');r=solve_sketch(c['sketch'])
    assert r['raw_result']=={'result':0,'dof':0,'nbad':0}
    assert r['solved_radii_mm']==pytest.approx({f'hole-{i}':3 for i in range(1,5)})
    assert r['solved_points_mm']['center-1']==pytest.approx([25,20])
    face,solid,report=build_profile(r,c['geometry'])
    area=120*80-4*pi*3**2
    assert face.Area()==pytest.approx(area,rel=1e-10)
    assert integrated_volume(solid)==pytest.approx(area*8,rel=1e-10)
    assert report['hole_circles']['hole-1']['radius_mm']==3


@pytest.mark.parametrize('kind',['parallel','perpendicular'])
def test_line_pair_equal_length_and_orientation(kind):
    s={'schema_version':1,'unit':'mm','points':[{'id':k,'initial_mm':v} for k,v in [('A',[0,0]),('B',[7,1]),('C',[0,20]),('D',[8,22] if kind=='parallel' else [1,28])]],
       'lines':[{'id':'L1','start':'A','end':'B'},{'id':'L2','start':'C','end':'D'}],'constraints':[
           {'id':'fixA','kind':'fixed_point','point':'A','datum':{'xy_mm':[0,0],'source':'test datum','status':'derived'}},
           {'id':'fixC','kind':'fixed_point','point':'C','datum':{'xy_mm':[0,20],'source':'test datum','status':'derived'}},
           {'id':'horizontal','kind':'horizontal','line':'L1'},
           {'id':'length','kind':'distance','a':'A','b':'B','parameter':parameter('length',10)},
           {'id':'eq','kind':'equal_length','a':'L1','b':'L2'},{'id':'orient','kind':kind,'a':'L1','b':'L2'}]}
    r=solve_sketch(s);assert r['success']
    p=r['solved_points_mm'];a=[p['B'][i]-p['A'][i] for i in range(2)];b=[p['D'][i]-p['C'][i] for i in range(2)]
    assert dist(p['C'],p['D'])==pytest.approx(10)
    if kind=='parallel':assert a[0]*b[1]-a[1]*b[0]==pytest.approx(0,abs=1e-8)
    else:assert a[0]*b[0]+a[1]*b[1]==pytest.approx(0,abs=1e-8)


def test_coincident_is_solved_not_counted():
    s={'schema_version':1,'unit':'mm','points':[{'id':'a','initial_mm':[0,0]},{'id':'b','initial_mm':[1,2]}],'constraints':[
       {'id':'datum','kind':'fixed_point','point':'a','datum':{'xy_mm':[0,0],'source':'test datum','status':'derived'}},
       {'id':'join','kind':'coincident','a':'a','b':'b'}]}
    r=solve_sketch(s)
    assert r['raw_result']['dof']==0 and r['success']
    assert r['solved_points_mm']['a']==r['solved_points_mm']['b']==[0,0]


def test_concurrent_solves_are_independent_native_processes():
    a=config()['sketch'];b=drive_dimensions(a,{'width':parameter('width',25),'height':parameter('height',17)})
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(solve_sketch,[a,b]))
    assert all(r['success'] for r in results)
    assert results[0]['isolation']['process_id']!=results[1]['isolation']['process_id']
    assert results[0]['solved_points_mm']['TR']==[100,60]
    assert results[1]['solved_points_mm']['TR']==[25,17]


@pytest.mark.parametrize('fault',['unknown_constraint','unknown_entity','duplicate_id','nan','boolean','unapproved','collapsed','unknown_field'])
def test_invalid_or_unapproved_inputs_are_rejected(fault):
    s=config()['sketch']
    if fault=='unknown_constraint':s['constraints'][1]['kind']='tangent'
    elif fault=='unknown_entity':s['lines'][0]['start']='missing'
    elif fault=='duplicate_id':s['points'][1]['id']=s['points'][0]['id']
    elif fault=='nan':s['points'][0]['initial_mm'][0]=float('nan')
    elif fault=='boolean':s['constraints'][-1]['parameter']['value']=True
    elif fault=='unapproved':s['constraints'][-1]['parameter']['status']='assumed'
    elif fault=='collapsed':s['points'][1]['initial_mm']=list(s['points'][0]['initial_mm'])
    else:s['constraints'][0]['unrecognized']='silently ignored would be wrong'
    with pytest.raises(ContractError):normalize_sketch(s)


def test_unsolved_workflow_keeps_report_and_has_no_geometry(tmp_path):
    c=config('under-case');c['source_parameter_references']=[];path=tmp_path/'under.json';path.write_text(json.dumps(c),encoding='utf-8')
    with pytest.raises(GeometryError) as e:run_solved_profile(path,tmp_path/'output')
    assert e.value.code=='sketch_not_determined'
    report=json.loads((tmp_path/'output/report.json').read_text(encoding='utf-8'))
    assert report['success'] is False and report['stages']['solver']['raw_result']['dof']==1
    assert not list((tmp_path/'output').glob('*.step')) and not list((tmp_path/'output').glob('*.dxf'))


def test_tilted_frame_and_hole_dxf_use_solved_values(tmp_path):
    c=config('hole-case');c['source_parameter_references']=[]
    c['geometry']['frame']={'axis':{'origin_mm':[3,-4,7],'direction':[1,2,3]},'radial_reference':[0,1,0]}
    path=tmp_path/'holes.json';path.write_text(json.dumps(c),encoding='utf-8');r=run_solved_profile(path,tmp_path/'output')
    assert r['success']
    expected=(120*80-4*pi*3**2)*8
    assert r['stages']['solid_step']['input_quality']['volume_mm3']==pytest.approx(expected,rel=1e-9)
    dxf=load_dxf(Path(r['outputs']['dxf']));assert len(dxf.wires)==5
    assert dxf.report['curve_types']=={'LINE':4,'CIRCLE':4}
    assert r['stages']['geometry']['outline_points_mm'][1]==[120,0]
    assert r['stages']['geometry']['hole_circles']['hole-4']=={'center_mm':[95,60],'radius_mm':3}


def test_holes_outside_and_unselected_geometry_are_not_dropped():
    c=config('hole-case');c['sketch']['constraints'][-2]['datum']['xy_mm']=[140,60]
    r=solve_sketch(c['sketch']);assert r['success']
    with pytest.raises(GeometryError):build_profile(r,c['geometry'])
    c=config('hole-case');r=solve_sketch(c['sketch']);c['geometry']['hole_circles']=[]
    with pytest.raises(ContractError,match='explicitly used'):build_profile(r,c['geometry'])
