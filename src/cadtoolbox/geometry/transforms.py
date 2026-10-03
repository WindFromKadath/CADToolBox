"""Exact rigid transforms between the shared local frame and world coordinates."""
import cadquery as cq
from OCP.gp import gp_Trsf
from ..contracts import Frame,dot


def transform_shape(shape: cq.Shape,frame: Frame,*,to_local: bool=False):
    bases=(frame.axis.direction,frame.radial_reference,frame.radial_2)
    if to_local:
        rows=[(*b,-dot(b,frame.axis.origin_mm)) for b in bases]
    else:
        rows=[(*(bases[j][i] for j in range(3)),frame.axis.origin_mm[i]) for i in range(3)]
    transform=gp_Trsf();transform.SetValues(*(v for row in rows for v in row))
    return shape.transformShape(cq.Matrix(transform))
