# On-disk repo

An **on-disk repo** is the *on-disk* side of a [repo](repo.md): the actual git
checkout mono-control places in the workspace. It is a different object from the
[repo definition](repo.md) — same repo, two things. The definition declares *what a
repo is and where to get it*; the on-disk repo is *what's actually on disk right
now*.

> This doc is the **on-disk checkout** (runtime, observed). For the config-bound
> definition (slug, sources, branches, aspects), see [repo](repo.md).

## Three local states

A repo's on-disk presence is one of:

- **absent** — no checkout locally.
- **offline** — a full checkout held in `mono-repos-offline/<slug>` (acquired but
  not placed, or retired from a location).
- **materialized** — placed at a **location** (a subdirectory under `mono-repos`).

The [source engine](../source/README.md) **creates** the checkout `absent → offline`
(clone an existing remote, or init a brand-new repo) and refreshes it (fetch); the
[layout engine](../layout/README.md) moves it `offline ↔ materialized` (place /
retire), checks it out to a commit, or relocates it. **"Materialized" is the *placed*
state** — a checkout sitting *offline* is on disk but **not** materialized.

## Observed, not declared

Unlike the definition, an on-disk repo's properties are **observed** at runtime,
never authored: its current **commit**, its **location**, and whether the working
tree is **dirty**. The layout engine reads these to diff against a
[layout-target](layout-target.md); they can also be captured into a
[snapshot](snapshot.md) (`{slug → (commit, location)}`).

## Opacity, and the aspect exception

By default mono-control **never reads an on-disk repo's contents** — it manages
*which revision is present*, not what's inside (the opacity boundary). The
exception is an [aspect](../repo-aspects/README.md) repo, such as a
[product cluster](../repo-aspects/product-cluster.md): there mono-control *does*
read structured data from the checkout (artifact configurations, snapshots). So
opacity is the rule; aspect repos are the deliberate, declared exception — and the
reason the on-disk repo is a first-class data-layer concept, not just a side effect.

## Identity: a self-stamped slug

An on-disk repo maps back to its [definition](repo.md) by **slug** — but its
*location* doesn't encode the slug (the path is a local, often lossy convention,
e.g. `products/<name>`). So a checkout is made **self-identifying**: the slug is
stamped into its own `.git/config` (`mono-control.slug = <slug>`) when the
[source engine](../source/README.md) clones or inits it (at **creation**, into
offline), alongside the FS stamp. Reverse-lookup (location → slug) is then just
reading that marker, with two useful properties:

- **Relocation-safe** — the marker lives in `.git`, so it moves with the checkout
  when the [layout engine](../layout/README.md) relocates it; there is no external
  index to keep in sync.
- **Distributed source of truth** — the current layout is *observed* by scanning
  `mono-repos` / `mono-repos-offline` and reading each checkout's
  `mono-control.slug`, so on-disk reality is always authoritative.
- **Purely local, never pushed** — `.git/config` lives in `.git`, is never tracked
  or committed, and git transfers only objects/refs (never config), so the stamp is
  invisible to the remote and absent from a fresh clone. This is why it works on
  remotes we don't control (we never modify or push to them) and why it must be
  `.git/config` rather than a *tracked* marker (a working-tree file or git note
  would travel to the remote and require its cooperation).

A checkout with **no marker** is a *foreign / unmanaged* checkout (not one
mono-control placed) — reported as such, never silently adopted. And a stamped slug
should still resolve to an existing [definition](repo.md); a dangling one (the def
was purged) is surfaced.
