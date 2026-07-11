"""
alka.tooltip — a small hover-tooltip helper.

Tkinter has no built-in tooltip, so this is the standard minimal pattern:
bind <Enter>/<Leave> on a widget to show/hide a borderless Toplevel with a
label. Used for supplementary explanation only — never to hide essential
information, since tooltips don't work for touch or screen readers and some
users never hover. Keep the critical facts visible in the panel itself.
"""
from __future__ import annotations

import tkinter as tk


class Tooltip:
    def __init__(self, widget, text: str, wraplength: int = 360, delay_ms: int = 350):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.delay_ms = delay_ms
        self._tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _show(self):
        if self._tip is not None:
            return
        # position just below-right of the widget
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)   # no window chrome
        self._tip.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(
            self._tip, text=self.text, justify="left",
            background="#fffbe6", foreground="#333",
            relief="solid", borderwidth=1, wraplength=self.wraplength,
            font=("", 8), padx=8, pady=6,
        )
        lbl.pack()

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _cancel(self):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None


def attach(widget, text: str, **kw) -> Tooltip:
    """Convenience: attach a tooltip to a widget."""
    return Tooltip(widget, text, **kw)