"""Six shared faces or explicit checked loft fallback, migrated from S044/S045."""
from dataclasses import dataclass,asdict
from math import pi,sqrt
import cadquery as cq
from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
from OCP.BRepLib import BRepLib
from ..contracts import Axis,ContractError,finite,ShapeExpectation,ShapeKind
from .quality import GeometryError,GeometryResult,validate_shape
from .surface_fit import FitConfig,fit_surface,target_point,independent_uv
from .shared_faces import build_all_side_faces
from .parametric import CORNERS

ONE=ShapeExpectation(ShapeKind.SOLID,1)

@dataclass(frozen=True)
class SewConfig:
    tolerances_mm:tuple=(1e-6,1e-5,1e-4,1e-3)
    max_tolerance_mm:float=1e-3
    gap_tolerance_mm:float=1e-5
    filling_tolerance_mm:float=1e-7
    loft_sections:int=17
    loft_curve_samples:int=81
    def __post_init__(self):
        for name in ['max_tolerance_mm','gap_tolerance_mm','filling_tolerance_mm']:
            if type(getattr(self,name)) is bool:raise ContractError(name+' must be numeric')
            finite(getattr(self,name),name,positive=True)
        if self.filling_tolerance_mm>self.gap_tolerance_mm:raise ContractError('side filling tolerance must not exceed edge gap limit')
        if not self.tolerances_mm or any(type(t) is bool or finite(t,'sewing tolerance',positive=True)>self.max_tolerance_mm for t in self.tolerances_mm):raise ContractError('sewing tolerances must be positive and within allowed maximum')
        for n in [self.loft_sections,self.loft_curve_samples]:
            if type(n) is not int or n<4:raise ContractError('loft station/sample counts must be integers >=4')


def sew_faces(faces,config:SewConfig):
    attempts=[]
    for tol in config.tolerances_mm:
        sew=BRepBuilderAPI_Sewing(tol);sew.SetFaceMode(True)
        for face in faces:sew.Add(face)
        sew.Perform();shape=cq.Shape.cast(sew.SewedShape());shells=shape.Shells()
        attempt={'tolerance_mm':tol,'shell_count':len(shells),'success':False}
        attempts.append(attempt)
        if len(shells)!=1:continue
        solid=cq.Solid.makeSolid(shells[0])
        BRepLib.OrientClosedSolid_s(solid.wrapped)
        try:quality=validate_shape(solid,ONE)
        except GeometryError as exc:attempt['failure']=exc.as_dict();continue
        if quality['shell_count']!=1:continue
        attempt['success']=True
        return solid,{'success':True,'sewing_tolerance_used_mm':tol,'attempts':attempts,'quality':quality}
    raise GeometryError('surface_sewing','six faces did not form one valid closed positive-volume solid',{'success':False,'attempts':attempts})


def loft_solid(base,field,axis,config:SewConfig):
    sections=[]
    for i in range(config.loft_sections):
        u=i/(config.loft_sections-1)
        a=[cq.Vector(*base.evaluate(u,j/(config.loft_curve_samples-1))) for j in range(config.loft_curve_samples)]
        b=[cq.Vector(*target_point(base,field,axis,u,j/(config.loft_curve_samples-1))) for j in range(config.loft_curve_samples)]
        edges=[cq.Edge.makeSpline(a),cq.Edge.makeLine(a[-1],b[-1]),cq.Edge.makeSpline(list(reversed(b))),cq.Edge.makeLine(b[0],a[0])]
        sections.append(cq.Wire.assembleEdges(edges))
    solid=cq.Solid.makeLoft(sections,ruled=False)
    validate_shape(solid,ONE)
    return solid


def validate_solid_target(solid,base,field,axis,fit:FitConfig):
    # Distance to individual faces avoids the zero distance assigned to points
    # anywhere inside a solid by a solid/point distance query.
    faces=solid.Faces();errors=[];lower_errors=[]
    for u,v in independent_uv(9,17):
        for point,group in [(target_point(base,field,axis,u,v),errors),(base.evaluate(u,v),lower_errors)]:
            vertex=cq.Vertex.makeVertex(*point);group.append(min(vertex.distances(*faces)))
    rms=sqrt(sum(x*x for x in errors)/len(errors))
    report={'success':max(errors)<=fit.max_error_mm and rms<=fit.rms_error_mm and max(lower_errors)<=fit.max_error_mm,
            'max_target_to_face_error_mm':max(errors),'rms_target_to_face_error_mm':rms,'max_base_to_face_error_mm':max(lower_errors),
            'sample_count':len(errors),'method':'independent UV samples to actual trimmed B-Rep faces, not whole-solid inside distance'}
    if not report['success']:raise GeometryError('solid_target_error','constructed solid exceeds original parametric target budget',report)
    return report


def build_twisted_solid(base,field,axis:Axis,fit:FitConfig|None=None,sewing:SewConfig|None=None,*,allow_loft_fallback=False,
                        construction='six_shared_faces',max_abs_theta_rad=pi,min_axis_radius_mm=.1):
    fit=fit or FitConfig();sewing=sewing or SewConfig()
    if type(allow_loft_fallback) is not bool:raise ContractError('fallback permission must be explicitly boolean')
    if construction not in ('six_shared_faces','multi_section_loft'):raise ContractError('unknown surface solid construction')
    theta_limit=finite(max_abs_theta_rad,'theta maximum',positive=True);radius_limit=finite(min_axis_radius_mm,'minimum axis radius',positive=True)
    samples=[];radii=[];crosses=[]
    for i in range(17):
        for j in range(33):
            u,v=i/16,j/32;p=cq.Vector(*base.evaluate(u,v))-cq.Vector(*axis.origin_mm)
            radius=p.cross(cq.Vector(*axis.direction)).Length;radii.append(radius)
            angle=finite(field.evaluate(u,v),'theta');samples.append(angle)
            if radius<radius_limit or abs(angle)>theta_limit:raise GeometryError('twist_limits','base radius or theta exceeds configured limits',{'uv':[u,v],'radius_mm':radius,'theta_rad':angle})
            if i<16 and j<32:
                a=cq.Vector(*target_point(base,field,axis,(i+1)/16,v))-cq.Vector(*target_point(base,field,axis,u,v))
                b=cq.Vector(*target_point(base,field,axis,u,(j+1)/32))-cq.Vector(*target_point(base,field,axis,u,v))
                crosses.append(a.cross(b).Length)
    if min(crosses)<1e-12:raise GeometryError('twist_regularity','sampled target is locally degenerate')
    if min(samples)<=0<=max(samples):raise GeometryError('twist_crossing','field crosses or reaches zero; collapsed/crossing base and target faces are unsupported')
    corners0=base.corners();corners1={k:target_point(base,field,axis,*q) for k,q in CORNERS.items()}
    face1,fit_report=fit_surface(base,field,axis,fit)
    report={'success':False,'fit':fit_report,'field':field.report,'base':base.report,'axis':asdict(axis),
        'sampled_limits':{'minimum_radius_mm':min(radii),'theta_range_rad':[min(samples),max(samples)],'minimum_target_cell_cross_mm2':min(crosses),'scope':'sampled local regularity; no global self-intersection certification'},
        'fallback_allowed':allow_loft_fallback,'requested_construction':construction,'construction_failures':[],'sewing_config':asdict(sewing)}
    if construction=='multi_section_loft':solid=loft_solid(base,field,axis,sewing);method=construction
    else:
        try:
            faces=build_all_side_faces(base.build_face().wrapped,face1.wrapped,corners0,corners1,sewing.gap_tolerance_mm,sewing.filling_tolerance_mm)
            solid,sew_report=sew_faces(faces,sewing);report['sewing']=sew_report;method='six_shared_faces'
        except Exception as exc:
            report['construction_failures'].append(exc.as_dict() if isinstance(exc,GeometryError) else {'error':str(exc)})
            if not allow_loft_fallback:raise GeometryError('six_face_failed','six-face construction failed; fallback not permitted',report) from exc
            solid=loft_solid(base,field,axis,sewing);method='multi_section_loft_fallback'
    report['constructed_target_validation']=validate_solid_target(solid,base,field,axis,fit)
    report.update(success=True,construction_method=method,geometry_changed_by_fallback=method=='multi_section_loft_fallback',quality=validate_shape(solid,ONE),
                  loft_station_count=sewing.loft_sections if method.startswith('multi_section') else None)
    return GeometryResult(solid,report)
