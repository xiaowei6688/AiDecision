from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import MaterialRef


class PurchaseRequestCommand(BaseModel):
    """ERP command accepted by erp.create_purchase_request."""

    model_config = ConfigDict(extra="forbid")

    material_id: str = Field(min_length=1)
    quantity: float = Field(gt=0)
    reason: str = Field(min_length=1)

    @property
    def material(self) -> MaterialRef:
        return MaterialRef(entity_id=self.material_id)
