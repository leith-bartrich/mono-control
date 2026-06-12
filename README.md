# mono-control

A **repo state manager** for the fiemono workspace — *not* a build system.

mono-control's job is to bring a set of project repositories to a known,
declared state. It reads the workspace manifest from `mono-config`, makes sure
the right repos exist in `mono-repos` at the right revisions, and reports on
what's actually checked out. It does not build anything and does not look inside
the repos it manages.

## What it does

- Reads the workspace configuration from `mono-config`.
- Knows which repos should exist in `mono-repos`, their remotes, and which
  branches / tags / commits matter.
- Clones repos into `mono-repos` if they aren't there yet.
- Brings each repo to the right state — "latest on the default branch" for
  day-to-day development, or specific commits/tags for a reproducible release.
- Reports what's checked out, and whether anything is dirty or behind.

## What it does NOT do

- It does **not** build anything.
- It does **not** know or care what's inside the repos — source layout,
  languages, dev containers, or toolchains.
- Each managed project owns its own build system, dev container, and toolchain.
  mono-control only governs *which revision of each repo is present*, like a
  package manager operating at the repository level.

## Architecture

```
mono-control-shim   thin host CLI — resolves & bootstraps the workspace
mono-control        this repo — the state manager (runs in a container)
mono-config         the workspace manifest (which repos, which states)
mono-repos          where managed project repos are cloned
```

The shim lives on the host and is deliberately minimal; the real work happens
here, inside a dev container, for host isolation and a reduced attack surface.

## Dev container

mono-control runs inside its own [dev container](.devcontainer/devcontainer.json)
for host isolation and security. It builds on the
`mcr.microsoft.com/devcontainers/universal:2` image (Python, Node, and more),
installs [uv](https://docs.astral.sh/uv/) for Python package management, and
preloads the Claude Code, Python, and Pylance VS Code extensions. The sibling
`mono-config` and `mono-repos` directories are bind-mounted into the container.

Open the folder in VS Code and run **Dev Containers: Reopen in Container**, or
open the repo in a GitHub Codespace.

> Placeholder — skeleton structure, to be built out.
