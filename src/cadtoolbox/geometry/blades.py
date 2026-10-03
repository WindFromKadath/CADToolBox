"""Radial theta laws and sampled blade boundaries, from S018/S023.

Curved side boundaries are interpolated BSplines; constant-theta chord sides
are exact straight lines. Their fit error is measured
against additional analytic radius samples and explicitly limited.
"""
from dataclasses import dataclass
from math import atan2,cos,sin,sqrt,hypot
import cadquery as cq
from ..contracts import Axis,Frame,Thickness,ThicknessKind,ShapeExpectation,ShapeKind,ContractError,finite
from .transforms import transform_shape
from .quality import GeometryError,validate_shape


@dataclass(frozen=True)
class CircleLaw:
    construction_radius_mm: float
    center_radial_2_mm: float
    branch: int
    def __post_init__(self):
        object.__setattr__(self,'construction_radius_mm',finite(self.construction_radius_mm,'construction radius',positive=True))
        object.__setattr__(self,'center_radial_2_mm',finite(self.center_radial_2_mm,'circle center'))
        if abs(self.center_radial_2_mm)<1e-12 or type(self.branch) is not int or self.branch not in (-1,1):
            raise ContractError('circle center must be off-axis and branch must be +1 or -1')
    def point(self,radius):
        r=finite(radius,'radius',positive=True);z0=self.center_radial_2_mm
        z=(r*r+z0*z0-self.construction_radius_mm**2)/(2*z0)
        squared=r*r-z*z
        if squared < -max(1e-9,r*r*1e-12):
            raise ContractError(f'no circle intersection at radius {r}')
        return self.branch*sqrt(max(0,squared)),z
    def theta(self,radius):
        y,z=self.point(radius)
        return atan2(z,y)


@dataclass(frozen=True)
class ThetaLaw:
    r_min_mm: float
    r_max_mm: float
    theta_root_rad: float
    theta_tip_rad: float
    exponent: float=1.35
    linear_blend: float=0.25
    def __post_init__(self):
        for name in ('r_min_mm','r_max_mm','exponent'):
            object.__setattr__(self,name,finite(getattr(self,name),name,positive=True))
        for name in ('theta_root_rad','theta_tip_rad','linear_blend'):
            object.__setattr__(self,name,finite(getattr(self,name),name))
        if self.r_max_mm<=self.r_min_mm or not 0<=self.linear_blend<=1:
            raise ContractError('invalid theta-law radial range or blend')
    def theta(self,radius):
        radius=finite(radius,'radius',positive=True)
        u=min(1,max(0,(radius-self.r_min_mm)/(self.r_max_mm-self.r_min_mm)))
        f=self.linear_blend*u+(1-self.linear_blend)*u**self.exponent
        return self.theta_root_rad+(self.theta_tip_rad-self.theta_root_rad)*f


@dataclass
class BladeResult:
    solid: cq.Solid
    centerline: cq.Wire
    outline: cq.Wire
    report: dict


def build_radial_blade(frame: Frame,axial_bounds_mm,radial_bounds_mm,thickness: Thickness,
                       law: CircleLaw | ThetaLaw,*,samples: int=121,fit_tolerance_mm: float=0.02,
                       centerline_bounds_mm=None) -> BladeResult:
    x0,x1=(finite(v,'axial bound') for v in axial_bounds_mm)
    r0,r1=(finite(v,'radial bound',positive=True) for v in radial_bounds_mm)
    limit=finite(fit_tolerance_mm,'fit tolerance',positive=True)
    if x1<=x0 or r1<=r0 or type(samples) is not int or samples<4:
        raise ContractError('ordered bounds and integer samples >=4 required')
    if thickness.kind==ThicknessKind.NORMAL:
        raise ContractError('normal thickness offset is not implemented')
    if thickness.half_angle(r0)>=1.5707963267948966:
        raise ContractError('blade angular half-thickness must be less than pi/2')
    local_frame=Frame(Axis())
    def side_point(r,sign):
        return local_frame.cylindrical(x0,r,law.theta(r)+sign*thickness.half_angle(r))
    rs=[r0+(r1-r0)*i/(samples-1) for i in range(samples)]
    sides=[[cq.Vector(*side_point(r,sign)) for r in rs] for sign in (1,-1)]
    try:
        straight=(isinstance(law,ThetaLaw) and law.theta_root_rad==law.theta_tip_rad and thickness.kind==ThicknessKind.CHORD)
        if straight:
            positive=cq.Edge.makeLine(sides[0][0],sides[0][-1]);negative=cq.Edge.makeLine(sides[1][-1],sides[1][0])
        else:
            positive=cq.Edge.makeSpline(sides[0]);negative=cq.Edge.makeSpline(list(reversed(sides[1])))
        outline=cq.Wire.assembleEdges([positive,cq.Edge.makeLine(sides[0][-1],sides[1][-1]),
                                      negative,cq.Edge.makeLine(sides[1][0],sides[0][0])])
        if not outline.IsClosed() or not outline.isValid():
            raise GeometryError('blade_outline','blade outline must be closed and valid')
        # Midpoints were not interpolation inputs. Distance to the actual OCC
        # edge measures geometric deviation, not agreement of two sample lists.
        errors=[]
        for i in range(samples-1):
            r=(rs[i]+rs[i+1])/2
            for sign,edge in [(1,positive),(-1,negative)]:
                errors.append(cq.Vertex.makeVertex(*side_point(r,sign)).distance(edge))
        maximum=max(errors)
        if maximum>limit:
            raise GeometryError('blade_fit','blade side fit exceeds explicit tolerance',{'max_fit_error_mm':maximum,'limit_mm':limit})
        if isinstance(law,CircleLaw):
            c0,c1=centerline_bounds_mm or (r0,r1)
            c0=finite(c0,'centerline lower radius',positive=True);c1=finite(c1,'centerline upper radius',positive=True)
            if not r0<=c0<c1<=r1:raise ContractError('centerline bounds must lie inside blade bounds')
            pts=[cq.Vector(*local_frame.cylindrical(x0,r,law.theta(r))) for r in (c0,(c0+c1)/2,c1)]
            center=cq.Edge.makeThreePointArc(*pts)
        else:
            center_points=[cq.Vector(*local_frame.cylindrical(x0,r,law.theta(r))) for r in rs]
            center=cq.Edge.makeLine(center_points[0],center_points[-1]) if law.theta_root_rad==law.theta_tip_rad else cq.Edge.makeSpline(center_points)
        solid=cq.Solid.extrudeLinear(outline,[],(x1-x0,0,0))
        solid=transform_shape(solid,frame)
        outline=transform_shape(outline,frame)
        center=transform_shape(center,frame)
        quality=validate_shape(solid,ShapeExpectation(ShapeKind.SOLID,1))
    except (GeometryError,ContractError):raise
    except Exception as exc:
        raise GeometryError('blade_build',f'blade construction failed: {exc}') from exc
    return BladeResult(solid,cq.Wire.assembleEdges([center]),outline,{'success':True,'unit':'mm',
        'law':type(law).__name__,'axial_bounds_mm':[x0,x1],'radial_bounds_mm':[r0,r1],
        'thickness':{'kind':thickness.kind.value,'full_value_mm':thickness.value_mm},'samples':samples,
        'max_side_fit_error_mm':maximum,'fit_limit_mm':limit,'fit_validation':'independent midpoint distances to interpolated OCC side edges',
        'side_construction':'exact constant-theta chord lines' if straight else 'interpolated BSplines',
        'quality':quality})


def extreme_chord_thickness(solid: cq.Solid,frame: Frame,*,radius_tolerance_mm=1e-5):
    # Periodic cylindrical ends add seam vertices on the middle of an end arc.
    # Side thickness is defined at extrusion-side endpoints, not at that seam.
    axis_vector=cq.Vector(*frame.axis.direction)
    extrusion_faces=[f for f in solid.Faces() if f.geomType()=='EXTRUSION' or
                     (f.geomType()=='PLANE' and abs(f.normalAt().dot(axis_vector))<1e-8)]
    vertices=solid.Vertices()
    if extrusion_faces:
        side_vertices=[v for f in extrusion_faces for v in f.Vertices()]
        vertices=[v for v in vertices if any(v.isSame(s) for s in side_vertices)]
    data=[frame.to_local(v.Center().toTuple()) for v in vertices]
    if not data:raise GeometryError('thickness_measurement','blade has no vertices')
    radii=[hypot(y,z) for _,y,z in data];result={}
    for name,target in [('inner',min(radii)),('outer',max(radii))]:
        points=[]
        for (_,y,z),r in zip(data,radii):
            if abs(r-target)>radius_tolerance_mm:continue
            if not any(hypot(y-py,z-pz)<1e-6 for py,pz in points):points.append((y,z))
        if len(points)!=2:
            raise GeometryError('thickness_measurement',f'{name}: expected two side points, got {len(points)}')
        result[name]={'radius_mm':target,'chord_mm':hypot(points[0][0]-points[1][0],points[0][1]-points[1][1]),
                      'method':'axial side-face endpoints' if extrusion_faces else 'unique radial-extreme vertices'}
    return result
