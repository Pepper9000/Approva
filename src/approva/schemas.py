from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RequestType(str, Enum):
    SOFTWARE = "software_license"
    EXPENSE = "expense_claim"
    UNKNOWN = "unknown"


class Role(str, Enum):
    MANAGER = "manager"
    FINANCE = "finance"
    SECURITY = "security"
    LEGAL = "legal"


class DataCategory(str, Enum):
    NONE = "none"
    INTERNAL = "internal"
    SOURCE_CODE = "source_code"
    PII = "pii"
    CUSTOMER = "customer_data"
    FINANCIAL = "financial"
    HEALTH = "health"


ManipulationSignal = Literal[
    "policy_override_attempt", "executive_name_drop", "urgency_pressure",
    "skip_verification", "instruction_injection",
]

ExpenseCategory = Literal[
    "travel", "accommodation", "meals", "local_conveyance",
    "training", "office_supplies", "other",
]


class ParsedRequest(BaseModel):
    """Intake Agent output. NOTE: no totals here; code computes them."""

    request_type: RequestType
    summary: str = Field(max_length=200)
    vendor_or_payee: Optional[str] = None
    item: Optional[str] = None
    expense_category: Optional[ExpenseCategory] = None
    quantity: int = 1
    unit_cost_inr: Optional[float] = None
    billing_period: Literal["one_time", "monthly", "annual"] = "one_time"
    expense_date: Optional[date] = None
    start_date: Optional[date] = None
    receipt_attached: Optional[bool] = None
    data_categories: list[DataCategory] = Field(default_factory=lambda: [DataCategory.NONE])
    justification: Optional[str] = None
    urgency: Literal["low", "normal", "high"] = "normal"
    manipulation_signals: list[ManipulationSignal] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class Citation(BaseModel):
    clause_id: str
    quote: str


class Violation(BaseModel):
    clause_id: str
    reason: str


class PolicyVerdict(BaseModel):
    """Policy Agent output (after Citation Validator filtering)."""

    applicable_clauses: list[Citation]
    required_roles: list[Role]
    required_checks: list[str] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    reasoning: str


class RiskFactor(BaseModel):
    name: str
    points: int
    detail: str


class RiskAssessment(BaseModel):
    score: int
    tier: Literal["LOW", "MEDIUM", "HIGH"]
    factors: list[RiskFactor]
    hard_stops: list[str] = Field(default_factory=list)


class DecisionType(str, Enum):
    AUTO_APPROVE = "AUTO_APPROVE"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    ESCALATE = "ESCALATE"
    REJECT = "REJECT"
    NEEDS_INFO = "NEEDS_INFO"


class Decision(BaseModel):
    type: DecisionType
    required_roles: list[Role] = Field(default_factory=list)
    rationale: list[str]
    clarifying_question: Optional[str] = None


class RoleFocus(BaseModel):
    role: Role
    check: str


class EscalationBrief(BaseModel):
    """Brief Agent output. Advisory only; humans decide."""

    headline: str
    situation: str
    why_escalated: list[str]
    key_risks: list[str]
    recommended_action: Literal["approve", "approve_with_conditions", "reject", "investigate"]
    conditions_or_questions: list[str]
    focus_by_role: list[RoleFocus]


class RequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    NEEDS_INFO = "NEEDS_INFO"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class Approval(BaseModel):
    request_id: str
    role: Role
    approver_id: str
    verdict: Literal["approve", "reject"]
    comment: Optional[str] = None
    ts: datetime


class PlanStep(BaseModel):
    name: str
    status: Literal["pending", "running", "done", "skipped", "failed"] = "pending"


class TraceEvent(BaseModel):
    request_id: str
    seq: int = 0
    ts: datetime
    agent: Literal[
        "orchestrator", "intake", "policy", "matrix", "risk", "decision",
        "brief", "approval", "executor", "auditor", "router", "laya",
    ]
    step: str
    status: Literal["started", "ok", "warn", "failed"]
    summary: str
    detail: dict = Field(default_factory=dict)
    latency_ms: Optional[int] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    tier: Literal["claude", "laya_rules", "manual"] = "claude"
    degraded: bool = False