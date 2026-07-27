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
    # https URLs only: the shim's _sanitize_remote_url mirrors the real host-side
    # broker, which refuses non-https / transport-helper URLs (see test_broker.py).
    broker = ShimBroker(tmp_path / "c", tmp_path / "w", tmp_path / "o")
    assert broker.remote_default_branch("https://example.com/x.git") == "main"
    broker.remote_default_branches["https://h/special.git"] = "trunk"
    assert broker.remote_default_branch("https://h/special.git") == "trunk"
    broker.default_remote_branch = None
    assert broker.remote_default_branch("https://example.com/y.git") is None


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
    result = repo_ui._prompt_dev_from_remote(store, "https://example.com/x.git")
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
    result = repo_ui._prompt_dev_from_remote(store, "https://example.com/x.git")
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
    assert repo_ui._prompt_dev_from_remote(store, "https://example.com/x.git") == "main"


def test_prompt_dev_broker_failure_degrades_to_prompt(tmp_path, monkeypatch):
    """A broker/transport failure degrades to the plain prompt rather than crashing."""

    class _Boom(FakeBroker):
        def call(self, method, params=None):
            if method == "remote_default_branch":
                raise RuntimeError("broker unreachable")
            return super().call(method, params)

    store = RepoStore(_Boom())
    monkeypatch.setattr(repo_ui.questionary, "text", lambda *a, **k: _Ans("fallback"))
    assert repo_ui._prompt_dev_from_remote(store, "https://example.com/x.git") == "fallback"


# --------------------------------------------------------------------------- #
# Guided add: the three provenance states decide which fields are meaningful
# --------------------------------------------------------------------------- #
def _stub(monkeypatch, *, choice, texts, confirm=True):
    """Stub questionary: one `select` answer, `text` routed by prompt substring."""

    def _text(msg, default="", **kw):
        for fragment, value in texts.items():
            if fragment in msg:
                return _Ans(value)
        return _Ans(default)  # unanswered prompt = the user pressing Enter

    monkeypatch.setattr(repo_ui.questionary, "select", lambda *a, **k: _Ans(choice))
    monkeypatch.setattr(repo_ui.questionary, "text", _text)
    monkeypatch.setattr(repo_ui.questionary, "confirm", lambda *a, **k: _Ans(confirm))


def test_add_existing_theirs_records_upstream_and_their_dev(tmp_path, monkeypatch):
    """Consuming someone else's repo: `dev` names their line, `dev-upstream` is redundant."""
    store = _store(tmp_path, default_branch="main")
    _stub(monkeypatch, choice=repo_ui._THEIRS, texts={"upstream URL": "https://ex/up.git"})

    repo_ui._add_existing(store, "Up", "up")

    repo = store.load("up")
    assert repo.sources == {"upstream": "https://ex/up.git"}
    assert repo.branches == {"dev": "main"}


def test_add_existing_ours_records_origin(tmp_path, monkeypatch):
    store = _store(tmp_path, default_branch="main")
    _stub(monkeypatch, choice=repo_ui._OURS, texts={"origin URL": "https://ex/mine.git"})

    repo_ui._add_existing(store, "Mine", "mine")

    repo = store.load("mine")
    assert repo.sources == {"origin": "https://ex/mine.git"}
    assert repo.branches == {"dev": "main"}
    assert "dev-upstream" not in repo.branches  # no upstream to have a second line


def test_add_existing_forked_points_dev_at_the_fork(tmp_path, monkeypatch):
    """The bug: `dev` must name the fork's line, with the base's kept as `dev-upstream`."""
    store = _store(tmp_path, default_branch="main")  # the upstream's line
    store.broker.remote_default_branches["https://ex/fork.git"] = "fie-main"
    _stub(
        monkeypatch,
        choice=repo_ui._OURS_FORKED,
        texts={"upstream URL": "https://ex/up.git", "fork (ours) URL": "https://ex/fork.git"},
    )

    repo_ui._add_existing(store, "Forked", "forked")

    repo = store.load("forked")
    assert repo.sources == {
        "upstream": "https://ex/up.git",
        "fork-ours": "https://ex/fork.git",
    }
    assert repo.branches == {"dev": "fie-main", "dev-upstream": "main"}


def test_add_existing_forked_same_line_records_no_dev_upstream(tmp_path, monkeypatch):
    """`dev-upstream` appears only when the fork's line actually differs from the base's."""
    store = _store(tmp_path, default_branch="main")  # fork's default matches too
    _stub(
        monkeypatch,
        choice=repo_ui._OURS_FORKED,
        texts={
            "upstream URL": "https://ex/up.git",
            "fork (ours) URL": "https://ex/fork.git",
            "our dev branch on the fork": "main",  # accept the seeded value
        },
    )

    repo_ui._add_existing(store, "Same", "same")

    repo = store.load("same")
    assert repo.sources["fork-ours"] == "https://ex/fork.git"  # fork still recorded
    assert repo.branches == {"dev": "main"}
    assert "dev-upstream" not in repo.branches


def test_fork_dev_is_asked_even_when_the_defaults_match(tmp_path, monkeypatch):
    """A fork whose HEAD still matches the base is usually just *unconfigured*.

    The fork's default branch is a proxy for our dev line, not the line itself. The
    short-circuit used to skip the question exactly when the proxy agreed with the
    base — i.e. where it is least likely to reflect intent — so a fork you had
    branched away from silently kept the base's line.
    """
    store = _store(tmp_path, default_branch="main")  # both remotes default to main
    _stub(
        monkeypatch,
        choice=repo_ui._OURS_FORKED,
        texts={
            "upstream URL": "https://ex/up.git",
            "fork (ours) URL": "https://ex/fork.git",
            "our dev branch on the fork": "my-line",  # ...but we work elsewhere
        },
    )

    repo_ui._add_existing(store, "Branched", "branched")

    repo = store.load("branched")
    assert repo.branches == {"dev": "my-line", "dev-upstream": "main"}


def test_fork_dev_prompt_is_seeded_with_the_forks_default(tmp_path, monkeypatch):
    """The probe seeds the prompt rather than answering it."""
    store = _store(tmp_path, default_branch="main")
    store.broker.remote_default_branches["https://ex/fork.git"] = "fie-main"
    seen = {}
    _stub(
        monkeypatch,
        choice=repo_ui._OURS_FORKED,
        texts={"upstream URL": "https://ex/up.git", "fork (ours) URL": "https://ex/fork.git"},
    )
    plain_text = repo_ui.questionary.text

    def _spy(msg, default="", **kw):
        if "our dev branch on the fork" in msg:
            seen["msg"], seen["default"] = msg, default
        return plain_text(msg, default=default, **kw)

    monkeypatch.setattr(repo_ui.questionary, "text", _spy)

    repo_ui._add_existing(store, "Seed", "seed")

    assert seen["default"] == "fie-main"  # pre-filled, one keypress to accept
    assert "fie-main" in seen["msg"]  # and surfaced in the question itself
    assert store.load("seed").branches == {"dev": "fie-main", "dev-upstream": "main"}
