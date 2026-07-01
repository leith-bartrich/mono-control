"""The layout engine's ``_move`` must work across filesystems (EXDEV).

In the container, mono-repos and mono-repos-offline are separate mounts, so a plain
``os.rename`` between them fails with EXDEV. These tests force that boundary by
monkeypatching ``os.rename`` (a single ``tmp_path`` is one filesystem, so the real
fallback path isn't otherwise exercised).
"""

import errno
import os
from pathlib import Path

import pytest

from mono_control.engines.layout import execute
from mono_control.engines.layout.errors import MoveFailedError


def _exdev_for(src: Path):
    """A fake os.rename that raises EXDEV only for the real src→dst move."""
    real_rename = os.rename

    def fake_rename(a, b):
        if Path(a) == src:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_rename(a, b)  # let the temp→dst publish through

    return fake_rename


def test_move_same_device_uses_rename(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("hi\n")
    dst = tmp_path / "out" / "dst"

    execute._move(src, dst)

    assert not src.exists()
    assert (dst / "f.txt").read_text() == "hi\n"


def test_move_falls_back_across_devices(tmp_path, monkeypatch):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "f.txt").write_text("hi\n")
    (src / "sub" / "g.txt").write_text("nested\n")
    dst = tmp_path / "out" / "dst"

    monkeypatch.setattr(execute.os, "rename", _exdev_for(src))
    execute._move(src, dst)

    assert not src.exists()
    assert (dst / "f.txt").read_text() == "hi\n"
    assert (dst / "sub" / "g.txt").read_text() == "nested\n"
    assert not (dst.parent / f".{dst.name}.tmp-move").exists()  # temp cleaned up


def test_move_cross_device_cleans_tmp_and_keeps_src_on_copy_failure(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("hi\n")
    dst = tmp_path / "out" / "dst"

    def boom(*a, **k):
        raise OSError("copy failed")

    monkeypatch.setattr(execute.os, "rename", _exdev_for(src))
    monkeypatch.setattr(execute.shutil, "copytree", boom)

    with pytest.raises(MoveFailedError):
        execute._move(src, dst)

    assert (src / "f.txt").read_text() == "hi\n"  # source untouched
    assert not dst.exists()
    assert not (dst.parent / f".{dst.name}.tmp-move").exists()
