"""One native sketch per short-lived process: global slvs state never shared."""
from importlib.metadata import version
import json,os,sys
from .model import normalize_sketch,dimension_mm


def execute(spec):
    import slvs
    if version('slvs')!='3.2':raise RuntimeError('slvs backend version must match audited 3.2')
    s=normalize_sketch(spec);slvs.clear_sketch()
    # Fixed reference entities in group 1; solve only the 2D entities in group 2.
    origin=slvs.add_point_3d(1,0,0,0);normal=slvs.add_normal_3d(1,1,0,0,0);wp=slvs.add_workplane(1,origin,normal);g=2
    initial={p['id']:list(p['initial_mm']) for p in s['points']}
    # WHERE_DRAGGED fixes the current parameters. Two different datum requests
    # for a point must remain inconsistent instead of one overwriting another.
    anchors={};anchor_constraints=[]
    for c in s['constraints']:
        if c['kind']=='fixed_point':
            if c['point'] not in anchors:
                anchors[c['point']]=c['datum']['xy_mm'];initial[c['point']]=c['datum']['xy_mm']
                anchor_constraints.append(c)
            elif anchors[c['point']]!=c['datum']['xy_mm']:
                raise ValueError('conflicting fixed datums for one point must be expressed as geometric distance constraints; unsupported native WHERE_DRAGGED duplicate')
            else:anchor_constraints.append(c)
    pts={key:slvs.add_point_2d(g,*point,wp) for key,point in initial.items()}
    lines={c['id']:slvs.add_line_2d(g,pts[c['start']],pts[c['end']],wp) for c in s['lines']}
    radii={c['id']:slvs.add_distance(g,c['initial_radius_mm'],wp) for c in s['circles']}
    circles={c['id']:slvs.add_circle(g,normal,pts[c['center']],radii[c['id']],wp) for c in s['circles']}
    handles={}
    for c in s['constraints']:
        kind=c['kind']
        if kind in ['horizontal','vertical']:native=getattr(slvs,kind)(g,lines[c['line']],wp)
        elif kind=='fixed_point':native=slvs.dragged(g,pts[c['point']],wp)
        elif kind=='distance':native=slvs.distance(g,pts[c['a']],pts[c['b']],dimension_mm(c),wp)
        elif kind=='coincident':native=slvs.coincident(g,pts[c['a']],pts[c['b']],wp)
        elif kind=='radius':native=slvs.diameter(g,circles[c['circle']],2*dimension_mm(c))
        else:native=getattr(slvs,{'equal_length':'equal','parallel':'parallel','perpendicular':'perpendicular'}[kind])(g,lines[c['a']],lines[c['b']],wp)
        handles[native['h']]=c['id']
    raw,bad=slvs.solve_sketch(g,True)
    return {'backend':'slvs','version':version('slvs'),'raw_result':dict(raw),'raw_failed_constraint_handles':list(bad),
            'failed_constraint_ids':[handles.get(h,'unmapped:'+str(h)) for h in bad],
            'backend_result_name':slvs.ResultFlag(raw['result']).name,
            'solved_points_mm':{key:[slvs.get_param_value(p['param'][0]),slvs.get_param_value(p['param'][1])] for key,p in pts.items()},
            'solved_radii_mm':{key:slvs.get_param_value(r['param'][0]) for key,r in radii.items()},
            'isolation':{'method':'one subprocess per solve','process_id':os.getpid(),'fixed_reference_group':1,'solved_group':2,'local_plane':'XY identity quaternion','reference_entity_types':{'origin':origin['type'],'normal':normal['type'],'workplane':wp['type']}}}


def main():
    try:print(json.dumps({'worker_success':True,**execute(json.loads(sys.stdin.read()))},allow_nan=False))
    except Exception as exc:
        print(json.dumps({'worker_success':False,'error_type':type(exc).__name__,'error':str(exc)},allow_nan=False));return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
