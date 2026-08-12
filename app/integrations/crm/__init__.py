"""CRM Agent sample without a connected adapter or executable actions."""

from app.agents.business_agents import BusinessAgentRegistry
from app.integrations.crm.agent import register_business_agent

__all__ = ["register_business_agent"]
