"""Guided repo-add probes a remote's default branch via the broker verb.

The probe is a git effect (``git ls-remote --symref``) that now runs broker-side
behind ``remote_default_branch``; the container authors the URL and asks the
broker to resolve its symbolic HEAD. These tests drive the interactive helper
directly with questionary stubbed and a canned/hermetic broker.
"""

from broker_shim import ShimBroker
from mono_control.broker import FakeBroker
from mono_control.cli import repo_ui
from mono_control.config import RepoStore


class _Ans:
    """Stand-in for a questionary question object: ``.ask()`` returns ``val``."""

    def __init__(self, val):
        self.val = val

    def ask(self):
        return self.val


def _store(tmp_path, *, default_branch="main"):
    broker = ShimBroker(tmp_path / "config", tmp_path / "ws", tmp_path / "off")
    broker.default_remote_branch = default_branch
    return RepoStore(broker)


def test_client_remote_default_branch_returns_branch_field(tmp_path):
    broker = ShimBroker(tmp_path / "c", tmp_path / "w", tmp_path / "o")
    assert broker.remote_default_branch("git@example.com:x.git") == "main"
    broker.remote_default_branches["git@h:special.git"] = "trunk"
    assert broker.remote_default_branch("git@h:special.git") == "trunk"
    broker.default_remote_branch = None
    assert broker.remote_default_branch("git@example.com:y.git") is None


def test_fake_serves_remote_default_branch_from_canned_results():
    fake = FakeBroker(results={"remote_default_branch": {"branch": "develop"}})
    assert fake.remote_default_branch("any://url") == "develop"


def test_prompt_dev_probes_and_offers_default(tmp_path, monkeypatch):
    """Got a branch + user confirms → that branch is used for `dev`."""
    store = _store(tmp_path, default_branch="trunk")
    confirmed = {}

    def _confirm(msg, **kw):
        confirmed["msg"] = msg
        return _Ans(True)

    monkeypatch.setattr(repo_ui.questionary, "confirm", _confirm)
    result = repo_ui._prompt_dev_from_remote(store, "git@example.com:x.git")
    assert result == "trunk"
    assert "trunk" in confirmed["msg"]  # the suggestion was surfaced


def test_prompt_dev_declined_falls_back_to_prompt(tmp_path, monkeypatch):
    """Got a branch but the user declines → fall through to the text prompt."""
    store = _store(tmp_path, default_branch="trunk")
    seen_default = {}

    def _text(msg, default="", **kw):
        seen_default["default"] = default
        return _Ans("hand-typed")

    monkeypatch.setattr(repo_ui.questionary, "confirm", lambda *a, **k: _Ans(False))
    monkeypatch.setattr(repo_ui.questionary, "text", _text)
    result = repo_ui._prompt_dev_from_remote(store, "git@example.com:x.git")
    assert result == "hand-typed"
    # the probed branch pre-fills the manual prompt (matches pre-refactor UX)
    assert seen_default["default"] == "trunk"


def test_prompt_dev_none_falls_back_to_plain_prompt(tmp_path, monkeypatch):
    """No default branch (None) → straight to the text prompt with no suggestion."""
    store = _store(tmp_path, default_branch=None)

    def _confirm(*a, **k):  # must NOT be reached when there is no default
        raise AssertionError("confirm should not be called when default is None")

    monkeypatch.setattr(repo_ui.questionary, "confirm", _confirm)
    monkeypatch.setattr(repo_ui.questionary, "text", lambda *a, **k: _Ans("main"))
    assert repo_ui._prompt_dev_from_remote(store, "git@example.com:x.git") == "main"


def test_prompt_dev_broker_failure_degrades_to_prompt(tmp_path, monkeypatch):
    """A broker/transport failure degrades to the plain prompt rather than crashing."""

    class _Boom(FakeBroker):
        def call(self, method, params=None):
            if method == "remote_default_branch":
                raise RuntimeError("broker unreachable")
            return super().call(method, params)

    store = RepoStore(_Boom())
    monkeypatch.setattr(repo_ui.questionary, "text", lambda *a, **k: _Ans("fallback"))
    assert repo_ui._prompt_dev_from_remote(store, "git@example.com:x.git") == "fallback"
