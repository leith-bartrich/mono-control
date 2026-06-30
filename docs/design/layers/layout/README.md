# Layout engine

The **layout engine** arranges the workspace's **local** layout to match a
[layout-target](../data/layout-target.md): which repos are materialized, where, and at what
commit. It is **local-only** — it never touches a remote, and it never **creates** a
checkout (no clone, no init, no fetch); it only *moves and checks out* checkouts the
[source engine](../source/README.md) already created and stamped. Bringing repos (and
the commits a target needs) into local availability is the source engine's job; the
layout engine assumes that has happened.

Its two headline actions are the **`mat`** / **`demat`** commands made concrete:
**`mat` = place** (offline → a location), **`demat` = retire** (a location →
offline). Both are pure local moves.

Per repo, the local state is one of three:

- **absent** — not present locally at all.
- **offline** — present in `mono-repos-offline/<slug>` (acquired but not placed, or
  retired from a location). A holding area, keyed by slug.
- **materialized** — placed at a location (a subdir under `mono-repos`).

The layout engine moves repos between **offline ↔ materialized** and checks out
commits that are **already local**; the [source engine](../source/README.md) does
**absent → offline** (clone) and refreshes refs (fetch).

## Phases

1. **Observe** — the actual local layout: scan `mono-repos` / `mono-repos-offline`,
   identify each checkout by its self-stamped slug (`mono-control.slug` in
   `.git/config` — see [on-disk repo](../data/on-disk-repo.md)), and read
   its location, commit, and whether the working tree is dirty. (git inspect +
   filesystem; no network.) A checkout with no marker is foreign/unmanaged.
2. **Pre-empt / diff** — classify each repo vs. the target: *satisfied* (no-op,
   idempotent), *blocked* (no safe action — e.g. a ref-change over a dirty tree, or
   a needed commit isn't local), or *actionable*.
3. **Execute — carefully** (see below).
4. **Capture** (optional) — record the resulting layout as a
   [snapshot](../data/snapshot.md).

## Resolving intent into actions

The target speaks high-level intent; the layout engine turns it into concrete local
actions. A `branch-head` request resolves to a precise commit by reading the
**local** ref the [source engine](../source/README.md) already fetched — no network.
If that commit isn't local, the repo is *blocked*: acquisition must run first.

**One materialization per repo** — a repo is checked out in at most one location, so
the workspace is a single coherent layout. From the observed state the engine
derives, per repo. The "+ checkout" steps below apply only when the desired
state carries a ref intent (`commit` / `branch-head`); for `present-as-is`
the move happens without any checkout — placement is preserved-as-is:

| Observed | Request | Action |
|---|---|---|
| offline | present (any kind) | **place** (move offline → location) + checkout the resolved commit (if any) |
| at the target location | present (with ref intent) | **checkout** to the resolved commit |
| at the target location | `present-as-is` | **satisfied** (no-op) |
| at a *different* location | present (`pre_clear` false) | **relocate** (move location → location) + checkout (if any) |
| materialized | `absent`, or a `pre_clear` extra | **retire** (move location → offline) |
| absent | present (any kind) | *blocked* — not local; the [source engine](../source/README.md) must acquire it first |

A shared repo therefore **moves** rather than duplicating: if two product clusters
both want repo X, the second relocates it — you switch layouts, never hold two at
once. And note there is **no clone here** — placement is always from offline;
reaching a remote is not the layout engine's job.

`pre_clear` makes the target *exclusive*: every materialized repo not named in it
becomes a *retire* action.

## Removal is non-destructive: retire to offline

The layout engine **never deletes a checkout.** "Removal" (a demat, a `pre_clear`
prune, a displaced relocate) **moves** the checkout to `mono-repos-offline/<slug>`.
This is the checkout-level analog of repo **[retire](../data/repo.md)** (soft,
reversible) vs. **purge** (hard, guarded): retiring a checkout preserves any
unpushed commits and local-only branches, and re-placing it later restores that
work intact. So reconcile is *never destructive*, and needs no fragile "is
everything pushed?" gate in the hot path.

True deletion of an offline copy is a **separate, guarded** step (the purge analog),
where an unpushed/clean check or an explicit confirmation applies — not part of
reconcile. (The one edge: retiring when `mono-repos-offline/<slug>` is already
occupied is guarded, so existing offline work isn't clobbered.)

`is_dirty` still matters narrowly: a **checkout** that changes the ref on a
materialized dirty tree would overwrite uncommitted work, so that is *blocked*. A
**retire** (move) preserves everything, so it isn't gated by dirtiness.

## Execute carefully: the check is advisory, the act self-guards

Observe→act is a genuine **race** — another process or a person can change on-disk
state between the engine looking and acting. So the engine treats the pre-empt/diff
result as *planning and UX* and never *trusts* it at the moment of action.

- **Failure-as-guard.** Prefer operations whose atomic failure *is* the race
  detector: let `mkdir` / a move into an occupied path fail, rather than
  check-then-act.
- **Atomic placement.** Move/place via **atomic-rename** into the location; a
  half-applied tree never appears, and a spot occupied meanwhile fails cleanly
  instead of merging.
- **Minimize the window.** Re-check a destructive precondition immediately before
  acting, not just in pre-flight.
- **No partial state.** On a race conflict, abort *that repo* with a clear message
  (optionally re-observe + retry once) and leave everything else consistent.

## Per-repo independence

A target spans many repos; the layout engine reconciles each **independently**. One
repo failing (blocked, or a race conflict) doesn't corrupt the others or silently
half-apply the set. The engine reports per-repo outcomes, so a multi-repo reconcile
stays legible.

## Relationships
- **[Layout-target](../data/layout-target.md)** — the input (desired local layout).
- **[Snapshot](../data/snapshot.md)** — the output (captured actual layout).
- **[Source engine](../source/README.md)** — ensures repos + refs are local first;
  it owns clone/fetch (and the host stamp).
- **[Git layer](../git/README.md)** — the local operations the layout engine drives
  (checkout / move / inspect).
- **[Repo definitions](../data/repo.md)** — the branch convention used to resolve a
  `branch-head` to a local ref.

## Observation (not yet a rule)
- **Default-branch resolution** — which of main/master/dev is "default" is the
  repo's [branch convention](../data/repo.md), still TBD.
- **Capture** may be always-on or opt-in, and *where* a captured snapshot lands
  (e.g. inside a [product cluster](../repo-aspects/product-cluster/README.md)) is open.
