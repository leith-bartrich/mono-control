# mono-control

A **repo state manager** for the fiemono workspace — *not* a build system.

mono-control's job is to bring a set of project repositories to a known,
declared state. It reads the workspace manifest from `mono-config`, makes sure
the right repos exist as worktrees in `mono-work` at the right revisions, and
reports on what's actually checked out. It does not build anything and does not
look inside the repos it manages.

## Physical model: bare repos + worktrees

Every managed repository is a **bare** repo under `mono-repos-bare/<slug>` that
is created once and **never moves**. Bringing it into the workspace is an
additive `git worktree add` under `mono-work/…`; retiring it is `git worktree
remove` (the bare repo, and everything committed in it, survives). This replaced
an earlier "clone into an offline dir, then rename it into the workspace" model,
whose directory move failed (`WinError 5` / `EACCES`) when an IDE or drvfs held
the directory being renamed — a worktree add moves nothing held, so that class of
failure is gone by construction.

The `offline` / `materialized` states are reinterpreted onto this model rather
than replaced: **offline = a bare repo with no worktree**; **materialized = a
bare repo with a worktree** under `mono-work`.

## Use through the shim

mono-control is a containerized **sub-component** of a larger system. The
proper way to deploy and drive it is through its host-side shim,
[**mono-control-shim**](https://github.com/leith-bartrich/mono-control-shim) —
a small, dependency-free CLI (`mproj`) installed on your host. The shim
locates your workspace, detects the host platform, and hands off into the
mono-control container; you should not invoke this project directly in normal
use. Install the shim and start with `mproj`.

Technically you *can* run mono-control without the shim — its CLI
(`mono-control <verb>`) is a normal Python entrypoint and works fine inside
the container's terminal once the container is up. That path exists for
testing, debugging, and unusual integrations; it's not the recommended
deployment.

## What it does

- Reads the workspace configuration from `mono-config`.
- Knows which repos should exist on disk, their remotes, and which
  branches / tags / commits matter.
- **Acquires** repos as **bare** repos (`mono-repos-bare/<slug>`) — the *source
  engine* clones `--bare` (or `git init --bare`s a brand-new repo) and stamps each
  bare repo with the host's filesystem-capability profile and its identity slug
  (inherited by every worktree added off it).
- **Arranges** them in the workspace (`mono-work/...`) — the *layout engine*
  places (`git worktree add`), relocates (`git worktree move`), retires (`git
  worktree remove`), and checks out commits as a target says, race-safely and
  per-repo independently.
- Knows about *aspects* — extra roles a repo can carry (today:
  `product-cluster`); the per-aspect CLI groups (`mproj control
  product-cluster <verb>`) plug onto the same engine machinery.

## What it does NOT do

- It does **not** build anything.
- It does **not** know or care what's inside the repos — source layout,
  languages, dev containers, or toolchains.
- Each managed project owns its own build system, dev container, and toolchain.
  mono-control only governs *which revision of each repo is present*, like a
  package manager operating at the repository level.

## Architecture

mono-control runs as a containerized tool driven by a thin host shim:

```
mono-control-shim   host-side CLI (`mproj`) — resolves the workspace and hands
                    off into the container; the only piece that runs on the host
mono-control        the state manager itself — baked into a slim container image
                    and run inside it, never on the host
```

The container is defined by Docker Compose and serves two modes from one image:

- **Interactive development** (VS Code "Reopen in Container"): live source and
  the sibling `mono-config` / `mono-work` directories are bind-mounted under
  `/workspaces`.
- **Headless execution** (the shim): the shim runs `docker compose run` against
  the baked image and bind-mounts the workspace's `mono-config` / `mono-work`
  into the container per invocation.

Inside the container the managed directories always live at fixed paths:

```
/workspaces/mono-control       this repo — the state manager (baked into the image)
/workspaces/mono-config        the workspace manifest (which repos, which states)
/workspaces/mono-work          where managed repos are *placed* — a worktree per materialized repo
/workspaces/mono-repos-bare    the bare repos (one per slug; created once, never moved)
```

The shim lives on the host and is deliberately minimal (standard library only,
zero third-party dependencies); the real work happens inside the container, for
host isolation and a reduced attack surface.

**IDE scoping (current intent, not yet solidified).** The division of `mono-work`
(worktrees a developer actually edits) from `mono-repos-bare` (bare object stores)
is meant to let an editor such as VS Code be scoped to **`mono-work` only**, and
*not* index `mono-repos-bare`. Keeping an IDE off the bare repos is also what makes
`git worktree add`/`move`/`remove` safe from the held-directory move failures the
old model hit. This is the *current intent* — the exact IDE-scoping mechanism is
not yet solidified.

## Runs only in the container

mono-control is meant to run **only** inside its container, and it is built to
resist running anywhere else. This is a deliberate supply-chain safeguard: the
code that manages your repos — and every dependency it pulls in — should never
execute against your host, where a compromised or typo-squatted package would
run with your full user privileges. Keeping it boxed in the container means an
`uv sync` that fetches a bad package can only reach the sandbox.

Two layers enforce this:

- **Install-time gate.** An in-tree [PEP 517](https://peps.python.org/pep-0517/)
  build backend checks for the container marker before it will build. Running
  `uv sync` (or `uv pip install -e .`) on the host fails fast — *before*
  resolving or installing any dependency — instead of pulling untrusted packages
  onto your host. Inside the container the marker is present and the build
  proceeds normally.
- **Run-time gate.** The CLI entrypoint (and the test suite) re-check the same
  marker on startup and refuse to run without it, so even a pre-built environment
  copied out to the host won't execute.

The gate is a **marker file** (`/etc/mono-control-container`) baked into the image
by the [Dockerfile](.devcontainer/Dockerfile) at a path *outside* the source tree —
so a host checkout never carries it, and no environment variable can fake it. (An
earlier design trusted a `MONO_CONTROL_IN_CONTAINER` env var, but a one-line
`export` defeated it, so the gate was moved to the baked file.) Use `mproj`, which
always runs mono-control in the container.

## GitHub authentication

Cloning private repos needs a credential, but the **container never holds one**.
All git and filesystem effects run on the *host* via the broker (see the broker
layer), so acquisition uses your host's own git credentials — the OS keyring
(Windows Credential Manager, the macOS Keychain) or `gh`'s store that native git
already reads. Nothing is injected into, or written from, the container.

## Dev container

Interactive development happens inside the container via VS Code Dev Containers
(or a GitHub Codespace). The image is **slim and purpose-built**:
`python:3.12-slim-bookworm` (Debian/glibc) with just git and
[uv](https://docs.astral.sh/uv/) — no foreign-language toolchains, since
mono-control only manages git and config data. A smaller image is also a smaller
supply-chain surface, in keeping with the isolation goal above.

The container is described by Docker Compose:

- [.devcontainer/docker-compose.yml](.devcontainer/docker-compose.yml) — the
  source of truth (image, sentinel, run context); also what the headless shim
  runs.
- [.devcontainer/docker-compose.devcontainer.yml](.devcontainer/docker-compose.devcontainer.yml)
  — a dev-time-only overlay (live source + sibling bind mounts + Claude Code
  persistence) layered on top for VS Code.
- [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json) — the VS
  Code attachment, preloading the Claude Code, Python, and Pylance extensions.

Open the folder in VS Code and run **Dev Containers: Reopen in Container**, or
open the repo in a GitHub Codespace.

## Building the image

The same Dockerfile produces the image used for headless (artifact-mode) runs.
From a workspace that has a `mono-control/` checkout, the shim builds it for you:

```sh
mproj build-control   # builds mono-control:latest into the local docker store
```

which is a thin wrapper over the standalone build:

```sh
docker build -t mono-control:latest -f .devcontainer/Dockerfile .
```

`mproj control` then runs mono-control against a workspace and picks the backend
by whether a `mono-control/` checkout is present beside `mono-config/`: if it is,
it uses Docker Compose against that live source (dev mode); if not, it runs the
`mono-control:latest` image (artifact mode). Distribution of a prebuilt image via
ghcr.io is planned; until then, build it locally with `mproj build-control`.

## Commands at a glance

Everything below is invoked through the shim as `mproj control -- <args>` (the
`--` keeps the shim from interpreting flags that belong to mono-control). A few
representative verbs:

```
repo add <name> [--slug X]               # author a repo def (slug auto-derived)
repo list                                # show repo defs
repo show <name-or-slug>                 # one repo in detail

repo init <name>                         # def + brand-new offline (bare) repo
repo mat moveto <name-or-slug> <subdir>  # add a worktree at mono-work/<subdir>
repo mat branchat <name-or-slug> <br>    # check out a branch at current location
repo mat commit <name-or-slug> <sha>     # check out a commit (detached)
repo demat <name-or-slug>                # retire to offline (remove the worktree)

product-cluster list-available           # repos declaring the aspect
product-cluster init <name>              # new product-cluster repo
product-cluster mat moveto <name-or-slug>  [<subdir>]   # default: products/<derived>
```

Run `mproj control -- --help` for the live tree.

## License

[MIT](LICENSE).
