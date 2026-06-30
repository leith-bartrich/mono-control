# Data layer

The **data layer** is mono-control's abstractions — the nouns it reads and (mostly)
persists. They don't all live in the same place, so the useful thing to index here
is **where each lives**.

## Where the abstractions live

- **Config source — the `mono-config` repo.** The workspace manifest mono-control
  reads (and authors in part). Mechanism: [config-source.md](config-source.md).
  Holds the [mono-project](mono-project.md) (workspace-level config) and
  [repo](repo.md) definitions (the managed pool).
- **The on-disk workspace — `mono-repos` (and `mono-repos-offline`).** The
  [on-disk repo](on-disk-repo.md)s the source + layout engines manage — observed
  runtime state, not authored config. (It includes *offline* checkouts, which are
  on disk but not yet materialized/placed.) mono-control treats a repo as opaque by
  default, but a repo carrying an
  [aspect](../repo-aspects/README.md) is read and written as structured data, so
  some abstractions live **inside** such a repo (not in a separate source). The
  first aspect — the [product cluster](../repo-aspects/product-cluster/README.md) — holds
  [snapshot](snapshot.md)s (captured state) and authored named sets / artifact
  configurations (the persisted form of a [repo-set](repo-set.md)).
- **Memory — constructed, never stored.** Some abstractions are built on the fly:
  the [layout-target](layout-target.md) (the layout engine's desired state, built
  from a snapshot or a development intent), and a bare [repo-set](repo-set.md) (the
  `members()` interface, projected from a product or a snapshot).

## Concept files
- [mono-project.md](mono-project.md) — the whole workspace.
- [repo.md](repo.md) — a managed repository's config-bound **definition**.
- [on-disk-repo.md](on-disk-repo.md) — the same repo's **on-disk** checkout.
- [repo-set.md](repo-set.md) — a named subset of repos (the `members()` interface).
- [layout-target.md](layout-target.md) — the layout engine's desired state (memory).
- [snapshot.md](snapshot.md) — a concrete, captured state.
