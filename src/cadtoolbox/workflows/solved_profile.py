"""Use only fully determined returned solver coordinates to build CAD/DXF."""
from dataclasses import asdict
from pathlib import Path
from math import dist
import json
from .. import geometry as _geometry_runtime
import cadquery as cq
import ezdxf
from ..contracts import Axis,Frame,ContractError,ShapeExpectation,ShapeKind,QualityPolicy
from ..solver.sketch import solve_sketch
from ..solver.model import number
from ..geometry.quality import GeometryError,validate_shape
from ..geometry.io import source_info,export_step,load_step,load_dxf
from ..geometry.transforms import transform_shape
from .surfaces import checked_reference
ONE=ShapeExpectation(ShapeKind.SOLID,1);FACE=ShapeExpectation(ShapeKind.FACE,0)


def build_profile(solved,geometry):
    if solved.get('geometry_eligible') is not True:raise GeometryError('sketch_not_determined','only a fully determined nonredundant checked sketch can generate geometry',solved)
    if set(geometry)-{'profile_lines','hole_circles','extrusion_mm','frame'}:raise ContractError('unknown solved-profile geometry fields')
    s=solved['sketch'];points=solved['solved_points_mm'];lines={c['id']:c for c in s['lines']};circles={c['id']:c for c in s['circles']}
    ids=geometry['profile_lines'];holes=geometry.get('hole_circles',[])
    if not isinstance(ids,list) or len(ids)<3 or len(set(ids))!=len(ids) or any(k not in lines for k in ids):raise ContractError('profile needs >=3 unique ordered declared line IDs')
    if not isinstance(holes,list) or len(set(holes))!=len(holes) or any(k not in circles for k in holes):raise ContractError('holes require unique declared circle IDs')
    if set(ids)!=set(lines) or set(holes)!=set(circles):raise ContractError('all nonconstruction lines and circles must be explicitly used; unselected geometry is unsupported')
    edges=[];outline=[];previous=None;first=None
    for key in ids:
        line=lines[key];a,b=points[line['start']],points[line['end']]
        if previous is not None:
            if dist(previous,a)<=1e-7:pass
            elif dist(previous,b)<=1e-7:a,b=b,a
            else:raise GeometryError('profile_connectivity','solved profile edges are not connected in declared order')
        if first is None:first=a
        outline.append(a);edges.append(cq.Edge.makeLine((*a,0),(*b,0)));previous=b
    if dist(previous,first)>1e-7:raise GeometryError('profile_open','solved profile does not close')
    outer=cq.Wire.assembleEdges(edges)
    inners=[cq.Wire.makeCircle(solved['solved_radii_mm'][key],(*points[circles[key]['center']],0),(0,0,1)) for key in holes]
    local_face=cq.Face.makeFromWires(outer,inners);validate_shape(local_face,FACE)
    # A hole must be inside the outer face. Area equality detects invalid outside,
    # nested or overlapping hole interpretation rather than silently dropping it.
    outer_face=cq.Face.makeFromWires(outer)
    expected_area=outer_face.Area()-sum(cq.Face.makeFromWires(w).Area() for w in inners)
    if expected_area<=0 or abs(local_face.Area()-expected_area)>max(1e-6,abs(expected_area)*1e-9):raise GeometryError('hole_topology','hole area does not match explicit disjoint subtraction')
    for i,w in enumerate(inners):
        hf=cq.Face.makeFromWires(w)
        outside=hf.cut(outer_face)
        if outside.Area()>1e-7:raise GeometryError('hole_outside','hole exits the solved outer contour')
        for other in inners[:i]:
            if hf.intersect(cq.Face.makeFromWires(other)).Area()>1e-7:raise GeometryError('holes_overlap','explicit hole interiors overlap or nest')
    height=number(geometry['extrusion_mm'],'extrusion',positive=True)
    solid=cq.Solid.extrudeLinear(outer,inners,(0,0,height))
    frame_data=geometry['frame'];frame=Frame(Axis(**frame_data['axis']),tuple(frame_data['radial_reference']))
    solid=transform_shape(solid,frame);face=transform_shape(local_face,frame)
    validate_shape(solid,ONE)
    return face,solid,{'outline_points_mm':outline,'hole_circles':{key:{'center_mm':points[circles[key]['center']],'radius_mm':solved['solved_radii_mm'][key]} for key in holes},
                     'local_face_area_mm2':local_face.Area(),'extrusion_mm':height,'frame':asdict(frame),'coordinate_source':'actual solver return; initial guesses never drive generated geometry'}


def export_dxf(path,geometry_report):
    doc=ezdxf.new('R2010');doc.units=4
    doc.layers.new('OUTLINE');doc.layers.new('HOLES');m=doc.modelspace()
    m.add_lwpolyline(geometry_report['outline_points_mm'],close=True,dxfattribs={'layer':'OUTLINE'})
    for hole in geometry_report['hole_circles'].values():m.add_circle(hole['center_mm'],hole['radius_mm'],dxfattribs={'layer':'HOLES'})
    doc.saveas(path)


def run_solved_profile(config_path,output,*,progress=None):
    config_path=Path(config_path).resolve();output=Path(output).resolve()
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    if config.get('schema_version')!=1 or config.get('unit')!='mm':raise ContractError('solved profile config requires schema_version=1 and mm')
    if output.exists():raise GeometryError('output_exists','solved profile workflow requires a new output directory')
    output.mkdir(parents=True)
    report={'schema_version':1,'success':False,'config':source_info(config_path),'config_snapshot':config,'stages':{},'outputs':{},'source_paths_read_only':True}
    def save():(output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    def stage(name,data):
        report['stages'][name]=data;save()
        if progress:progress(name)
    try:
        report['source_parameter_references']=[checked_reference(spec,config_path)[1] for spec in config.get('source_parameter_references',[])]
        solved=solve_sketch(config['sketch'],**config.get('solver_options',{}));stage('solver',solved)
        face,solid,geometry=build_profile(solved,config['geometry']);stage('geometry',geometry)
        policy=QualityPolicy(**config.get('quality_policy',{}))
        stage('face_step',export_step(face,output/'solved-face.step',FACE,policy))
        stage('solid_step',export_step(solid,output/'solved-profile.step',ONE,policy))
        stage('solid_reread',load_step(output/'solved-profile.step',ONE).report)
        export_dxf(output/'solved-profile.dxf',geometry)
        stage('dxf_reread',load_dxf(output/'solved-profile.dxf').report)
        report['outputs']={key:str(output/value) for key,value in [('face_step','solved-face.step'),('solid_step','solved-profile.step'),('dxf','solved-profile.dxf')]}
        report.update(success=True,dimension_provenance='constraint parameters and datums retained; source examples derived, not user-confirmed design');save();return report
    except Exception as exc:
        report['failure']=exc.as_dict() if isinstance(exc,GeometryError) else {'error':str(exc)};save()
        if isinstance(exc,GeometryError):raise GeometryError(exc.code,str(exc),report) from exc
        raise
