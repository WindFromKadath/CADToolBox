"""Four continuous angle-field modes migrated from S041; all outputs radians."""
import ast,bisect,math
from types import SimpleNamespace
from OCP.GeomAPI import GeomAPI_Interpolate
from OCP.TColgp import TColgp_HArray1OfPnt
from OCP.TColStd import TColStd_HArray1OfReal
from OCP.gp import gp_Pnt
from ..contracts import Axis,ContractError,finite
from .parametric import uv


def factor(unit):
    if unit in ('degree','degrees','deg'):return math.pi/180
    if unit in ('radian','radians','rad'):return 1.0
    raise ContractError('angle unit must be degree or radian')


def value(x,name):
    if type(x) is bool:raise ContractError(name+' cannot be boolean')
    return finite(x,name)


def unwrap(values):
    out=[values[0]]
    for x in values[1:]:
        delta=finite(x-out[-1],'phase difference')
        wrapped=(delta+math.pi)%(2*math.pi)-math.pi
        if wrapped==-math.pi and delta>0:wrapped=math.pi
        out.append(out[-1]+wrapped)
    return out


class Field:
    def gradient(self,u,v):
        u,v=uv(u,v);h=1e-6;ua=max(0,u-h);ub=min(1,u+h);va=max(0,v-h);vb=min(1,v+h)
        return ((self.evaluate(ub,v)-self.evaluate(ua,v))/(ub-ua),(self.evaluate(u,vb)-self.evaluate(u,va))/(vb-va))


class FormulaField(Field):
    FUNCTIONS={name:getattr(math,name) for name in ['sin','cos','tan','sqrt','exp','log']}
    FUNCTIONS.update(abs=abs,min=min,max=max)
    def __init__(self,expression,base,axis:Axis,unit='degree'):
        if not isinstance(expression,str):raise ContractError('formula must be text')
        try:tree=ast.parse(expression,mode='eval')
        except SyntaxError as exc:raise ContractError('invalid angle formula') from exc
        allowed=(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow,ast.Mod,ast.UAdd,ast.USub,ast.Load,ast.Name,ast.Constant,ast.Call,ast.Attribute)
        nodes=list(ast.walk(tree))
        if len(nodes)>128:raise ContractError('angle formula is too large')
        for node in nodes:
            if not isinstance(node,allowed):raise ContractError('unsupported syntax in angle formula')
            if isinstance(node,ast.Constant) and (type(node.value) not in (int,float) or not math.isfinite(node.value)):
                raise ContractError('formula constants must be finite numeric values')
            if isinstance(node,ast.Name) and node.id not in set(self.FUNCTIONS)|{'u','v','x','y','z','r','pi','math'}:
                raise ContractError('unknown name in angle formula: '+node.id)
            if isinstance(node,ast.Attribute) and (not isinstance(node.value,ast.Name) or node.value.id!='math' or node.attr not in set(self.FUNCTIONS)|{'pi'}):
                raise ContractError('formula attribute access is restricted to named math functions')
            if isinstance(node,ast.Call):
                name=node.func.id if isinstance(node.func,ast.Name) else node.func.attr if isinstance(node.func,ast.Attribute) else ''
                if name not in self.FUNCTIONS or node.keywords:raise ContractError('unsupported formula call')
        self.code=compile(tree,'<theta_formula>','eval');self.base=base;self.axis=axis;self.scale=factor(unit)
        self.report={'mode':'formula','expression':expression,'input_unit':unit,'output_unit':'rad','formula_coordinates':'world xyz, perpendicular axis radius mm'}
    def evaluate(self,u,v):
        u,v=uv(u,v);p=self.base.evaluate(u,v);d=tuple(x-o for x,o in zip(p,self.axis.origin_mm));a=self.axis.direction
        r=math.sqrt((d[1]*a[2]-d[2]*a[1])**2+(d[2]*a[0]-d[0]*a[2])**2+(d[0]*a[1]-d[1]*a[0])**2)
        env={**self.FUNCTIONS,'math':SimpleNamespace(**self.FUNCTIONS,pi=math.pi),'pi':math.pi,'u':u,'v':v,'x':p[0],'y':p[1],'z':p[2],'r':r}
        try:return finite(eval(self.code,{'__builtins__':{}},env)*self.scale,'formula theta')
        except (ValueError,TypeError,OverflowError,ZeroDivisionError) as exc:raise ContractError('angle formula evaluation failed: '+str(exc)) from exc


class SampleField(Field):
    def __init__(self,samples,unit='degree'):
        if len(samples)<2:raise ContractError('at least two theta samples required')
        data=sorted((value(s['v'],'sample v'),value(s['value'],'sample angle')*factor(unit)) for s in samples)
        xs=[x for x,_ in data];ys=unwrap([y for _,y in data])
        if abs(xs[0])>1e-12 or abs(xs[-1]-1)>1e-12 or any(b-a<=1e-12 for a,b in zip(xs,xs[1:])):
            raise ContractError('theta samples must be distinct, ordered over [0,1], with both endpoints')
        pts=TColgp_HArray1OfPnt(1,len(xs));params=TColStd_HArray1OfReal(1,len(xs))
        for i,(x,y) in enumerate(zip(xs,ys),1):pts.SetValue(i,gp_Pnt(x,y,0));params.SetValue(i,x)
        interp=GeomAPI_Interpolate(pts,params,False,1e-12);interp.Perform()
        if not interp.IsDone():raise ContractError('theta B-Spline interpolation failed')
        self.curve=interp.Curve()
        residuals=[abs(self.curve.Value(x).Y()-y) for x,y in zip(xs,ys)]
        self.report={'mode':'radial_samples','input_unit':unit,'output_unit':'rad','sample_count':len(xs),'sample_max_error_rad':max(residuals),'unwrap':'nearest continuous phase, as source','interpolation':'parameter-specified B-Spline'}
    def evaluate(self,u,v):
        _,v=uv(u,v);return finite(self.curve.Value(v).Y(),'sampled theta')


class EndField(Field):
    def __init__(self,u0_samples,u1_samples,unit='degree',axial_interp='linear'):
        if axial_interp not in ('linear','smoothstep'):raise ContractError('unknown axial interpolation')
        self.a=SampleField(u0_samples,unit);self.b=SampleField(u1_samples,unit);self.interp=axial_interp
        self.report={'mode':'end_laws','output_unit':'rad','axial_interp':axial_interp,'u0':self.a.report,'u1':self.b.report}
    def evaluate(self,u,v):
        u,v=uv(u,v);w=u if self.interp=='linear' else u*u*(3-2*u)
        return (1-w)*self.a.evaluate(0,v)+w*self.b.evaluate(1,v)


def hermite(xs,ys,t):
    i=max(0,min(bisect.bisect_right(xs,t)-1,len(xs)-2));h=xs[i+1]-xs[i];q=(t-xs[i])/h
    slopes=[(ys[1]-ys[0])/(xs[1]-xs[0])]+[(ys[k+1]-ys[k-1])/(xs[k+1]-xs[k-1]) for k in range(1,len(xs)-1)]+[(ys[-1]-ys[-2])/(xs[-1]-xs[-2])]
    return (2*q**3-3*q*q+1)*ys[i]+(q**3-2*q*q+q)*h*slopes[i]+(-2*q**3+3*q*q)*ys[i+1]+(q**3-q*q)*h*slopes[i+1]


class GridField(Field):
    def __init__(self,u_grid,v_grid,values_2d,unit='degree'):
        self.u=[value(x,'u grid') for x in u_grid];self.v=[value(x,'v grid') for x in v_grid]
        for xs in [self.u,self.v]:
            if len(xs)<2 or abs(xs[0])>1e-12 or abs(xs[-1]-1)>1e-12 or any(b<=a for a,b in zip(xs,xs[1:])):raise ContractError('strictly increasing grids spanning [0,1] required')
        if len(values_2d)!=len(self.u) or any(len(row)!=len(self.v) for row in values_2d):raise ContractError('theta grid shape mismatch')
        self.values=[unwrap([value(x,'grid angle')*factor(unit) for x in row]) for row in values_2d]
        for j in range(len(self.v)):
            column=unwrap([row[j] for row in self.values])
            for i,x in enumerate(column):self.values[i][j]=x
        self.report={'mode':'grid','shape':[len(self.u),len(self.v)],'input_unit':unit,'output_unit':'rad','interpolation':'nonuniform separable C1 cubic Hermite, exact at nodes','unwrap':'v then u, as source'}
    def evaluate(self,u,v):
        u,v=uv(u,v);return finite(hermite(self.u,[hermite(self.v,row,v) for row in self.values],u),'grid theta')


def build_field(config,base,axis):
    c=dict(config);mode=c.pop('mode')
    if mode=='formula':return FormulaField(base=base,axis=axis,**c)
    if mode=='radial_samples':return SampleField(**c)
    if mode=='end_laws':return EndField(**c)
    if mode=='grid':return GridField(**c)
    raise ContractError('unsupported theta mode: '+str(mode))
