"""``repo_ops.apply_target`` orchestration order (source → re-scan → layout).

``apply_target`` is the container's core broker client: it runs the source half
(acquire), re-scans the broker-observed on-disk inventory, then runs the layout
half — so layout consumes the POST-acquire state, not a stale pre-acquire one.
This drives a real ``apply_target`` against a call-recording real-effect shim and
asserts that verb ordering directly (no other test pins it).
"""

from pathlib import Path

from broker_shim import ShimBroker, run_git
from mono_control.config import Repo, RepoStore
from mono_control.layout_target import LayoutTarget, LayoutTargetPresentCommit
from mono_control.repo_ops import apply_target

_LAYOUT_VERBS = {"place", "relocate", "retire", "checkout"}


class _RecordingBroker(ShimBroker):
    """A real-effect shim that also records each verb name, in call order."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.verbs: list[str] = []

    def call(self, method, params=None):
        self.verbs.append(method)
        return super().call(method, params)


def _origin(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--initial-branch", "main", str(path)])
    (path / "README.md").write_text("hello\n")
    run_git(["add", "."], cwd=path)
    run_git(["commit", "-m", "initial"], cwd=path)
    return run_git(["rev-parse", "HEAD"], cwd=path)


def test_apply_target_orders_acquire_then_scan_then_layout(tmp_path):
    head = _origin(tmp_path / "origin")
    ws, off = tmp_path / "ws", tmp_path / "off"
    ws.mkdir()
    off.mkdir()
    broker = _RecordingBroker(tmp_path / "config", ws, off)
    RepoStore(broker).create(
        Repo(
            version=1,
            slug="alpha",
            name="Alpha",
            sources={"origin": str(tmp_path / "origin")},
        )
    )

    # Isolate apply_target's own calls from the store-setup calls above.
    broker.verbs.clear()

    target = LayoutTarget(
        targets={"alpha": LayoutTargetPresentCommit(commit=head, location="apps/web")}
    )
    apply_target(target, broker=broker, work_root=ws, bare_root=off)

    # The effect actually landed (a worktree was added under the work root).
    assert (ws / "apps" / "web" / ".git").exists()

    verbs = broker.verbs
    acquire_indices = [i for i, v in enumerate(verbs) if v == "acquire"]
    layout_indices = [i for i, v in enumerate(verbs) if v in _LAYOUT_VERBS]
    assert acquire_indices, f"expected at least one acquire, got {verbs}"
    assert "scan" in verbs, f"expected a scan, got {verbs}"
    assert layout_indices, f"expected at least one layout op, got {verbs}"
    scan_index = verbs.index("scan")

    # Every source acquire precedes the scan, which precedes every layout op:
    # layout ran against the post-acquire re-scan.
    assert max(acquire_indices) < scan_index < min(layout_indices), verbs
