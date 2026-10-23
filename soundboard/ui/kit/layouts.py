"""Layout helpers: take an item out of a layout, or read its widget, without leaving
Qt items or PySide wrappers behind."""
from __future__ import annotations

from shiboken6 import delete as qt_delete
from shiboken6 import invalidate as qt_invalidate


def take_out(layout, i: int = 0) -> None:
    """Take item `i` out of `layout` and free it; its widget stays alive.

    Qt's takeAt() hands the item to the caller, and from Python nobody ever frees it.
    A widget remembers the first item made for it, so after it's added back to a
    layout (columns re-stacked, a grid reflowed) its size changes kept going to the
    old, orphaned item: the new one kept a stale height for that width, and a card
    whose text grew was squeezed (its buttons drawn over the text) until the
    width changed."""
    item = layout.takeAt(i)
    if item is not None:
        qt_delete(item)


def widget_at(layout, i: int):
    """The widget of `layout`'s item `i` (None for a spacer, a nested layout or past
    the end). Use it, never ``layout.itemAt(i).widget()``.

    itemAt() makes a Python wrapper for the item that the layout keeps. When Qt
    deletes the item itself (its widget deleted or moved), the wrapper stays listed at
    that address, and the next Qt object made there reaches Python as that dead
    item: a new menu was handed to the style's polish() as a QWidgetItem. So the
    wrapper is dropped from the list right away; the item itself is untouched.
    (Not for our own layouts, e.g. panel.py's: they keep their items' wrappers in
    a list of their own, and that wrapper is the item.)"""
    item = layout.itemAt(i)
    if item is None:
        return None
    w = item.widget()
    if type(layout).__module__.startswith("PySide6."):
        qt_invalidate(item)
    return w
