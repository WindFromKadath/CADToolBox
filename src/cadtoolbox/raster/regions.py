"""从三色填充图提取共享边界的 low/flow/high 子午剖面。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw

from .config import CalibrationConfig, GeometryConfig, RegionConfig
from .profiles import (
    PixelPoint,
    RasterProfile,
    XRPoint,
    _deduplicate,
    _polygon_area,
    _rdp,
    sha256_file,
    _point_segment_distance,
)


REQUIRED_REGION_ORDER = ("low_body", "flow_channel", "high_body")


def _color_mask(
    rgb: np.ndarray,
    color: tuple[int, int, int],
    tolerance: int,
) -> np.ndarray:
    target = np.asarray(color, dtype=np.int16)
    difference = np.abs(rgb.astype(np.int16) - target)
    return np.max(difference, axis=2) <= tolerance


def _row_interval(mask: np.ndarray, y_value: int, label: str) -> tuple[int, int]:
    xs = np.flatnonzero(mask[y_value])
    if len(xs) == 0:
        raise ValueError(
            f"区域 {label} 在图像行 y={y_value} 缺失；"
            "三色最小实现要求三个区域共享完整的半径范围"
        )
    if len(xs) > 1 and np.any(np.diff(xs) != 1):
        raise ValueError(
            f"区域 {label} 在图像行 y={y_value} 不连续"
        )
    return int(xs[0]), int(xs[-1])


def _calibrate_points(
    points: Iterable[PixelPoint],
    image_size: tuple[int, int],
    calibration: CalibrationConfig,
) -> tuple[XRPoint, ...]:
    if calibration.mode != 'image_bbox':raise ValueError('three regions require image_bbox')
    return calibration.map(points,image_size,(0,0,image_size[0]-1,image_size[1]-1))


def _make_profile(
    *,
    image_path: Path,
    image_size: tuple[int, int],
    source_sha256: str,
    mask: np.ndarray,
    left_top_bottom: list[PixelPoint],
    right_top_bottom: list[PixelPoint],
    calibration: CalibrationConfig,
    geometry: GeometryConfig,
) -> RasterProfile:
    left_simple = list(reversed(left_top_bottom))
    right_simple = right_top_bottom
    points_px = _deduplicate(left_simple + right_simple)
    if len(points_px) < 4:
        raise ValueError("共享边界简化后不足 4 个剖面点")
    points_xr = _calibrate_points(
        points_px,
        image_size,
        calibration,
    )
    area = _polygon_area(points_xr)
    if area < 0.0:
        points_px = list(reversed(points_px))
        points_xr = tuple(reversed(points_xr))
        area = -area
    if area < geometry.minimum_profile_area_mm2:
        raise ValueError(
            f"区域标定面积 {area:.6f} mm² 小于配置要求"
        )
    foreground_y, foreground_x = np.nonzero(mask)
    return RasterProfile(
        image_path=image_path,
        image_size_px=image_size,
        foreground_bbox_px=(
            int(foreground_x.min()),
            int(foreground_y.min()),
            int(foreground_x.max()),
            int(foreground_y.max()),
        ),
        foreground_pixel_count=int(mask.sum()),
        foreground_rows=(
            int(foreground_y.max()) - int(foreground_y.min()) + 1
        ),
        points_px=tuple(points_px),
        points_xr_mm=points_xr,
        area_mm2=area,
        source_sha256=source_sha256,
        diagnostics={"calibration":calibration.report(image_size,(0,0,image_size[0]-1,image_size[1]-1)),"boundary_convention":"adjacent color pixel midpoint; shared chain simplified once"},
    )


def extract_three_region_profiles(
    image_path: str | Path,
    region_configs: tuple[RegionConfig, ...],
    calibration: CalibrationConfig,
    geometry: GeometryConfig,
    minimum_rows: int = 20,
) -> dict[str, RasterProfile]:
    """提取三个按 X 排列的色块，并对相邻边界执行一次共享求解。"""
    path = Path(image_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    config_by_name = {region.name: region for region in region_configs}
    if len(region_configs)!=3 or set(config_by_name) != set(REQUIRED_REGION_ORDER):
        raise ValueError(
            "三色模式必须且只能配置 low_body、flow_channel、high_body"
        )

    with Image.open(path) as source:
        if source.convert('RGBA').getextrema()[3] != (255,255):
            raise ValueError('transparent raster pixels require an explicit background; controlled mode accepts opaque images only')
        image = source.convert("RGB")
    rgb = np.asarray(image, dtype=np.uint8)
    masks = {
        name: _color_mask(
            rgb,
            config_by_name[name].color_rgb,
            config_by_name[name].tolerance,
        )
        for name in REQUIRED_REGION_ORDER
    }
    if np.any(sum(mask.astype(int) for mask in masks.values())>1):raise ValueError("ambiguous overlapping color masks")
    unknown=(~np.logical_or.reduce(list(masks.values()))) & np.any(rgb!=255,axis=2)
    if np.any(unknown):raise ValueError('three-region input contains unclassified nonwhite pixels; text or unknown colors unsupported')
    for name, mask in masks.items():
        if not np.any(mask):
            raise ValueError(f"图像中没有找到颜色区域 {name}")

    for name,mask in masks.items():
        rows=np.flatnonzero(mask.any(axis=1))
        for y0,y1 in zip(rows,rows[1:]):
            a=np.flatnonzero(mask[y0]);b=np.flatnonzero(mask[y1])
            if y1!=y0+1 or b[0]>a[-1]+1 or a[0]>b[-1]+1:
                raise ValueError('color foreground rows are disconnected: '+name)
    y_ranges = []
    for mask in masks.values():
        foreground_y = np.nonzero(mask)[0]
        y_ranges.append((int(foreground_y.min()), int(foreground_y.max())))
    if len(set(y_ranges)) != 1:
        raise ValueError(
            "三个颜色区域的半径范围不一致；"
            "当前最小实现要求它们具有相同的上下边界"
        )
    y_min, y_max = y_ranges[0]
    if y_max<=y_min or y_max-y_min+1<minimum_rows:raise ValueError("three-region radial range too small")

    low_outer: list[PixelPoint] = []
    low_flow_interface: list[PixelPoint] = []
    flow_high_interface: list[PixelPoint] = []
    high_outer: list[PixelPoint] = []
    for y_value in range(y_min, y_max + 1):
        low_left, low_right = _row_interval(
            masks["low_body"],
            y_value,
            "low_body",
        )
        flow_left, flow_right = _row_interval(
            masks["flow_channel"],
            y_value,
            "flow_channel",
        )
        high_left, high_right = _row_interval(
            masks["high_body"],
            y_value,
            "high_body",
        )
        if not (
            low_left <= low_right < flow_left <= flow_right
            < high_left <= high_right
        ):
            raise ValueError(
                f"图像行 y={y_value} 的颜色区域顺序不是 "
                "low_body → flow_channel → high_body"
            )
        if flow_left-low_right!=1 or high_left-flow_right!=1:
            raise ValueError(f'color regions have an unfilled gap at row {y_value}; cannot infer a shared interface')
        low_outer.append((float(low_left), float(y_value)))
        low_flow_interface.append(
            ((low_right + flow_left) / 2.0, float(y_value))
        )
        flow_high_interface.append(
            ((flow_right + high_left) / 2.0, float(y_value))
        )
        high_outer.append((float(high_right), float(y_value)))

    raw_chains=[low_outer,low_flow_interface,flow_high_interface,high_outer]
    # 两条共享边界只简化一次，再同时传给相邻区域，避免独立拟合产生缝隙。
    shared_low_flow = _rdp(
        low_flow_interface,
        geometry.simplify_tolerance_px,
    )
    shared_flow_high = _rdp(
        flow_high_interface,
        geometry.simplify_tolerance_px,
    )
    low_outer_simple = _rdp(
        low_outer,
        geometry.simplify_tolerance_px,
    )
    high_outer_simple = _rdp(
        high_outer,
        geometry.simplify_tolerance_px,
    )

    source_hash = sha256_file(path)
    profiles = {
        "low_body": _make_profile(
            image_path=path,
            image_size=image.size,
            source_sha256=source_hash,
            mask=masks["low_body"],
            left_top_bottom=low_outer_simple,
            right_top_bottom=shared_low_flow,
            calibration=calibration,
            geometry=geometry,
        ),
        "flow_channel": _make_profile(
            image_path=path,
            image_size=image.size,
            source_sha256=source_hash,
            mask=masks["flow_channel"],
            left_top_bottom=shared_low_flow,
            right_top_bottom=shared_flow_high,
            calibration=calibration,
            geometry=geometry,
        ),
        "high_body": _make_profile(
            image_path=path,
            image_size=image.size,
            source_sha256=source_hash,
            mask=masks["high_body"],
            left_top_bottom=shared_flow_high,
            right_top_bottom=high_outer_simple,
            calibration=calibration,
            geometry=geometry,
        ),
    }
    simple_chains=[low_outer_simple,shared_low_flow,shared_flow_high,high_outer_simple]
    errors=[max(min(_point_segment_distance(p,a,b) for a,b in zip(simple,simple[1:])) for p in raw)
            for raw,simple in zip(raw_chains,simple_chains)]
    if max(errors)>geometry.simplify_tolerance_px+1e-9:raise ValueError('shared RDP budget exceeded')
    for profile in profiles.values():
        profile.diagnostics.update(shared_boundary_max_deviation_px=max(errors),simplification_tolerance_px=geometry.simplify_tolerance_px,
                                   ignored_background_pixels=int((~np.logical_or.reduce(list(masks.values()))).sum()),
                                   unfilled_interface_gap_pixels=0)
    return profiles


def export_three_region_overlay(
    profiles: dict[str, RasterProfile],
    output_path: str | Path,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    first = profiles[REQUIRED_REGION_ORDER[0]]
    with Image.open(first.image_path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    colors = {
        "low_body": (0, 0, 128),
        "flow_channel": (0, 80, 0),
        "high_body": (128, 0, 0),
    }
    for name in REQUIRED_REGION_ORDER:
        points = [
            (round(x_value), round(y_value))
            for x_value, y_value in profiles[name].points_px
        ]
        draw.line(
            points + [points[0]],
            fill=colors[name],
            width=4,
        )
        for x_value, y_value in points:
            draw.ellipse(
                (
                    x_value - 3,
                    y_value - 3,
                    x_value + 3,
                    y_value + 3,
                ),
                fill=(255, 255, 255),
                outline=colors[name],
                width=2,
            )
    image.save(destination)
    return destination

