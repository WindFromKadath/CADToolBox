"""Explicit normalized UV bases, Coons boundaries from S035/S042.

DXF geometry is local XY millimetres and is mapped through the shared frame.
Two corner anchors define U/V semantics; curve parameter samples preserve
actual ARC/BSPLINE geometry instead of replacing curves by endpoint chords.
"""
from itertools import permutations,product
from math import dist
import cadquery as cq
from ..contracts import Axis,Frame,ContractError,finite,vector,ShapeExpectation,ShapeKind
from .transforms import transform_shape
from .quality import GeometryError,validate_shape

CORNERS={'p00':(0,0),'p10':(1,0),'p11':(1,1),'p01':(0,1)}


def uv(u,v):
    u=finite(u,'u');v=finite(v,'v')
    if not 0<=u<=1 or not 0<=v<=1:raise ContractError('UV parameters must lie in [0,1]')
    return u,v


def edge_point(edge,t,reverse=False):
    curve=edge._geomAdaptor()
    t=1-t if reverse else t
    return cq.Vector(curve.Value(curve.FirstParameter()+t*(curve.LastParameter()-curve.FirstParameter()))).toTuple()


class RectangularBase:
    def __init__(self,frame:Frame,axial_bounds_mm,radial_bounds_mm):
        self.frame=frame
        self.x0,self.x1=[finite(x,'axial bound') for x in axial_bounds_mm]
        self.r0,self.r1=[finite(r,'radial bound',positive=True) for r in radial_bounds_mm]
        if self.x1<=self.x0 or self.r1<=self.r0:raise ContractError('ordered base bounds required')
        self.report={'mode':'rectangular_annulus','axial_bounds_mm':[self.x0,self.x1],'radial_bounds_mm':[self.r0,self.r1],'unit':'mm','uv':'u axial, v radial'}
    def evaluate(self,u,v):
        u,v=uv(u,v)
        return self.frame.to_world((self.x0+(self.x1-self.x0)*u,self.r0+(self.r1-self.r0)*v,0))
    def corners(self):return {k:self.evaluate(*q) for k,q in CORNERS.items()}
    def build_face(self):
        c=list(self.corners().values())
        face=cq.Face.makeFromWires(cq.Wire.assembleEdges([cq.Edge.makeLine(c[i],c[(i+1)%4]) for i in range(4)]))
        validate_shape(face,ShapeExpectation(ShapeKind.FACE,0));return face


class CoonsBase:
    def __init__(self,edges,frame:Frame,*,start_mm,next_mm,endpoint_tolerance_mm=1e-7):
        if len(edges)!=4:raise ContractError('exactly four boundary edges required')
        self.frame=frame;tol=finite(endpoint_tolerance_mm,'endpoint tolerance',positive=True)
        start=vector(start_mm,'p00 anchor');next_point=vector(next_mm,'p10 anchor')
        best=None
        for perm in permutations(edges):
            for flips in product((False,True),repeat=4):
                ends=[(edge_point(e,0,f),edge_point(e,1,f)) for e,f in zip(perm,flips)]
                score=max([dist(ends[i][1],ends[(i+1)%4][0]) for i in range(4)]+[dist(ends[0][0],start),dist(ends[0][1],next_point)])
                if best is None or score<best[0]:best=(score,list(zip(perm,flips)),ends)
        if best[0]>tol:raise GeometryError('boundary_order','four edges cannot satisfy explicit corner anchors and connectivity',{'max_gap_mm':best[0],'limit_mm':tol})
        self.edges=best[1];self.local_corners=[x[0] for x in best[2]]
        if any(dist(self.local_corners[i],self.local_corners[j])<=tol for i in range(4) for j in range(i)):
            raise ContractError('four distinct noncollapsed corners required')
        local_wire=cq.Wire.assembleEdges([e for e,_ in self.edges])
        if not local_wire.IsClosed() or not local_wire.isValid():raise GeometryError('boundary_wire','invalid closed boundary')
        local_face=cq.Face.makeFromWires(local_wire)
        validate_shape(local_face,ShapeExpectation(ShapeKind.FACE,0))
        if any(abs(p[2])>tol for e,_ in self.edges for p in [edge_point(e,t) for t in [0,.25,.5,.75,1]]):
            raise ContractError('Coons DXF base currently requires local XY curves')
        self.face=transform_shape(local_face,frame)
        self.report={'mode':'four_edge_coons','unit':'mm','curve_types':[e.geomType() for e,_ in self.edges],
                     'max_endpoint_gap_mm':best[0],'endpoint_limit_mm':tol,'start_anchor_mm':start,'u_next_anchor_mm':next_point,
                     'uv':'ordered p00 -> p10 -> p11 -> p01; normalized underlying curve parameters',
                     'base_face':'exact planar Wire, no boundary chord substitution'}
        # Sampled mapping validation is an explicit limit, not a global theorem.
        signs=[]
        for i in range(17):
            for j in range(17):
                u=i/16;v=j/16;p=self.evaluate(u,v)
                if cq.Vertex.makeVertex(*p).distance(self.face)>max(1e-7,tol):
                    raise GeometryError('coons_outside','Coons parameter map exits its exact planar boundary')
                h=1e-5;ua=max(0,u-h);ub=min(1,u+h);va=max(0,v-h);vb=min(1,v+h)
                a=cq.Vector(*self.evaluate(ub,v))-cq.Vector(*self.evaluate(ua,v))
                b=cq.Vector(*self.evaluate(u,vb))-cq.Vector(*self.evaluate(u,va))
                jac=a.cross(b).dot(cq.Vector(*frame.radial_2))/((ub-ua)*(vb-va))
                if abs(jac)<1e-10:raise GeometryError('coons_degenerate','sampled Coons map is locally singular')
                signs.append(jac>0)
        if any(s!=signs[0] for s in signs):raise GeometryError('coons_fold','sampled Coons map changes orientation')
        self.report['map_validation']={'samples':17*17,'consistent_orientation':True,'scope':'sampled local mapping, not global self-intersection proof'}
    def evaluate(self,u,v):
        u,v=uv(u,v)
        e=self.edges
        a=edge_point(e[0][0],u,e[0][1])
        b=edge_point(e[1][0],v,e[1][1])
        c=edge_point(e[2][0],1-u,e[2][1])
        d=edge_point(e[3][0],1-v,e[3][1])
        p00,p10,p11,p01=self.local_corners
        p=tuple((1-v)*a[k]+v*c[k]+(1-u)*d[k]+u*b[k]-((1-u)*(1-v)*p00[k]+u*(1-v)*p10[k]+u*v*p11[k]+(1-u)*v*p01[k]) for k in range(3))
        return self.frame.to_world(p)
    def corners(self):return {k:self.evaluate(*q) for k,q in CORNERS.items()}
    def build_face(self):return self.face
