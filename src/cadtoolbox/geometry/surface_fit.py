"""Two-parameter target fitting with independent surface and boundary checks (S043)."""
from dataclasses import dataclass,asdict
from math import cos,sin,sqrt
import cadquery as cq
from OCP.GeomAPI import GeomAPI_PointsToBSplineSurface,GeomAPI_ProjectPointOnSurf
from OCP.GeomAbs import GeomAbs_C1
from OCP.TColgp import TColgp_Array2OfPnt
from OCP.gp import gp_Pnt
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from ..contracts import Axis,finite,ContractError
from .quality import GeometryError
from .parametric import CORNERS
from .shared_faces import classify_edges,actual_corners,LABEL_PAIRS


@dataclass(frozen=True)
class FitConfig:
    initial_u:int=20
    initial_v:int=40
    max_u:int=160
    max_v:int=320
    degree:int=3
    max_error_mm:float=0.001
    rms_error_mm:float=0.0002
    boundary_error_mm:float=0.001
    endpoint_error_mm:float=1e-7
    def __post_init__(self):
        for name in ['initial_u','initial_v','max_u','max_v']:
            if type(getattr(self,name)) is not int or getattr(self,name)<4:raise ContractError('fit sample counts must be integers >=4')
        if self.initial_u>self.max_u or self.initial_v>self.max_v:raise ContractError('initial samples exceed fit budget')
        if type(self.degree) is not int or not 2<=self.degree<=8:raise ContractError('surface degree must be 2..8')
        for name in ['max_error_mm','rms_error_mm','boundary_error_mm','endpoint_error_mm']:
            if type(getattr(self,name)) is bool:raise ContractError(name+' must be numeric')
            finite(getattr(self,name),name,positive=True)


def rotate_point(p,axis:Axis,angle):
    angle=finite(angle,'angle rad');a=cq.Vector(*axis.direction);v=cq.Vector(*p)-cq.Vector(*axis.origin_mm)
    out=v*cos(angle)+a.cross(v)*sin(angle)+a*(a.dot(v)*(1-cos(angle)))+cq.Vector(*axis.origin_mm)
    return out.toTuple()


def target_point(base,field,axis,u,v):return rotate_point(base.evaluate(u,v),axis,field.evaluate(u,v))


def independent_uv(nu,nv,cap_u=None,cap_v=None):
    # Half-grid samples are never fit inputs. Add full boundaries and corners.
    ui=range(nu-1) if cap_u is None or nu-1<=cap_u else sorted({int(i*(nu-2)/(cap_u-1)) for i in range(cap_u)})
    vi=range(nv-1) if cap_v is None or nv-1<=cap_v else sorted({int(i*(nv-2)/(cap_v-1)) for i in range(cap_v)})
    pts=[((i+.5)/(nu-1),(j+.5)/(nv-1)) for i in ui for j in vi]
    for t in [i/32 for i in range(33)]:pts.extend([(0,t),(1,t),(t,0),(t,1)])
    return pts


def fit_surface(base,field,axis,config:FitConfig):
    nu,nv=config.initial_u,config.initial_v;attempts=[]
    while True:
        arr=TColgp_Array2OfPnt(1,nu,1,nv)
        for i in range(nu):
            for j in range(nv):arr.SetValue(i+1,j+1,gp_Pnt(*target_point(base,field,axis,i/(nu-1),j/(nv-1))))
        builder=GeomAPI_PointsToBSplineSurface(arr,min(config.degree,nu-1,nv-1),min(config.degree,nu-1,nv-1),GeomAbs_C1,1e-9)
        if not builder.IsDone():raise GeometryError('surface_fit_backend','OCC B-Spline fitting failed')
        surface=builder.Surface();face=cq.Face(BRepBuilderAPI_MakeFace(surface,1e-7).Face())
        errors=[];maximum_uv=None;maximum=-1
        for u,v in independent_uv(nu,nv,40,80):
            p=target_point(base,field,axis,u,v)
            projection=GeomAPI_ProjectPointOnSurf(gp_Pnt(*p),surface)
            if projection.NbPoints()==0:raise GeometryError('fit_projection','target projection failed',{'uv':[u,v]})
            d=projection.LowerDistance();errors.append(d)
            if d>maximum:maximum=d;maximum_uv=[u,v]
        corners={key:target_point(base,field,axis,*q) for key,q in CORNERS.items()}
        labels=classify_edges(face.wrapped,corners);actual=actual_corners(face.wrapped,corners)
        corner_errors=[cq.Vector(*actual[k]).sub(cq.Vector(*corners[k])).Length for k in corners]
        boundary=[]
        for label,edge in labels.items():
            for i in range(33):
                t=i/32;u,v={'u0':(0,t),'u1':(1,t),'v0':(t,0),'v1':(t,1)}[label]
                boundary.append(cq.Vertex.makeVertex(*target_point(base,field,axis,u,v)).distance(cq.Edge(edge)))
        report={'success':maximum<=config.max_error_mm and sqrt(sum(d*d for d in errors)/len(errors))<=config.rms_error_mm and max(boundary)<=config.boundary_error_mm and max(corner_errors)<=config.endpoint_error_mm,
            'samples_u':nu,'samples_v':nv,'max_error_mm':maximum,'rms_error_mm':sqrt(sum(d*d for d in errors)/len(errors)),
            'max_error_uv':maximum_uv,'boundary_max_error_mm':max(boundary),'endpoint_max_error_mm':max(corner_errors),
            'validation_sample_count':len(errors),'limits':asdict(config),'method':'independent half-grid target-to-surface projection and target-to-actual-edge boundary distances'}
        attempts.append(report)
        if report['success']:return face,{'success':True,'attempts':attempts,**report}
        if nu>=config.max_u and nv>=config.max_v:raise GeometryError('surface_fit_budget','fit did not meet configured surface/boundary budget',{'attempts':attempts,'success':False})
        nu=min(config.max_u,2*nu-1);nv=min(config.max_v,2*nv-1)
