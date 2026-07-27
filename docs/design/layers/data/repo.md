# Repo definition

A **repo definition** is the config-bound data object for a single managed
repository in the [mono project](mono-project.md) — its identity, where to fetch
it, and the roles it carries. It lives in the [config source](config-source.md)
(`mono-config`). It is the analogue of a Visual Studio *Project*, the *abstract*
kind: mono-control governs *which revision of each repo is present*, like a package
manager at the repository level — not a build system.

> This doc is the **definition** (declarative config). It is **not** the on-disk
> checkout — that is the [on-disk repo](on-disk-repo.md), which has a
> location, a commit, and (for aspect repos) readable contents. Same repo, two
> objects.

The definition is deliberately **content-agnostic**: it captures identity, sources,
branches, and aspects — never the repo's language, build system, or toolchain.
"Repo" is chosen over "project" to signal that opacity; a VS project implies a known
build, ours is intentionally generic. (mono-control reading a repo's *contents* is
the exception reserved for [aspect](../repo-aspects/README.md) repos — see the
[on-disk repo](on-disk-repo.md).)

## Identity, name, and source

These are three different things, and keeping them separate is what lets a
[snapshot](snapshot.md) stay valid as the world around a repo changes:

- **Identity — an immutable slug/key.** Set once, never changes. This is the
  durable key everything else references a repo by. It is *not* a description; it
  may drift from the display name over time, and that's fine.
- **Display name — mutable.** A free, human-facing label that can be renamed at
  will without affecting identity or any existing snapshot.
- **Source(s) — governed named remotes.** A repo can have any number of remotes
  (URLs) — GitHub today, GitLab tomorrow, a local mirror the next. The *values* are
  free; the *names* are mono-control's reserved, governed vocabulary (see
  [Sources](#sources) below), not git's local naming. Following git, a source is
  **not part of the repo** — it's local/workspace metadata on the definition, keyed
  by the slug, and is **never serialized into a snapshot**.

This mirrors git's own split — immutable object hashes versus mutable refs and
remotes — with one deliberate choice: we use a **human-readable slug** as the
immutable key rather than an opaque hash, trading a little drift-from-name for
legible snapshots and config.

Both **sources** and **branches** are stored as *named maps* (`name → url` and
`purpose → branch`). For **sources** the key vocabulary is now **governed** — see
[Sources](#sources) below. For **branches** see [Branches](#branches) — the *definition*
is settled (shared bare-name labels, resolved by composition); the purpose vocabulary
(`dev`, stable lines, …) is still being designed.

## Sources

`sources` is a named map (`name → url`), but the **names are governed**, not free —
they are mono-control's vocabulary, identical in every instance of the workspace, so a
reference like "the fork's dev line" resolves to the same thing on every machine. Git
remote names are otherwise *local* state that drifts per checkout; mono-control takes
control of them. (This is the *control* in mono-control: remote configuration is just
more declared state it conforms.) The local git clone is **conformed** to this
declaration — the canonical remotes are stamped into `.git/config` at materialize,
alongside the slug + FS-capability [stamps](../git/README.md) — so operations can run
`git fetch <name>` / `git checkout <name>/<branch>` and *trust* the names.

The reserved vocabulary turns on one question — **is the repo ours, or based on someone
else's?** — and `origin` versus `upstream` answers it. They are **mutually exclusive**: a
repo cannot both originate with us and be based on an external base.

- **`origin`** — the canonical home of a repo that is **ours, originated by us** (no
  upstream). Singular and solo. This is the one place we keep git's own name, because
  here it is unambiguous and *aligned* with git: an owned repo clones into `origin` by
  default — no fighting.
- **`upstream`** — the single, authoritative base we **do not** own. At most one; its
  mere presence declares the repo *fundamentally not ours* (we consume it). Git never
  auto-creates this name. (Distinct from git's *word* "upstream" for a branch's tracking
  ref — a different concept that coexists fine.)
- **`fork-<purpose>`** — a **divergent copy** of the canonical. It may be our own
  (`fork-ours`) or someone else's we track for reference (`fork-<them>`), and it can sit
  beside *either* canonical — forks of our `origin`, or forks of an `upstream`.
- **`mirror-<purpose>`** — a **read copy** of the canonical (a faster/local clone source,
  a backup), never authored. Like forks, it may be ours or others' (`mirror-ours`,
  `mirror-<them>`) and accompany either canonical.

So a key is `origin`, `upstream`, or `<kind>-<purpose>` with `<kind>` from the reserved
set {`fork`, `mirror`}. The vocabulary is governed by the **authoring flows** — the guided
UI and the fork/source verbs construct only governed keys — and, eventually, by engine
conformance; it is deliberately *not* enforced by schema validation at load, so arbitrary
extra names remain legal in the model (runtime meaning is the engines' concern). The
*values* stay free (any URL or path). The structural rule:
**`origin` and `upstream` are mutually exclusive** (a repo is ours *or* based on an
external base, never both), while `fork-*` / `mirror-*` are **copies relative to whichever
canonical is present**. The purpose `ours` is reserved to mark *our own* copy, so "our
writable remote" resolves deterministically — `origin`, else `fork-ours` — with no
guessing; every other purpose (a peer's, e.g. `fork-bob`) is a **tracked reference**,
never auto-selected. **Provenance is just the canonical:** no sources ⇒ local-only (a freshly
`init`-ed repo); `origin` ⇒ ours; `upstream` ⇒ not ours. Forks and mirrors are additional
copies — others' or ours — and never change who owns the repo.

**Adopting an upstream is a governed migration.** Because `origin` and `upstream` cannot
coexist, the moment an `origin` repo gains an upstream its `origin` must reclassify to
`fork-ours` (we diverge from the base) or `mirror-ours` (we only track it) — a transition
mono-control performs, re-stamping the local remote. It forces a conscious "fork it or
mirror it?" decision at the moment the relationship changes, rather than letting `origin`
silently mean two things. When there *is* an upstream, git's default `origin` is
suppressed at clone with `git clone --origin <name>`.

**Forking an upstream is a governed transition.** The mirror-image moment: a consumed
`upstream` repo gets forked by us (typically because the base won't take our patches and
our fork now carries the development line). The definition gains `fork-ours` beside the
`upstream` — ownership does not change; the upstream remains the canonical — and, when
the fork's development line differs from the base's, `branches["dev"]` repoints to the
fork's branch with the upstream's old dev line preserved under the reserved purpose
[`dev-upstream`](#branches). mono-control performs this transition (interactively via
`repo manage` → "add fork", or scriptably via `repo fork add`) rather than leaving two
maps to be hand-edited in the right order. The new source key is appended *after* the
canonical, so first-declared source resolution is unchanged. When a checkout exists on
disk (materialized or offline), the transition **eagerly stamps** the fork remote into
`.git/config` (`git remote add fork-ours <url>`); the engines will additionally conform
declared remotes as ordinary declared state in the future — the eager stamp just makes
the fork fetchable immediately. Config is saved first; a failed stamp is reported, never
rolled back. A third-party fork (`fork-<them>`) may be added by the same flow as a
tracked reference — it never repoints `dev`.

*Deferred:* **per-instance source overrides** — e.g. a machine-local mirror preferred as
a clone source — would live in a local layer *on top of* shared `mono-config`, not in the
repo def (whose sources are shared and identical in every instance). Reserving mirror
purposes like `local` waits on that layer; for now mirror purposes stay free.

The *resolution behavior* each kind drives — push only to a fork, prefer a mirror as a
clone source, track the base from `upstream` — leans out of these meanings but is firmed
up with the [source engine](../source/README.md); the names above are the locked part.

## Branches

`branches` is a map of **purpose → branch name** — a label saying which concrete branch
*means* the dev line, a stable line, and so on. Like sources the purposes are governed
vocabulary; *unlike* sources, mono-control does **not** create branches (commits do), so it
governs the *naming convention* and resolves it against git's actual refs.

**Branches are bare names, resolved by composition.** A purpose names only the branch; the
*remote* comes from the [source](#sources)/role context, and the two compose into a git ref
— `<remote>/<branch>`. A `dev` purpose resolves to `upstream/<dev>` for a consume-role repo,
or `fork-ours/<dev>` / `origin/<dev>` for our own work. The map **never** binds a purpose to
a specific source.

**Branches are *shared* lines — not fork-additive ones.** A purpose here is a line that
exists the same way across remotes (`main`, `master`, `develop`, a release line). A branch
that lives in exactly *one* fork as a construction — e.g. "upstream's dev plus our
cherry-picked patches, rebased periodically" — is **not** a branch label and is **not** in
this map. That is the **patch-stack**: source-bound, recipe-bearing (base ref, patch source,
output branch), maintained by a rebase operation — its own construct, designed separately.
(`branches` couldn't hold its recipe regardless.)

**Two standardized purposes: `dev` and `dev-upstream`.** `dev` is the active development
line ("the development line, whatever it's literally named"), resolving to the remote's
**default branch** unless a repo overrides it (`branches: {dev: develop}`).
`dev-upstream` is the **upstream base's development line**: it appears only on
upstream-based repos whose `dev` has been repointed to our fork's line (the
[fork transition](#sources)), recording what `dev` used to mean so the base's line stays
addressable — e.g. as the base ref of a future patch-stack recipe. The name follows the
`<thing>-<qualifier>` pattern of `fork-ours`. It is still a bare branch name resolved by
composition — by its meaning it composes against the `upstream` remote
(`upstream/<branch>`) — and it is a shared line, not a patch-stack. A repo may also
declare **arbitrary named branches** (free purposes) and reference them explicitly, but
mono-control standardizes no meaning for them.

**An absent purpose means "the remote's default", not "unknown".** That is already how
`dev` behaves — absent, it resolves to the default branch of whichever remote it composes
against — and `dev-upstream` inherits it: absent, the base's development line *is* the
`upstream` remote's default branch. So neither purpose needs a null or empty-string
sentinel. The two states already say everything there is to say: **absent** follows the
remote's default, **present** is an explicit override.

That makes hand-filling `dev-upstream` both pointless and misleading. Pointless because
an absent one already resolves to the upstream's default; misleading because
mono-control writes it *only* in the [fork transition](#sources), and only where that
transition repointed `dev` away from a line it had already recorded — so its presence is
a **signal that a repoint happened**. Writing it yourself fakes that signal without
adding information. Leave it out.

An upstream with *no* development line is not a case to model — it is degenerate. A repo
whose HEAD names no existing branch has no commits at all, and an empty repo is nothing
to fork or to base on. (It is the same unborn-HEAD condition that left a freshly
`init`-ed bare repo unplaceable until it was given a root commit.)

We deliberately do **not** define `stable` / release / version branches here. Those are
upstream conventions we don't control, and "stability" is usually expressed as a *tag*
(frozen) — fundamentally a different thing from a *branch* (floating). How pinned versions
are handled — tags, snapshots, some "blessed version", whether it's even a separate config
axis — is **unresolved and not yet decided**; nothing about it is assumed here.

A consequence for materialization: with no version system yet, a **`dep`-role member has
exactly one choice when brought from source — `dev`** (the active line / default branch),
the same as a `dev`-role member. The role is recorded for a future where versions can be
pinned; until then it does not change ref resolution.

## Aspects

A definition may declare one or more [aspects](../repo-aspects/README.md) — extra
roles a repo carries, such as being a
[product cluster](../repo-aspects/product-cluster/README.md). The *declaration* lives here
in config, so an aspect is discoverable without checking the repo out; the aspect's
*detailed* data lives inside the [on-disk repo](on-disk-repo.md). Aspects
**compose** — a repo may carry several.

## Storage and lifecycle

Each definition is one JSON file at `mono-config/repos/<slug>.json` — the directory
*is* the registry (adding a file adds a repo), and the filename is the slug,
cross-checked against the in-file `slug`. mono-control **authors** these files (via
`mono-control repo …` and the interactive `repo manage` UI); this is the first
place the tool writes config rather than only reading it.

Deletion is two-tiered, because a [snapshot](snapshot.md) may reference a repo by
slug:

- **Retire** (soft, default) — a tombstone flag; the slug stays reserved and the
  change is reversible. Retired repos are hidden from normal listings.
- **Purge** (hard, heavily guarded) — physically removes the definition. The
  guarded path that makes true deletion possible without making it easy.

Repo definitions are referenced by **slug** — the members of
[repo sets](repo-set.md), the things a [layout-target](layout-target.md) pins to a
desired ref, and a [snapshot](snapshot.md) records at an exact commit. The slug also
keys the repo's [on-disk](on-disk-repo.md) checkout.
