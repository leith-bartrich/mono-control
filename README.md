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
mono-control-shim   host-side CLI — resolves & bootstraps the workspace, then
                    hands off into the container (the only piece that runs on
                    the host)
```

Everything else runs inside the dev container, where the three managed
directories are bind-mounted as siblings under `/workspaces`:

```
/workspaces/mono-control   this repo — the state manager
/workspaces/mono-config    the workspace manifest (which repos, which states)
/workspaces/mono-repos     where managed project repos are cloned
```

The shim lives on the host and is deliberately minimal; the real work happens
here, inside the dev container, for host isolation and a reduced attack surface.

## Runs only in the dev container

mono-control is meant to run **only** inside its dev container, and it is built
to resist running anywhere else. This is a deliberate supply-chain safeguard:
the code that manages your repos — and every dependency it pulls in — should
never execute against your host, where a compromised or typo-squatted package
would run with your full user privileges. Keeping it boxed in the container
means an `uv sync` that fetches a bad package can only reach the sandbox.

Two layers enforce this:

- **Install-time gate.** Once a `pyproject.toml` lands, the project will use an
  in-tree [PEP 517](https://peps.python.org/pep-0517/) build backend that
  checks for the container sentinel before it will build. Running `uv sync` (or
  `uv pip install -e .`) on the host fails fast — *before* resolving or
  installing any dependency — instead of pulling untrusted packages onto your
  host. Inside the container the sentinel is present and the build proceeds
  normally.
- **Run-time gate.** The CLI entrypoint re-checks the same sentinel on startup
  and refuses to run without it, so even a pre-built environment copied out to
  the host won't execute.

The sentinel is the `MONO_CONTROL_IN_CONTAINER` variable set by the dev
container itself (via `containerEnv` in
[devcontainer.json](.devcontainer/devcontainer.json), corroborated by the
`/workspaces` bind-mount layout), so there is nothing to remember to turn on.

## Dev container

mono-control runs inside its own [dev container](.devcontainer/devcontainer.json)
for host isolation and security. It builds on the
`mcr.microsoft.com/devcontainers/universal:2` image (Python, Node, and more),
installs [uv](https://docs.astral.sh/uv/) for Python package management, and
preloads the Claude Code, Python, and Pylance VS Code extensions. The sibling
`mono-config` and `mono-repos` directories are bind-mounted alongside this repo
under `/workspaces`.

Open the folder in VS Code and run **Dev Containers: Reopen in Container**, or
open the repo in a GitHub Codespace.

> Placeholder — skeleton structure, to be built out.
