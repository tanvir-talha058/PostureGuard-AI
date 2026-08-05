"""ViewModel cue/action override fields.

No QApplication fixture needed: this only touches the dataclass and Fault, never a
Qt widget or paint method.
"""

from __future__ import annotations

from postureguard.overlay import ViewModel


class TestViewModelCueOverride:
    def test_defaults_to_empty_override(self):
        model = ViewModel()
        assert model.cue_text == ""
        assert model.action_text == ""

    def test_carries_an_explicit_override(self):
        model = ViewModel(cue_text="Custom cue.", action_text="Custom action")
        assert model.cue_text == "Custom cue."
        assert model.action_text == "Custom action"
