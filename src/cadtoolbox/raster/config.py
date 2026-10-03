"""Strict source-labelled calibration; pixel centres, not pixel cell extents."""
from dataclasses import asdict, dataclass
from math import isfinite
from ..contracts import ContractError, Parameter


def number(value, name, *, minimum=None, maximum=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ContractError(f'{name} needs a finite number')
    if integer and not isinstance(value, int): raise ContractError(f'{name} needs an integer')
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ContractError(f'{name} out of range')
    return value


def fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value)-set(required)-set(optional) or set(required)-set(value):
        raise ContractError('missing or unknown fields: '+str(required))
    return value


@dataclass(frozen=True)
class ImageConfig:
    threshold: int = 64
    foreground: str = 'dark'
    require_single_interval_per_row: bool = True
    minimum_foreground_rows: int = 20
    def __post_init__(self):
        number(self.threshold,'threshold',minimum=0,maximum=255,integer=True)
        number(self.minimum_foreground_rows,'minimum rows',minimum=3,integer=True)
        if self.foreground not in {'dark','light'} or self.require_single_interval_per_row is not True:
            raise ContractError('controlled filled profiles require dark/light and single interval per row')


@dataclass(frozen=True)
class GeometryConfig:
    simplify_tolerance_px: float = 1.5
    minimum_profile_area_mm2: float = 10
    def __post_init__(self):
        number(self.simplify_tolerance_px,'simplification',minimum=0)
        number(self.minimum_profile_area_mm2,'minimum area',minimum=1e-12)


@dataclass(frozen=True)
class RegionConfig:
    name: str
    color_rgb: tuple[int,int,int]
    tolerance: int = 0
    def __post_init__(self):
        if self.name not in {'low_body','flow_channel','high_body'} or len(self.color_rgb)!=3:
            raise ContractError('three region names and RGB required')
        for value in self.color_rgb:number(value,'RGB',minimum=0,maximum=255,integer=True)
        number(self.tolerance,'color tolerance',minimum=0,maximum=255,integer=True)


@dataclass(frozen=True)
class CalibrationConfig:
    mode: str
    x_min: Parameter
    x_max: Parameter
    r_min: Parameter
    r_max: Parameter
    def __post_init__(self):
        if self.mode not in {'foreground_bbox','image_bbox'}:raise ContractError('unsupported calibration mode')
        for p in [self.x_min,self.x_max,self.r_min,self.r_max]:
            if not isinstance(p,Parameter):raise ContractError('calibration requires source-labelled Parameter')
            p.resolved_mm()
        if self.x_max_mm<=self.x_min_mm or self.r_min_mm<0 or self.r_max_mm<=self.r_min_mm:
            raise ContractError('calibration requires increasing axial bounds and 0 <= r_min < r_max')
    @property
    def x_min_mm(self):return self.x_min.resolved_mm()
    @property
    def x_max_mm(self):return self.x_max.resolved_mm()
    @property
    def r_min_mm(self):return self.r_min.resolved_mm()
    @property
    def r_max_mm(self):return self.r_max.resolved_mm()
    def report(self,image_size,bbox):
        w,h=image_size
        domain=bbox if self.mode=='foreground_bbox' else (0,0,w-1,h-1)
        x0,y0,x1,y1=domain
        if x1<=x0 or y1<=y0:raise ContractError('degenerate calibration pixel span')
        sx=(self.x_max_mm-self.x_min_mm)/(x1-x0);sr=(self.r_max_mm-self.r_min_mm)/(y1-y0)
        return {'mode':self.mode,'parameters':{k:asdict(getattr(self,k)) for k in ['x_min','x_max','r_min','r_max']},
                'pixel_domain':domain,'mm_per_pixel':{'axial':sx,'radial':sr},
                'mapping':'x=x_min+(px-x0)*sx; r=r_min+(y1-py)*sr',
                'boundary_convention':'foreground pixel centres; image extents use width-1/height-1',
                'contour_status':'derived_from_pixels','calibration_is_design_confirmation':False,
                'uncertainty':'pixel centre / threshold / RDP approximation; no OCR or physical accuracy certification'}
    def map(self,points,image_size,bbox):
        report=self.report(image_size,bbox);x0,y0,x1,y1=report['pixel_domain'];s=report['mm_per_pixel']
        return tuple((self.x_min_mm+(x-x0)*s['axial'],self.r_min_mm+(y1-y)*s['radial']) for x,y in points)


def settings(config):
    c=fields(config,['mode','image','calibration','geometry'],['regions'])
    if c['mode'] not in {'single','three_regions'}:raise ContractError('unsupported raster profile mode')
    image=ImageConfig(**fields(c['image'],['threshold','foreground','require_single_interval_per_row','minimum_foreground_rows']))
    geometry=GeometryConfig(**fields(c['geometry'],['simplify_tolerance_px','minimum_profile_area_mm2']))
    cal=fields(c['calibration'],['mode','x_min','x_max','r_min','r_max'])
    for k in ['x_min','x_max','r_min','r_max']:
        spec=fields(cal[k],['name','value','unit','source','status'])
        if not all(isinstance(spec[n],str) and spec[n].strip() for n in ['name','unit','source','status']):raise ContractError('calibration requires text name/unit/source/status')
    ps={k:Parameter(**cal[k]) for k in ['x_min','x_max','r_min','r_max']}
    for spec in [cal[k] for k in ps]:
        if spec['value'] is not None:number(spec['value'],'calibration value')
    calibration=CalibrationConfig(cal['mode'],**ps)
    regions=tuple(RegionConfig(**fields(s,['name','color_rgb','tolerance'])) for s in c.get('regions',[]))
    if c['mode']=='single' and regions:raise ContractError('single mode does not accept color regions')
    if c['mode']=='three_regions' and (len(regions)!=3 or len({r.name for r in regions})!=3 or calibration.mode!='image_bbox'):
        raise ContractError('three regions require exactly low/flow/high and image_bbox calibration')
    return image,calibration,geometry,regions
