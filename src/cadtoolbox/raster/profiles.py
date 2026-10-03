"""从受约束二值图像提取闭合轴对称子午剖面。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import math
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw

from .config import CalibrationConfig, GeometryConfig, ImageConfig
from ..contracts import ContractError


PixelPoint = tuple[float, float]
XRPoint = tuple[float, float]


@dataclass(frozen=True)
class RasterProfile:
    image_path: Path
    image_size_px: tuple[int, int]
    foreground_bbox_px: tuple[int, int, int, int]
    foreground_pixel_count: int
    foreground_rows: int
    points_px: tuple[PixelPoint, ...]
    points_xr_mm: tuple[XRPoint, ...]
    area_mm2: float
    source_sha256: str
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self):
        d=asdict(self);d["image_path"]=str(self.image_path);return d


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    if denominator <= 1.0e-18:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / denominator
    t = max(0.0, min(1.0, t))
    nearest_x = ax + t * dx
    nearest_y = ay + t * dy
    return math.hypot(px - nearest_x, py - nearest_y)


def _rdp(points: list[PixelPoint], tolerance: float) -> list[PixelPoint]:
    if len(points) <= 2 or tolerance <= 0.0:
        return points
    start = points[0]
    end = points[-1]
    maximum_distance = -1.0
    maximum_index = -1
    for index, point in enumerate(points[1:-1], start=1):
        distance = _point_segment_distance(point, start, end)
        if distance > maximum_distance:
            maximum_distance = distance
            maximum_index = index
    if maximum_distance > tolerance:
        left = _rdp(points[: maximum_index + 1], tolerance)
        right = _rdp(points[maximum_index:], tolerance)
        return left[:-1] + right
    return [start, end]


def _deduplicate(points: Iterable[PixelPoint]) -> list[PixelPoint]:
    result: list[PixelPoint] = []
    for point in points:
        if not result or math.dist(point, result[-1]) > 1.0e-9:
            result.append(point)
    if len(result) > 1 and math.dist(result[0], result[-1]) <= 1.0e-9:
        result.pop()
    return result


def _polygon_area(points: tuple[XRPoint, ...]) -> float:
    total = 0.0
    for index, (x0, r0) in enumerate(points):
        x1, r1 = points[(index + 1) % len(points)]
        total += x0 * r1 - x1 * r0
    return 0.5 * total


def _make_mask(image: Image.Image, config: ImageConfig) -> np.ndarray:
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    if config.foreground == "dark":
        return gray <= config.threshold
    return gray >= config.threshold


def extract_raster_profile(
    image_path: str | Path,
    image_config: ImageConfig,
    calibration: CalibrationConfig,
    geometry: GeometryConfig,
) -> RasterProfile:
    """提取单个填充轮廓；不对工程图文字或断线进行猜测。"""
    path = Path(image_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    with Image.open(path) as source:
        if source.convert('RGBA').getextrema()[3] != (255,255):
            raise ValueError('transparent raster pixels require an explicit background; controlled mode accepts opaque images only')
        image = source.convert("RGB")
    mask = _make_mask(image, image_config)
    foreground_y, foreground_x = np.nonzero(mask)
    if len(foreground_x) == 0:
        raise ValueError("图像中没有找到前景像素")

    x_min_px = int(foreground_x.min())
    x_max_px = int(foreground_x.max())
    y_min_px = int(foreground_y.min())
    y_max_px = int(foreground_y.max())
    if x_max_px <= x_min_px or y_max_px <= y_min_px:
        raise ValueError("前景包围盒退化，无法进行二维标定")

    rows = list(range(y_min_px, y_max_px + 1))
    if len(rows) < image_config.minimum_foreground_rows:
        raise ValueError(
            f"有效前景行只有 {len(rows)}，少于配置要求的 "
            f"{image_config.minimum_foreground_rows}"
        )

    left_by_row: list[PixelPoint] = []
    right_by_row: list[PixelPoint] = []
    for y_value in rows:
        xs = np.flatnonzero(mask[y_value])
        if len(xs) == 0:
            raise ValueError(
                f"前景在图像行 y={y_value} 断开；当前最小实现要求每行连续"
            )
        if (
            image_config.require_single_interval_per_row
            and len(xs) > 1
            and np.any(np.diff(xs) != 1)
        ):
            raise ValueError(
                f"图像行 y={y_value} 包含多个前景区间；"
                "当前最小实现不支持孔洞、文字或多个实体"
            )
        left_by_row.append((float(xs[0]), float(y_value)))
        right_by_row.append((float(xs[-1]), float(y_value)))

    left_chain = list(reversed(left_by_row))
    right_chain = right_by_row
    left_simple = _rdp(left_chain, geometry.simplify_tolerance_px)
    right_simple = _rdp(right_chain, geometry.simplify_tolerance_px)
    points_px = _deduplicate(left_simple + right_simple)
    if len(points_px) < 4:
        raise ValueError(
            f"简化后的剖面只有 {len(points_px)} 个点，不能形成有效区域"
        )

    points_xr = calibration.map(points_px,image.size,(x_min_px,y_min_px,x_max_px,y_max_px))
    # Adjacent foreground rows must connect; a horizontal jump is a second region.
    for previous,current in zip(zip(left_by_row,right_by_row),zip(left_by_row[1:],right_by_row[1:])):
        if current[0][0]>previous[1][0]+1 or previous[0][0]>current[1][0]+1:
            raise ValueError('foreground rows are disconnected')
    raw_px=_deduplicate(left_chain+right_chain)
    error=max(min(_point_segment_distance(p,points_px[i],points_px[(i+1)%len(points_px)]) for i in range(len(points_px))) for p in raw_px)
    if error>geometry.simplify_tolerance_px+1e-9:raise ValueError('RDP exceeds declared pixel error budget')
    signed_area = _polygon_area(points_xr)
    if signed_area < 0.0:
        points_xr = tuple(reversed(points_xr))
        points_px = list(reversed(points_px))
        signed_area = -signed_area
    if signed_area < geometry.minimum_profile_area_mm2:
        raise ValueError(
            f"标定后剖面面积 {signed_area:.6f} mm² 小于配置要求"
        )

    return RasterProfile(
        image_path=path,
        image_size_px=image.size,
        foreground_bbox_px=(
            x_min_px,
            y_min_px,
            x_max_px,
            y_max_px,
        ),
        foreground_pixel_count=int(mask.sum()),
        foreground_rows=len(rows),
        points_px=tuple(points_px),
        points_xr_mm=points_xr,
        area_mm2=signed_area,
        source_sha256=sha256_file(path),
        diagnostics={'calibration':calibration.report(image.size,(x_min_px,y_min_px,x_max_px,y_max_px)),
                     'simplification_max_deviation_px':error,'simplification_tolerance_px':geometry.simplify_tolerance_px,
                     'raw_point_count':len(raw_px),'interpretation':'one filled meridian; straight boundary segments; no inferred arcs'},
    )


def export_overlay(profile: RasterProfile, output_path: str | Path) -> Path:
    """在源图上叠加最终使用的简化闭合轮廓。"""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(profile.image_path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    points = [(round(x), round(y)) for x, y in profile.points_px]
    draw.line(points + [points[0]], fill=(255, 0, 0), width=3)
    for x_value, y_value in points:
        radius = 3
        draw.ellipse(
            (
                x_value - radius,
                y_value - radius,
                x_value + radius,
                y_value + radius,
            ),
            fill=(0, 102, 255),
        )
    image.save(destination)
    return destination

