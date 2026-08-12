from app.agents.business_agents import BusinessAgentManifest, BusinessAgentRegistry

HR_BUSINESS_AGENT_PROMPT = (
    "你是 HR 业务 Agent。分析员工、组织、排班和请假场景，输出建议 action_id、"
    "缺失参数、建议查询、跨系统依赖和风险。你不能调用 HR 后端或执行真实动作。"
)


def register_business_agent(registry: BusinessAgentRegistry) -> None:
    registry.register(BusinessAgentManifest(
        business_id="hr",
        title="HR 业务 Agent",
        description="分析员工、组织、请假和人员排班相关问题。",
        system_prompt=HR_BUSINESS_AGENT_PROMPT,
        datasources=("hr",),
        action_prefixes=("hr.",),
        cross_system_notes="涉及现场任务时，确认人员可用性后再交由巡检系统执行。",
    ))
