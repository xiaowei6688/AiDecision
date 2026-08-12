import pytest
from pydantic import ValidationError

from app.domain.models import DeviceRef, EmployeeRef, MaterialRef
from app.integrations.erp.models import PurchaseRequestCommand
from app.integrations.hr.models import LeaveRequestCommand
from app.integrations.inspection.models import InspectionTaskCommand


def test_system_entity_refs_keep_ownership_boundary() -> None:
    assert EmployeeRef(entity_id="E100").system == "hr"
    assert DeviceRef(entity_id="D100").system == "inspection"
    assert MaterialRef(entity_id="M100").system == "erp"


def test_domain_commands_expose_cross_system_references() -> None:
    task = InspectionTaskCommand(
        device_id="D100", assignee_id="E100", due_time="2026-08-08T09:00:00"
    )

    assert task.device.system == "inspection"
    assert task.assignee.system == "hr"
    assert PurchaseRequestCommand(material_id="M100", quantity=2, reason="补货").material.entity_id == "M100"


def test_leave_command_requires_a_valid_time_range() -> None:
    with pytest.raises(ValidationError, match="end_time must be after start_time"):
        LeaveRequestCommand(
            employee_id="E100",
            start_time="2026-08-08T10:00:00",
            end_time="2026-08-08T09:00:00",
            reason="年假",
        )
