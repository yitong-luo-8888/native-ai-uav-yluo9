"""exclusive_pane_group.py — "only one of these panes open at a time".

Several checkable ribbon buttons each toggle a left-hand pane open/closed,
and clicking one must close every other pane in the group (and uncheck its
button) first. ExclusivePaneGroup replaces N hand-written, near-identical
toggle handlers with one generic implementation registered once per pane.
"""

from __future__ import annotations

from typing import Callable, List, NamedTuple, Optional

from PyQt5.QtWidgets import QToolButton, QWidget


class _Member(NamedTuple):
    button: QToolButton
    pane: QWidget
    on_shown: Optional[Callable[[], None]]
    on_hidden: Optional[Callable[[], None]]


class ExclusivePaneGroup:
    """register() wires button.clicked itself -- callers just construct the
    group and register each (button, pane) pair once, no per-pane toggle
    handler needed. on_shown/on_hidden cover the one member (ScenePane)
    with a side effect beyond show/hide+reposition, e.g. toggling the
    map's scene-drag mode."""

    def __init__(self) -> None:
        self._members: List[_Member] = []

    def register(
        self,
        button: QToolButton,
        pane: QWidget,
        on_shown: Optional[Callable[[], None]] = None,
        on_hidden: Optional[Callable[[], None]] = None,
    ) -> None:
        member = _Member(button, pane, on_shown, on_hidden)
        self._members.append(member)
        button.clicked.connect(lambda checked, m=member: self._on_toggle(m, checked))

    def _on_toggle(self, member: _Member, checked: bool) -> None:
        if checked:
            self._close_all_except(member)
            member.pane.show()
            member.pane.reposition()
            if member.on_shown is not None:
                member.on_shown()
        else:
            member.pane.hide()
            if member.on_hidden is not None:
                member.on_hidden()

    def _close_all_except(self, keep: _Member) -> None:
        for m in self._members:
            if m is keep:
                continue
            m.pane.hide()
            if m.on_hidden is not None:
                m.on_hidden()
            m.button.blockSignals(True)
            m.button.setChecked(False)
            m.button.blockSignals(False)
