"""The quick setup's mic test result, kept for the uninstaller's feedback form."""
from types import SimpleNamespace

from soundboard.mic import mictest


class FakeKey:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_winreg(store, fail=False):
    def create(root, key):
        if fail:
            raise PermissionError
        store["key"] = key
        return FakeKey(store)

    def set_value(k, name, _r, _t, value):
        store[name] = value

    return SimpleNamespace(HKEY_CURRENT_USER=1, REG_SZ=1, CreateKey=create,
                           SetValueEx=set_value)


def test_saves_pass_or_fail_and_when(monkeypatch):
    store = {}
    monkeypatch.setattr(mictest, "winreg", fake_winreg(store))
    mictest.save(True)
    assert store["key"] == r"Software\OnionBoard" and store["MicTest"] == "pass"
    assert store["MicTestAt"].endswith("Z") and len(store["MicTestAt"]) == 20
    mictest.save(False)
    assert store["MicTest"] == "fail"


def test_a_registry_error_is_quiet(monkeypatch):
    monkeypatch.setattr(mictest, "winreg", fake_winreg({}, fail=True))
    mictest.save(True)   # no exception
