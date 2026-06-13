"""Multi-character Stage session.

Stage owns roster, shared transcript, turn arbitration, and one-lock-per-round
execution. It does not write any character memory layer.
"""

from core.stage.models import Stage, StageSettings, TranscriptEntry
from core.stage.runtime import run_reality_stage_turn

__all__ = ["Stage", "StageSettings", "TranscriptEntry", "run_reality_stage_turn"]
