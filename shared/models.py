from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    ticker: str
    action: SignalAction
    confidence: float
    price_target: float
    stop_loss: float
    reasoning: str
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def is_actionable(self, threshold: float = 0.75) -> bool:
        return self.confidence >= threshold and self.action != SignalAction.HOLD


@dataclass
class TradeResult:
    signal: TradeSignal
    executed: bool
    order_id: str | None
    fill_price: float | None
    quantity: float | None
    executed_at: datetime | None
    rejection_reason: str | None = None
