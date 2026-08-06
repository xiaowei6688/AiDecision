from dataclasses import dataclass

from app.agents.roles.domains.erp import ERP_EXPERT_PROMPT
from app.agents.roles.domains.hr import HR_EXPERT_PROMPT
from app.agents.roles.domains.inspection import INSPECTION_EXPERT_PROMPT


@dataclass(frozen=True)
class DomainExpert:
    domain: str
    title: str
    prompt: str


DOMAIN_EXPERTS: dict[str, DomainExpert] = {
    "inspection": DomainExpert(
        domain="inspection",
        title="巡检领域专家",
        prompt=INSPECTION_EXPERT_PROMPT,
    ),
    "erp": DomainExpert(
        domain="erp",
        title="ERP 领域专家",
        prompt=ERP_EXPERT_PROMPT,
    ),
    "hr": DomainExpert(
        domain="hr",
        title="HR 领域专家",
        prompt=HR_EXPERT_PROMPT,
    ),
}


def get_domain_expert(domain: str) -> DomainExpert | None:
    return DOMAIN_EXPERTS.get(domain.strip().lower())


def list_domain_experts() -> list[dict[str, str]]:
    return [
        {"domain": expert.domain, "title": expert.title}
        for expert in DOMAIN_EXPERTS.values()
    ]
