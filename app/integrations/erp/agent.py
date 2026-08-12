from app.agents.business_agents import BusinessAgentManifest, BusinessAgentRegistry

ERP_BUSINESS_AGENT_PROMPT = (
    "你是 ERP 业务 Agent。分析库存、采购、供应商和订单场景，输出建议 action_id、"
    "缺失参数、建议查询、跨系统依赖和风险。你不能调用 ERP 后端或执行真实动作。"
)


def register_business_agent(registry: BusinessAgentRegistry) -> None:
    registry.register(BusinessAgentManifest(
        business_id="erp",
        title="ERP 业务 Agent",
        description="分析库存、采购、供应商和订单，并为跨系统流程提供 ERP 侧约束。",
        system_prompt=ERP_BUSINESS_AGENT_PROMPT,
        datasources=("erp",),
        action_prefixes=("erp.",),
        cross_system_notes="涉及采购时，可能需要 HR 的审批人或巡检系统的设备需求。",
    ))
