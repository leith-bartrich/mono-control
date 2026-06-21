import pytest

from mono_control import host_platform as hp


def test_read_absent_defaults_to_generic(monkeypatch):
    monkeypatch.delenv(hp.HOST_PLATFORM_ENV, raising=False)
    assert hp.read() == hp.GENERIC


@pytest.mark.parametrize("token", sorted(hp.KNOWN))
def test_read_known_token_returned(monkeypatch, token):
    monkeypatch.setenv(hp.HOST_PLATFORM_ENV, token)
    assert hp.read() == token


def test_read_garbage_rejected(monkeypatch):
    monkeypatch.setenv(hp.HOST_PLATFORM_ENV, "windoze")
    with pytest.raises(hp.HostPlatformError):
        hp.read()


def test_require_specific_rejects_generic(monkeypatch):
    monkeypatch.setenv(hp.HOST_PLATFORM_ENV, hp.GENERIC)
    with pytest.raises(hp.HostPlatformError):
        hp.require_specific()


def test_require_specific_rejects_absent(monkeypatch):
    monkeypatch.delenv(hp.HOST_PLATFORM_ENV, raising=False)  # absent -> generic
    with pytest.raises(hp.HostPlatformError):
        hp.require_specific()


@pytest.mark.parametrize("token", sorted(hp.SPECIFIC))
def test_require_specific_returns_specific(monkeypatch, token):
    monkeypatch.setenv(hp.HOST_PLATFORM_ENV, token)
    assert hp.require_specific() == token


@pytest.mark.parametrize(
    "token,filemode,symlinks,ignorecase",
    [
        (hp.WINDOWS, False, False, True),
        (hp.DARWIN, True, True, True),
        (hp.LINUX, True, True, False),
    ],
)
def test_profile_matches_table(monkeypatch, token, filemode, symlinks, ignorecase):
    monkeypatch.setenv(hp.HOST_PLATFORM_ENV, token)
    prof = hp.profile()
    assert (prof.filemode, prof.symlinks, prof.ignorecase) == (
        filemode,
        symlinks,
        ignorecase,
    )


def test_profile_rejects_generic(monkeypatch):
    monkeypatch.setenv(hp.HOST_PLATFORM_ENV, hp.GENERIC)
    with pytest.raises(hp.HostPlatformError):
        hp.profile()


def test_require_valid_exits_on_garbage(monkeypatch):
    monkeypatch.setenv(hp.HOST_PLATFORM_ENV, "nonsense")
    with pytest.raises(SystemExit):
        hp.require_valid()


def test_require_valid_passes_for_known(monkeypatch):
    monkeypatch.setenv(hp.HOST_PLATFORM_ENV, hp.WINDOWS)
    hp.require_valid()  # should not raise


def test_require_valid_passes_when_absent(monkeypatch):
    monkeypatch.delenv(hp.HOST_PLATFORM_ENV, raising=False)
    hp.require_valid()  # absent -> generic -> valid
