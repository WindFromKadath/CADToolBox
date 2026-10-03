"""Validated point/line/circle sketch contracts; no native solver state here."""
from copy import deepcopy
from math import dist
from ..contracts import ContractError,Parameter,ParameterStatus,finite


def number(value,name,positive=False):
    if type(value) not in (int,float):raise ContractError(name+' must be numeric, not boolean or text')
    return finite(value,name,positive=positive)


def xy(value,name):
    if not isinstance(value,(list,tuple)) or len(value)!=2:raise ContractError(name+' requires two millimetre coordinates')
    return [number(v,name) for v in value]


def provenance(value,name):
    if not isinstance(value,dict) or not isinstance(value.get('source'),str) or not value['source'].strip():raise ContractError(name+' requires source provenance')
    if value.get('status') not in ['confirmed','derived']:raise ContractError(name+' must be resolved; assumed/missing/conflicting are not approved dimensions')


def normalize_sketch(spec):
    s=deepcopy(spec)
    if not isinstance(s,dict) or s.get('schema_version')!=1 or s.get('unit')!='mm':raise ContractError('sketch requires schema_version=1 and internal mm')
    allowed={'schema_version','unit','points','lines','circles','constraints'}
    if set(s)-allowed:raise ContractError('unknown sketch fields: '+str(sorted(set(s)-allowed)))
    ids=set()
    def index(group,max_count):
        values=s.setdefault(group,[])
        if not isinstance(values,list) or len(values)>max_count:raise ContractError(group+' exceeds supported count')
        result={}
        for entry in values:
            if not isinstance(entry,dict) or not isinstance(entry.get('id'),str) or not entry['id'].strip() or entry['id'] in ids:raise ContractError('all entity and constraint IDs must be unique nonempty text')
            ids.add(entry['id']);result[entry['id']]=entry
        return result
    pts=index('points',512);lines=index('lines',1024);circles=index('circles',128);constraints=index('constraints',4096)
    if not pts:raise ContractError('sketch requires points')
    for p in pts.values():
        if set(p)!={'id','initial_mm'}:raise ContractError('point fields are id and initial_mm')
        p['initial_mm']=xy(p['initial_mm'],'point initial guess')
    for line in lines.values():
        if set(line)!={'id','start','end'} or line['start'] not in pts or line['end'] not in pts or line['start']==line['end']:raise ContractError('line needs two distinct declared point IDs')
        if dist(pts[line['start']]['initial_mm'],pts[line['end']]['initial_mm'])<1e-9:raise ContractError('line initial guess is collapsed')
    for c in circles.values():
        if set(c)!={'id','center','initial_radius_mm'} or c['center'] not in pts:raise ContractError('circle fields are id, center and initial_radius_mm')
        c['initial_radius_mm']=number(c['initial_radius_mm'],'initial circle radius',positive=True)
    fixed_datums={}
    for c in constraints.values():
        kind=c.get('kind');fields={'id','kind'}
        if kind in ['horizontal','vertical']:
            fields|={'line'}
            if c.get('line') not in lines:raise ContractError('orientation constraint requires declared line')
        elif kind in ['coincident','distance']:
            fields|={'a','b'}
            if c.get('a') not in pts or c.get('b') not in pts or c['a']==c['b']:raise ContractError('point constraint requires two distinct point IDs')
            if kind=='distance':fields|={'parameter'}
        elif kind in ['equal_length','parallel','perpendicular']:
            fields|={'a','b'}
            if c.get('a') not in lines or c.get('b') not in lines or c['a']==c['b']:raise ContractError('line-pair constraint requires two distinct line IDs')
        elif kind=='fixed_point':
            fields|={'point','datum'}
            if c.get('point') not in pts:raise ContractError('fixed point is undeclared')
            provenance(c.get('datum'),'point datum')
            if set(c['datum'])!={'xy_mm','source','status'}:raise ContractError('datum fields are xy_mm/source/status')
            c['datum']['xy_mm']=xy(c['datum']['xy_mm'],'fixed point datum')
            if c['point'] in fixed_datums and fixed_datums[c['point']]!=c['datum']['xy_mm']:raise ContractError('multiple different WHERE_DRAGGED datums for one point are unsupported; use explicit geometric distance constraints')
            fixed_datums[c['point']]=c['datum']['xy_mm']
        elif kind=='radius':
            fields|={'circle','parameter'}
            if c.get('circle') not in circles:raise ContractError('radius requires declared circle')
        else:raise ContractError('unsupported constraint kind: '+str(kind))
        if set(c)!=fields:raise ContractError('unknown or missing constraint fields: '+c['id'])
        if 'parameter' in c:
            p=c['parameter'];provenance(p,'dimension')
            if not isinstance(p,dict) or set(p)!={'name','value','unit','source','status'}:raise ContractError('dimension requires Parameter fields')
            number(p['value'],'dimension')
            resolved=Parameter(**p).resolved_mm()
            if resolved<=0:raise ContractError('distance/radius must be positive')
    return s


def dimension_mm(constraint):return Parameter(**constraint['parameter']).resolved_mm()


def drive_dimensions(spec,updates):
    s=normalize_sketch(spec);constraints={c['id']:c for c in s['constraints']}
    if not isinstance(updates,dict):raise ContractError('dimension updates must map constraint IDs to Parameter objects')
    for key,param in updates.items():
        if key not in constraints or constraints[key]['kind'] not in ['distance','radius']:raise ContractError('only declared distance/radius constraints can be driven')
        constraints[key]['parameter']=deepcopy(param)
    return normalize_sketch(s)
