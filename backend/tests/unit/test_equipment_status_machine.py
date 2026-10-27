import itertools
from datetime import date

import pytest

from app.core.exceptions import BusinessRuleError, InvalidStatusTransitionError
from app.domain.equipment.entities import ensure_installation_consistency
from app.domain.equipment.status import (
    STATUS_LABELS,
    STATUS_TRANSITIONS,
    EquipmentStatus,
    ensure_initial_status,
    ensure_transition_allowed,
)

S = EquipmentStatus
ALLOWED = {
    (S.NAO_INSTALADO, S.OPERACIONAL),
    (S.NAO_INSTALADO, S.DESATIVADO),
    (S.OPERACIONAL, S.MAU_FUNCIONAMENTO),
    (S.OPERACIONAL, S.EM_MANUTENCAO),
    (S.OPERACIONAL, S.DESATIVADO),
    (S.OPERACIONAL, S.FURTADO),
    (S.MAU_FUNCIONAMENTO, S.EM_MANUTENCAO),
    (S.MAU_FUNCIONAMENTO, S.OPERACIONAL),
    (S.MAU_FUNCIONAMENTO, S.DESATIVADO),
    (S.MAU_FUNCIONAMENTO, S.FURTADO),
    (S.EM_MANUTENCAO, S.OPERACIONAL),
    (S.EM_MANUTENCAO, S.MAU_FUNCIONAMENTO),
    (S.EM_MANUTENCAO, S.DESATIVADO),
    (S.DESATIVADO, S.EM_MANUTENCAO),
    (S.DESATIVADO, S.OPERACIONAL),
    (S.FURTADO, S.NAO_INSTALADO),
    (S.FURTADO, S.DESATIVADO),
}
ALL_PAIRS = list(itertools.product(EquipmentStatus, repeat=2))


def test_every_status_has_label_and_transition_entry() -> None:
    assert set(STATUS_LABELS) == set(EquipmentStatus)
    assert set(STATUS_TRANSITIONS) == set(EquipmentStatus)


@pytest.mark.parametrize(("current", "target"), sorted(ALLOWED))
def test_allowed_transition_should_pass(current: S, target: S) -> None:
    ensure_transition_allowed(current, target)


@pytest.mark.parametrize(("current", "target"), [pair for pair in ALL_PAIRS if pair not in ALLOWED])
def test_forbidden_transition_should_raise_with_allowed_list(current: S, target: S) -> None:
    with pytest.raises(InvalidStatusTransitionError) as error:
        ensure_transition_allowed(current, target)
    assert error.value.extra["allowed_transitions"] == sorted(
        s.value for s in STATUS_TRANSITIONS[current]
    )


def test_stolen_equipment_must_be_recovered_before_operating_again() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        ensure_transition_allowed(S.FURTADO, S.OPERACIONAL)


@pytest.mark.parametrize("status", [S.FURTADO, S.EM_MANUTENCAO])
def test_equipment_cannot_be_created_as(status: S) -> None:
    with pytest.raises(BusinessRuleError):
        ensure_initial_status(status)


def test_installed_status_requires_installation_date() -> None:
    with pytest.raises(BusinessRuleError):
        ensure_installation_consistency(S.OPERACIONAL, None, date(2026, 10, 1))


def test_installation_date_cannot_be_in_the_future() -> None:
    with pytest.raises(BusinessRuleError):
        ensure_installation_consistency(S.NAO_INSTALADO, date(2026, 10, 2), date(2026, 10, 1))
