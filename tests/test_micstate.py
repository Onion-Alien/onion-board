"""Windows' microphone privacy switches, read from a fake registry (micstate.windows_blocks_mic)."""
import pytest

from soundboard.mic import micstate


class _Key:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("values, blocked", [
    ({}, False),                                     # no such keys: can't tell
    ({"pc": "Allow", "apps": "Allow", "desktop": "Allow"}, False),
    ({"pc": "Deny", "apps": "Allow", "desktop": "Allow"}, True),
    ({"apps": "Deny"}, True),
    ({"pc": "Allow", "apps": "Allow", "desktop": "Deny"}, True)])
def test_any_switch_off_blocks_the_mic(monkeypatch, values, blocked):
    where = {micstate._CONSENT[0]: "pc", micstate._CONSENT[1]: "apps",
             micstate._CONSENT[2]: "desktop"}

    def open_key(root, path):
        name = where[(root, path)]
        if name not in values:
            raise FileNotFoundError(path)
        return _Key(values[name])
    monkeypatch.setattr(micstate.winreg, "OpenKey", open_key)
    monkeypatch.setattr(micstate, "_value", lambda k, name: k.value)
    assert micstate.windows_blocks_mic() is blocked
