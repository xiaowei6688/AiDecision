from app.agents.roles.domains.erp import build_erp_domain_agent
from app.agents.roles.domains.hr import build_hr_domain_agent
from app.agents.roles.domains.inspection import build_inspection_domain_agent

__all__ = [
    "build_erp_domain_agent",
    "build_hr_domain_agent",
    "build_inspection_domain_agent",
]
