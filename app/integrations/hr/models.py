from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import EmployeeRef


class LeaveRequestCommand(BaseModel):
    """HR command accepted by hr.create_leave_request."""

    model_config = ConfigDict(extra="forbid")

    employee_id: str = Field(min_length=1)
    start_time: datetime
    end_time: datetime
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def end_time_must_follow_start_time(self) -> "LeaveRequestCommand":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self

    @property
    def employee(self) -> EmployeeRef:
        return EmployeeRef(entity_id=self.employee_id)
