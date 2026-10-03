"""Shared semantics. Lengths inside geometry are millimetres; angles are radians."""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from math import asin, cos, hypot, isfinite, sin

class ContractError(ValueError):
    pass

class Unit(StrEnum):
    MM = "mm"
    CM = "cm"
    M = "m"
    INCH = "inch"
    @property
    def mm_factor(self) -> float:
        return {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4}[self.value]


def finite(value: float, name: str, *, positive: bool = False) -> float:
    value = float(value)
    if not isfinite(value) or (positive and value <= 0):
        raise ContractError(f"{name} must be finite" + (" and positive" if positive else ""))
    return value


def vector(values, name: str) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ContractError(f"{name} needs three coordinates")
    return tuple(finite(v, name) for v in values)


def dot(a, b):
    return sum(x*y for x,y in zip(a,b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def normalized(values):
    v = vector(values, "direction")
    length = hypot(*v)
    if length < 1e-12:
        raise ContractError("direction cannot be zero")
    return tuple(x/length for x in v)


@dataclass(frozen=True)
class Axis:
    origin_mm: tuple[float, float, float] = (0,0,0)
    direction: tuple[float, float, float] = (1,0,0)
    def __post_init__(self):
        object.__setattr__(self, 'origin_mm', vector(self.origin_mm, 'origin_mm'))
        object.__setattr__(self, 'direction', normalized(self.direction))


@dataclass(frozen=True)
class Frame:
    """Right-handed local (axial, radial_1, radial_2); theta grows about axis."""
    axis: Axis
    radial_reference: tuple[float, float, float] = (0,1,0)
    def __post_init__(self):
        r = vector(self.radial_reference, 'radial_reference')
        axial_component = dot(r,self.axis.direction)
        r = tuple(v-axial_component*a for v,a in zip(r,self.axis.direction))
        object.__setattr__(self,'radial_reference',normalized(r))
    @property
    def radial_2(self):
        return cross(self.axis.direction,self.radial_reference)
    def to_world(self, local):
        local = vector(local,'local point')
        bases = (self.axis.direction,self.radial_reference,self.radial_2)
        return tuple(self.axis.origin_mm[i]+sum(local[j]*bases[j][i] for j in range(3)) for i in range(3))
    def to_local(self, world):
        delta = tuple(v-o for v,o in zip(vector(world,'world point'),self.axis.origin_mm))
        return tuple(dot(delta,b) for b in (self.axis.direction,self.radial_reference,self.radial_2))
    def cylindrical(self, axial_mm, radius_mm, theta_rad):
        radius = finite(radius_mm,'radius_mm',positive=True)
        theta = finite(theta_rad,'theta_rad')
        return self.to_world((axial_mm,radius*cos(theta),radius*sin(theta)))


class ThicknessKind(StrEnum):
    ARC_LENGTH = 'arc_length'
    CHORD = 'chord'
    NORMAL = 'normal'


@dataclass(frozen=True)
class Thickness:
    """value_mm always denotes full thickness; normal requires surface offset."""
    value_mm: float
    kind: ThicknessKind
    def __post_init__(self):
        object.__setattr__(self,'value_mm',finite(self.value_mm,'thickness',positive=True))
        object.__setattr__(self,'kind',ThicknessKind(self.kind))
    def half_angle(self, radius_mm: float) -> float:
        r = finite(radius_mm,'radius_mm',positive=True)
        if self.kind == ThicknessKind.NORMAL:
            raise ContractError('normal thickness requires a surface normal; angular conversion is unsupported')
        if self.kind == ThicknessKind.CHORD:
            if self.value_mm > 2*r:
                raise ContractError('chord thickness cannot exceed diameter')
            return asin(self.value_mm/(2*r))
        return self.value_mm/(2*r)


class ParameterStatus(StrEnum):
    CONFIRMED='confirmed'
    DERIVED='derived'
    ASSUMED='assumed'
    MISSING='missing'
    CONFLICTING='conflicting'


@dataclass(frozen=True)
class Parameter:
    name: str
    value: float | None
    unit: Unit
    source: str
    status: ParameterStatus  # No default: AI assumptions must be labelled.
    def __post_init__(self):
        if not self.name.strip() or not self.source.strip():
            raise ContractError('parameter name and source are required')
        object.__setattr__(self,'unit',Unit(self.unit))
        object.__setattr__(self,'status',ParameterStatus(self.status))
        if self.value is not None:
            object.__setattr__(self,'value',finite(self.value,self.name))
        if self.status == ParameterStatus.MISSING and self.value is not None:
            raise ContractError('missing parameter cannot have a value')
        if self.status not in {ParameterStatus.MISSING,ParameterStatus.CONFLICTING} and self.value is None:
            raise ContractError('resolved parameter requires a value')
    def resolved_mm(self, *, allow_assumed: bool = False):
        if self.status in {ParameterStatus.MISSING,ParameterStatus.CONFLICTING} or (self.status == ParameterStatus.ASSUMED and not allow_assumed):
            raise ContractError(f'{self.name}: unresolved or unapproved assumed parameter')
        if self.value is None:
            raise ContractError(f'{self.name}: no value')
        return finite(self.value*self.unit.mm_factor,self.name+' in mm')
    def check_mm(self, *, minimum: float | None = None, maximum: float | None = None, allow_assumed: bool = False) -> dict:
        limits = {k:finite(v,k) for k,v in [('minimum',minimum),('maximum',maximum)] if v is not None}
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ContractError('minimum exceeds maximum')
        errors = []
        value_mm = None
        try:
            value_mm = self.resolved_mm(allow_assumed=allow_assumed)
            if minimum is not None and value_mm < minimum:
                errors.append('below minimum')
            if maximum is not None and value_mm > maximum:
                errors.append('above maximum')
        except ContractError as exc:
            errors.append(str(exc))
        return {'success':not errors,'name':self.name,'value_mm':value_mm,'source':self.source,
                'status':self.status.value,'limits_mm':limits,'errors':errors}


class DomainKind(StrEnum):
    AXISYMMETRIC_MERIDIONAL='axisymmetric_meridional'
    PROJECTED_EXTRUSION='projected_extrusion'
    MATERIAL_SOLID='material_solid'


@dataclass(frozen=True)
class DomainSpec:
    kind: DomainKind
    frame: Frame
    source: str
    def __post_init__(self):
        object.__setattr__(self,'kind',DomainKind(self.kind))
        if not self.source.strip():
            raise ContractError('domain source required')


class ShapeKind(StrEnum):
    FACE='Face'
    SOLID='Solid'
    COMPOUND='Compound'


@dataclass(frozen=True)
class ShapeExpectation:
    kind: ShapeKind
    solid_count: int = 0
    def __post_init__(self):
        object.__setattr__(self,'kind',ShapeKind(self.kind))
        if type(self.solid_count) is not int or self.solid_count < 0:
            raise ContractError('solid_count must be a nonnegative integer')
        if (self.kind == ShapeKind.SOLID and self.solid_count != 1) or (self.kind == ShapeKind.FACE and self.solid_count != 0):
            raise ContractError('Solid requires one solid; Face requires zero solids')


@dataclass(frozen=True)
class QualityPolicy:
    area_abs_mm2: float = 1e-6
    area_rel: float = 1e-7
    volume_abs_mm3: float = 1e-6
    volume_rel: float = 1e-7
    bbox_abs_mm: float = 1e-5
    reject_degenerated_edges: bool = False
    def __post_init__(self):
        for name in ('area_abs_mm2','area_rel','volume_abs_mm3','volume_rel','bbox_abs_mm'):
            object.__setattr__(self,name,finite(getattr(self,name),name,positive=True))
