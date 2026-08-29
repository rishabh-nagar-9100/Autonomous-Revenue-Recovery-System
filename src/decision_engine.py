from typing import Optional, Union, Dict, List
import sqlite3
from src.models import RootCauseEnum, ActionType, Intervention
from src.db import insert_intervention
from src.audit import log_audit


# Fixed deterministic playbook table strictly defined in ARCHITECTURE.md
PLAYBOOK: Dict[str, List[str]] = {
    "bank_timeout": ["smart_retry", "payment_link"],
    "nsf": ["delayed_retry", "payment_link"],
    "expired_card": ["payment_link", "reminder"],
    "cart_abandonment": ["discount_nudge", "reminder"],
    "recent_overdue": ["reminder", "payment_link"],
    "chronic_non_payer": [],  # empty list = escalate immediately
    "receivable_overdue": ["reminder", "payment_link", "escalate_to_crm"],
    "promise_to_pay_missed": ["reminder", "payment_link", "escalate_to_collections"],
}


def next_action(root_cause: Union[RootCauseEnum, str], index: int) -> Optional[ActionType]:
    """
    Deterministic playbook lookup function.
    Returns the ActionType for the given root_cause at the specified action index.
    Returns None if:
      - The root_cause is not in PLAYBOOK (e.g., unknown or invalid)
      - The index is out of bounds (e.g., negative or >= length of actions list)
      - The playbook list is empty (e.g., chronic_non_payer)
    """
    if index < 0:
        return None

    key = root_cause.value if isinstance(root_cause, RootCauseEnum) else str(root_cause)
    actions = PLAYBOOK.get(key)

    if actions is None:
        return None

    if index >= len(actions):
        return None

    return ActionType(actions[index])


def record_intervention(
    conn: sqlite3.Connection,
    risk_id: str,
    action_index: int,
    action_type: ActionType,
    draft_message: Optional[str] = None,
) -> Intervention:
    """
    Creates and persists an Intervention record in the database, and logs an audit entry.
    """
    intervention = Intervention(
        risk_id=risk_id,
        action_index=action_index,
        action_type=action_type,
        draft_message=draft_message,
    )
    insert_intervention(conn, intervention)

    log_audit(
        conn=conn,
        risk_id=risk_id,
        layer="decision_engine",
        input_data={"action_index": action_index, "action_type": action_type.value},
        output_data=intervention,
        decision="action_selected",
    )

    return intervention
