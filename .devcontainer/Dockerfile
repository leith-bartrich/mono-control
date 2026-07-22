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

# The sandbox marker — THE security gate for both the build backend (_build/gate.py)
# and the run-time CLI/test gates (mono_control.sandbox). Baked at a system path
# OUTSIDE the source tree, so a host checkout never carries it and no environment
# variable can fake it (the old MONO_CONTROL_IN_CONTAINER env sentinel was a one-line
# bypass). Created here as root, before the USER switch, so it exists for the
# editable install below (whose build backend checks it).
RUN printf 'mono-control dev container\n' > /etc/mono-control-container

# Put the user's tool bin on PATH for ALL processes — VS Code terminals and the
# headless shim path alike — so the baked `mono-control` console script resolves
# without relying on devcontainer.json's remoteEnv (which the headless path skips).
ENV PATH="/home/${USERNAME}/.local/bin:${PATH}"

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
# the baked copy. Editable so that one path is the source of truth in both modes.
#
# The build backend (_build/gate.py) requires the sandbox marker created above;
# image build is the sanctioned container context, and the marker is present by
# now, so the editable install proceeds. On the host the marker is absent, so the
# same build fails fast.
COPY --chown=${USERNAME}:${USERNAME} . /workspaces/mono-control
RUN uv tool install --editable /workspaces/mono-control
