# On-disk repo

An **on-disk repo** is the *on-disk* side of a [repo](repo.md): the actual git
repo mono-control manages in the workspace. It is a different object from the
[repo definition](repo.md) — same repo, two things. The definition declares *what a
repo is and where to get it*; the on-disk repo is *what's actually on disk right
now*.

> This doc is the **on-disk repo** (runtime, observed). For the config-bound
> definition (slug, sources, branches, aspects), see [repo](repo.md).

## Physical model: a bare repo + an optional worktree

Every managed repository is a **bare** repo under `mono-repos-bare/<slug>` that is
created once and **never moves**. Placing it in the workspace is an additive `git
worktree add` under `mono-work/…`; retiring it is `git worktree remove` (the bare
repo, and everything committed in it, survives). This replaced an earlier "clone
offline, then rename into the workspace" model whose directory move failed when an
IDE or drvfs held the tree being renamed — a worktree add moves nothing held.

## Three local states

A repo's on-disk presence is one of:

- **absent** — no bare repo locally.
- **offline** — a bare repo under `mono-repos-bare/<slug>` with **no worktree**
  (acquired but not placed, or retired from a location).
- **materialized** — the bare repo has a **worktree** at a **location** (a
  subdirectory under `mono-work`).

The [source engine](../source/README.md) **creates** the bare repo `absent → offline`
(clone `--bare` an existing remote, or `init --bare` a brand-new repo) and refreshes
it (fetch); the [layout engine](../layout/README.md) moves it `offline ↔ materialized`
(worktree add / remove), checks its worktree out to a commit, or relocates the
worktree. **"Materialized" is the *placed* state** — a bare repo with no worktree is
on disk but **not** materialized.

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
[product cluster](../repo-aspects/product-cluster/README.md): there mono-control *does*
read structured data from the checkout (artifact configurations, snapshots). So
opacity is the rule; aspect repos are the deliberate, declared exception — and the
reason the on-disk repo is a first-class data-layer concept, not just a side effect.

## Identity: a self-stamped slug

An on-disk repo maps back to its [definition](repo.md) by **slug** — but its
*location* doesn't encode the slug (the path is a local, often lossy convention,
e.g. `products/<name>`). So a repo is made **self-identifying**: the slug is
stamped into the **bare repo's** config (`mono-control.slug = <slug>`) when the
[source engine](../source/README.md) clones or inits it (at **creation**), alongside
the FS stamp. Because a worktree shares its bare repo's config, every worktree added
off it inherits the stamp. Reverse-lookup is then just reading that marker, with
these useful properties:

- **Bare repo never moves** — the marker lives in the bare repo's config, which is
  created once and never relocated; a worktree add/move/remove leaves it untouched,
  and there is no external index to keep in sync.
- **Distributed source of truth** — the current layout is *observed* by scanning
  `mono-repos-bare` for bare repos, reading each one's `mono-control.slug`, and
  detecting whether it has a worktree under `mono-work` (materialized) or not
  (offline), so on-disk reality is always authoritative.
- **Purely local, never pushed** — the bare repo's config is never tracked or
  committed, and git transfers only objects/refs (never config), so the stamp is
  invisible to the remote and absent from a fresh clone. This is why it works on
  remotes we don't control (we never modify or push to them) and why it must be
  config rather than a *tracked* marker (a working-tree file or git note would
  travel to the remote and require its cooperation).

A bare repo with **no marker** is a *foreign / unmanaged* repo (not one mono-control
created) — reported as such, never silently adopted. And a stamped slug should still
resolve to an existing [definition](repo.md); a dangling one (the def was purged) is
surfaced.
