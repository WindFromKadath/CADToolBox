"""S023 junction rules for extruded blades and CYLINDER/CONE/TORUS/PLANE rotors.

This is a specialised two-end rotor rule, applied in an explicit local frame.
Expected edge counts and probe scale are caller constraints, never inferred.
"""
from __future__ import annotations
import cadquery as cq
from collections import Counter
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from OCP.gp import gp_Pnt
ROTOR_SURFACE_TYPES=frozenset({'CYLINDER','CONE','TORUS','PLANE'})
BLADE_SURFACE_TYPE='EXTRUSION'


def recognize_concave_junction_edges(
    fused: cq.Solid,
    *, probe_mm: float = 0.1, classification_tolerance_mm: float = 1e-7,
) -> tuple[list[cq.Edge], Counter[tuple[str, str]], int]:
    edge_faces = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndUniqueAncestors_s(
        fused.wrapped,
        TopAbs_EDGE,
        TopAbs_FACE,
        edge_faces,
        False,
    )
    selected: list[cq.Edge] = []
    type_counts: Counter[tuple[str, str]] = Counter()
    semantic_candidates = 0
    for index in range(1, edge_faces.Extent() + 1):
        faces = [cq.Face(face) for face in edge_faces.FindFromIndex(index)]
        if len(faces) != 2:
            continue
        types = tuple(sorted(face.geomType() for face in faces))
        if BLADE_SURFACE_TYPE not in types or not any(
            value in types for value in ROTOR_SURFACE_TYPES
        ):
            continue
        semantic_candidates += 1
        edge = cq.Edge(edge_faces.FindKey(index))
        point = edge.positionAt(0.5)
        normal_1 = faces[0].normalAt(point)
        normal_2 = faces[1].normalAt(point)
        states = []
        for direction in (normal_1 - normal_2, normal_2 - normal_1):
            if direction.Length < 1.0e-10:
                states.append(None)
                continue
            probe = point + direction.normalized() * probe_mm
            classifier = BRepClass3d_SolidClassifier(
                fused.wrapped,
                gp_Pnt(probe.x, probe.y, probe.z),
                classification_tolerance_mm,
            )
            states.append(classifier.State())
        if states == [TopAbs_IN, TopAbs_IN]:
            selected.append(edge)
            type_counts[types] += 1
    if not selected:
        raise RuntimeError("未识别到叶片—转子内凹连接边")
    return selected, type_counts, semantic_candidates


def split_junction_edges_by_x(
    edges: list[cq.Edge],
    *,
    expected_low: int,
    expected_high: int,
) -> tuple[list[cq.Edge], list[cq.Edge], float]:
    if len(edges) < 2:
        raise ValueError("至少需要2条连接边")
    ordered = sorted(edges, key=lambda edge: edge.positionAt(0.5).x)
    x_values = [edge.positionAt(0.5).x for edge in ordered]
    gaps = [right - left for left, right in zip(x_values, x_values[1:])]
    split_index = max(range(len(gaps)), key=gaps.__getitem__) + 1
    low_x = ordered[:split_index]
    high_x = ordered[split_index:]
    if len(low_x) != expected_low or len(high_x) != expected_high:
        raise RuntimeError(
            f"low/high-X内凹边数量应为 {expected_low}/{expected_high}，"
            f"实际为 {len(low_x)}/{len(high_x)}"
        )
    split_x = 0.5 * (x_values[split_index - 1] + x_values[split_index])
    return low_x, high_x, split_x


def apply_split_radius_fillet(
    fused: cq.Solid,
    low_x_edges: list[cq.Edge],
    high_x_edges: list[cq.Edge],
    *,
    low_x_radius: float,
    high_x_radius: float,
) -> cq.Solid:
    builder = BRepFilletAPI_MakeFillet(fused.wrapped)
    for edge in low_x_edges:
        builder.Add(low_x_radius, edge.wrapped)
    for edge in high_x_edges:
        builder.Add(high_x_radius, edge.wrapped)
    builder.Build()
    if not builder.IsDone():
        raise RuntimeError("双半径圆角构造失败")
    solids = cq.Shape.cast(builder.Shape()).Solids()
    if len(solids) != 1:
        raise RuntimeError(f"圆角后应为1个 Solid，实际为 {len(solids)}")
    rounded = solids[0]
    if (
        len(rounded.Shells()) != 1
        or not BRepCheck_Analyzer(rounded.wrapped).IsValid()
    ):
        raise RuntimeError("圆角结果不是有效单壳 Solid")
    return rounded
