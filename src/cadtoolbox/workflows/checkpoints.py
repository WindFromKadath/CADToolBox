"""Source S024 checkpoint semantics, separate from strict generic STEP I/O.

Intermediate exports in the source rotor pipeline verify one closed valid
shell per solid, and feed the loaded geometry into the next stage. Generic
strict volume/area/bounds audits remain explicit measurements in this report;
they are not a passed check when outside the unchanged generic limits.
"""
from pathlib import Path
import hashlib,os,uuid
from ..contracts import ShapeExpectation,QualityPolicy
from ..geometry.io import load_step
from ..geometry.quality import GeometryError,GeometryResult,validate_shape
import cadquery as cq


def export_checkpoint(shape, path:Path, expected:ShapeExpectation, *, source_policy=False):
    if source_policy is not True:
        raise GeometryError('checkpoint_scope','source checkpoint mode must be explicitly selected')
    before=validate_shape(shape,expected)
    if before['shell_count']!=expected.solid_count:
        raise GeometryError('checkpoint_shells','source checkpoint requires one shell per solid',before)
    path=Path(path).resolve()
    if path.exists():raise GeometryError('output_exists',f'refusing to overwrite {path}')
    path.parent.mkdir(parents=True,exist_ok=True)
    stage=path.with_name(f'.{path.stem}.{uuid.uuid4().hex}.pending.step')
    report={'success':False,'validation_scope':'S024 intermediate checkpoint: type/count/valid/closed/positive volume/one shell per solid',
            'input_quality':before,'output':str(path),'source_semantics':'loaded checkpoint drives subsequent geometry'}
    try:
        cq.exporters.export(shape,str(stage),exportType='STEP',unit='MM')
        loaded=load_step(stage,expected)
        after=validate_shape(loaded.shape,expected)
        report['roundtrip_quality']=after
        if after['shell_count']!=expected.solid_count:
            raise GeometryError('checkpoint_shells','loaded checkpoint has incorrect shell count',report)
        policy=QualityPolicy()
        volume_error=abs(after['volume_mm3']-before['volume_mm3'])
        area_error=abs(after['area_mm2']-before['area_mm2'])
        bbox_error=max(abs(after['bbox_mm'][k]-v) for k,v in before['bbox_mm'].items())
        v_limit=max(policy.volume_abs_mm3,abs(before['volume_mm3'])*policy.volume_rel)
        a_limit=max(policy.area_abs_mm2,abs(before['area_mm2'])*policy.area_rel)
        report['generic_strict_io_audit']={'success':volume_error<=v_limit and area_error<=a_limit and bbox_error<=policy.bbox_abs_mm,
            'volume_error_mm3':volume_error,'volume_limit_mm3':v_limit,'area_error_mm2':area_error,'area_limit_mm2':a_limit,
            'bbox_error_mm':bbox_error,'bbox_limit_mm':policy.bbox_abs_mm,
            'separate_from_source_checkpoint_acceptance':True}
        os.link(stage,path);stage.unlink()
        report.update(success=True,output_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        return GeometryResult(loaded.shape,report)
    except Exception as exc:
        report['failure_artifact']=str(stage) if stage.exists() else None
        if isinstance(exc,GeometryError):
            report.update(exc.report);raise GeometryError(exc.code,str(exc),report) from exc
        raise GeometryError('checkpoint_io',f'checkpoint export/read failed: {exc}',report) from exc
