"""Pure shared-boundary helpers extracted from audited S036, no legacy imports."""
import itertools,math
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge,BRepBuilderAPI_MakeWire
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeFilling
from OCP.GeomAbs import GeomAbs_Shape
from OCP.TopAbs import TopAbs_EDGE,TopAbs_REVERSED,TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt
LABEL_PAIRS={'u0':('p00','p01'),'u1':('p10','p11'),'v0':('p00','p10'),'v1':('p01','p11')}

def _xyz(point):
    return float(point.X()), float(point.Y()), float(point.Z())

def _endpoints(edge):
    curve = BRepAdaptor_Curve(edge)
    ends = (
        _xyz(curve.Value(curve.FirstParameter())),
        _xyz(curve.Value(curve.LastParameter())),
    )
    return (ends[1], ends[0]) if edge.Orientation() == TopAbs_REVERSED else ends

def _pair_cost(edge, a, b):
    p, q = _endpoints(edge)
    return min(math.dist(p, a) + math.dist(q, b),
               math.dist(p, b) + math.dist(q, a))

def classify_edges(face, target_corners: dict):
    edges = []
    explorer = TopExp_Explorer(face, TopAbs_EDGE)
    while explorer.More():
        edges.append(TopoDS.Edge_s(explorer.Current()))
        explorer.Next()
    if len(edges) != 4:
        raise RuntimeError(f"叶片边界面应有 4 条边，实际得到 {len(edges)} 条")

    labels = tuple(LABEL_PAIRS)
    best = None
    for permutation in itertools.permutations(edges):
        cost = sum(
            _pair_cost(edge, target_corners[a], target_corners[b])
            for edge, label in zip(permutation, labels)
            for a, b in [LABEL_PAIRS[label]]
        )
        if best is None or cost < best[0]:
            best = cost, dict(zip(labels, permutation))
    return best[1]

def actual_corners(face, target_corners: dict):
    vertices = []
    explorer = TopExp_Explorer(face, TopAbs_VERTEX)
    while explorer.More():
        vertex = TopoDS.Vertex_s(explorer.Current())
        vertices.append(_xyz(BRep_Tool.Pnt_s(vertex)))
        explorer.Next()
    unique = []
    for point in vertices:
        if not any(math.dist(point, other) < 1e-10 for other in unique):
            unique.append(point)
    return {
        key: min(unique, key=lambda point: math.dist(point, target))
        for key, target in target_corners.items()
    }

def _reversed(edge):
    return TopoDS.Edge_s(edge.Reversed())

def _order_edges(edges, gap_tolerance: float):
    best = None
    for permutation in itertools.permutations(edges):
        for reversals in itertools.product((False, True), repeat=4):
            candidate = [
                _reversed(edge) if reverse else edge
                for edge, reverse in zip(permutation, reversals)
            ]
            ends = [_endpoints(edge) for edge in candidate]
            gaps = [
                math.dist(ends[i][1], ends[(i + 1) % 4][0])
                for i in range(4)
            ]
            score = max(gaps)
            if best is None or score < best[0]:
                best = score, candidate
    if best[0] > gap_tolerance:
        raise RuntimeError(f"侧面边界未闭合，最大端点间隙 {best[0]:.6g} mm")
    return best[1]

def _filled_face(edges, gap_tolerance: float, filling_tolerance: float = 1e-7):
    ordered = _order_edges(edges, gap_tolerance)
    wire_builder = BRepBuilderAPI_MakeWire()
    for edge in ordered:
        wire_builder.Add(edge)
    if not wire_builder.IsDone():
        raise RuntimeError("无法构建侧面 Wire")

    filling = BRepOffsetAPI_MakeFilling(Tol2d=min(1e-7, filling_tolerance), Tol3d=filling_tolerance)
    for edge in ordered:
        filling.Add(edge, GeomAbs_Shape.GeomAbs_C0, True)
    filling.Build()
    if not filling.IsDone():
        raise RuntimeError("无法填充叶片侧面")
    return TopoDS.Face_s(filling.Shape())

def build_all_side_faces(
    lower_face,
    upper_face,
    lower_targets: dict,
    upper_targets: dict,
    gap_tolerance: float = 1e-5,
    filling_tolerance: float = 1e-7,
):
    lower_edges = classify_edges(lower_face, lower_targets)
    upper_edges = classify_edges(upper_face, upper_targets)
    lower_corners = actual_corners(lower_face, lower_targets)
    upper_corners = actual_corners(upper_face, upper_targets)
    connectors = {
        key: BRepBuilderAPI_MakeEdge(
            gp_Pnt(*lower_corners[key]), gp_Pnt(*upper_corners[key]),
        ).Edge()
        for key in ("p00", "p10", "p11", "p01")
    }
    sides = [
        _filled_face([lower_edges["u0"], connectors["p01"],
                      upper_edges["u0"], connectors["p00"]], gap_tolerance, filling_tolerance),
        _filled_face([lower_edges["u1"], connectors["p11"],
                      upper_edges["u1"], connectors["p10"]], gap_tolerance, filling_tolerance),
        _filled_face([lower_edges["v0"], connectors["p10"],
                      upper_edges["v0"], connectors["p00"]], gap_tolerance, filling_tolerance),
        _filled_face([lower_edges["v1"], connectors["p11"],
                      upper_edges["v1"], connectors["p01"]], gap_tolerance, filling_tolerance),
    ]
    return [lower_face, upper_face, *sides]
