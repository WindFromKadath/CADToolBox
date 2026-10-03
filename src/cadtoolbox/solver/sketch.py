"""Real SolveSpace status plus independent residuals, not equation counting."""
from pathlib import Path
from math import hypot,dist
import json,os,subprocess,sys,time
from .model import normalize_sketch,dimension_mm,number
ROOT=Path(__file__).resolve().parents[3]


def residuals(spec,result,tolerance):
    pts=result['solved_points_mm'];radii=result['solved_radii_mm'];lines={c['id']:c for c in spec['lines']}
    def direction(key):
        c=lines[key];a,b=pts[c['start']],pts[c['end']];return [b[i]-a[i] for i in range(2)]
    checks=[]
    for c in spec['constraints']:
        kind=c['kind']
        if kind=='fixed_point':error=dist(pts[c['point']],c['datum']['xy_mm'])
        elif kind=='coincident':error=dist(pts[c['a']],pts[c['b']])
        elif kind=='distance':error=abs(dist(pts[c['a']],pts[c['b']])-dimension_mm(c))
        elif kind=='radius':error=abs(radii[c['circle']]-dimension_mm(c))
        elif kind in ['horizontal','vertical']:error=abs(direction(c['line'])[1 if kind=='horizontal' else 0])
        else:
            a,b=direction(c['a']),direction(c['b']);la,lb=hypot(*a),hypot(*b)
            if min(la,lb)<1e-9:error=float('inf')
            elif kind=='equal_length':error=abs(la-lb)
            elif kind=='parallel':error=abs(a[0]*b[1]-a[1]*b[0])/max(la,lb)
            else:error=abs(a[0]*b[0]+a[1]*b[1])/max(la,lb)
        checks.append({'id':c['id'],'kind':kind,'error_mm':error if error!=float('inf') else None,'passed':error<=tolerance})
    geometrically_noncollapsed=all(hypot(*direction(key))>1e-9 for key in lines) and all(r>1e-9 for r in radii.values())
    return {'success':all(c['passed'] for c in checks) and geometrically_noncollapsed,'tolerance_mm':tolerance,
            'checks':checks,'max_error_mm':max([c['error_mm'] for c in checks if c['error_mm'] is not None],default=0),
            'geometrically_noncollapsed':geometrically_noncollapsed,'method':'independent distance/orientation/radius/datum residuals using returned parameters'}


def solve_sketch(spec,*,residual_tolerance_mm=1e-7,timeout_seconds=30):
    s=normalize_sketch(spec);tol=number(residual_tolerance_mm,'residual tolerance',positive=True)
    timeout=number(timeout_seconds,'solve timeout',positive=True)
    if timeout>60:raise ValueError('solve timeout must not exceed 60 seconds')
    env=dict(os.environ);env['PYTHONPATH']=str(ROOT/'src');started=time.monotonic()
    report={'schema_version':1,'success':False,'geometry_eligible':False,'sketch':s,'unit':'mm'}
    try:
        p=subprocess.run([sys.executable,'-X','utf8','-B','-m','cadtoolbox.solver.worker'],input=json.dumps(s,allow_nan=False),
                         cwd=ROOT,env=env,text=True,encoding='utf-8',capture_output=True,timeout=timeout)
    except subprocess.TimeoutExpired:
        return {**report,'status':'backend_timeout','error':'native solve process exceeded configured timeout','timeout_seconds':timeout}
    try:result=json.loads(p.stdout)
    except ValueError:
        return {**report,'status':'backend_process_failed','exit_code':p.returncode,'stderr':p.stderr,'stdout':p.stdout}
    if p.returncode!=0 or result.get('worker_success') is not True:
        return {**report,'status':'backend_error','exit_code':p.returncode,'backend_failure':result,'stderr':p.stderr}
    flag=result['raw_result']['result'];dof=result['raw_result']['dof']
    report.update(result,elapsed_seconds=time.monotonic()-started,backend_converged=flag in [0,4],
                  coordinate_scope='group-2 local XY; failed solve coordinates are diagnostic, never geometry input')
    if flag==0:
        report['residuals']=residuals(s,result,tol)
        status='under_constrained' if dof>0 else 'fully_determined' if dof==0 else 'invalid_backend_dof'
        if not report['residuals']['success']:status='residual_or_degeneracy_failure'
    else:status={1:'inconsistent',2:'did_not_converge',3:'too_many_unknowns',4:'redundant'}.get(flag,'unknown_backend_status')
    report.update(status=status,success=status=='fully_determined',geometry_eligible=status=='fully_determined')
    return report
