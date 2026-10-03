"""Explicit channel constructions and all-component intersections (S014/S016)."""
from dataclasses import dataclass
import cadquery as cq
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from ..contracts import DomainSpec,DomainKind,Frame,ShapeExpectation,ShapeKind,ContractError,finite
from .quality import GeometryResult,GeometryError,validate_shape
from .transforms import transform_shape

ONE=ShapeExpectation(ShapeKind.SOLID,1)

@dataclass
class Domain:
    shape: cq.Shape
    spec: DomainSpec
    report: dict

@dataclass
class ClipResult:
    parts: tuple[cq.Shape,...]
    report: dict
    def require_one(self):
        if len(self.parts)!=1:
            raise GeometryError('component_count',f'expected one component, got {len(self.parts)}',self.report)
        return self.parts[0]


def closed_profile(points,*,mode='periodic_bspline',plane='XY',position=0,tolerance_mm=1e-7):
    tol=finite(tolerance_mm,'profile tolerance',positive=True)
    pairs=[]
    for p in points:
        if len(p)!=2:raise ContractError('profile points require two coordinates')
        pair=tuple(finite(v,'profile coordinate') for v in p)
        if pairs and sum((a-b)**2 for a,b in zip(pair,pairs[-1]))<=tol**2:
            raise ContractError('consecutive duplicate profile points')
        pairs.append(pair)
    if len(pairs)>1 and sum((a-b)**2 for a,b in zip(pairs[0],pairs[-1]))<=tol**2:pairs.pop()
    if mode not in {'polyline','periodic_bspline'} or plane not in {'XY','YZ'}:
        raise ContractError('unsupported profile strategy or local plane')
    if len(set(pairs))!=len(pairs) or len(pairs)<(4 if mode=='periodic_bspline' else 3):
        raise ContractError('not enough distinct ordered profile points')
    position=finite(position,'profile position')
    vectors=[cq.Vector(x,y,position) if plane=='XY' else cq.Vector(position,x,y) for x,y in pairs]
    if mode=='periodic_bspline':
        wire=cq.Wire.assembleEdges([cq.Edge.makeSpline(vectors,periodic=True,tol=tol)])
    else:
        wire=cq.Wire.makePolygon(vectors,close=True)
    if not wire.IsClosed() or not wire.isValid():raise GeometryError('profile_invalid','profile not closed and valid')
    return wire


def axisymmetric_channel(wire: cq.Wire,frame: Frame,*,source: str,inner_wires=()):
    b=wire.BoundingBox()
    if not wire.IsClosed() or b.zlen>1e-6 or abs(b.zmin)>1e-6 or b.ymin < -1e-6:
        raise ContractError('meridional profile must be closed in local XY, with nonnegative radius Y')
    for inner in inner_wires:
        ib=inner.BoundingBox()
        if not inner.IsClosed() or max(abs(ib.zmin),abs(ib.zmax))>1e-6 or ib.ymin < -1e-6:
            raise ContractError('invalid meridional inner wire')
    solid=cq.Solid.revolve(wire,list(inner_wires),360,(0,0,0),(1,0,0))
    solid=transform_shape(solid,frame)
    report=validate_shape(solid,ONE)
    return Domain(solid,DomainSpec(DomainKind.AXISYMMETRIC_MERIDIONAL,frame,source),
                  {'success':True,'construction':'revolve exact meridional wires','quality':report})


def projected_channel(wire: cq.Wire,bounds_mm,frame: Frame,*,source: str,inner_wires=()):
    x0,x1=(finite(v,'extrusion bound') for v in bounds_mm)
    if x1<=x0:raise ContractError('ordered extrusion bounds required')
    b=wire.BoundingBox()
    if not wire.IsClosed() or b.xlen>1e-6:
        raise ContractError('projection wire must be closed in a fixed local YZ plane')
    mid=(b.xmin+b.xmax)/2
    positioned=wire.translate((x0-mid,0,0))
    holes=[]
    for inner in inner_wires:
        ib=inner.BoundingBox()
        if not inner.IsClosed() or ib.xlen>1e-6 or abs((ib.xmin+ib.xmax)/2-mid)>1e-6:
            raise ContractError('projection hole must share the outer wire plane')
        holes.append(inner.translate((x0-mid,0,0)))
    solid=cq.Solid.extrudeLinear(positioned,holes,(x1-x0,0,0))
    solid=transform_shape(solid,frame)
    report=validate_shape(solid,ONE)
    return Domain(solid,DomainSpec(DomainKind.PROJECTED_EXTRUSION,frame,source),
                  {'success':True,'construction':'extrude exact projected wires','quality':report})


def material_domain(shape: cq.Shape,frame: Frame,*,source: str):
    count=len(shape.Solids())
    if not count:raise ContractError('material domain requires solids')
    expected=ShapeExpectation(ShapeKind.SOLID,1) if shape.ShapeType()=='Solid' else ShapeExpectation(ShapeKind.COMPOUND,count)
    report=validate_shape(shape,expected)
    return Domain(shape,DomainSpec(DomainKind.MATERIAL_SOLID,frame,source),{'success':True,'quality':report})


def _trim(source: cq.Shape,domain: Domain,*,face: bool,tolerance_mm: float):
    tolerance=finite(tolerance_mm,'boolean tolerance',positive=True)
    if face:
        validate_shape(source,ShapeExpectation(ShapeKind.FACE))
        if source.geomType()!='BSPLINE':raise ContractError('face trim accepts BSPLINE supporting surfaces only')
    else:validate_shape(source,ONE)
    op=BRepAlgoAPI_Common(source.wrapped,domain.shape.wrapped)
    op.SetNonDestructive(True);op.SetFuzzyValue(tolerance);op.Build()
    if not op.IsDone():raise GeometryError('intersection_failed','channel intersection failed')
    result=cq.Shape.cast(op.Shape())
    parts=result.Faces() if face else result.Solids()
    records=[]
    for part in parts:
        if face and part.geomType()!='BSPLINE':raise GeometryError('surface_changed','trim changed BSPLINE supporting surface')
        validate_shape(part,ShapeExpectation(ShapeKind.FACE) if face else ONE)
        remainder=part.cut(domain.shape,tol=tolerance)
        outside=remainder.Area() if face else sum(s.Volume() for s in remainder.Solids())
        amount=part.Area() if face else part.Volume()
        limit=max(1e-8 if face else 1e-6,amount*1e-9)
        if outside>limit:
            raise GeometryError('outside_domain','trim result extends outside allowed domain',{'outside_measure':outside,'limit':limit})
        records.append({'measure':amount,'outside_measure':outside,'outside_limit':limit,
                        'measure_unit':'mm2' if face else 'mm3','support_type':part.geomType() if face else None})
    return ClipResult(tuple(parts),{'success':True,'status':'empty' if not parts else 'complete',
        'domain_kind':domain.spec.kind.value,'part_count':len(parts),'all_components_preserved':True,
        'containment_check':'boolean difference against full domain','parts':records})


def trim_solid(solid: cq.Solid,domain: Domain,*,tolerance_mm=1e-6):
    return _trim(solid,domain,face=False,tolerance_mm=tolerance_mm)


def trim_bspline_face(face: cq.Face,domain: Domain,*,tolerance_mm=1e-6):
    return _trim(face,domain,face=True,tolerance_mm=tolerance_mm)
