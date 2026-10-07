"""A second launch while the first is still starting up brings the first to the
front instead of saying "already open, look in the tray"."""
import os
import uuid

import pytest

from conftest import own_time
from soundboard import singleinstance as si


@pytest.fixture
def instance(monkeypatch):
    """A private instance name, so the real, running app is never found."""
    monkeypatch.setattr(si, "INSTANCE_NAME", f"onionboard-test-{os.getpid()}-{uuid.uuid4().hex}")
    boxes = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: boxes.append(a)))
    return boxes


def test_second_launch_waits_for_a_first_one_still_starting(qapp, instance, monkeypatch):
    assert si.claim_single_instance()   # the first copy: holds the lock, not listening yet
    servers = []

    def sleep(_s):   # the first copy gets as far as listening while the second waits
        if not servers:
            servers.append(si.listen_for_second_launch(qapp, lambda: None))
    own_time(monkeypatch, si, sleep=sleep)
    assert not si.claim_single_instance()   # the second copy
    assert instance == []                   # no "already open" message
    from conftest import process_events
    process_events(qapp, lambda: servers[0].show_requested, 3)
    assert servers[0].show_requested        # the first one will show its window
    servers[0].close()


def test_second_launch_gives_up_and_says_so(qapp, instance, monkeypatch):
    assert si.claim_single_instance()
    monkeypatch.setattr(si, "CONNECT_SECONDS", 0.3)
    assert not si.claim_single_instance()
    assert len(instance) == 1
