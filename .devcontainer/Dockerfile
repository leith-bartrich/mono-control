# Slim dev container image for mono-control.
#
# mono-control only manages git + config data — it runs no foreign-language
# builds — so this image carries just Python, git, and uv rather than the
# multi-GB universal image it replaced. A smaller image is also a smaller
# supply-chain surface, which is the whole reason this tool is boxed in a
# container in the first place (see README.md).
#
# Debian (glibc), NOT Alpine: the VS Code Server, Pylance, and the Claude Code
# extension all require glibc; musl would break them.
FROM python:3.12-slim-bookworm

# git: what mono-control manages (and eventually shells out to).
# sudo: postCreateCommand chowns the .claude named volume as root.
# ca-certificates: TLS for uv package downloads and git-over-HTTPS.
# less: ergonomics for interactive shells and git pagers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        sudo \
        less \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. The name is kept as `codespace` to match the .claude volume
# target (/home/codespace/.claude), devcontainer.json's remoteUser, and the
# postCreateCommand chown. Passwordless sudo lets that chown run unattended.
ARG USERNAME=codespace
RUN useradd --create-home --shell /bin/bash "${USERNAME}" \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${USERNAME}" \
    && chmod 0440 "/etc/sudoers.d/${USERNAME}"

# uv (Astral's Python package manager), copied from its official image instead
# of a build-time curl|sh — reproducible and pinned by the base image digest.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Trust the host bind mounts for git. Their files carry a non-codespace UID
# purely as a Docker filesystem-sharing artifact (not an adversary, in this
# single-user sandbox), which would otherwise trip git's "dubious ownership"
# guard in every managed repo. System scope so it covers all users and all
# repos — mono-control, mono-config, and every repo under mono-repos — and so
# it applies in the headless path too, which runs no VS Code lifecycle hooks.
RUN git config --system --add safe.directory '*'

# Where the baked mono-control environment lives. DELIBERATELY outside
# /workspaces/mono-control: dev mode bind-mounts live source over that path, which
# would shadow an in-tree .venv and leave the tool unrunnable. (The shim already
# relies on this same trick for `mproj test-control`.)
ENV MONO_CONTROL_VENV="/home/${USERNAME}/.mono-control-venv"

# Put that venv's bin on PATH for ALL processes — VS Code terminals and the
# headless shim path alike — so the baked `mono-control` console script resolves
# without relying on devcontainer.json's remoteEnv (which the headless path skips).
# ~/.local/bin stays on PATH for any other user-installed tooling.
ENV PATH="${MONO_CONTROL_VENV}/bin:/home/${USERNAME}/.local/bin:${PATH}"

# Safe default for the host-platform sentinel (see docs/design/host-platform.md).
# DELIBERATELY baked as a persistent ENV — unlike MONO_CONTROL_IN_CONTAINER, which
# is intentionally NOT baked (the security gate must be absent on the host). This
# one is an operational default with no security meaning: the image is
# multi-platform, so `generic` is the safe fallback the shim / dev container
# override per invocation with the detected host.
ENV MONO_CONTROL_HOST_PLATFORM=generic

USER ${USERNAME}

# Bake mono-control into the image so the headless path (which runs no lifecycle
# hooks) has the tool ready with no source mount. The code lives at its canonical
# workspace path; in dev the overlay bind-mounts live source over this, shadowing
# the baked copy. `uv sync` installs the project EDITABLE, so in dev mode it is
# that mount which actually executes — one source of truth in both modes.
#
# `--locked` is the whole point of this step: it installs exactly the versions
# pinned in uv.lock and VERIFIES each artifact's hash, failing the build if the
# lock is stale or a downloaded artifact does not match. This is why the
# environment is built with `uv sync` and not `uv tool install` — the latter
# resolves dependencies fresh and ignores hashes even when handed a hashed
# constraints file, so every rebuild would be an unpinned resolve. `--no-dev`
# keeps pytest and friends out of the shipped artifact.
#
# The sentinel is set inline for THIS build step only — the build gate
# (_build/gate.py) requires it, and image build is the sanctioned container
# context. It is deliberately not baked as a persistent ENV; the run-time gate
# relies on the sentinel set on the service in docker-compose.yml.
COPY --chown=${USERNAME}:${USERNAME} . /workspaces/mono-control
RUN cd /workspaces/mono-control \
    && MONO_CONTROL_IN_CONTAINER=1 \
       UV_PROJECT_ENVIRONMENT="${MONO_CONTROL_VENV}" \
       uv sync --locked --no-dev
