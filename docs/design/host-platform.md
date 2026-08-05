# Host platform

mono-control runs inside a Linux container, but the working trees it manages
usually live on the **host** filesystem (Windows NTFS, macOS APFS, Linux ext4),
reached through a bind mount. How git should treat those files — executable bits,
symlinks, case-sensitivity — depends on the platform the files actually live on,
not on the container's own Linux-ness.

This document covers how that host platform is **declared** to mono-control and
how the declaration is **gated**. It does *not* cover how the platform is *used*
to configure git; that belongs to the [git operations layer](layers/git/README.md),
which consumes the profile defined here.

## Why it must be declared, not detected

The container is *always* Linux. When the working tree is bind-mounted from the
host, the container's git sees it through a translation layer (drvfs on
Windows/WSL2, gRPC-FUSE on macOS) — a synthetic view, not the host's real
filesystem semantics. So container-side auto-detection is unreliable: it can
decide a Windows tree tracks executable bits, producing phantom "mode changed"
diffs that the host's own git would never show.

The container therefore cannot *infer* the host platform. It must be **told**.
And because a wrong-but-silent value corrupts clones subtly, an absent or
unrecognized value is a loud failure, not a guess.

## The declaration: `MONO_CONTROL_HOST_PLATFORM`

The host platform is declared by the environment variable
`MONO_CONTROL_HOST_PLATFORM`, whose value is one of a small recognized set:

- `windows`, `darwin`, `linux` — a specific host platform.
- `generic` — **no specific platform assumed**; only platform-agnostic work is
  safe. This is the baked default (see below), not a detection failure.

## A second sentinel — but a *dynamic* one

mono-control already has a sentinel, `MONO_CONTROL_IN_CONTAINER`, that refuses to
run outside the container (see the project README, "Runs only in the container").
`MONO_CONTROL_HOST_PLATFORM` is a second sentinel with the same *refuse-on-absence*
posture but a fundamentally different nature:

| | `MONO_CONTROL_IN_CONTAINER` | `MONO_CONTROL_HOST_PLATFORM` |
|---|---|---|
| Question | "am I inside the container?" | "what host filesystem am I operating on?" |
| Value | **constant** (`1`) | **variable** (`windows`/`darwin`/`linux`/`generic`) |
| Source | baked on the service (Compose `environment:`) | **supplied per invocation** |
| Why not static | running on the host is *always* wrong | one image serves *every* host — nothing to bake |
| Security meaning | yes — the host-isolation gate | none — an operational default |

The first is a property of *where the code runs*; the second is a property of
*what the call is operating on*. The image is multi-platform by nature, so the
platform value cannot ride along on it the way the container sentinel does — it
has to be injected, every call, by whoever knows the host.

## Baking the default

`MONO_CONTROL_HOST_PLATFORM=generic` is baked as a real image `ENV` in the
Dockerfile, so the variable is **always present** on any launch — Compose, the
shim, or a bare `docker run`. Callers that know the host override it.

> Deliberate contrast with the security sentinel: `MONO_CONTROL_IN_CONTAINER` is
> intentionally **not** baked as a persistent `ENV` — code copied out to the host
> must *lack* it and refuse to run. The platform default is the opposite kind of
> thing — an operational default we *want* always present, carrying no security
> meaning — so it gets the opposite treatment. The two must not be conflated.

## Who overrides it

Whoever sits on the host boundary detects the real platform and overrides the
default, treating it as mandatory:

- **The shim** — the host-side `mproj`, and host-side Python in *every* mode: dev
  mode (`docker compose run` against live source) and artifact mode (`docker run`
  the prebuilt image) alike. In both it detects the host (`platform.system()` →
  token) and passes `-e MONO_CONTROL_HOST_PLATFORM=<token>` — an explicit `-e` wins
  over any `.env` or the image's baked `ENV`, so there is no precedence ambiguity.
  It never falls back to `generic`: if it cannot map the host to a known token it
  errors **on the host side**. Supplying specificity is its entire job here.
- **The Compose default** — the `${MONO_CONTROL_HOST_PLATFORM:-generic}`
  interpolation in the Compose service. This was the fallback for the interactive
  "Reopen in Container" path, which VS Code started itself without the shim; that
  path has since been retired, so the shim is now the *only* way the container
  starts and its explicit `-e` always wins. The interpolation is kept as a safe
  default for a hand-run `docker compose up`, where degrading to `generic` (only
  the stamping operations then refuse) beats failing the container outright.

## The gate: two tiers

Because the variable is always present, there is no "missing" branch in normal
operation. The check splits in two:

1. **Global, lenient.** At startup, validate the value is a *recognized token*;
   reject only garbage. A sanity check, not a demand for specificity. Lives beside
   the existing run-time container gate.
2. **Per-operation, strict.** Operations that stamp filesystem config (clone /
   init) call `require_specific_platform()`, which raises if the value is still
   `generic`. Platform-agnostic commands (listing repos, showing config, status
   reads) never call it and run happily on `generic`.

A useful side effect: forgetting to wire the platform breaks only the stamping
operations — with a clear, shim-pointing message — not every command.

## The filesystem-capability profile

A specific platform maps to the git config that makes a working tree faithfully
*representable* on that filesystem:

| Platform | `core.filemode` | `core.symlinks` | `core.ignorecase` |
|---|---|---|---|
| `windows` | false | false | true |
| `darwin` | true | true | true |
| `linux` | true | true | false |
| `generic` | — (no profile) | — | — |

These are **capability** settings — about representing the files, not about their
contents. Content policy (line endings, `.gitattributes`) is deliberately *not*
here; under mono-control's opaque-repo principle that belongs to the managed
project. The profile is *declared* here and *applied* by the
[git operations layer](layers/git/README.md) when it stamps a clone.

## Relationship to other documents

- The [git operations layer](layers/git/README.md) consumes this profile to stamp
  a repo's `.git/config` at clone time.
- The container sentinel it parallels is described in the project README ("Runs
  only in the container").
