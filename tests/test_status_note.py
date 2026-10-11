"""The sidebar's hover help. (The floating status note it once tested is gone:
notices are toasts now, tests/test_toast.py.)"""
from test_mainwindow import window  # noqa: F401


def test_sidebar_controls_have_hover_help_only_where_the_words_are_hidden(window):  # noqa: F811
    rail = window.rail
    for opened in (False, True, False):
        rail.set_open(opened)
        for button in (*rail.extras, rail.toggle):
            assert button.accessibleName()
        assert not any(b.toolTip() for b in rail.extras)
        # the arrow's tip names a warning that's waiting out of sight, shut; else none
        assert bool(rail.toggle.toolTip()) == bool(rail.toggle.property("dot"))
        assert not (rail.is_open() and rail.toggle.toolTip())
        for button in rail.buttons:   # a tab: its name on hover while shut, nothing open
            assert bool(button.toolTip()) == (not rail.is_open() and not button.isHidden())
            assert button.accessibleName()
    assert window.gear.accessibleDescription()
