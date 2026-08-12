from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import DeviceRef, EmployeeRef


class InspectionTaskCommand(BaseModel):
    """Inspection command accepted by inspection.create_task."""

    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1)
    assignee_id: str = Field(min_length=1)
    due_time: datetime

    @property
    def device(self) -> DeviceRef:
        return DeviceRef(entity_id=self.device_id)

    @property
    def assignee(self) -> EmployeeRef:
        return EmployeeRef(entity_id=self.assignee_id)
