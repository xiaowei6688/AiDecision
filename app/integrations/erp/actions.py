from app.actions.registry import ActionRegistry
from app.actions.schemas import (
    ActionConfirmation,
    ActionExecutorSpec,
    ActionInputSpec,
    ActionSpec,
)
from app.integrations.erp.models import PurchaseRequestCommand


def register_actions(registry: ActionRegistry, adapter_name: str) -> None:
    registry.register(
        ActionSpec(
            action_id="erp.create_purchase_request",
            title="创建采购申请",
            description="在 ERP 中为指定物料创建采购申请。",
            system="erp",
            intent_examples=[
                "帮我采购一批滤芯",
                "库存不足时创建采购申请",
                "给这个备件走采购",
            ],
            inputs=[
                ActionInputSpec(
                    name="material_id",
                    description="物料编码，可通过 semantic_query 从物料名称解析。",
                    resolver="semantic_query:erp",
                ),
                ActionInputSpec(
                    name="quantity",
                    type="number",
                    description="采购数量。",
                ),
                ActionInputSpec(
                    name="reason",
                    description="采购原因。",
                ),
            ],
            pre_checks=["erp.material_id_present", "erp.quantity_positive"],
            confirmation=ActionConfirmation(
                required=True,
                template="确认创建采购申请：物料 {{material_id}}，数量 {{quantity}}？",
            ),
            risk_level="medium",
            executor=ActionExecutorSpec(
                adapter=adapter_name,
                method="create_purchase_request",
            ),
            success_template="采购申请已创建，申请号：{{request_id}}",
            input_model=PurchaseRequestCommand,
        )
    )
