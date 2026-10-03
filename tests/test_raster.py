"""E007 independent references, input bounds and candidate status gates."""
from copy import deepcopy
from pathlib import Path
from math import pi,dist,sin,cos,radians
import hashlib,json,xml.etree.ElementTree as ET
import numpy as np
from PIL import Image,ImageDraw
import pytest
from cadtoolbox.contracts import Parameter,ContractError,ShapeExpectation,ShapeKind,Frame,Axis
from cadtoolbox.geometry.quality import GeometryError,integrated_volume
from cadtoolbox.geometry.io import load_step
from cadtoolbox.raster.config import CalibrationConfig,ImageConfig,GeometryConfig,RegionConfig,settings
from cadtoolbox.raster.profiles import extract_raster_profile
from cadtoolbox.raster.regions import extract_three_region_profiles
from cadtoolbox.raster.primitives import PrimitiveExtractionConfig,extract_primitives,_thin,_classify_chains,export_primitive_svg
from cadtoolbox.workflows.raster import run_raster
ROOT=Path(__file__).resolve().parents[1]


def parameter(n,v,unit='mm',status='derived'):
    return Parameter(n,v,unit,'independent controlled raster test',status)

def calibration(mode='foreground_bbox',bounds=(0,20,10,30),unit='mm'):
    return CalibrationConfig(mode,*(parameter(n,v,unit) for n,v in zip(['x_min','x_max','r_min','r_max'],bounds)))

def rectangle(root,box=(10,20,90,80),size=(101,101),name='input.png'):
    image=Image.new('RGB',size,'white');ImageDraw.Draw(image).rectangle(box,fill='black');path=root/name;image.save(path);return path


def config_for(image,mode='single'):
    c=json.loads((ROOT/('configs/raster-'+('single' if mode=='single' else 'three-regions')+'-case.json')).read_text(encoding='utf-8'))
    c['image_input']={'path':str(image),'sha256':hashlib.sha256(image.read_bytes()).hexdigest()};c.pop('source_parameter_references')
    c['profile_settings']['calibration']={'mode':'foreground_bbox' if mode=='single' else 'image_bbox',**{n:{'name':n,'value':v,'unit':'mm','source':'independent test','status':'derived'} for n,v in zip(['x_min','x_max','r_min','r_max'],[0,20,10,30])}}
    c['profile_settings']['geometry']={'simplify_tolerance_px':0,'minimum_profile_area_mm2':1e-6}
    return c


def run_config(root,c,*,name='run',candidates=False):
    p=root/(name+'.json');p.write_text(json.dumps(c),encoding='utf-8');return run_raster(p,root/name,candidates=candidates)


def test_bbox_modes_and_units(case_dir):
    path=rectangle(case_dir);geo=GeometryConfig(0,1)
    fg=extract_raster_profile(path,ImageConfig(),calibration(),geo)
    full=extract_raster_profile(path,ImageConfig(),calibration('image_bbox'),geo)
    cm=extract_raster_profile(path,ImageConfig(),calibration(bounds=(0,2,1,3),unit='cm'),geo)
    assert {(0,10),(0,30),(20,10),(20,30)}.issubset(fg.points_xr_mm)
    assert all(x in [0,20] and 10<=r<=30 for x,r in fg.points_xr_mm)
    assert len(fg.points_xr_mm)==122  # zero tolerance retains all 61 points per side
    assert min(x for x,r in full.points_xr_mm)==pytest.approx(2)
    assert max(x for x,r in full.points_xr_mm)==pytest.approx(18)
    assert min(r for x,r in full.points_xr_mm)==pytest.approx(14)
    assert max(r for x,r in full.points_xr_mm)==pytest.approx(26)
    assert cm.points_xr_mm==fg.points_xr_mm
    assert fg.diagnostics['calibration']['parameters']['x_max']['status']=='derived'


def test_tilted_axis_tube_reference_and_step(case_dir):
    path=rectangle(case_dir);c=config_for(path);c['profile_settings']['geometry']['simplify_tolerance_px']=1
    c['frame']={'axis':{'origin_mm':[9,-7,4],'direction':[1,2,3]},'radial_reference':[0,1,0]}
    r=run_config(case_dir,c);shape=load_step(r['outputs']['models']['body']['solid_step'],ShapeExpectation(ShapeKind.SOLID,1)).shape
    assert integrated_volume(shape)==pytest.approx(20*pi*(30**2-10**2),rel=1e-9)
    frame=Frame(Axis((9,-7,4),(1,2,3)),(0,1,0))
    centroid=frame.to_local(shape.Center().toTuple());assert centroid==pytest.approx((10,0,0),abs=1e-7)
    assert r['status']=='calibrated_derived_geometry'
    assert r['stages']['body_solid_step']['roundtrip_quality']['solid_count']==1
    assert r['stages']['profiles']['body']['area_mm2']==pytest.approx(400)
    with pytest.raises(GeometryError,match='new directory'):run_raster(case_dir/'run.json',case_dir/'run')


@pytest.mark.parametrize('kind',['multiple_intervals','hole','missing_row','row_jump','empty','single_row'])
def test_profile_rejects_unknown_regions(case_dir,kind):
    im=Image.new('RGB',(101,101),'white');d=ImageDraw.Draw(im)
    if kind in ['multiple_intervals','hole']:
        d.rectangle((10,20,90,80),fill='black');d.rectangle((35,40,65,60),fill='white')
        if kind=='multiple_intervals':d.rectangle((35,20,65,80),fill='white')
    elif kind=='missing_row':d.rectangle((10,20,90,80),fill='black');d.line((0,50,100,50),fill='white')
    elif kind=='row_jump':d.rectangle((10,20,20,50),fill='black');d.rectangle((70,51,90,80),fill='black')
    elif kind=='single_row':d.line((10,20,90,20),fill='black')
    path=case_dir/'bad.png';im.save(path)
    with pytest.raises(ValueError):extract_raster_profile(path,ImageConfig(),calibration(),GeometryConfig())


@pytest.mark.parametrize('mutation',['assumed','missing','conflicting','reverse','negative_radius','mode','bool','unknown_field','relaxed_interval','unknown_unit'])
def test_calibration_contract_blocks_geometry(case_dir,mutation):
    c=config_for(rectangle(case_dir));s=c['profile_settings']
    if mutation in ['assumed','missing','conflicting']:
        s['calibration']['x_max']['status']=mutation
        if mutation=='missing':s['calibration']['x_max']['value']=None
    elif mutation=='reverse':s['calibration']['x_max']['value']=-1
    elif mutation=='negative_radius':s['calibration']['r_min']['value']=-1
    elif mutation=='mode':s['calibration']['mode']='inferred'
    elif mutation=='bool':s['calibration']['x_max']['value']=True
    elif mutation=='unknown_field':s['calibration']['inferred_scale']=1
    elif mutation=='relaxed_interval':s['image']['require_single_interval_per_row']=False
    else:s['calibration']['x_max']['unit']='pixel'
    with pytest.raises(GeometryError):run_config(case_dir,c)
    r=json.loads((case_dir/'run/report.json').read_text(encoding='utf-8'));assert r['success'] is False
    assert not list((case_dir/'run').glob('*.step'))


def colors(root,kind='good'):
    im=Image.new('RGB',(121,101),'white');d=ImageDraw.Draw(im)
    vals=[('low_body',(0,102,204),10,39),('flow_channel',(0,176,80),40,79),('high_body',(220,60,60),80,109)]
    if kind=='gap':vals[1]=('flow_channel',(0,176,80),43,79)
    if kind=='order':vals[0],vals[1]=('low_body',(0,176,80),10,39),('flow_channel',(0,102,204),40,79)
    for name,color,x0,x1 in vals:d.rectangle((x0,20,x1,80 if kind!='range' or name!='flow_channel' else 75),fill=color)
    path=root/'colors.png';im.save(path);return path


def test_three_regions_volume_and_shared_contact(case_dir):
    c=config_for(colors(case_dir),'three');c['profile_settings']['geometry']['simplify_tolerance_px']=1
    r=run_config(case_dir,c);reports=r['stages']['interfaces_after_reload']
    for pair,data in reports.items():
        assert data['overlap_volume_mm3']<=1e-6
        if data['adjacent_expected']:assert data['minimum_distance_mm']<=1e-6
    # Image bbox calibration: radial bounds actually used are 14..26 mm.
    widths={'low_body':(39.5-10)*20/120,'flow_channel':40*20/120,'high_body':(109-79.5)*20/120}
    for n,w in widths.items():
        actual=r['stages'][n+'_solid_step']['roundtrip_quality']['volume_mm3']
        assert actual==pytest.approx(w*pi*(26**2-14**2),rel=1e-9)
    assert len(r['outputs']['models'])==3


@pytest.mark.parametrize('kind',['gap','order','range','color_overlap','duplicate','wrong_calibration','text'])
def test_three_regions_cannot_invent_interfaces(case_dir,kind):
    c=config_for(colors(case_dir,kind),'three');s=c['profile_settings']
    if kind=='color_overlap':s['regions'][1]['color_rgb']=s['regions'][0]['color_rgb']
    elif kind=='duplicate':s['regions'][1]['name']='low_body'
    elif kind=='wrong_calibration':s['calibration']['mode']='foreground_bbox'
    elif kind=='text':
        im=Image.open(c['image_input']['path']).convert('RGB');ImageDraw.Draw(im).text((1,1),'100',fill='black');im.save(c['image_input']['path']);c['image_input']['sha256']=hashlib.sha256(Path(c['image_input']['path']).read_bytes()).hexdigest()
    with pytest.raises(GeometryError):run_config(case_dir,c)
    assert not list((case_dir/'run').glob('*.step'))


def primitive_image(root,shape):
    im=Image.new('RGB',(240,240),'white');d=ImageDraw.Draw(im)
    if shape=='line':d.line((20,120,220,120),fill='black',width=5)
    elif shape=='circle':d.ellipse((40,40,200,200),outline='black',width=5)
    elif shape=='arc':d.arc((40,40,200,200),20,170,fill='black',width=5)
    p=root/(shape+'.png');im.save(p);return p


@pytest.mark.parametrize('kind',['line','circle','arc'])
def test_real_pixel_fits_are_unconfirmed(case_dir,kind):
    p=primitive_image(case_dir,kind);r,mask,skeleton=extract_primitives(p)
    selected=[x for x in r.primitives if x.type==kind];assert len(selected)==1
    value=selected[0];data=r.to_dict()
    assert data['geometry_eligible'] is False and data['physical_calibration'] is None
    assert value.status=='candidate' and value.source_chain_id in data['diagnostics']['source_chains_px']
    assert value.fit_rmse_px<1 and value.fit_max_error_px<2
    if kind=='line':assert value.length_px==pytest.approx(196,abs=3)
    else:
        assert value.center_px==pytest.approx((120,120),abs=2);assert value.radius_px==pytest.approx(78,abs=1.5)
    if kind=='arc':
        assert value.sweep_angle_deg==pytest.approx(150,abs=5)
        assert value.skeleton_sweep_angle_deg<value.sweep_angle_deg
        assert value.endpoint_method.startswith('angular extent of original isolated')
        assert dist(value.start_px,value.center_px)==pytest.approx(value.radius_px,abs=1e-9)
        assert dist(value.end_px,value.center_px)==pytest.approx(value.radius_px,abs=1e-9)
        out=case_dir/'arc.svg';export_primitive_svg(r,out);assert len(ET.parse(out).findall('.//{http://www.w3.org/2000/svg}path'))==1


def test_explicit_component_filter_and_light_otsu(case_dir):
    p=primitive_image(case_dir,'line');im=Image.open(p).convert('RGB');ImageDraw.Draw(im).point((5,5),fill='black');im.save(p)
    r,mask,sk=extract_primitives(p)
    assert r.diagnostics['removed_component_count']==1 and r.diagnostics['removed_pixel_count']==1
    im=Image.eval(im,lambda p:255-p);q=case_dir/'light.png';im.save(q)
    lr,lightmask,_=extract_primitives(q,PrimitiveExtractionConfig(foreground='light'))
    assert lr.threshold_used==0 and np.array_equal(mask,lightmask)
    assert len(lr.primitives)==1


def test_thinning_limit_is_failure():
    thick=np.zeros((40,40),bool);thick[5:35,5:35]=True
    with pytest.raises(ValueError,match='converge'):_thin(thick,1)


def test_polyline_fallback_residual_not_fabricated():
    chain=[(float(i),float(i*i/20)) for i in range(81)]
    cfg=PrimitiveExtractionConfig(line_max_rmse_px=.01,circle_max_rmse_px=.01,minimum_chain_length_px=5)
    r=_classify_chains([chain],cfg);assert r
    assert all(p.fit_method=='rdp_fallback_polyline' and p.fit_rmse_px is None and p.confidence==.35 for p in r)


@pytest.mark.parametrize('kwargs',[{'threshold':True},{'line_max_rmse_px':0},{'circle_max_rmse_px':float('nan')},{'minimum_component_pixels':0},{'minimum_arc_degrees':80,'full_circle_degrees':40},{'thinning_max_iterations':0}])
def test_primitive_settings_strict(kwargs):
    with pytest.raises(ContractError):PrimitiveExtractionConfig(**kwargs)


def test_candidate_workflow_has_no_cad_and_hash_gate(case_dir):
    p=primitive_image(case_dir,'arc');c={'schema_version':1,'image_input':{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()},'primitive_settings':{}}
    r=run_config(case_dir,c,candidates=True)
    assert r['success'] and not r['geometry_eligible'] and r['status']=='candidates_pending_confirmation'
    assert set(r['outputs'])=={'clean','skeleton','overlay','svg'} and not list((case_dir/'run').glob('*.step'))
    assert all(Path(v).is_file() for v in r['outputs'].values())
    c['image_input']['sha256']='0'*64
    with pytest.raises(GeometryError,match='hash'):run_config(case_dir,c,name='changed',candidates=True)


def test_empty_is_candidate_result_not_cad(case_dir):
    p=case_dir/'blank.png';Image.new('RGB',(40,40),'white').save(p)
    c={'schema_version':1,'image_input':{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()},'primitive_settings':{}}
    r=run_config(case_dir,c,candidates=True);assert r['success'] and r['status']=='no_candidates' and not r['geometry_eligible']


@pytest.mark.parametrize('only',[False,True])
def test_transparency_has_no_implicit_foreground(case_dir,only):
    p=case_dir/'alpha.png';Image.new('RGBA',(50,50),(0,0,0,0)).save(p)
    if only:
        with pytest.raises(ValueError,match='transparent'):extract_primitives(p)
    else:
        with pytest.raises(ValueError,match='transparent'):extract_raster_profile(p,ImageConfig(),calibration(),GeometryConfig())


def test_nearly_closed_open_chain_stays_arc_candidate():
    pts=[(100+70*cos(radians(t)),100+70*sin(radians(t))) for t in range(341)]
    values=_classify_chains([pts],PrimitiveExtractionConfig())
    assert len(values)==1 and values[0].type=='arc' and values[0].sweep_angle_deg==pytest.approx(340)
