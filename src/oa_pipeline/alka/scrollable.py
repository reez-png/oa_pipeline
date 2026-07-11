"""
alka.scrollable — a scrollable container frame.

Tkinter frames don't scroll on their own. This wraps a Canvas + Scrollbar so an
arbitrarily tall stack of widgets (e.g. the results panel with the per-pair
detail expanded) stays reachable in a fixed-size window. Put your content in
`.body` and grid/pack as usual.

Also binds the mouse wheel while the pointer is over the area, so scrolling feels
native on Windows/macOS/Linux.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self._canvas = tk.Canvas(self, highlightthickness=0)
        self._vbar = ttk.Scrollbar(self, orient="vertical",
                                   command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vbar.set)

        self._vbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        # the frame that actually holds content
        self.body = ttk.Frame(self._canvas)
        self._win = self._canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._on_body_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # mouse-wheel scrolling only while pointer is over this widget
        self._canvas.bind("<Enter>", self._bind_wheel)
        self._canvas.bind("<Leave>", self._unbind_wheel)

    def _on_body_configure(self, _event):
        # update scroll region to encompass the body
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # make the body match the canvas width (so content fills horizontally)
        self._canvas.itemconfigure(self._win, width=event.width)

    def _bind_wheel(self, _event):
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)         # Win/mac
        self._canvas.bind_all("<Button-4>", self._on_wheel_linux)     # Linux up
        self._canvas.bind_all("<Button-5>", self._on_wheel_linux)     # Linux down

    def _unbind_wheel(self, _event):
        self._canvas.unbind_all("<MouseWheel>")
        self._canvas.unbind_all("<Button-4>")
        self._canvas.unbind_all("<Button-5>")

    def _on_wheel(self, event):
        # Windows delta is multiples of 120; macOS is small integers
        delta = int(-1 * (event.delta / 120)) if abs(event.delta) >= 120 else -event.delta
        self._canvas.yview_scroll(delta, "units")

    def _on_wheel_linux(self, event):
        self._canvas.yview_scroll(-1 if event.num == 4 else 1, "units")