# Git operations layer

The **git operations layer** is the part of mono-control that actually touches
git — the keystone the whole tool stands on, and the first thing that *does*
anything rather than just describing state. The [data layer](../data/README.md)
holds the nouns (what repos exist, where they come from, what state they should
be in); this layer holds the verbs (clone, fetch, checkout, inspect).

It is **pure mechanism**. It knows about paths and refs; it does **not** know what
a [repo definition](../data/repo.md) is. Callers above it translate repo defs
(sources, branches, location) into the paths and refs this layer operates on.

## Talking to git: our own subprocess wrapper

mono-control drives git by **shelling out to the installed `git` CLI** through a
thin wrapper we own — not GitPython, pygit2, or dulwich. The reasons are the same
ones that shape the rest of the project:

- **Zero new dependencies**, and the smallest possible supply-chain surface — the
  whole reason mono-control is boxed in a container. A compiled binding (pygit2)
  or a reimplementation (dulwich) is exactly the kind of surface we avoid.
- **Behavior parity** — we get the real git that the container already installs,
  with no risk of a library diverging from it.
- It is what the README already commits to ("git: what mono-control manages *and
  eventually shells out to*").

The cost — parsing porcelain output and mapping exit codes — is contained at a
single chokepoint.

## Shape

- **`GitRepo(path)`** — bound to an existing checkout: `current_commit()`
  (`rev-parse HEAD`), `is_dirty()` (`status --porcelain`), `fetch()`,
  `checkout(ref)`, `ahead_behind(ref)` (`rev-list --count`).
- **Module-level operations** not bound to a checkout: `clone(url, dest, …)`,
  `ls_remote(url, ref)` (used for resolvability — does the remote expose this ref).
- **`_run_git([...], cwd=...)`** — the one subprocess chokepoint: list-form args
  (never a shell string), captured output, and exit-code → typed-error mapping.
  Everything else goes through it, so behavior and error handling stay uniform.
- **`GitError` hierarchy** — typed failures mirroring the config layer's
  `ConfigError` (`config/errors.py`), so callers get a clear message instead of a
  raw `CalledProcessError`.

The package will live at `mono_control/git/`. (Note: avoid a module literally named
`platform.py` — it shadows the stdlib `platform` the shim uses to detect the host.)

## The clone-stamp consistency contract

A clone is the **consistency anchor**. When this layer clones a repo, it stamps
the [filesystem-capability profile](../../host-platform.md) — `core.filemode`,
`core.symlinks`, `core.ignorecase` — into the new repo's `.git/config`, chosen for
the **host platform** the working tree lives on (supplied per the
[host-platform contract](../../host-platform.md), never auto-detected by the
container's git through a bind mount).

Because that config persists and is local to the checkout, every later git
invocation on that tree — ours *or* a developer's native git on the same shared
checkout — honors it. "Stamp once at clone, then let git handle it." We stamp only
clones **we** create; a pre-existing checkout we adopt is respected as-is.

## What stays out: content

Under the opaque-repo principle ([repo](../data/repo.md)), mono-control governs
*which revision/location* is present, never contents. So **content policy** — line
endings, `core.autocrlf`, `.gitattributes` — is the managed project's
responsibility, not this layer's. We configure the *container* of the files, not
opinions about the files.

This keeps the cross-platform problem small. Commit identity (`rev-parse`) and
ahead/behind (`rev-list`) are hash- and graph-based, so they are inherently
platform-independent. The *only* read that platform noise can pollute is the
**dirty check** (`status`) via phantom filemode diffs — and the clone-stamp's
`core.filemode` setting is exactly what neutralizes that. Genuine line-ending
differences (made by some other git) we report faithfully; preventing them is the
project's `.gitattributes`, not us.

## Testing

This layer is tested against **real temporary git repositories** — initialize
local repos in temp dirs and clone/fetch/checkout between them — so we exercise
the actual installed git rather than mocks. This runs in the dev container where
git is present.

## Observation (not yet a rule)

Threads deliberately left open here, to be settled as the layer is built:

- **Reconcile MVP scope** — whether the first reconcile runs against a loose
  "latest default branch" intent built from existing repo defs, or waits on the
  [target](../data/target.md) and [repo-set](../data/repo-set.md) nouns.
- **Resolution and the resolvability gate** — turning a loose/precise desired ref
  into a concrete commit, and checking it can be materialized now (does a source
  expose the slug, does the commit still exist). See [target](../data/target.md)
  and [snapshot](../data/snapshot.md).
- **A per-invocation `-c` backstop** — injecting normalized config on individual
  calls for repos we did *not* clone (and thus never stamped), in addition to the
  primary clone-stamp.

## Relationship to other documents

- [host-platform.md](../../host-platform.md) — declares the platform and the
  filesystem-capability profile this layer applies at clone.
- [data layer](../data/README.md) — supplies the repo defs (sources, branches,
  location) this layer is pointed at; in particular [repo](../data/repo.md),
  [target](../data/target.md), and [snapshot](../data/snapshot.md).
