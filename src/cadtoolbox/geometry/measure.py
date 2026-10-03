"""Axis candidates and precise axial measurements, replacing S038 heuristics."""
from __future__ import annotations
from dataclasses import asdict
from math import sqrt
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.gp import gp_Trsf
from ..contracts import Axis, Frame, cross, dot
from .quality import GeometryError, topology


def _cylinders(shape):
    for face in shape.Faces():
        surf = BRepAdaptor_Surface(face.wrapped)
        if surf.GetType() == GeomAbs_Cylinder:
            cylinder = surf.Cylinder()
            line = cylinder.Axis()
            p = line.Location(); d = line.Direction()
            yield Axis((p.X(),p.Y(),p.Z()),(d.X(),d.Y(),d.Z())), cylinder.Radius(),face.Area()


def _same_line(a: Axis, b: Axis, tolerance_mm=1e-5):
    delta = tuple(x-y for x,y in zip(a.origin_mm,b.origin_mm))
    normal = cross(delta,a.direction)
    return abs(dot(a.direction,b.direction)) >= 1-1e-10 and sqrt(dot(normal,normal)) <= tolerance_mm


def axis_candidates(shape: cq.Shape) -> list[dict]:
    topology(shape)
    candidates = []
    for axis,radius,area in _cylinders(shape):
        match = next((c for c in candidates if _same_line(c['axis_object'],axis)),None)
        if match is None:
            # Direction sign is deterministic, but says nothing about rotor handedness.
            direction = axis.direction
            first = next(x for x in direction if abs(x)>1e-10)
            if first < 0:
                direction = tuple(-x for x in direction)
            t = dot(axis.origin_mm,direction)
            origin = tuple(p-t*d for p,d in zip(axis.origin_mm,direction))
            match = {'axis_object':Axis(origin,direction),'area_mm2':0.0,'radii_mm':[],
                     'method':'coaxial analytic cylindrical faces','status':'candidate'}
            candidates.append(match)
        match['area_mm2'] += area
        if not any(abs(radius-r)<1e-7 for r in match['radii_mm']):
            match['radii_mm'].append(radius)
    candidates.sort(key=lambda c:c['area_mm2'],reverse=True)
    return [{**{k:v for k,v in c.items() if k!='axis_object'},'axis':asdict(c['axis_object']),
             'radii_mm':sorted(c['radii_mm'])} for c in candidates]


def measure(shape: cq.Shape, axis: Axis | None = None) -> dict:
    quality = topology(shape)
    candidates = axis_candidates(shape)
    if axis is None:
        if not candidates:
            raise GeometryError('axis_required','no analytic cylindrical axis; supply an explicit axis',
                                {'quality':quality,'axis_candidates':[]})
        axis = Axis(**candidates[0]['axis'])
        axis_source = 'largest cylindrical surface candidate; user confirmation required'
    else:
        axis_source = 'explicit argument'
    reference = min(((1,0,0),(0,1,0),(0,0,1)),key=lambda v:abs(dot(v,axis.direction)))
    frame = Frame(axis,reference)
    bases = (axis.direction,frame.radial_reference,frame.radial_2)
    transform = gp_Trsf()
    transform.SetValues(*(value for base in bases for value in (*base,-dot(base,axis.origin_mm))))
    b = shape.transformShape(cq.Matrix(transform)).BoundingBox()
    radii = []
    for a,radius,_ in _cylinders(shape):
        if _same_line(a,axis) and not any(abs(radius-r)<1e-7 for r in radii):
            radii.append(radius)
    radii.sort()
    return {'success':quality['valid'],'unit':'mm','axis':asdict(axis),'axis_source':axis_source,
            'axis_candidates':candidates,'axial_min_mm':b.xmin,'axial_max_mm':b.xmax,
            'axial_length_mm':b.xlen,'radial_bbox_spans_mm':[b.ylen,b.zlen],
            'coaxial_cylindrical_radii_mm':radii,'diameter_candidates_mm':[2*r for r in radii],
            'volume_mm3':quality['volume_mm3'],'area_mm2':quality['area_mm2'],
            'semantics':'radii are analytic face candidates; no universal inner/outer diameter inference',
            'quality':quality}


def count_axis_cylinder_faces(shape, axis, radius_mm, *, tolerance_mm=1e-5):
    """Analytic face count about an explicit axis; adapted from S024."""
    from .quality import integrated_area
    from ..contracts import finite
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    radius=finite(radius_mm,'cylinder radius',positive=True)
    tolerance=finite(tolerance_mm,'cylinder tolerance',positive=True)
    origin=cq.Vector(*axis.origin_mm);direction=cq.Vector(*axis.direction)
    areas=[]
    for face in shape.Faces():
        if face.geomType()!='CYLINDER':continue
        cylinder=BRepAdaptor_Surface(face.wrapped).Cylinder()
        d=cylinder.Axis().Direction();p=cylinder.Axis().Location()
        face_direction=cq.Vector(d.X(),d.Y(),d.Z());location=cq.Vector(p.X(),p.Y(),p.Z())
        offset=location-origin
        if (abs(abs(direction.dot(face_direction))-1)<=1e-8
            and offset.cross(direction).Length<=tolerance and abs(cylinder.Radius()-radius)<=tolerance):
            areas.append(integrated_area(face))
    return {'radius_mm':radius,'face_count':len(areas),'area_mm2':sum(areas),'tolerance_mm':tolerance}
