from app.agents.business_agents import BusinessAgentManifest, BusinessAgentRegistry

INSPECTION_BUSINESS_AGENT_PROMPT = (
    "你是巡检业务 Agent。分析设备状态、巡检计划和现场任务，输出建议 action_id、"
    "缺失参数、建议查询、跨系统依赖和风险。你不能调用巡检后端或执行真实动作。"
)


def register_business_agent(registry: BusinessAgentRegistry) -> None:
    registry.register(BusinessAgentManifest(
        business_id="inspection",
        title="巡检业务 Agent",
        description="分析设备、巡检计划和现场任务，并识别物料或人员依赖。",
        system_prompt=INSPECTION_BUSINESS_AGENT_PROMPT,
        datasources=("inspection",),
        action_prefixes=("inspection.",),
        cross_system_notes="设备异常可能触发 ERP 采购；任务分派前需要 HR 确认人员可用性。",
    ))
