"""STEP I/O and explicit, loss-checked planar DXF curves (S024/S032)."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import uuid
import cadquery as cq
from cadquery.occ_impl.importers.dxf import DXF_CONVERTERS
import ezdxf
from ..contracts import QualityPolicy, ShapeExpectation, ShapeKind, Unit, finite
from .quality import GeometryError, GeometryResult, topology, validate_shape


def source_info(path: Path) -> dict:
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def _canonical(shape, expected):
    # STEP represents a standalone face as a one-face shell. Remove only
    # single-child containers under an explicit expectation; record raw type.
    if expected is None or expected.kind == ShapeKind.COMPOUND:
        return shape
    while shape.ShapeType() == 'Compound' or (shape.ShapeType() == 'Shell' and expected.kind == ShapeKind.FACE):
        children = list(shape)
        if len(children) != 1:
            break
        child = children[0]
        if child.ShapeType() == expected.kind.value:
            return child
        if child.ShapeType() not in {'Compound','Shell'}:
            break
        shape = child
    return shape


def load_step(path: str | Path, expected: ShapeExpectation | None = None) -> GeometryResult:
    path = Path(path)
    if not path.is_file():
        raise GeometryError('missing_input',f'STEP input not found: {path}')
    try:
        objects = cq.importers.importStep(str(path),unit='MM').vals()
        if not objects or any(not isinstance(s,cq.Shape) for s in objects):
            raise ValueError('no shapes in STEP roots')
        shape = objects[0] if len(objects) == 1 else cq.Compound.makeCompound(objects)
        raw_kind = shape.ShapeType()
        shape = _canonical(shape,expected)
        quality = validate_shape(shape,expected) if expected else topology(shape)
        if not quality['valid']:
            raise GeometryError('invalid_step','STEP contains invalid topology',quality)
    except GeometryError:
        raise
    except Exception as exc:
        raise GeometryError('step_import',f'cannot import STEP: {exc}',source_info(path)) from exc
    return GeometryResult(shape,{'success':True,'source':source_info(path),'unit':'mm',
                                 'unit_policy':'OCCT converts file-declared units to MM',
                                 'raw_root_kind':raw_kind,'quality':quality})


def export_step(shape: cq.Shape, path: str | Path, expected: ShapeExpectation,
                policy: QualityPolicy | None = None, *, overwrite: bool = False) -> dict:
    policy = policy or QualityPolicy()
    before = validate_shape(shape,expected,policy)
    path = Path(path).resolve()
    if path.exists() and not overwrite:
        raise GeometryError('output_exists',f'refusing to overwrite {path}')
    if path.suffix.lower() not in {'.step','.stp'}:
        raise GeometryError('output_format','STEP output must end in .step or .stp')
    path.parent.mkdir(parents=True,exist_ok=True)
    stage = path.with_name(f'.{path.stem}.{uuid.uuid4().hex}.pending.step')
    report = {'success':False,'input_quality':before,'output':str(path),'expectation':{
        'kind':expected.kind.value,'solid_count':expected.solid_count}}
    try:
        cq.exporters.export(shape,str(stage),exportType='STEP',unit='MM')
        loaded = load_step(stage,expected)
        after = validate_shape(loaded.shape,expected,policy)
        error = abs(after['volume_mm3']-before['volume_mm3'])
        limit = max(policy.volume_abs_mm3,abs(before['volume_mm3'])*policy.volume_rel)
        bbox_error = max(abs(after['bbox_mm'][k]-v) for k,v in before['bbox_mm'].items())
        area_error = abs(after['area_mm2']-before['area_mm2'])
        area_limit = max(policy.area_abs_mm2,abs(before['area_mm2'])*policy.area_rel)
        report.update(roundtrip_quality=after,volume_error_mm3=error,volume_limit_mm3=limit,
                      bbox_error_mm=bbox_error,bbox_limit_mm=policy.bbox_abs_mm,
                      area_error_mm2=area_error,area_limit_mm2=area_limit)
        if error > limit or bbox_error > policy.bbox_abs_mm or area_error > area_limit:
            raise GeometryError('roundtrip_mismatch','STEP roundtrip changed volume, area or bounds',report)
        if overwrite:
            os.replace(stage,path)
        else:
            # Atomic no-clobber publication on Windows/NTFS; a raced destination
            # raises instead of overwriting an unrelated file.
            os.link(stage,path)
            stage.unlink()
        report.update(success=True,output_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        return report
    except Exception as exc:
        report['failure_artifact'] = str(stage) if stage.exists() else None
        if isinstance(exc,GeometryError):
            report.update(exc.report)
            raise GeometryError(exc.code,str(exc),report) from exc
        raise GeometryError('step_export',f'cannot export/read back STEP: {exc}',report) from exc


@dataclass
class ProfileResult:
    wires: list[cq.Wire]
    report: dict


_DXF_UNITS = {1:Unit.INCH,4:Unit.MM,5:Unit.CM,6:Unit.M}


def load_dxf(path: str | Path, *, input_unit: Unit | None = None,
             include_layers: list[str] | None = None, tolerance_mm: float = 1e-6) -> ProfileResult:
    tolerance_mm = finite(tolerance_mm,'tolerance_mm',positive=True)
    path = Path(path)
    if not path.is_file():
        raise GeometryError('missing_input',f'DXF input not found: {path}')
    try:
        doc = ezdxf.readfile(path)
    except Exception as exc:
        raise GeometryError('dxf_import',f'cannot read DXF: {exc}') from exc
    header_code = int(doc.header.get('$INSUNITS',0))
    header_unit = _DXF_UNITS.get(header_code)
    if input_unit is not None:
        input_unit = Unit(input_unit)
    if header_code and header_unit is None:
        raise GeometryError('dxf_unit','unsupported DXF unit code; rescale input explicitly')
    if input_unit and header_unit and input_unit != header_unit:
        raise GeometryError('unit_conflict','explicit unit conflicts with DXF $INSUNITS')
    unit = input_unit or header_unit
    if unit is None:
        raise GeometryError('unit_missing','unitless DXF requires explicit input_unit')
    selected = {s.lower() for s in include_layers} if include_layers else None
    entities = [e for e in doc.modelspace() if selected is None or e.dxf.layer.lower() in selected]
    if not entities:
        raise GeometryError('empty_profile','no entities in selected DXF layers')
    edges = []
    entity_counts = Counter()
    layers = {}
    for entity in entities:
        kind = entity.dxftype()
        entity_counts[kind] += 1
        if kind not in DXF_CONVERTERS:
            raise GeometryError('unsupported_entity',f'DXF {kind} unsupported in selected layer {entity.dxf.layer}')
        normal = tuple(entity.dxf.get('extrusion',(0,0,1)))
        if normal != (0,0,1):
            raise GeometryError('dxf_plane','only XY profiles with +Z extrusion are supported')
        if kind == 'POLYLINE' and (entity.is_3d_polyline or entity.is_polygon_mesh or entity.is_poly_face_mesh):
            raise GeometryError('dxf_plane','3D/mesh POLYLINE unsupported')
        # Expand polylines so malformed segments cannot be silently omitted by
        # the backend converter. Reject every failed individual conversion.
        parts = list(entity.virtual_entities()) if kind in {'POLYLINE','LWPOLYLINE'} else [entity]
        if not parts:
            raise GeometryError('dxf_conversion',f'empty {kind}')
        layer_edges = layers.setdefault(entity.dxf.layer.lower(),[])
        for part in parts:
            try:
                converted = tuple(DXF_CONVERTERS[part.dxftype()](part))
            except Exception as exc:
                raise GeometryError('dxf_conversion',f'cannot convert {kind}: {exc}') from exc
            if not converted:
                raise GeometryError('dxf_conversion',f'backend failed to convert {kind}; no entity dropped')
            for edge in converted:
                edge = edge.scale(unit.mm_factor) if unit.mm_factor != 1 else edge
                b = edge.BoundingBox()
                if max(abs(b.zmin),abs(b.zmax)) > tolerance_mm:
                    raise GeometryError('dxf_plane','profile must lie in XY at z=0')
                layer_edges.append(edge)
                edges.append(edge)
    wires = []
    try:
        for layer_edges in layers.values():
            wires.extend(cq.Wire.combine(layer_edges,tol=tolerance_mm))
        if not wires or any(not w.IsClosed() for w in wires):
            raise GeometryError('open_profile','DXF contains open wires')
        for wire in wires:
            face = cq.Face.makeFromWires(wire)
            validate_shape(face,ShapeExpectation(ShapeKind.FACE))
            if face.Area() <= tolerance_mm**2:
                raise GeometryError('empty_profile','profile encloses no usable area')
    except GeometryError:
        raise
    except Exception as exc:
        raise GeometryError('dxf_profile',f'cannot build closed DXF profiles: {exc}') from exc
    return ProfileResult(wires,{'success':True,'source':source_info(path),'input_unit':unit.value,
        'unit_source':'DXF $INSUNITS' if header_unit else 'explicit argument','unit':'mm',
        'scale_to_mm':unit.mm_factor,'selected_layers':sorted(layers),'entity_counts':dict(entity_counts),
        'wire_count':len(wires),'edge_count':sum(len(w.Edges()) for w in wires),'all_wires_closed':True,
        'curve_types':dict(Counter(e.geomType() for w in wires for e in w.Edges())),
        'tolerance_mm':tolerance_mm,'scope':'closed XY curves, separate layers; hole nesting is a workflow decision',
        'converter':'CadQuery 2.8 DXF_CONVERTERS; each conversion checked, no sampling'})
