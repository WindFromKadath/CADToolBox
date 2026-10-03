"""Raster workflow: declared calibration -> exact polylines -> strict STEP.
Primitive workflow intentionally ends at pixel candidates and diagnostic exports.
"""
from dataclasses import asdict
from pathlib import Path
from math import pi
from importlib.metadata import version
import json,sys
from .. import geometry as _geometry_runtime
import cadquery as cq
from ..contracts import Axis,Frame,ContractError,ShapeExpectation,ShapeKind,QualityPolicy
from ..geometry.quality import GeometryError,validate_shape,integrated_volume
from ..geometry.io import source_info,export_step,load_step
from ..geometry.domains import closed_profile,axisymmetric_channel
from ..geometry.transforms import transform_shape
from ..raster.config import fields,settings
from ..raster.profiles import extract_raster_profile,export_overlay
from ..raster.regions import extract_three_region_profiles,export_three_region_overlay,REQUIRED_REGION_ORDER
from ..raster.primitives import PrimitiveExtractionConfig,extract_primitives,export_primitive_overlay,export_primitive_svg,_save_binary_image
from .surfaces import checked_reference
ONE=ShapeExpectation(ShapeKind.SOLID,1);FACE=ShapeExpectation(ShapeKind.FACE,0)


def polygon_reference(points):
    # Green's theorem: volume about X = 2*pi*integral(r dA).
    crosses=[x*r1-x1*r for (x,r),(x1,r1) in zip(points,points[1:]+points[:1])]
    area=sum(crosses)/2
    moment=sum((a[1]+b[1])*c for a,b,c in zip(points,points[1:]+points[:1],crosses))/6
    return {'area_mm2':abs(area),'revolved_volume_mm3':2*pi*abs(moment),
            'method':'signed polygon area and radial first moment; straight extracted segments only'}


def interfaces(shapes):
    reports={}
    for a,b in [('low_body','flow_channel'),('flow_channel','high_body'),('low_body','high_body')]:
        distance=shapes[a].distance(shapes[b]);common=shapes[a].intersect(shapes[b])
        volume=sum(integrated_volume(s) for s in common.Solids());adjacent='flow_channel' in {a,b}
        data={'minimum_distance_mm':distance,'overlap_volume_mm3':volume,'adjacent_expected':adjacent,
              'distance_limit_mm':1e-6,'overlap_limit_mm3':1e-6}
        reports[a+'__'+b]=data
        if volume>1e-6 or adjacent and distance>1e-6:raise GeometryError('region_interfaces','region contact/overlap requirement failed',reports)
    return reports


def run_raster(config_path,output,*,candidates=False,progress=None):
    config_path=Path(config_path).resolve();output=Path(output).resolve()
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    if output.exists():raise GeometryError('output_exists','raster workflow requires a new directory')
    output.mkdir(parents=True)
    report={'schema_version':1,'success':False,'config':source_info(config_path),'config_snapshot':config,'stages':{},'outputs':{},
            'source_paths_read_only':True,'environment':{'python':sys.version,'packages':{p:version(p) for p in ['cadquery','cadquery-ocp','numpy','Pillow']}}}
    def save():(output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    def stage(name,data):
        report['stages'][name]=data;save()
        if progress:progress(name)
    try:
        required=['schema_version','image_input','primitive_settings'] if candidates else ['schema_version','image_input','profile_settings','frame']
        fields(config,required,['source_parameter_references','quality_policy'] if not candidates else ['source_parameter_references'])
        if type(config['schema_version']) is not int or config['schema_version']!=1:raise ContractError('schema_version=1 required')
        image,info=checked_reference(fields(config['image_input'],['path','sha256']),config_path);stage('image_input',info)
        references=[checked_reference(fields(s,['path','sha256']),config_path)[1] for s in config.get('source_parameter_references',[])];stage('source_references',references)
        if candidates:
            cfg=PrimitiveExtractionConfig(**config['primitive_settings']);result,mask,skeleton=extract_primitives(image,cfg)
            data=result.to_dict();stage('candidates',data)
            _save_binary_image(mask,output/'clean-geometry.png');_save_binary_image(skeleton,output/'skeleton.png')
            export_primitive_overlay(result,output/'candidate-overlay.png');export_primitive_svg(result,output/'candidates.svg')
            report['outputs']={k:str(output/v) for k,v in [('clean','clean-geometry.png'),('skeleton','skeleton.png'),('overlay','candidate-overlay.png'),('svg','candidates.svg')]}
            report.update(success=True,status='candidates_pending_confirmation' if result.primitives else 'no_candidates',geometry_eligible=False,physical_calibration=None)
        else:
            image_cfg,cal,geo,regions=settings(config['profile_settings']);mode=config['profile_settings']['mode']
            # Validate calibration/interpretation before any CAD construction.
            frame_spec=fields(config['frame'],['axis','radial_reference']);frame=Frame(Axis(**fields(frame_spec['axis'],['origin_mm','direction'])),frame_spec['radial_reference'])
            if mode=='single':
                profile=extract_raster_profile(image,image_cfg,cal,geo);profiles={'body':profile};export_overlay(profile,output/'profile-overlay.png')
            else:
                profiles=extract_three_region_profiles(image,regions,cal,geo,image_cfg.minimum_foreground_rows);export_three_region_overlay(profiles,output/'profile-overlay.png')
            stage('profiles',{k:p.to_dict() for k,p in profiles.items()});stage('frame',asdict(frame))
            shapes={};references={}
            for name,p in profiles.items():
                wire=closed_profile(p.points_xr_mm,mode='polyline');face=cq.Face.makeFromWires(wire);validate_shape(face,FACE)
                domain=axisymmetric_channel(wire,frame,source=str(image)+' sha256:'+p.source_sha256)
                ref=polygon_reference(list(p.points_xr_mm));actual=integrated_volume(domain.shape)
                if abs(face.Area()-ref['area_mm2'])>max(1e-6,ref['area_mm2']*1e-9) or abs(actual-ref['revolved_volume_mm3'])>max(1e-6,ref['revolved_volume_mm3']*1e-9):
                    raise GeometryError('raster_analytic_reference','polygon area/radial moment disagrees with constructed geometry',ref)
                references[name]={**ref,'actual_volume_mm3':actual};shapes[name]=domain.shape
            stage('independent_polygon_reference',references)
            if mode!='single':stage('interfaces_before_export',interfaces(shapes))
            policy=QualityPolicy(**config.get('quality_policy',{}));outputs={};reloaded={}
            for name,p in profiles.items():
                local_face=cq.Face.makeFromWires(closed_profile(p.points_xr_mm,mode='polyline'))
                stage(name+'_face_step',export_step(transform_shape(local_face,frame),output/(name+'-profile.step'),FACE,policy))
                stage(name+'_solid_step',export_step(shapes[name],output/(name+'.step'),ONE,policy))
                reloaded[name]=load_step(output/(name+'.step'),ONE).shape
                actual=integrated_volume(reloaded[name]);expected=references[name]['revolved_volume_mm3']
                if abs(actual-expected)>max(1e-6,expected*1e-8):raise GeometryError('raster_roundtrip_reference','reread volume differs from analytic polygon reference')
                outputs[name]={'face_step':str(output/(name+'-profile.step')),'solid_step':str(output/(name+'.step'))}
            if mode!='single':stage('interfaces_after_reload',interfaces(reloaded))
            report.update(success=True,status='calibrated_derived_geometry',geometry_eligible=True,
                          outputs={'models':outputs,'overlay':str(output/'profile-overlay.png')},
                          semantics='separate axisymmetric regions; flow_channel is an allowed-domain volume, not a fused material body',
                          limitations=['filled continuous row intervals only; no OCR, holes, multiple unknown regions, perspective or general engineering drawings',
                                       'bbox calibration and straight/RDP segments approximate raster boundary; not certification of design dimensions',
                                       'three regions require exact adjacency, fixed order, shared radius range and image_bbox calibration'])
        save();return report
    except Exception as exc:
        failure=exc.as_dict() if isinstance(exc,GeometryError) else {'error':str(exc),'type':type(exc).__name__}
        report['failure']=failure;save()
        if isinstance(exc,GeometryError):raise GeometryError(exc.code,str(exc),report) from exc
        if isinstance(exc,(ValueError,TypeError,KeyError,OSError)):
            raise GeometryError('raster_input_or_processing',str(exc),report) from exc
        raise
