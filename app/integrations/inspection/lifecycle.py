"""Inspection registration for the generic refresh lifecycle."""

from __future__ import annotations

from app.integrations.inspection.allcore_auth import (
    InspectionAllCoreAuthClient,
    get_inspection_allcore_auth_client,
)
from app.services.refresh_lifecycle import RefreshLifecycle


class InspectionLifecycle(RefreshLifecycle):
    def __init__(
        self,
        auth_client: InspectionAllCoreAuthClient | None = None,
    ) -> None:
        super().__init__(auth_client or get_inspection_allcore_auth_client())
