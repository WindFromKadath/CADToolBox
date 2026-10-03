from math import pi, sin
import pytest
from cadtoolbox.contracts import (Axis,Frame,Thickness,ThicknessKind,Parameter,ParameterStatus,
                                  Unit,ContractError,DomainKind,DomainSpec,ShapeKind,ShapeExpectation,QualityPolicy)


def test_frame_coordinates_and_right_hand_rule():
    frame = Frame(Axis((10,20,30),(2,0,0)),(0,2,0))
    assert frame.to_world((3,4,5)) == (13,24,35)
    assert frame.to_local((13,24,35)) == (3,4,5)
    assert frame.cylindrical(3,4,pi/2) == pytest.approx((13,20,34))
    tilted = Frame(Axis((7,-3,2),(1,2,3)),(0,1,0))
    assert tilted.to_local(tilted.to_world((12,-7,3))) == pytest.approx((12,-7,3))


@pytest.mark.parametrize('origin,direction',[((0,0,0),(0,0,0)),((0,0,0),(float('nan'),1,0)),((float('inf'),0,0),(1,0,0))])
def test_bad_axis(origin,direction):
    with pytest.raises(ContractError):
        Axis(origin,direction)


def test_parallel_radial_reference_rejected():
    with pytest.raises(ContractError):
        Frame(Axis(),(1,0,0))


def test_thickness_definitions_are_distinct():
    arc = Thickness(12,ThicknessKind.ARC_LENGTH).half_angle(10)
    chord = Thickness(12,ThicknessKind.CHORD).half_angle(10)
    assert arc == pytest.approx(0.6)
    assert 2*10*sin(chord) == pytest.approx(12)
    assert chord > arc
    assert Thickness(20,ThicknessKind.CHORD).half_angle(10) == pytest.approx(pi/2)
    with pytest.raises(ContractError):
        Thickness(20.001,ThicknessKind.CHORD).half_angle(10)
    with pytest.raises(ContractError,match='surface normal'):
        Thickness(1,ThicknessKind.NORMAL).half_angle(10)
    with pytest.raises(ContractError):
        Thickness(0,ThicknessKind.ARC_LENGTH)


def test_parameter_provenance_and_unit_conversion():
    p = Parameter('length',2,Unit.CM,'dimension A',ParameterStatus.CONFIRMED)
    assert p.resolved_mm() == 20
    assert Parameter('length',2,Unit.INCH,'drawing',ParameterStatus.DERIVED).resolved_mm() == 50.8
    assumed = Parameter('length',2,Unit.M,'AI estimate',ParameterStatus.ASSUMED)
    with pytest.raises(ContractError):
        assumed.resolved_mm()
    assert assumed.resolved_mm(allow_assumed=True) == 2000
    for status in (ParameterStatus.MISSING,ParameterStatus.CONFLICTING):
        with pytest.raises(ContractError):
            Parameter('length',None,Unit.MM,'drawing missing',status).resolved_mm()
    with pytest.raises(ContractError):
        Parameter('length',2,Unit.MM,'',ParameterStatus.CONFIRMED)
    with pytest.raises(ContractError):
        Parameter('length',2,Unit.MM,'unknown',ParameterStatus.MISSING)


def test_domains_and_result_semantics():
    frame=Frame(Axis())
    domains = [DomainSpec(k,frame,'confirmed drawing') for k in DomainKind]
    assert len({d.kind for d in domains}) == 3
    assert ShapeExpectation(ShapeKind.FACE).solid_count == 0
    assert ShapeExpectation(ShapeKind.COMPOUND,2).solid_count == 2
    with pytest.raises(ContractError):
        ShapeExpectation(ShapeKind.SOLID,2)
    with pytest.raises(ContractError):
        ShapeExpectation(ShapeKind.FACE,1)
    with pytest.raises(ContractError):
        QualityPolicy(volume_rel=float('nan'))


def test_dimensions_bounds_keep_assumed_status():
    p=Parameter('length',2,Unit.CM,'manual dimension',ParameterStatus.CONFIRMED)
    assert p.check_mm(minimum=20,maximum=20)['success']
    assert not p.check_mm(maximum=19.9)['success']
    assert not p.check_mm(minimum=20.1)['success']
    assumed=Parameter('length',2,Unit.CM,'AI estimate',ParameterStatus.ASSUMED)
    assert not assumed.check_mm()['success']
    assert assumed.check_mm(allow_assumed=True)['status'] == 'assumed'
    assert Axis(direction=(1e308,0,0)).direction == (1,0,0)
