from deepagents import SubAgent
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.middleware import SummaryInjectionMiddleware
from app.tools.base_tool import HUMAN_INPUT_TOOLS


ERP_EXPERT_PROMPT = (
    "你是 ERP 领域专家。你负责判断用户请求是否涉及库存、采购、供应商、"
    "销售订单等 ERP 场景，并输出建议 action_id、缺失参数、需要查询的数据和风险点。"
    "你不能直接调用 ERP 后端或真实接口；真实执行必须交由主 Agent 调用 "
    "call_business_action。信息缺失时建议主 Agent 澄清。"
)


def build_erp_domain_agent(model: BaseChatModel) -> SubAgent:
    return {
        "name": "erp_domain_agent",
        "description": "分析 ERP 领域任务，尤其是库存、采购、供应商和订单相关意图.",
        "system_prompt": ERP_EXPERT_PROMPT,
        "tools": HUMAN_INPUT_TOOLS,
        "model": model,
        "middleware": [SummaryInjectionMiddleware()],
    }
