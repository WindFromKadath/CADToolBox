"""Explicit unique components, pattern validation and two-end fillets (S020/S023/S039)."""
from dataclasses import dataclass
from math import degrees,pi
import cadquery as cq
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from ..contracts import Axis,Frame,ShapeExpectation,ShapeKind,ContractError,finite
from .quality import GeometryResult,GeometryError,validate_shape,topology,integrated_volume,INTEGRATION_EPS
from .transforms import transform_shape
from .rotor_junction import recognize_concave_junction_edges,split_junction_edges_by_x,apply_split_radius_fillet

ONE=ShapeExpectation(ShapeKind.SOLID,1)

@dataclass(frozen=True)
class Component:
    id: str
    role: str
    solid: cq.Solid


def _components(items):
    if not items:raise ContractError('nonempty component list required')
    ids=[];shapes=[]
    for item in items:
        if not item.id.strip() or not item.role.strip() or item.id in ids:
            raise ContractError('component IDs must be nonempty and unique; roles must be explicit')
        if any(item.solid.isSame(previous) for previous in shapes):
            raise ContractError('the same physical component was supplied twice')
        validate_shape(item.solid,ONE);ids.append(item.id);shapes.append(item.solid)


def unify_same_domain(solid: cq.Solid,*,tolerance_mm=1e-5,volume_rel=1e-9):
    tolerance=finite(tolerance_mm,'unify tolerance',positive=True)
    if type(volume_rel) is bool:raise ContractError('volume relative tolerance must be numeric, not boolean')
    volume_rel=finite(volume_rel,'unify volume relative tolerance',positive=True)
    unifier=ShapeUpgrade_UnifySameDomain(solid.wrapped,True,True,True)
    unifier.AllowInternalEdges(False);unifier.SetLinearTolerance(tolerance);unifier.SetAngularTolerance(1e-6);unifier.Build()
    solids=cq.Shape.cast(unifier.Shape()).Solids()
    if len(solids)!=1:raise GeometryError('unify_count','same-domain unification changed solid count')
    result=solids[0];validate_shape(result,ONE)
    before=integrated_volume(solid);after=integrated_volume(result)
    if abs(after-before)>max(1e-5,before*volume_rel):
        error=GeometryError('unify_volume','same-domain unification changed volume',{'before_mm3':before,'after_mm3':after,'difference_mm3':abs(after-before),'limit_mm3':max(1e-5,before*volume_rel),'volume_relative_tolerance':volume_rel})
        error.partial_shape=result
        raise error
    return result


def fuse_components(items: list[Component],*,tolerance_mm=1e-6,glue=False,unify_tolerance_mm=1e-5,base_role=None,volume_rel=1e-8,unify_volume_rel=1e-9):
    _components(items)
    tolerance=finite(tolerance_mm,'fusion tolerance',positive=True)
    if type(volume_rel) is bool or type(unify_volume_rel) is bool:
        raise ContractError('volume relative tolerances must be numeric, not boolean')
    volume_rel=finite(volume_rel,'fusion volume relative tolerance',positive=True)
    unify_volume_rel=finite(unify_volume_rel,'unify volume relative tolerance',positive=True)
    if type(glue) is not bool:raise ContractError('glue must be explicitly boolean')
    report={'success':False,'components':[{'id':c.id,'role':c.role,'volume_mm3':integrated_volume(c.solid)} for c in items],
            'tolerance_mm':tolerance,'glue':glue,'mass_integration_relative_target':INTEGRATION_EPS,'volume_relative_tolerance':volume_rel,'unify_volume_relative_tolerance':unify_volume_rel}
    try:
        if base_role is not None:
            base=[c.solid for c in items if c.role==base_role];remaining=[c.solid for c in items if c.role!=base_role]
            if not base or not remaining:raise ContractError('base role requires both base and remaining components')
            result=cq.Compound.makeCompound(base).fuse(*remaining,tol=tolerance,glue=glue).clean()
        else:
            result=items[0].solid.fuse(*(c.solid for c in items[1:]),tol=tolerance,glue=glue).clean() if len(items)>1 else items[0].solid
        report.update(base_role=base_role,unify_tolerance_mm=unify_tolerance_mm)
        solids=result.Solids()
        report['result_solid_count']=len(solids)
        if len(solids)!=1:
            report['status']='partial'
            raise GeometryError('partial_fusion','components did not fuse into one solid',report)
        solid=unify_same_domain(solids[0],tolerance_mm=unify_tolerance_mm,volume_rel=unify_volume_rel) if unify_tolerance_mm is not None else solids[0]
        quality=validate_shape(solid,ONE)
        total=sum(c['volume_mm3'] for c in report['components']);volume=quality['volume_mm3']
        report.update(input_volume_sum_mm3=total,fused_volume_mm3=volume,
                      volume_excess_mm3=volume-total,volume_limit_mm3=max(1e-5,total*volume_rel),quality=quality)
        if volume>total+max(1e-5,total*volume_rel):
            error=GeometryError('fusion_volume','union exceeds sum of input volumes',report)
            error.partial_shape=solid  # diagnostic access, never serialized as a passed result
            raise error
        report.update(success=True,status='complete',quality=quality,input_volume_sum_mm3=total,
                      fused_volume_mm3=volume,overlap_volume_mm3=total-volume)
        return GeometryResult(solid,report)
    except GeometryError:raise
    except Exception as exc:raise GeometryError('fusion_failed',f'fusion failed: {exc}',report) from exc


def circular_pattern(solid: cq.Solid,axis: Axis,count: int,*,total_angle_rad=2*pi,separation_mm=1e-6):
    validate_shape(solid,ONE)
    if type(count) is not int or count<1:raise ContractError('pattern count must be an integer >=1')
    total=finite(total_angle_rad,'total angle',positive=True)
    limit=finite(separation_mm,'separation threshold',positive=True)
    if total>2*pi+1e-12:raise ContractError('pattern sweep cannot exceed one full turn')
    endpoint=tuple(o+d for o,d in zip(axis.origin_mm,axis.direction))
    copies=tuple(solid.rotate(axis.origin_mm,endpoint,degrees(i*total/count)) for i in range(count))
    base_volume=integrated_volume(solid)
    for copy in copies:
        copy_quality=validate_shape(copy,ONE)
        if abs(copy_quality['volume_mm3']-base_volume)>max(1e-5,base_volume*1e-10):
            raise GeometryError('pattern_volume','rigid pattern changed blade volume')
    # Every possible relative pitch is represented by base -> copy[k], which
    # covers all pairs by rotational invariance, including nonadjacent blades.
    distances=list(copies[0].distances(*copies[1:]))
    if any(d<=limit for d in distances):
        raise GeometryError('pattern_interference','pattern copies touch or intersect',{'relative_pitch_distances_mm':distances})
    compound=cq.Compound.makeCompound(copies)
    return copies,{'success':True,'count':count,'pitch_rad':total/count,'total_angle_rad':total,
                   'relative_pitch_distances_mm':distances,'quality':validate_shape(compound,ShapeExpectation(ShapeKind.COMPOUND,count))}


def assemble_unique(items: list[Component],*,require_blade_shell_contact=True,tolerance_mm=1e-6):
    _components(items)
    tolerance=finite(tolerance_mm,'contact tolerance',positive=True)
    distances=[]
    if require_blade_shell_contact:
        shells=[c for c in items if c.role=='shell'];blades=[c for c in items if c.role=='blade']
        if not shells or not blades:raise ContractError('contact check requires explicit shell and blade roles')
        for blade in blades:
            for shell,d in zip(shells,blade.solid.distances(*(s.solid for s in shells))):
                distances.append({'blade':blade.id,'shell':shell.id,'distance_mm':d})
                if d>max(1e-5,tolerance*10):
                    raise GeometryError('missing_contact','a patterned blade does not contact its declared shell',{'contacts':distances})
    compound=cq.Compound.makeCompound([c.solid for c in items])
    return GeometryResult(compound,{'success':True,'contacts':distances,
        'quality':validate_shape(compound,ShapeExpectation(ShapeKind.COMPOUND,len(items)))})


def fillet_two_end_rotor(fused: cq.Solid,frame: Frame,*,low_radius_mm,high_radius_mm,
                         expected_semantic_candidates:int,expected_low_edges:int,expected_high_edges:int,
                         probe_mm=0.1,classification_tolerance_mm=1e-7):
    validate_shape(fused,ONE)
    low=finite(low_radius_mm,'low fillet radius',positive=True);high=finite(high_radius_mm,'high fillet radius',positive=True)
    probe=finite(probe_mm,'concavity probe scale',positive=True)
    tolerance=finite(classification_tolerance_mm,'classification tolerance',positive=True)
    for value in (expected_semantic_candidates,expected_low_edges,expected_high_edges):
        if type(value) is not int or value<1:raise ContractError('expected junction counts must be positive integers')
    local=transform_shape(fused,frame,to_local=True)
    try:
        edges,type_counts,candidates=recognize_concave_junction_edges(local,probe_mm=probe,classification_tolerance_mm=tolerance)
        if candidates!=expected_semantic_candidates or len(edges)!=expected_low_edges+expected_high_edges:
            raise GeometryError('junction_counts','junction counts differ from declared rotor rule',
                {'semantic_candidates':candidates,'concave_edges':len(edges)})
        low_edges,high_edges,split=split_junction_edges_by_x(edges,expected_low=expected_low_edges,expected_high=expected_high_edges)
        rounded=apply_split_radius_fillet(local,low_edges,high_edges,low_x_radius=low,high_x_radius=high)
        rounded=transform_shape(rounded,frame)
        quality=validate_shape(rounded,ONE)
    except GeometryError:raise
    except Exception as exc:raise GeometryError('rotor_fillet',f'two-end rotor fillet failed: {exc}') from exc
    return GeometryResult(rounded,{'success':True,'rule':'EXTRUSION blade against CYLINDER/CONE/TORUS/PLANE rotor; two axial groups',
        'semantic_candidates':candidates,'concave_edges':len(edges),'low_edges':len(low_edges),'high_edges':len(high_edges),
        'split_axial_mm':split,'low_radius_mm':low,'high_radius_mm':high,'probe_mm':probe,
        'surface_pairs':{' + '.join(k):v for k,v in type_counts.items()},'quality':quality})


def extract_rounded_blade(rounded: cq.Solid,shells: list[cq.Solid],*,tolerance_mm=1e-6):
    if not shells:raise ContractError('extraction requires the original shells')
    tolerance=finite(tolerance_mm,'cut tolerance',positive=True)
    result=rounded.cut(*shells,tol=tolerance).clean()
    solids=result.Solids()
    if len(solids)!=1:raise GeometryError('blade_extraction','subtracting shells did not leave one blade',{'solid_count':len(solids),'components':[topology(s) for s in solids]})
    validate_shape(solids[0],ONE)
    return GeometryResult(solids[0],{'success':True,'shell_count':len(shells),'quality':topology(solids[0])})
