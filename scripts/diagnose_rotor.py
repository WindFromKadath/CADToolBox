"""Build a reviewable rotor and retain failed STEP checks without relaxing policy.

This diagnostic never finalizes tasks or claims a passed workflow. Only its
process-local export observer allows construction to continue after a failed
roundtrip so all discrepancies can be reviewed together.
"""
from pathlib import Path
import argparse,json,shutil
from cadtoolbox.geometry import assembly
from unittest.mock import patch
from cadtoolbox.workflows import rotor
from cadtoolbox.geometry.quality import GeometryError,GeometryResult

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('config',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--retain-memory-checkpoints',action='store_true')
    parser.add_argument('--review-unify-limit',action='store_true')
    args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT):raise SystemExit('diagnostic output must be within CADToolbox')
    original=rotor.export_step;original_validate=rotor.validate_shape;failures=[];quality_failures=[]
    original_fuse=rotor.fuse_components
    original_checkpoint=rotor.export_checkpoint;original_unify=assembly.unify_same_domain
    def observe_checkpoint(*a,**kw):
        result=original_checkpoint(*a,**kw)
        if args.retain_memory_checkpoints:
            result.shape=a[0];result.report['diagnostic_geometry_driver']='original in-memory shape; loaded geometry audited separately'
        return result
    def observe_unify(*a,**kw):
        try:return original_unify(*a,**kw)
        except GeometryError as exc:
            if not args.review_unify_limit or exc.code!='unify_volume' or not hasattr(exc,'partial_shape'):raise
            quality_failures.append(exc.as_dict());return exc.partial_shape
    def observe_fuse(*a,**kw):
        try:return original_fuse(*a,**kw)
        except GeometryError as exc:
            if exc.code!='fusion_volume' or not hasattr(exc,'partial_shape'):raise
            quality_failures.append(exc.as_dict())
            return GeometryResult(exc.partial_shape,exc.report)
    def observe_quality(*a,**kw):
        try:return original_validate(*a,**kw)
        except GeometryError as exc:
            if exc.code!='shape_quality' or exc.report.get('errors')!=['degenerated edges forbidden by task policy']:raise
            quality_failures.append(exc.as_dict())
            return exc.report
    def observe(*a,**kw):
        try:return original(*a,**kw)
        except GeometryError as exc:
            if exc.code not in {'roundtrip_mismatch','shape_quality'} or not exc.report.get('failure_artifact'):raise
            failure=exc.as_dict();failures.append(failure)
            stage=Path(exc.report['failure_artifact'])
            review=output/('unverified-'+Path(a[1]).name)
            shutil.copy2(stage,review)
            failure['review_file']=str(review)
            return failure
    try:
        with patch.object(rotor,'export_step',side_effect=observe), patch.object(rotor,'validate_shape',side_effect=observe_quality), patch.object(rotor,'fuse_components',side_effect=observe_fuse), patch.object(rotor,'export_checkpoint',side_effect=observe_checkpoint), patch.object(rotor,'unify_same_domain',side_effect=observe_unify), patch.object(assembly,'unify_same_domain',side_effect=observe_unify):
            report=rotor.run_rotor(args.config,output,progress=lambda name:print('geometry completed '+name,flush=True))
        report.update(success=False,status='diagnostic_only',geometry_stages_completed=True,
                      strict_step_failures=failures,strict_geometry_policy_failures=quality_failures,finalization_allowed=False,
                      diagnostic_options={'retain_memory_checkpoints':args.retain_memory_checkpoints,'review_unify_limit':args.review_unify_limit})
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        entries=[]
        for failure in failures:
            r=failure['report'];before=r.get('input_quality',{});after=r.get('roundtrip_quality',r)
            entries.append({'output':r.get('output'),'code':failure['code'],
                'volume_relative_error':r.get('volume_error_mm3',abs(after.get('volume_mm3',0)-before.get('volume_mm3',0)))/before['volume_mm3'],
                'area_relative_error':r.get('area_error_mm2',abs(after.get('area_mm2',0)-before.get('area_mm2',0)))/before['area_mm2'],
                'input_degenerated_edges':before.get('degenerated_edge_count'),
                'loaded_degenerated_edges':after.get('degenerated_edge_count'),
                'loaded_valid':after.get('valid'),'review_file':failure['review_file']})
        summary={'success':False,'diagnostic_geometry_completed':True,'strict_failure_count':len(failures),
                 'strict_geometry_policy_failure_count':len(quality_failures),'geometry_policy_failures':quality_failures,'failures':entries,'report':str(output/'report.json')}
        (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False,indent=2))
        return 0
    except Exception as exc:
        print('diagnostic failed: '+str(exc),flush=True)
        raise

if __name__=='__main__':raise SystemExit(main())
