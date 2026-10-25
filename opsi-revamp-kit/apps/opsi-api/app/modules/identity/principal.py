"""The authenticated caller, derived ONLY from a verified token or the existing Opsi session.

Never build a Principal from request bodies, query strings, AG-UI ``state``,
``forwardedProps`` or CopilotKit context: those are client-controlled hints.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({"chat:use", "catalog:read", "ontology:read", "search:use"}),
    "investigator": frozenset({"chat:use", "chat:share", "catalog:read", "ontology:read", "search:use",
                               "action:request", "attachment:upload", "feedback:write"}),
    "approver": frozenset({"chat:use", "catalog:read", "ontology:read", "search:use", "action:request",
                           "action:approve", "attachment:upload", "feedback:write"}),
    "ontology_editor": frozenset({"ontology:write"}),
    "admin": frozenset({"chat:use", "chat:share", "catalog:read", "ontology:read", "ontology:write", "search:use",
                        "action:request", "action:approve", "attachment:upload", "feedback:write", "admin:read"}),
}


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    display_name: str | None = None
    service_scope: frozenset[str] | None = None  # None = all services in tenant
    groups: frozenset[str] = field(default_factory=frozenset)
    auth_source: str = "oidc"

    @property
    def permissions(self) -> frozenset[str]:
        perms: set[str] = set()
        for role in self.roles:
            perms |= ROLE_PERMISSIONS.get(role, frozenset())
        return frozenset(perms)

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def can_access_service(self, service_id: str | None) -> bool:
        if service_id is None or self.service_scope is None:
            return True
        return service_id in self.service_scope

    def __post_init__(self) -> None:
        if not self.user_id or not self.tenant_id:
            raise ValueError("principal requires user_id and tenant_id")
        if len(self.tenant_id) > 128 or len(self.user_id) > 256:
            raise ValueError("identity claims too long")
