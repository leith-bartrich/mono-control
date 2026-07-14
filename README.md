# mono-control

A **repo state manager** for the fiemono workspace — *not* a build system.

mono-control's job is to bring a set of project repositories to a known,
declared state. It reads the workspace manifest from `mono-config`, makes sure
the right repos exist in `mono-repos` at the right revisions, and reports on
what's actually checked out. It does not build anything and does not look inside
the repos it manages.

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
- **Acquires** repos into a holding area (`mono-repos-offline/<slug>`) — the
  *source engine* clones (or `git init`s a brand-new repo) and stamps each
  checkout with the host's filesystem-capability profile and its identity slug.
- **Arranges** them in the workspace (`mono-repos/...`) — the *layout engine*
  places, relocates, retires, and checks out commits as a target says,
  race-safely and per-repo independently.
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
  the sibling `mono-config` / `mono-repos` directories are bind-mounted under
  `/workspaces`.
- **Headless execution** (the shim): the shim runs `docker compose run` against
  the baked image and bind-mounts the workspace's `mono-config` / `mono-repos`
  into the container per invocation.

Inside the container the managed directories always live at fixed paths:

```
/workspaces/mono-control        this repo — the state manager (baked into the image)
/workspaces/mono-config          the workspace manifest (which repos, which states)
/workspaces/mono-repos           where managed project repos are *placed* (materialized)
/workspaces/mono-repos-offline   holding area for acquired-but-not-placed checkouts
```

The shim lives on the host and is deliberately minimal (standard library only,
zero third-party dependencies); the real work happens inside the container, for
host isolation and a reduced attack surface.

## Runs only in the container

mono-control is meant to run **only** inside its container, and it is built to
resist running anywhere else. This is a deliberate supply-chain safeguard: the
code that manages your repos — and every dependency it pulls in — should never
execute against your host, where a compromised or typo-squatted package would
run with your full user privileges. Keeping it boxed in the container means an
`uv sync` that fetches a bad package can only reach the sandbox.

Two layers enforce this:

- **Install-time gate.** An in-tree [PEP 517](https://peps.python.org/pep-0517/)
  build backend checks for the container sentinel before it will build. Running
  `uv sync` (or `uv pip install -e .`) on the host fails fast — *before*
  resolving or installing any dependency — instead of pulling untrusted packages
  onto your host. Inside the container the sentinel is present and the build
  proceeds normally.
- **Run-time gate.** The CLI entrypoint re-checks the same sentinel on startup
  and refuses to run without it, so even a pre-built environment copied out to
  the host won't execute.

The sentinel is the `MONO_CONTROL_IN_CONTAINER` variable set on the container by
Docker Compose (the `environment:` key in
[.devcontainer/docker-compose.yml](.devcontainer/docker-compose.yml)), so both
modes — and every process inside the container — inherit it, and there is
nothing to remember to turn on.

## GitHub authentication

Managed repos are usually private, so cloning them needs a credential — and the
container cannot get one itself: your host's lives in an OS keyring (Windows
Credential Manager, the macOS Keychain, `gh`'s store) that a Linux container cannot
reach. The credential is therefore **handed in per invocation** by the shim, as
`MONO_CONTROL_GITHUB_TOKEN`.

You do not normally set this yourself. `mproj` resolves a token host-side: it uses
`MONO_CONTROL_GITHUB_TOKEN` if you have exported one, and otherwise falls back to
your `gh auth token` (warning when it does).

**Prefer a scoped token.** mono-control never writes to a remote — it only clones,
fetches refs, and checks out — so a **fine-grained PAT with read-only Contents,
limited to the repos you manage**, is all it needs. A `gh` OAuth token, by contrast,
carries `repo` + `workflow` + `gist` *write* access to everything you own. Export the
scoped one and the fallback never fires:

```sh
export MONO_CONTROL_GITHUB_TOKEN=github_pat_...
```

The token is read from the environment by a credential helper baked into the image
and is **never written to disk** — in particular, never into a clone's `.git/config`,
which lives on your host via the bind mount and would persist there indefinitely. The
helper is registered for `https://github.com` **only**, so a wrong or malicious remote
URL in a repo definition can never be handed your token. Without a usable credential
git fails loudly (`GitAuthError`, naming both ways out) rather than prompting.

Full rationale, including what a stolen token would and would not buy an attacker:
[docs/design/github-auth.md](docs/design/github-auth.md).

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

repo init <name>                         # def + brand-new offline checkout
repo mat moveto <name-or-slug> <subdir>  # place at mono-repos/<subdir>
repo mat branchat <name-or-slug> <br>    # check out a branch at current location
repo mat commit <name-or-slug> <sha>     # check out a commit (detached)
repo demat <name-or-slug>                # retire to offline

product-cluster list-available           # repos declaring the aspect
product-cluster init <name>              # new product-cluster repo
product-cluster mat moveto <name-or-slug>  [<subdir>]   # default: products/<derived>
```

Run `mproj control -- --help` for the live tree.

## License

[MIT](LICENSE).
