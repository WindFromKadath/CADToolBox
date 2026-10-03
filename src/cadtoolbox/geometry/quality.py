"""Topology inspection adapted from S024/S044, with task-specific expectations."""
from __future__ import annotations
from collections import Counter
from dataclasses import asdict, dataclass, field
import cadquery as cq
from OCP.BRep import BRep_Tool
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from math import isfinite
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from ..contracts import QualityPolicy, ShapeExpectation, ShapeKind


class GeometryError(ValueError):
    def __init__(self, code: str, message: str, report: dict | None = None):
        super().__init__(message)
        self.code = code
        self.report = report or {}
    def as_dict(self):
        return {'success':False,'code':self.code,'error':str(self),'report':self.report}


@dataclass
class GeometryResult:
    shape: cq.Shape
    report: dict = field(default_factory=dict)
    unit: str = 'mm'



# Keep numerical integration well below existing geometry acceptance limits.
# The non-adaptive overload used by Shape.Volume()/Area() loses accuracy on
# trimmed BSpline faces. These estimates do not certify STEP equivalence.
INTEGRATION_EPS = 1e-11


def integrated_volume(solid: cq.Solid) -> float:
    if not isinstance(solid, cq.Solid):
        raise GeometryError('mass_kind', 'volume integration requires one solid')
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid.wrapped, props, INTEGRATION_EPS, True, False)
    value = props.Mass()
    if not isfinite(value):
        raise GeometryError('mass_integration', 'volume integration returned a nonfinite value')
    return value


def integrated_area(shape: cq.Shape) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape.wrapped, props, INTEGRATION_EPS, False)
    value = props.Mass()
    if not isfinite(value):
        raise GeometryError('mass_integration', 'surface integration returned a nonfinite value')
    return value


def topology(shape: cq.Shape) -> dict:
    if not isinstance(shape,cq.Shape) or shape.wrapped.IsNull() or not shape.Vertices():
        raise GeometryError('empty_shape','geometry contains no vertices')
    mapping = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape.wrapped,TopAbs_EDGE,TopAbs_FACE,mapping)
    edges = [cq.Shape.cast(mapping.FindKey(i)) for i in range(1,mapping.Extent()+1)]
    degenerated = [e for e in edges if BRep_Tool.Degenerated_s(e.wrapped)]
    # Closed-surface seams appear twice in the ancestor list. Degenerate poles
    # are permitted by OCCT and are not open boundaries.
    free = sum(1 for i in range(1,mapping.Extent()+1)
               if mapping.FindFromIndex(i).Size() < 2 and not BRep_Tool.Degenerated_s(cq.Shape.cast(mapping.FindKey(i)).wrapped))
    b = shape.BoundingBox()
    solids = shape.Solids()
    volumes = [integrated_volume(s) for s in solids]
    return {'shape_kind':shape.ShapeType(),'valid':bool(BRepCheck_Analyzer(shape.wrapped).IsValid()),
            'solid_count':len(solids),'shell_count':len(shape.Shells()),'face_count':len(shape.Faces()),
            'edge_count':len(edges),'vertex_count':len(shape.Vertices()),'free_edge_count':free,
            'degenerated_edge_count':len(degenerated),'all_shells_closed':all(s.Closed() for s in shape.Shells()),
            'solid_volumes_mm3':volumes,
            'volume_mm3':sum(volumes),'area_mm2':integrated_area(shape),
            'mass_integration':{'method':'OCCT adaptive Gauss, exact surfaces','face_relative_target':INTEGRATION_EPS,
                                'volume_only_closed':True,'target_is_not_geometry_tolerance':True},
            'minimum_edge_length_mm':min((e.Length() for e in edges),default=None),
            'surface_types':dict(Counter(f.geomType() for f in shape.Faces())),
            'curve_types':dict(Counter(e.geomType() for e in edges if not BRep_Tool.Degenerated_s(e.wrapped))),
            'curve_type_scope':'non-degenerated edges',
            'bbox_mm':{k:getattr(b,k) for k in ('xmin','xmax','ymin','ymax','zmin','zmax')}}


def validate_shape(shape: cq.Shape, expected: ShapeExpectation, policy: QualityPolicy | None = None) -> dict:
    policy = policy or QualityPolicy()
    report = topology(shape)
    errors = []
    if not report['valid']:
        errors.append('OCCT topology is invalid')
    if report['shape_kind'] != expected.kind.value:
        errors.append(f'expected {expected.kind}, got {report["shape_kind"]}')
    if report['solid_count'] != expected.solid_count:
        errors.append(f'expected {expected.solid_count} solids, got {report["solid_count"]}')
    if expected.kind == ShapeKind.FACE and report['face_count'] != 1:
        errors.append('expected exactly one face')
    if expected.solid_count and (report['free_edge_count'] or not report['all_shells_closed']):
        errors.append('solid shells are not closed')
    if any(v <= 0 for v in report['solid_volumes_mm3']):
        errors.append('solid volume must be positive')
    if expected.solid_count and expected.kind == ShapeKind.COMPOUND and any(not isinstance(c,cq.Solid) for c in shape):
        errors.append('solid compound contains non-solid children')
    if policy.reject_degenerated_edges and report['degenerated_edge_count']:
        errors.append('degenerated edges forbidden by task policy')
    report.update(success=not errors,expectation=asdict(expected),policy=asdict(policy),errors=errors)
    if errors:
        raise GeometryError('shape_quality','; '.join(errors),report)
    return report
