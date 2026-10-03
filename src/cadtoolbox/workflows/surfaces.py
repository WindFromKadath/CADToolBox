"""Source-grounded UV twist workflow; never executes source-project modules."""
from dataclasses import asdict
from pathlib import Path
from importlib.metadata import version
import json,sys
from ..contracts import Axis,Frame,Unit,QualityPolicy,ContractError,ShapeExpectation,ShapeKind
from ..geometry.io import source_info,load_dxf,load_step,export_step
from ..geometry.quality import GeometryError,validate_shape
from ..geometry.parametric import RectangularBase,CoonsBase
from ..geometry.theta_fields import build_field
from ..geometry.surface_fit import FitConfig
from ..geometry.twisted_solid import SewConfig,build_twisted_solid,validate_solid_target
ONE=ShapeExpectation(ShapeKind.SOLID,1)
FACE=ShapeExpectation(ShapeKind.FACE,0)


def checked_reference(spec,config_path):
    path=Path(spec['path'])
    if not path.is_absolute():path=(config_path.parent/path).resolve()
    if not path.is_file():raise GeometryError('missing_reference','reference input is missing',{'path':str(path)})
    actual=source_info(path)
    if actual['sha256']!=spec['sha256']:raise GeometryError('source_input_changed','reference content hash differs',actual)
    return path,actual


def run_surface_blade(config_path,output,*,progress=None):
    config_path=Path(config_path).resolve();output=Path(output).resolve()
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    if config.get('schema_version')!=1 or config.get('unit')!='mm':raise ContractError('surface workflow requires schema_version=1 and mm')
    if output.exists():raise GeometryError('output_exists','surface workflow requires a new output directory')
    output.mkdir(parents=True)
    report={'schema_version':1,'success':False,'config':source_info(config_path),'config_snapshot':config,
            'output_directory':str(output),'stages':{},'outputs':{},'source_paths_read_only':True,
            'environment':{'python':sys.version,'packages':{p:version(p) for p in ['cadquery','cadquery-ocp','ezdxf']}}}
    def save():
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    def stage(name,data):
        report['stages'][name]=data;save()
        if progress:progress(name)
    try:
        references=[]
        for spec in config.get('source_parameter_references',[]):
            _,actual=checked_reference(spec,config_path);references.append(actual)
        report['source_parameter_references']=references
        frame=Frame(Axis(**config['frame']['axis']),tuple(config['frame']['radial_reference']))
        axis=Axis(**config.get('rotation_axis',config['frame']['axis']))
        spec=dict(config['base']);mode=spec.pop('mode')
        if mode=='rectangular_annulus':base=RectangularBase(frame,**spec)
        elif mode=='four_edge_dxf':
            path,actual=checked_reference(spec.pop('input'),config_path)
            layers=spec.pop('layers',None);unit=Unit(spec.pop('input_unit','mm'))
            loaded=load_dxf(path,input_unit=unit,include_layers=layers)
            if len(loaded.wires)!=1:raise GeometryError('four_edge_wires','four-edge base requires exactly one closed Wire',loaded.report)
            base=CoonsBase(loaded.wires[0].Edges(),frame,**spec)
            report['dxf_input']={**actual,'import':loaded.report}
        elif mode=='step_face':raise GeometryError('unsupported_step_base','STEP base parameterization is not implemented')
        else:raise ContractError('unknown base mode: '+str(mode))
        stage('base',{'frame':asdict(frame),'base':base.report})
        field=build_field(config['field'],base,axis)
        fit=FitConfig(**config.get('fit',{}));sewing=SewConfig(**config.get('sewing',{}))
        policy=QualityPolicy(**config.get('quality_policy',{}))
        stage('field',field.report)
        result=build_twisted_solid(base,field,axis,fit,sewing,**config.get('construction',{}))
        stage('solid',result.report)
        report['outputs']['base_step']=str(output/'base.step')
        stage('base_step',export_step(base.build_face(),output/'base.step',FACE,policy))
        final=output/'twisted-blade.step'
        report['outputs']['solid_step']=str(final)
        stage('solid_step',export_step(result.shape,final,ONE,policy))
        reread=load_step(final,ONE)
        stage('reread_target',validate_solid_target(reread.shape,base,field,axis,fit))
        stage('reread_quality',validate_shape(reread.shape,ONE,policy))
        report.update(success=True,angle_semantics='rotation field between base and target; straight corner connectors; not normal constant thickness')
        save();return report
    except Exception as exc:
        report['failure']=exc.as_dict() if isinstance(exc,GeometryError) else {'code':'invalid_parameters' if isinstance(exc,(ContractError,TypeError,KeyError)) else 'unexpected_backend_failure','message':str(exc)}
        save()
        if isinstance(exc,GeometryError):raise GeometryError(exc.code,str(exc),report) from exc
        if isinstance(exc,(ContractError,TypeError,KeyError)):raise GeometryError('invalid_parameters',str(exc),report) from exc
        raise
