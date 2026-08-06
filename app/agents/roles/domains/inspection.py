from deepagents import SubAgent
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.middleware import SummaryInjectionMiddleware
from app.tools.base_tool import HUMAN_INPUT_TOOLS


INSPECTION_EXPERT_PROMPT = (
    "你是巡检领域专家。你负责判断用户请求是否涉及设备状态、巡检任务、"
    "异常记录、维保安排等场景，并输出建议 action_id、缺失参数、需要查询的数据和风险点。"
    "你不能直接调用巡检后端或真实接口；真实执行必须交由主 Agent 调用 "
    "call_business_action。信息缺失时建议主 Agent 澄清。"
)


def build_inspection_domain_agent(model: BaseChatModel) -> SubAgent:
    return {
        "name": "inspection_domain_agent",
        "description": "分析设备、巡检任务、异常记录等巡检领域任务.",
        "system_prompt": INSPECTION_EXPERT_PROMPT,
        "tools": HUMAN_INPUT_TOOLS,
        "model": model,
        "middleware": [SummaryInjectionMiddleware()],
    }
