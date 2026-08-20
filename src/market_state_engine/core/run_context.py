"""RunContext: injected, immutable per-run environment.

Time is injected (never read from the clock inside pure components) so features and scoring are
byte-reproducible on replay. Carries the run identity, ordering, previous regime, and the exact
artifact versions used.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .enums import RegimeState, TriggerType
from .models import TriggerDetail


# غیرقابل تغییر بعد ساخت
class RunContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    run_sequence: int
    trigger_type: TriggerType
    trigger_detail: TriggerDetail | None = None
    # Injected wall-clock for this run; all time-relative math uses this, never datetime.now().
    now: datetime
    previous_state: RegimeState | None = None
    versions: dict[str, str]
