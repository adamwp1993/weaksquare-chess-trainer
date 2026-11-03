"""v0.6-B4: the backend's think time starts when the trainer has played the opponent's move. Its delays must
match the trainer view's animation delays."""

from __future__ import annotations

import re
from pathlib import Path

from weaksquare.core.modes.base import OPPONENT_DELAY_MS, REPLY_DELAY_MS

TRAINER = Path(__file__).resolve().parents[2] / "web" / "src" / "views" / "TrainerView.tsx"


def test_delays_match_the_trainer_view() -> None:
    text = TRAINER.read_text(encoding="utf-8")
    found = dict(re.findall(r"const (OPPONENT_DELAY_MS|REPLY_DELAY_MS) = (\d+);", text))
    assert found == {"OPPONENT_DELAY_MS": str(OPPONENT_DELAY_MS), "REPLY_DELAY_MS": str(REPLY_DELAY_MS)}
