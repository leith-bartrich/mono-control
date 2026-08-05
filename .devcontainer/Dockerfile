# Slim dev container image for mono-control.
#
# mono-control only manages git + config data — it runs no foreign-language
# builds — so this image carries just Python, git, and uv rather than the
# multi-GB universal image it replaced. A smaller image is also a smaller
# supply-chain surface, which is the whole reason this tool is boxed in a
# container in the first place (see README.md).
#
# Debian (glibc), NOT Alpine. The original reason — the VS Code Server, Pylance
# and the Claude Code extension all needing glibc — retired with the devcontainer
# path. The base is deliberately unchanged anyway: swapping it is a decision with
# its own testing (wheel availability, image size, git behavior), not a tidy-up to
# be folded into a comment edit.
FROM python:3.12-slim-bookworm

# git: what mono-control manages (and eventually shells out to).
# sudo: root-owned paths occasionally need fixing from inside `mproj shell-control`
#       (this was the devcontainer's postCreateCommand chown; the need outlived it).
# ca-certificates: TLS for uv package downloads and git-over-HTTPS.
# less: ergonomics for interactive shells and git pagers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        sudo \
        less \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. The name `codespace` is now load-bearing only through the paths
# built on it — the baked venv (/home/codespace/.mono-control-venv), the shim's
# test venv and its uv cache mount. Renaming it is a coordinated change across the
# shim, not a rename here. Passwordless sudo is retained for in-container work.
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
# repos — mono-control, mono-config, and every repo under mono-repos. System scope
# also means it needs no lifecycle hook to apply, which is what the shim's path has
# always relied on.
RUN git config --system --add safe.directory '*'

# The sandbox marker — THE security gate for both the build backend (_build/gate.py)
# and the run-time CLI/test gates (mono_control.sandbox). Baked at a system path
# OUTSIDE the source tree, so a host checkout never carries it and no environment
# variable can fake it (the old MONO_CONTROL_IN_CONTAINER env sentinel was a one-line
# bypass). Created here as root, before the USER switch, so it exists for the
# editable install below (whose build backend checks it).
RUN printf 'mono-control dev container\n' > /etc/mono-control-container

# Where the baked mono-control environment lives. DELIBERATELY outside
# /workspaces/mono-control: dev mode bind-mounts live source over that path, which
# would shadow an in-tree .venv and leave the tool unrunnable. (The shim already
# relies on this same trick for `mproj test-control`.)
ENV MONO_CONTROL_VENV="/home/${USERNAME}/.mono-control-venv"

# Put that venv's bin on PATH for ALL processes, so the baked `mono-control`
# console script resolves from the image itself rather than from any per-session
# environment setup — there is no lifecycle hook to rely on.
# ~/.local/bin stays on PATH for any other user-installed tooling.
ENV PATH="${MONO_CONTROL_VENV}/bin:/home/${USERNAME}/.local/bin:${PATH}"

# Safe default for the host-platform hint (see docs/design/host-platform.md).
# Baked as a persistent ENV — an operational default with no security meaning: the
# image is multi-platform, so `generic` is the safe fallback the shim / dev
# container override per invocation with the detected host. (The security gate is
# the marker file created above, not any env var.)
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
# The build backend (_build/gate.py) requires the sandbox marker created above;
# image build is the sanctioned container context, and the marker is present by
# now, so the editable install proceeds. On the host the marker is absent, so the
# same build fails fast.
COPY --chown=${USERNAME}:${USERNAME} . /workspaces/mono-control
RUN cd /workspaces/mono-control \
    && UV_PROJECT_ENVIRONMENT="${MONO_CONTROL_VENV}" \
       uv sync --locked --no-dev
