"""从干净或已裁剪的工程线稿中提取二维几何基元候选。

这是图纸语义理解之前的轻量基线：它只回答“哪些像素看起来属于直线、
圆或圆弧”，不尝试识别尺寸文字，也不把像素长度解释为毫米。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .profiles import sha256_file
from .config import number
from ..contracts import ContractError


PixelPoint = tuple[float, float]
GridPoint = tuple[int, int]


@dataclass(frozen=True)
class PrimitiveExtractionConfig:
    threshold: int | None = None
    foreground: str = "dark"
    minimum_component_pixels: int = 12
    minimum_chain_length_px: float = 12.0
    line_max_rmse_px: float = 1.15
    circle_max_rmse_px: float = 1.75
    minimum_arc_degrees: float = 30.0
    full_circle_degrees: float = 330.0
    fallback_polyline_tolerance_px: float = 2.0
    thinning_max_iterations: int = 200

    def __post_init__(self):
        if self.threshold is not None:number(self.threshold,'threshold',minimum=0,maximum=255,integer=True)
        if self.foreground not in {'dark','light'}:raise ContractError('invalid foreground')
        number(self.minimum_component_pixels,'minimum component',minimum=1,integer=True)
        number(self.thinning_max_iterations,'thinning limit',minimum=1,maximum=2000,integer=True)
        for name in ['minimum_chain_length_px','line_max_rmse_px','circle_max_rmse_px','fallback_polyline_tolerance_px']:
            number(getattr(self,name),name,minimum=1e-9)
        number(self.minimum_arc_degrees,'minimum arc',minimum=1e-9,maximum=360)
        number(self.full_circle_degrees,'full circle',minimum=self.minimum_arc_degrees,maximum=360)



@dataclass(frozen=True)
class LinePrimitive:
    id: str
    type: str
    start_px: PixelPoint
    end_px: PixelPoint
    length_px: float
    angle_deg: float
    fit_rmse_px: float | None
    confidence: float
    source_point_count: int
    source_chain_id: str = ''
    fit_method: str = ''
    fit_max_error_px: float | None = None
    status: str = 'candidate'


@dataclass(frozen=True)
class CirclePrimitive:
    id: str
    type: str
    center_px: PixelPoint
    radius_px: float
    fit_rmse_px: float | None
    confidence: float
    source_point_count: int
    source_chain_id: str = ''
    fit_method: str = ''
    fit_max_error_px: float | None = None
    status: str = 'candidate'


@dataclass(frozen=True)
class ArcPrimitive:
    id: str
    type: str
    center_px: PixelPoint
    radius_px: float
    start_angle_deg: float
    end_angle_deg: float
    sweep_angle_deg: float
    clockwise: bool
    start_px: PixelPoint
    end_px: PixelPoint
    fit_rmse_px: float | None
    confidence: float
    source_point_count: int
    source_chain_id: str = ''
    fit_method: str = ''
    fit_max_error_px: float | None = None
    status: str = 'candidate'
    endpoint_method: str = 'skeleton endpoints projected to fitted circle'
    skeleton_sweep_angle_deg: float | None = None
    support_component_pixel_count: int | None = None


Primitive = LinePrimitive | CirclePrimitive | ArcPrimitive


@dataclass(frozen=True)
class PrimitiveExtractionResult:
    image_path: Path
    image_size_px: tuple[int, int]
    threshold_used: int
    foreground_pixel_count: int
    skeleton_pixel_count: int
    component_count: int
    chain_count: int
    primitives: tuple[Primitive, ...]
    source_sha256: str
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        counts = {"line": 0, "circle": 0, "arc": 0}
        primitive_values: list[dict[str, object]] = []
        for primitive in self.primitives:
            counts[primitive.type] += 1
            primitive_values.append(asdict(primitive))
        return {
            "schema_version": 1,
            "success": True,
            "status": "candidates_pending_confirmation" if self.primitives else "no_candidates",
            "geometry_eligible": False,
            "physical_calibration": None,
            "confidence_semantics": "heuristic fit score; not calibrated probability or dimension certainty",
            "diagnostics": self.diagnostics,
            "coordinate_system": {
                "unit": "pixel",
                "origin": "image_top_left",
                "x_direction": "right",
                "y_direction": "down",
            },
            "source": {
                "file": str(self.image_path),
                "sha256": self.source_sha256,
                "image_size_px": list(self.image_size_px),
            },
            "preprocessing": {
                "threshold_used": self.threshold_used,
                "foreground_pixel_count": self.foreground_pixel_count,
                "skeleton_pixel_count": self.skeleton_pixel_count,
                "component_count": self.component_count,
                "chain_count": self.chain_count,
            },
            "summary": {
                "primitive_count": len(self.primitives),
                "counts_by_type": counts,
            },
            "primitives": primitive_values,
            "limitations": [
                "所有坐标仍为像素坐标，不能作为图纸毫米尺寸",
                "尚未区分零件轮廓、尺寸线、中心线、引出线和文字",
                "低置信度折线可能被拆成多个直线候选",
                "骨架半径近似笔画中心；孤立弧端点按原像素角度范围投影，不能恢复设计圆弧端点或语义",
            ],
        }


def _otsu_threshold(gray: np.ndarray) -> int:
    histogram = np.bincount(gray.ravel(), minlength=256).astype(float)
    total = float(gray.size)
    weighted_total = float(np.dot(np.arange(256), histogram))
    background_weight = 0.0
    background_sum = 0.0
    maximum_variance = -1.0
    best_threshold = 127
    for threshold in range(256):
        background_weight += histogram[threshold]
        if background_weight == 0.0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight == 0.0:
            break
        background_sum += threshold * histogram[threshold]
        background_mean = background_sum / background_weight
        foreground_mean = (
            weighted_total - background_sum
        ) / foreground_weight
        variance = (
            background_weight
            * foreground_weight
            * (background_mean - foreground_mean) ** 2
        )
        if variance > maximum_variance:
            maximum_variance = variance
            best_threshold = threshold
    return best_threshold


def _connected_components(
    mask: np.ndarray,
) -> tuple[np.ndarray, list[list[GridPoint]]]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[list[GridPoint]] = []
    for y_value, x_value in zip(*np.nonzero(mask), strict=True):
        if visited[y_value, x_value]:
            continue
        stack = [(int(y_value), int(x_value))]
        visited[y_value, x_value] = True
        component: list[GridPoint] = []
        while stack:
            y_current, x_current = stack.pop()
            component.append((y_current, x_current))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    y_next = y_current + dy
                    x_next = x_current + dx
                    if (
                        0 <= y_next < height
                        and 0 <= x_next < width
                        and mask[y_next, x_next]
                        and not visited[y_next, x_next]
                    ):
                        visited[y_next, x_next] = True
                        stack.append((y_next, x_next))
        components.append(component)
    return visited, components


def _remove_small_components(
    mask: np.ndarray,
    minimum_pixels: int,
) -> tuple[np.ndarray, int]:
    _, components = _connected_components(mask)
    cleaned = np.zeros_like(mask, dtype=bool)
    retained = 0
    for component in components:
        if len(component) < minimum_pixels:
            continue
        retained += 1
        ys, xs = zip(*component, strict=True)
        cleaned[np.asarray(ys), np.asarray(xs)] = True
    return cleaned, retained


def _transitions(neighbors: list[bool]) -> int:
    return sum(
        not neighbors[index] and neighbors[(index + 1) % 8]
        for index in range(8)
    )


def _thin(mask: np.ndarray, maximum_iterations: int) -> np.ndarray:
    """Zhang-Suen thinning，返回单像素宽骨架。"""
    image = np.pad(mask.astype(np.uint8), 1)
    for _ in range(maximum_iterations):
        changed = False
        for first_step in (True, False):
            to_remove: list[GridPoint] = []
            ys, xs = np.nonzero(image)
            for y_value, x_value in zip(ys, xs, strict=True):
                if (
                    y_value == 0
                    or x_value == 0
                    or y_value == image.shape[0] - 1
                    or x_value == image.shape[1] - 1
                ):
                    continue
                p2 = bool(image[y_value - 1, x_value])
                p3 = bool(image[y_value - 1, x_value + 1])
                p4 = bool(image[y_value, x_value + 1])
                p5 = bool(image[y_value + 1, x_value + 1])
                p6 = bool(image[y_value + 1, x_value])
                p7 = bool(image[y_value + 1, x_value - 1])
                p8 = bool(image[y_value, x_value - 1])
                p9 = bool(image[y_value - 1, x_value - 1])
                neighbors = [p2, p3, p4, p5, p6, p7, p8, p9]
                count = sum(neighbors)
                if count < 2 or count > 6 or _transitions(neighbors) != 1:
                    continue
                if first_step:
                    condition_a = p2 and p4 and p6
                    condition_b = p4 and p6 and p8
                else:
                    condition_a = p2 and p4 and p8
                    condition_b = p2 and p6 and p8
                if not condition_a and not condition_b:
                    to_remove.append((int(y_value), int(x_value)))
            if to_remove:
                changed = True
                ys_remove, xs_remove = zip(*to_remove, strict=True)
                image[np.asarray(ys_remove), np.asarray(xs_remove)] = 0
        if not changed:
            return image[1:-1, 1:-1].astype(bool)
    raise ValueError('thinning did not converge within declared iteration limit')


def _neighbors(
    point: GridPoint,
    pixels: set[GridPoint],
) -> list[GridPoint]:
    y_value, x_value = point
    candidates: list[GridPoint] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            neighbor = (y_value + dy, x_value + dx)
            if neighbor not in pixels:
                continue
            # 若斜向连接可经任一正交中间像素到达，忽略冗余对角边。
            # 这会消除数字骨架拐弯处常见的小三角，否则一个圆会被错误
            # 拆成许多分支链；真正的 45° 单像素线仍保留对角连接。
            if (
                dx != 0
                and dy != 0
                and (
                    (y_value + dy, x_value) in pixels
                    or (y_value, x_value + dx) in pixels
                )
            ):
                continue
            candidates.append(neighbor)
    return candidates


def _edge_key(first: GridPoint, second: GridPoint) -> tuple[GridPoint, GridPoint]:
    return (first, second) if first <= second else (second, first)


def _trace_skeleton(skeleton: np.ndarray) -> list[list[PixelPoint]]:
    pixels = {
        (int(y_value), int(x_value))
        for y_value, x_value in zip(*np.nonzero(skeleton), strict=True)
    }
    adjacency = {
        point: _neighbors(point, pixels)
        for point in pixels
    }
    visited_edges: set[tuple[GridPoint, GridPoint]] = set()
    chains: list[list[PixelPoint]] = []

    def trace(start: GridPoint, next_point: GridPoint) -> list[GridPoint]:
        chain = [start, next_point]
        visited_edges.add(_edge_key(start, next_point))
        previous = start
        current = next_point
        while len(adjacency[current]) == 2:
            candidates = [
                point for point in adjacency[current] if point != previous
            ]
            if not candidates:
                break
            following = candidates[0]
            edge = _edge_key(current, following)
            if edge in visited_edges:
                break
            visited_edges.add(edge)
            chain.append(following)
            previous, current = current, following
        return chain

    nodes = [point for point, links in adjacency.items() if len(links) != 2]
    for node in sorted(nodes):
        for neighbor in adjacency[node]:
            if _edge_key(node, neighbor) in visited_edges:
                continue
            chain = trace(node, neighbor)
            chains.append([(float(x), float(y)) for y, x in chain])

    # 没有端点的闭环。
    for point in sorted(pixels):
        for neighbor in adjacency[point]:
            if _edge_key(point, neighbor) in visited_edges:
                continue
            chain = trace(point, neighbor)
            if chain[-1] != point and point in adjacency[chain[-1]]:
                visited_edges.add(_edge_key(chain[-1], point))
                chain.append(point)
            chains.append([(float(x), float(y)) for y, x in chain])
    return chains


def _polyline_length(points: Iterable[PixelPoint]) -> float:
    values = list(points)
    return sum(math.dist(first, second) for first, second in zip(values, values[1:]))


def _fit_line(
    points: list[PixelPoint],
) -> tuple[PixelPoint, PixelPoint, float]:
    values = np.asarray(points, dtype=float)
    center = values.mean(axis=0)
    _, _, vectors = np.linalg.svd(values - center, full_matrices=False)
    direction = vectors[0]
    projections = (values - center) @ direction
    start = center + direction * projections.min()
    end = center + direction * projections.max()
    distances = np.abs(
        (values[:, 0] - center[0]) * direction[1]
        - (values[:, 1] - center[1]) * direction[0]
    )
    return (
        (float(start[0]), float(start[1])),
        (float(end[0]), float(end[1])),
        float(np.sqrt(np.mean(distances**2))),
    )


def _fit_circle(
    points: list[PixelPoint],
) -> tuple[PixelPoint, float, float] | None:
    if len(points) < 5:
        return None
    values = np.asarray(points, dtype=float)
    matrix = np.column_stack(
        (2.0 * values[:, 0], 2.0 * values[:, 1], np.ones(len(values)))
    )
    target = values[:, 0] ** 2 + values[:, 1] ** 2
    solution, _, rank, _ = np.linalg.lstsq(matrix, target, rcond=None)
    if rank < 3:
        return None
    center_x, center_y, constant = solution
    radius_squared = constant + center_x**2 + center_y**2
    if radius_squared <= 0.0:
        return None
    radius = float(math.sqrt(radius_squared))
    distances = np.hypot(
        values[:, 0] - center_x,
        values[:, 1] - center_y,
    )
    rmse = float(np.sqrt(np.mean((distances - radius) ** 2)))
    return ((float(center_x), float(center_y)), radius, rmse)


def _arc_angles(
    points: list[PixelPoint],
    center: PixelPoint,
) -> tuple[float, float, float, bool]:
    center_x, center_y = center
    raw = np.asarray(
        [
            math.atan2(y_value - center_y, x_value - center_x)
            for x_value, y_value in points
        ],
        dtype=float,
    )
    unwrapped = np.unwrap(raw)
    start = math.degrees(float(unwrapped[0]))
    end = math.degrees(float(unwrapped[-1]))
    signed_sweep = end - start
    # 图像坐标 y 向下，因此 atan2 角度正方向在画面上表现为顺时针。
    return start % 360.0, end % 360.0, abs(signed_sweep), signed_sweep > 0.0


def _point_segment_distance(
    point: PixelPoint,
    start: PixelPoint,
    end: PixelPoint,
) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    denominator = dx * dx + dy * dy
    if denominator <= 1.0e-12:
        return math.dist(point, start)
    parameter = ((px - ax) * dx + (py - ay) * dy) / denominator
    parameter = max(0.0, min(1.0, parameter))
    return math.hypot(
        px - (ax + parameter * dx),
        py - (ay + parameter * dy),
    )


def _rdp(points: list[PixelPoint], tolerance: float) -> list[PixelPoint]:
    if len(points) <= 2:
        return points
    distances = [
        _point_segment_distance(point, points[0], points[-1])
        for point in points[1:-1]
    ]
    if not distances:
        return [points[0], points[-1]]
    maximum = max(distances)
    if maximum <= tolerance:
        return [points[0], points[-1]]
    index = distances.index(maximum) + 1
    left = _rdp(points[: index + 1], tolerance)
    right = _rdp(points[index:], tolerance)
    return left[:-1] + right


def _confidence(rmse: float, tolerance: float, coverage: float = 1.0) -> float:
    fit_score = max(0.0, 1.0 - rmse / max(tolerance, 1.0e-9))
    return round(max(0.01, min(0.99, 0.55 + 0.44 * fit_score * coverage)), 4)


def _classify_chains(
    chains: list[list[PixelPoint]],
    config: PrimitiveExtractionConfig,
) -> list[Primitive]:
    raw: list[tuple[str, dict[str, object]]] = []
    for chain_index,points in enumerate(chains,1):
        length = _polyline_length(points)
        if length < config.minimum_chain_length_px or len(points) < 2:
            continue

        start, end, line_rmse = _fit_line(points)
        if line_rmse <= config.line_max_rmse_px:
            line_length = math.dist(start, end)
            if line_length >= config.minimum_chain_length_px:
                raw.append(
                    (
                        "line",
                        {
                            "start_px": start,
                            "end_px": end,
                            "length_px": line_length,
                            "angle_deg": math.degrees(
                                math.atan2(
                                    end[1] - start[1],
                                    end[0] - start[0],
                                )
                            ),
                            "fit_rmse_px": line_rmse,
                            "fit_method": "least_squares_line",
                            "fit_max_error_px": max(_point_segment_distance(p,start,end) for p in points),
                            "confidence": _confidence(
                                line_rmse,
                                config.line_max_rmse_px,
                            ),
                            "source_point_count": len(points),
                            "source_chain_id": f"K{chain_index:04d}",
                        },
                    )
                )
                continue

        circle_fit = _fit_circle(points)
        if circle_fit is not None:
            center, radius, circle_rmse = circle_fit
            start_angle, end_angle, sweep, clockwise = _arc_angles(
                points,
                center,
            )
            if (
                circle_rmse <= config.circle_max_rmse_px
                and sweep >= config.minimum_arc_degrees
            ):
                coverage = min(1.0, sweep / 180.0)
                if sweep >= config.full_circle_degrees and math.dist(points[0],points[-1])<=math.sqrt(2)+1e-9:
                    raw.append(
                        (
                            "circle",
                            {
                                "center_px": center,
                                "radius_px": radius,
                                "fit_rmse_px": circle_rmse,
                                "fit_method": "algebraic_circle",
                                "fit_max_error_px": max(abs(math.dist(p,center)-radius) for p in points),
                                "confidence": _confidence(
                                    circle_rmse,
                                    config.circle_max_rmse_px,
                                    coverage,
                                ),
                                "source_point_count": len(points),
                            "source_chain_id": f"K{chain_index:04d}",
                            },
                        )
                    )
                else:
                    raw.append(
                        (
                            "arc",
                            {
                                "center_px": center,
                                "radius_px": radius,
                                "start_angle_deg": start_angle,
                                "end_angle_deg": end_angle,
                                "sweep_angle_deg": sweep,
                                "clockwise": clockwise,
                                "start_px": (center[0]+radius*math.cos(math.radians(start_angle)),center[1]+radius*math.sin(math.radians(start_angle))),
                                "end_px": (center[0]+radius*math.cos(math.radians(end_angle)),center[1]+radius*math.sin(math.radians(end_angle))),
                                "fit_rmse_px": circle_rmse,
                                "fit_method": "algebraic_circle",
                                "fit_max_error_px": max(abs(math.dist(p,center)-radius) for p in points),
                                "confidence": _confidence(
                                    circle_rmse,
                                    config.circle_max_rmse_px,
                                    coverage,
                                ),
                                "source_point_count": len(points),
                            "source_chain_id": f"K{chain_index:04d}",
                            },
                        )
                    )
                continue

        # 无法整体拟合时，保守降级为简化折线候选。
        simplified = _rdp(points, config.fallback_polyline_tolerance_px)
        for first, second in zip(simplified, simplified[1:]):
            segment_length = math.dist(first, second)
            if segment_length < config.minimum_chain_length_px:
                continue
            raw.append(
                (
                    "line",
                    {
                        "start_px": first,
                        "end_px": second,
                        "length_px": segment_length,
                        "angle_deg": math.degrees(
                            math.atan2(
                                second[1] - first[1],
                                second[0] - first[0],
                            )
                        ),
                        "fit_rmse_px": None,
                        "fit_method": "rdp_fallback_polyline",
                        "confidence": 0.35,
                        "source_point_count": len(points),
                            "source_chain_id": f"K{chain_index:04d}",
                    },
                )
            )

    primitives: list[Primitive] = []
    counters = {"line": 0, "circle": 0, "arc": 0}
    prefixes = {"line": "L", "circle": "C", "arc": "A"}
    for primitive_type, values in raw:
        counters[primitive_type] += 1
        primitive_id = f"{prefixes[primitive_type]}{counters[primitive_type]:03d}"
        if primitive_type == "line":
            primitives.append(
                LinePrimitive(
                    id=primitive_id,
                    type="line",
                    **values,
                )
            )
        elif primitive_type == "circle":
            primitives.append(
                CirclePrimitive(
                    id=primitive_id,
                    type="circle",
                    **values,
                )
            )
        else:
            primitives.append(
                ArcPrimitive(
                    id=primitive_id,
                    type="arc",
                    **values,
                )
            )
    return primitives


def _recover_isolated_arc_extent(primitives,chains,mask):
    """Recover angular stroke support only when an entire component has one chain.
    Thinning erodes end caps. Do not join branches or infer occluded endpoints.
    Radius and fit residuals still describe the skeleton circle hypothesis.
    """
    _,components=_connected_components(mask)
    lookup={p:i for i,c in enumerate(components) for p in c}
    by_component={}
    for i,chain in enumerate(chains,1):
        key=lookup.get((round(chain[0][1]),round(chain[0][0])))
        by_component.setdefault(key,[]).append(f'K{i:04d}')
    result=[]
    for primitive in primitives:
        if not isinstance(primitive,ArcPrimitive):result.append(primitive);continue
        index=next((i for i,ids in by_component.items() if ids==[primitive.source_chain_id]),None)
        if index is None:result.append(primitive);continue
        pts=components[index];cx,cy=primitive.center_px
        direction=1 if primitive.clockwise else -1
        midpoint=math.radians(primitive.start_angle_deg+direction*primitive.sweep_angle_deg/2)
        angles=[midpoint+math.atan2(math.sin(math.atan2(y-cy,x-cx)-midpoint),math.cos(math.atan2(y-cy,x-cx)-midpoint)) for y,x in pts]
        low,high=min(angles),max(angles);span=math.degrees(high-low)
        # Ambiguous support crossing the opposite side is retained unchanged.
        if span>primitive.sweep_angle_deg+30 or span>=330:result.append(primitive);continue
        start,end=(low,high) if primitive.clockwise else (high,low)
        projected=lambda a:(cx+primitive.radius_px*math.cos(a),cy+primitive.radius_px*math.sin(a))
        result.append(replace(primitive,start_angle_deg=math.degrees(start)%360,end_angle_deg=math.degrees(end)%360,
                              sweep_angle_deg=span,start_px=projected(start),end_px=projected(end),
                              endpoint_method='angular extent of original isolated stroke component; projected to skeleton circle hypothesis',
                              skeleton_sweep_angle_deg=primitive.sweep_angle_deg,support_component_pixel_count=len(pts)))
    return result


def extract_primitives(
    image_path: str | Path,
    config: PrimitiveExtractionConfig | None = None,
) -> tuple[PrimitiveExtractionResult, np.ndarray, np.ndarray]:
    """提取像素空间基元，返回结果、清理后的前景和骨架。"""
    settings = config or PrimitiveExtractionConfig()
    path = Path(image_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    with Image.open(path) as source:
        if source.convert('RGBA').getextrema()[3] != (255,255):
            raise ValueError('transparent raster pixels require an explicit background; controlled mode accepts opaque images only')
        image = source.convert("L")
    gray = np.asarray(image, dtype=np.uint8)
    threshold = (
        _otsu_threshold(gray)
        if settings.threshold is None
        else settings.threshold
    )
    if settings.foreground == "dark":
        mask = gray <= threshold
    elif settings.foreground == "light":
        mask = gray > threshold if settings.threshold is None else gray >= threshold
    else:
        raise ValueError("foreground 必须为 dark 或 light")
    raw_mask=mask.copy()
    _,raw_components=_connected_components(raw_mask)
    mask, component_count = _remove_small_components(
        mask,
        settings.minimum_component_pixels,
    )
    skeleton = _thin(mask, settings.thinning_max_iterations)
    chains = _trace_skeleton(skeleton)
    primitives = _recover_isolated_arc_extent(_classify_chains(chains, settings),chains,mask)
    result = PrimitiveExtractionResult(
        image_path=path,
        image_size_px=image.size,
        threshold_used=int(threshold),
        foreground_pixel_count=int(mask.sum()),
        skeleton_pixel_count=int(skeleton.sum()),
        component_count=component_count,
        chain_count=len(chains),
        primitives=tuple(primitives),
        source_sha256=sha256_file(path),
        diagnostics={'config':asdict(settings),'raw_foreground_pixel_count':int(raw_mask.sum()),
                     'raw_component_count':len(raw_components),'removed_component_count':len(raw_components)-component_count,
                     'removed_pixel_count':int(raw_mask.sum()-mask.sum()),'thinning_converged':True,
                     'short_or_isolated_chain_count':sum(len(c)<2 or _polyline_length(c)<settings.minimum_chain_length_px for c in chains),
                     'represented_chain_count':len({p.source_chain_id for p in primitives}),
                     'fallback_primitive_count':sum(p.fit_method=='rdp_fallback_polyline' for p in primitives),
                     'source_chains_px':{f'K{i:04d}':c for i,c in enumerate(chains,1)},
                     'missing_topology':'candidate chain IDs only; no constraints, closed profile or semantic role approval'},
    )
    return result, mask, skeleton


def _save_binary_image(values: np.ndarray, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pixels = np.where(values, 0, 255).astype(np.uint8)
    Image.fromarray(pixels).save(output_path)
    return output_path


def export_primitive_overlay(
    result: PrimitiveExtractionResult,
    output_path: str | Path,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(result.image_path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for primitive in result.primitives:
        if isinstance(primitive, LinePrimitive):
            draw.line(
                [primitive.start_px, primitive.end_px],
                fill=(220, 20, 60),
                width=3,
            )
            label_position = primitive.start_px
        elif isinstance(primitive, CirclePrimitive):
            center_x, center_y = primitive.center_px
            radius = primitive.radius_px
            draw.ellipse(
                (
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                ),
                outline=(0, 130, 255),
                width=3,
            )
            label_position = (center_x + radius, center_y)
        else:
            center_x, center_y = primitive.center_px
            radius = primitive.radius_px
            direction = 1.0 if primitive.clockwise else -1.0
            sample_count = max(8, math.ceil(primitive.sweep_angle_deg / 3.0))
            angles = np.linspace(
                primitive.start_angle_deg,
                primitive.start_angle_deg
                + direction * primitive.sweep_angle_deg,
                sample_count,
            )
            arc_points = [
                (
                    center_x + radius * math.cos(math.radians(angle)),
                    center_y + radius * math.sin(math.radians(angle)),
                )
                for angle in angles
            ]
            draw.line(arc_points, fill=(40, 180, 80), width=3)
            label_position = primitive.start_px
        draw.text(
            (label_position[0] + 4, label_position[1] + 4),
            primitive.id,
            fill=(120, 0, 160),
            font=font,
            stroke_width=2,
            stroke_fill="white",
        )
    image.save(destination)
    return destination


def export_primitive_svg(
    result: PrimitiveExtractionResult,
    output_path: str | Path,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    width, height = result.image_size_px
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
        '<g fill="none" stroke-width="2">',
    ]
    for primitive in result.primitives:
        if isinstance(primitive, LinePrimitive):
            parts.append(
                (
                    f'<line id="{primitive.id}" x1="{primitive.start_px[0]:.3f}" '
                    f'y1="{primitive.start_px[1]:.3f}" '
                    f'x2="{primitive.end_px[0]:.3f}" '
                    f'y2="{primitive.end_px[1]:.3f}" stroke="#dc143c"/>'
                )
            )
        elif isinstance(primitive, CirclePrimitive):
            parts.append(
                (
                    f'<circle id="{primitive.id}" '
                    f'cx="{primitive.center_px[0]:.3f}" '
                    f'cy="{primitive.center_px[1]:.3f}" '
                    f'r="{primitive.radius_px:.3f}" stroke="#0082ff"/>'
                )
            )
        else:
            large_arc = 1 if primitive.sweep_angle_deg > 180.0 else 0
            sweep_flag = 1 if primitive.clockwise else 0
            parts.append(
                (
                    f'<path id="{primitive.id}" '
                    f'd="M {primitive.start_px[0]:.3f} {primitive.start_px[1]:.3f} '
                    f'A {primitive.radius_px:.3f} {primitive.radius_px:.3f} 0 '
                    f'{large_arc} {sweep_flag} '
                    f'{primitive.end_px[0]:.3f} {primitive.end_px[1]:.3f}" '
                    'stroke="#28b450"/>'
                )
            )
    parts.extend(["</g>", "</svg>"])
    destination.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return destination

