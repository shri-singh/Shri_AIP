"""Agent context is a typed hint; never trust client tenant or permission assertions."""
from pydantic import BaseModel,Field
from typing import Literal
class OpsiUiContext(BaseModel):
    page: Literal['dashboard','incident','services','metadata','settings','chat']
    service_id: str|None=None
    incident_id: str|None=None
    time_from: str|None=None
    time_to: str|None=None
    selected_panel_id: str|None=None
    filters: dict[str,str]=Field(default_factory=dict)

ALLOWED_ACTIONS={'open_incident','set_dashboard_filter','render_chart','draft_incident_update'}
def authorize_ui_action(action:dict,permission_check):
    kind=action.get('kind')
    if kind not in ALLOWED_ACTIONS: raise PermissionError('Unrecognized UI action')
    if not permission_check(action): raise PermissionError('Denied by Opsi authorization policy')
    return action
