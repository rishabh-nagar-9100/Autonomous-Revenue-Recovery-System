from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class RiskType(str, Enum):
    PAYMENT_FAILED = "payment_failed"
    CART_ABANDONMENT = "cart_abandonment"
    RECENT_OVERDUE = "recent_overdue"
    RECEIVABLE_OVERDUE = "receivable_overdue"


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EventStatus(str, Enum):
    DETECTED = "DETECTED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_RECONCILIATION = "PENDING_RECONCILIATION"
    INFO_REQUESTED = "INFO_REQUESTED"
    WAITING_FOR_CUSTOMER_INFO = "WAITING_FOR_CUSTOMER_INFO"
    RECOVERED = "RECOVERED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class RootCauseEnum(str, Enum):
    BANK_TIMEOUT = "bank_timeout"
    NSF = "nsf"
    EXPIRED_CARD = "expired_card"
    CART_ABANDONMENT = "cart_abandonment"
    RECENT_OVERDUE = "recent_overdue"
    CHRONIC_NON_PAYER = "chronic_non_payer"
    RECEIVABLE_OVERDUE = "receivable_overdue"
    PROMISE_TO_PAY_MISSED = "promise_to_pay_missed"
    UNKNOWN = "unknown"


class ActionType(str, Enum):
    SMART_RETRY = "smart_retry"
    PAYMENT_LINK = "payment_link"
    DELAYED_RETRY = "delayed_retry"
    REMINDER = "reminder"
    DISCOUNT_NUDGE = "discount_nudge"
    ESCALATE = "escalate"
    ESCALATE_TO_CRM = "escalate_to_crm"
    ESCALATE_TO_COLLECTIONS = "escalate_to_collections"


class GuardrailResultEnum(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"


class ExecutionStatusEnum(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING_RECONCILIATION = "PENDING_RECONCILIATION"


class WebhookProcessingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class ExecutionModeEnum(str, Enum):
    MOCK = "mock"
    SANDBOX = "sandbox"


class OutcomeResultEnum(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class EscalationStatusEnum(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    PENDING = "PENDING"


class ReceivableStatusEnum(str, Enum):
    OPEN = "open"
    PARTIALLY_PAID = "partially_paid"
    PROMISED = "promised"
    RECOVERED = "recovered"
    WRITTEN_OFF = "written_off"
    ESCALATED = "escalated"


class Receivable(BaseModel):
    receivable_id: str
    customer_id: str
    invoice_id: str
    amount_due: float
    due_date: datetime
    days_overdue: int = 0
    status: ReceivableStatusEnum = ReceivableStatusEnum.OPEN
    customer_tier: str = "STANDARD"
    last_contacted_at: Optional[datetime] = None
    promise_to_pay_date: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NormalizedEvent(BaseModel):
    event_id: str
    event_type: str
    amount: float  # In INR (rupees)
    currency: str = "INR"
    customer_id: str
    error_code: Optional[str] = None
    error_description: Optional[str] = None
    error_source: Optional[str] = None
    error_reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RiskEvent(BaseModel):
    risk_id: str
    event_id: str
    risk_type: RiskType
    amount: float
    priority: Priority
    status: EventStatus
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RootCause(BaseModel):
    risk_id: str
    root_cause: RootCauseEnum
    confidence: float
    source: str = "rule"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Intervention(BaseModel):
    risk_id: str
    action_index: int
    action_type: ActionType
    draft_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GuardrailCheck(BaseModel):
    risk_id: str
    action_index: int
    result: GuardrailResultEnum
    reason: Optional[str] = None
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class Execution(BaseModel):
    risk_id: str
    action_index: int
    action_type: ActionType
    execution_id: str
    status: ExecutionStatusEnum
    executed_at: datetime = Field(default_factory=datetime.utcnow)


class ExecutionResult(BaseModel):
    execution_id: str
    action_type: ActionType
    status: ExecutionStatusEnum
    details: Dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime = Field(default_factory=datetime.utcnow)


class Outcome(BaseModel):
    risk_id: str
    action_index: int
    result: OutcomeResultEnum
    amount_recovered: float
    resolved_at: datetime = Field(default_factory=datetime.utcnow)


class Escalation(BaseModel):
    risk_id: str
    reason: str
    escalated_at: datetime = Field(default_factory=datetime.utcnow)
    status: EscalationStatusEnum = EscalationStatusEnum.OPEN


class AuditLogEntry(BaseModel):
    id: Optional[int] = None
    risk_id: str
    layer: str
    input_json: str
    output_json: str
    decision: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class InfoRequestStatusEnum(str, Enum):
    REQUESTED = "REQUESTED"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    ELIGIBILITY_FAILED = "ELIGIBILITY_FAILED"


class InfoRequest(BaseModel):
    risk_id: str
    question: str
    response: Optional[str] = None
    extracted_root_cause: Optional[str] = None
    status: InfoRequestStatusEnum = InfoRequestStatusEnum.REQUESTED
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    responded_at: Optional[datetime] = None
    eligibility_check_result: Optional[str] = None


class VoiceIntent(str, Enum):
    SEND_PAYMENT_LINK = "SEND_PAYMENT_LINK"
    CONFIRM_PAYMENT = "CONFIRM_PAYMENT"
    ASK_STATUS = "ASK_STATUS"
    SPEAK_TO_HUMAN = "SPEAK_TO_HUMAN"
    DECLINE = "DECLINE"


class VoiceInteraction(BaseModel):
    interaction_id: str
    risk_id: str
    call_sid: Optional[str] = None
    eligibility_status: str
    transcript: Optional[str] = None
    intent: Optional[VoiceIntent] = None
    action_requested: Optional[ActionType] = None
    guardrail_result: Optional[str] = None
    execution_result: Optional[str] = None
    escalation_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
