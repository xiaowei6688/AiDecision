from app.agents.business_agents import BusinessAgentManifest, BusinessAgentRegistry


def register_business_agent(registry: BusinessAgentRegistry) -> None:
    """Register analysis capabilities only until a real CRM connector is supplied."""

    registry.register(BusinessAgentManifest(
        business_id="crm",
        title="CRM 业务 Agent",
        description="示例：分析客户、商机和服务请求；未接入真实 CRM 数据源或可执行动作。",
        system_prompt=(
            "你是 CRM 业务 Agent。仅根据主 Agent 提供的上下文分析客户、商机和服务问题。"
            "当前 CRM 连接器尚未接入，不得虚构 CRM 查询结果或建议可立即执行的 CRM 动作。"
        ),
        datasources=(),
        action_prefixes=(),
        cross_system_notes="CRM 接入完成后，可为 ERP 订单、合同履约和客户服务提供客户上下文。",
    ))
