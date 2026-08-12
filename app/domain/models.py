from pydantic import BaseModel, ConfigDict, Field


class SystemEntityRef(BaseModel):
    """Stable reference to an entity owned by one business system."""

    model_config = ConfigDict(extra="forbid")

    system: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    display_name: str | None = None


class EmployeeRef(SystemEntityRef):
    system: str = "hr"


class DeviceRef(SystemEntityRef):
    system: str = "inspection"


class MaterialRef(SystemEntityRef):
    system: str = "erp"
