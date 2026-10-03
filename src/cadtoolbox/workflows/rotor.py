"""Source-grounded circle/theta rotor workflow with explicit constraints."""
from __future__ import annotations
from dataclasses import asdict
from math import hypot
from pathlib import Path
import hashlib,json
from ..contracts import Axis,Frame,Thickness,ThicknessKind,ShapeKind,ShapeExpectation,QualityPolicy,finite,ContractError
from ..geometry.blades import CircleLaw,ThetaLaw,build_radial_blade,extreme_chord_thickness
from ..geometry.domains import material_domain,trim_solid
from ..geometry.assembly import (Component,fuse_components,fillet_two_end_rotor,extract_rounded_blade,circular_pattern,assemble_unique,unify_same_domain)
from ..geometry.io import load_step,export_step
from ..geometry.measure import count_axis_cylinder_faces
from .checkpoints import export_checkpoint
from ..geometry.io import source_info
from ..geometry.transforms import transform_shape
from ..geometry.quality import GeometryError,validate_shape

ONE=ShapeExpectation(ShapeKind.SOLID,1)


def run_rotor(config_path: Path,output: Path,*,progress=None):
    config_path=Path(config_path).resolve();output=Path(output).resolve()
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    if config.get('schema_version')!=1 or config.get('unit')!='mm':raise ContractError('rotor schema_version=1 and mm required')
    if output.exists():raise GeometryError('output_exists','rotor workflow requires a new output directory')
    output.mkdir(parents=True)
    report={'schema_version':1,'success':False,'config':source_info(config_path),'config_snapshot':config,
            'output_directory':str(output),'stages':{},'outputs':{}}
    def checkpoint(name,data):
        report['stages'][name]=data
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if progress:progress(name)
    policy=QualityPolicy(**config.get('quality_policy',{}))
    driver=config.get('geometry_driver','step_reload')
    if driver not in {'step_reload','in_memory'}:raise ContractError('geometry_driver must be step_reload or in_memory')
    volume_rel=finite(config.get('geometry_volume_rel',1e-8),'workflow volume relative tolerance',positive=True)
    report.update(geometry_driver=driver,geometry_volume_relative_tolerance=volume_rel)
    try:
        frame=Frame(Axis(**config['frame']['axis']),tuple(config['frame']['radial_reference']))
        translation=tuple(finite(v,'input translation') for v in config['input_translation_mm'])
        if len(translation)!=3:raise ContractError('translation requires three coordinates')
        source_reference=config.get('source_parameter_reference')
        if source_reference:
            source_path=Path(source_reference['path'])
            if not source_path.is_file() or hashlib.sha256(source_path.read_bytes()).hexdigest()!=source_reference['sha256']:
                raise GeometryError('source_configuration_changed','source parameter reference changed')
        inputs={}
        for name,expected in [('flow',ONE),('rotor',ShapeExpectation(ShapeKind.COMPOUND,2))]:
            spec=config['inputs'][name];p=Path(spec['path'])
            if not p.is_absolute():p=(config_path.parent/p).resolve()
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=spec['sha256']:
                raise GeometryError('source_input_changed',f'input hash differs: {p}')
            loaded=load_step(p,expected)
            translated=loaded.shape.translate(translation)
            normalized_path=output/('normalized-'+name+'.step')
            normalized_io=export_step(translated,normalized_path,expected,QualityPolicy(volume_rel=1e-10,area_rel=1e-10))
            normalized=load_step(normalized_path,expected)
            if len(normalized.shape.Faces())!=len(loaded.shape.Faces()):
                raise GeometryError('normalize_faces','normalization changed face count')
            inputs[name]=normalized.shape
            report.setdefault('normalization',{})[name]=normalized_io
            report.setdefault('inputs',{})[name]=loaded.report
        flow=inputs['flow'];shells=inputs['rotor'].Solids()
        checkpoint('inputs',{'translation_mm':translation,'frame':asdict(frame),'source_paths_read_only':True})
        local=transform_shape(flow,frame,to_local=True);b=local.BoundingBox()
        blade_config=config['blade'];law_config=dict(config['law']);kind=law_config.pop('kind')
        law=CircleLaw(**law_config) if kind=='circular_arc' else ThetaLaw(**law_config) if kind=='theta_r' else None
        if law is None:raise ContractError('unsupported blade law')
        r0,r1=blade_config['nominal_radial_bounds_mm'];margin=finite(blade_config['radial_margin_mm'],'radial margin')
        x_margin=finite(blade_config['axial_margin_mm'],'axial margin')
        if margin<0 or x_margin<0:raise ContractError('margins cannot be negative')
        thickness=Thickness(**blade_config['thickness'])
        blank=build_radial_blade(frame,(b.xmin-x_margin,b.xmax+x_margin),(r0-margin,r1+margin),thickness,law,
                                  samples=blade_config['samples'],fit_tolerance_mm=blade_config['fit_tolerance_mm'],
                                  centerline_bounds_mm=(r0,r1) if kind=='circular_arc' else None)
        checkpoint('blank',blank.report)
        domain=material_domain(flow,frame,source=report['inputs']['flow']['source']['path'])
        trimmed=trim_solid(blank.solid,domain,tolerance_mm=config['boolean_tolerance_mm'])
        blade=trimmed.require_one();validate_shape(blade,ONE,policy)
        measured=extreme_chord_thickness(blade,frame)
        chord_limit=finite(blade_config['chord_tolerance_mm'],'chord tolerance',positive=True)
        for value in measured.values():
            expected=thickness.value_mm if thickness.kind==ThicknessKind.CHORD else 2*value['radius_mm']*__import__('math').sin(thickness.half_angle(value['radius_mm']))
            if abs(value['chord_mm']-expected)>chord_limit:
                raise GeometryError('chord_mismatch','trimmed blade chord differs from declared thickness',{'measurements':measured,'limit_mm':chord_limit})
        trimmed_io=export_checkpoint(blade,output/'trimmed-blade.step',ONE,source_policy=True)
        if driver=='step_reload':blade=trimmed_io.shape
        report['outputs']['trimmed_blade']=trimmed_io.report
        measured=extreme_chord_thickness(blade,frame)
        for value in measured.values():
            expected=thickness.value_mm if thickness.kind==ThicknessKind.CHORD else 2*value['radius_mm']*__import__('math').sin(thickness.half_angle(value['radius_mm']))
            if abs(value['chord_mm']-expected)>chord_limit:
                raise GeometryError('chord_mismatch','loaded checkpoint chord differs from declared thickness',{'measurements':measured,'limit_mm':chord_limit})
        checkpoint('trimmed_blade',{'intersection':trimmed.report,'endpoint_chords':measured})
        single=fuse_components([Component('shell-'+str(i),'shell',s) for i,s in enumerate(shells)]+[Component('blade','blade',blade)],
                               tolerance_mm=config['boolean_tolerance_mm'],glue=False,unify_tolerance_mm=None,base_role='shell',volume_rel=volume_rel,unify_volume_rel=volume_rel)
        checkpoint('single_blade_fusion',single.report)
        rounded=fillet_two_end_rotor(single.shape,frame,**config['fillet'])
        rounded_io=export_checkpoint(rounded.shape,output/'single-rounded-rotor.step',ONE,source_policy=True)
        if driver=='step_reload':rounded.shape=rounded_io.shape
        report['outputs']['single_rounded_rotor']=rounded_io.report
        checkpoint('fillet',rounded.report)
        independent=extract_rounded_blade(rounded.shape,shells,tolerance_mm=config['boolean_tolerance_mm'])
        independent_io=export_checkpoint(independent.shape,output/'independent-rounded-blade.step',ONE,source_policy=True)
        if driver=='step_reload':independent.shape=independent_io.shape
        report['outputs']['independent_blade']=independent_io.report
        checkpoint('extraction',independent.report)
        copies,pattern_report=circular_pattern(independent.shape,frame.axis,config['pattern_count'])
        components=[Component('shell-'+str(i),'shell',s) for i,s in enumerate(shells)]+[Component('blade-'+str(i),'blade',s) for i,s in enumerate(copies)]
        assembly=assemble_unique(components,tolerance_mm=config['boolean_tolerance_mm'])
        expectation=ShapeExpectation(ShapeKind.COMPOUND,len(components))
        report['outputs']['assembly']=export_step(assembly.shape,output/'unfused-rotor.step',expectation,policy)
        loaded_assembly=load_step(output/'unfused-rotor.step',expectation)
        assembly_quality=validate_shape(loaded_assembly.shape,expectation,policy)
        if assembly_quality['minimum_edge_length_mm']<config['minimum_edge_length_mm']:
            raise GeometryError('short_edge','assembly checkpoint edge below configured limit',assembly_quality)
        loaded_components=loaded_assembly.shape.Solids()
        if len(loaded_components)!=len(components):raise GeometryError('checkpoint_components','component count changed')
        # Export/import order is checked against independent per-component shape
        # metadata. Do not infer roles by ordering volumes.
        for item,loaded in zip(components,loaded_components):
            before=item.solid.Center();after=loaded.Center()
            if (before-after).Length>1e-5:
                raise GeometryError('checkpoint_order','STEP component order cannot be verified geometrically')
        if driver=='step_reload':components=[Component(item.id,item.role,loaded) for item,loaded in zip(components,loaded_components)]
        checkpoint('pattern_and_assembly',{'pattern':pattern_report,'assembly':assembly.report})
        fused=fuse_components(components,tolerance_mm=config['boolean_tolerance_mm'],glue=config['fusion']['glue'],
                              unify_tolerance_mm=config['fusion']['unify_tolerance_mm'],base_role='shell',volume_rel=volume_rel,unify_volume_rel=volume_rel)
        validate_shape(fused.shape,ONE,policy)
        min_edge=fused.report['quality']['minimum_edge_length_mm']
        if min_edge is None or min_edge<config['minimum_edge_length_mm']:
            raise GeometryError('short_edge','final rotor edge below configured limit')
        final_io=export_step(fused.shape,output/'fused-rotor-candidate.step',ONE,policy)
        final_loaded=load_step(output/'fused-rotor-candidate.step',ONE)
        final_quality=validate_shape(final_loaded.shape,ONE,policy)
        outer=count_axis_cylinder_faces(final_loaded.shape,frame.axis,config['outer_cylinder']['radius_mm'],tolerance_mm=config['fusion']['unify_tolerance_mm'])
        before_outer=outer
        if outer['face_count']!=config['outer_cylinder']['expected_face_count']:
            unified=unify_same_domain(final_loaded.shape,tolerance_mm=config['fusion']['unify_tolerance_mm'],volume_rel=volume_rel)
            final_io=export_step(unified,output/'fused-rotor.step',ONE,policy)
        else:
            final_io=export_step(final_loaded.shape,output/'fused-rotor.step',ONE,policy)
        final_loaded=load_step(output/'fused-rotor.step',ONE)
        final_quality=validate_shape(final_loaded.shape,ONE,policy)
        outer=count_axis_cylinder_faces(final_loaded.shape,frame.axis,config['outer_cylinder']['radius_mm'],tolerance_mm=config['fusion']['unify_tolerance_mm'])
        if outer['face_count']!=config['outer_cylinder']['expected_face_count']:
            raise GeometryError('outer_cylinder_count','final outer cylinder face count differs after source-prescribed readback unification',outer)
        fused.report['outer_cylinder_before_readback_unify']=before_outer
        if final_quality['shell_count']!=1 or final_quality['minimum_edge_length_mm']<config['minimum_edge_length_mm']:
            raise GeometryError('final_quality','loaded final shell count or minimum edge failed',final_quality)
        report['outputs']['fused_rotor']=final_io
        fused.report['outer_cylinder']=outer
        fused.report['loaded_final_quality']=final_quality
        checkpoint('fusion',fused.report)
        report.update(success=True,status='complete',final_shape_mirror_used=False,law_kind=kind,
                      validation_scope='Explicitly configured geometry driver; intermediate STEP metrics audited; assembly/final use strict generic STEP and configured topology gates',
                      strict_generic_audit_failures=[key for key,value in report['outputs'].items() if not value.get('generic_strict_io_audit',{'success':True})['success']])
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return report
    except Exception as exc:
        report.update(success=False,status='failed',error=str(exc),failure_code=getattr(exc,'code','workflow_input'),failure_details=getattr(exc,'report',{}))
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if isinstance(exc,(GeometryError,ContractError)):raise
        raise GeometryError('rotor_workflow',str(exc),{'report_path':str(output/'report.json')}) from exc
