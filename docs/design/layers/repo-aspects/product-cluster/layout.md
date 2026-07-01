# Cluster layout

A product cluster's **layout** is its single, authored arrangement of member repos —
the artifact-domain analog of a Visual Studio solution's project layout. One cluster
expresses exactly one layout. It answers two things per member: *where* the repo sits
under `mono-repos/`, and *what role* it plays (`dev` vs `dep`).

The layout is **authored, not captured**. You build and edit it through the cluster's
manager — scriptable CLI verbs plus an interactive `manage` flow, the same
[two-surface convention](../../../ui/README.md) every other mono-control document
uses. (An earlier idea of *capturing* the on-disk arrangement into the file was
dropped for now: a member's role can't be read off disk — disk shows only where a
repo sits, never whether it is a dev target or a dependency — so authoring is the
honest primary mode. Capture may return later as a convenience that re-syncs
*locations* only.)

## Where it lives

Per the [aspect contract](../README.md), an aspect's content lives under an
`<aspect-name>/` subdirectory inside the materialized cluster repo. The authored
layout is:

```text
product-cluster/default-layout.json
```

`default-` because a [snapshot](../../data/snapshot.md) carries a location per entry
and is therefore itself an *alternative* layout — the name leaves room for
snapshot-derived or archived layouts (e.g. `product-cluster/layouts/<name>.json`)
without renaming the canonical one.

## The model

A versioned pydantic model (`ClusterLayout`), strict-by-default like every persisted
document:

```json
{
  "version": 1,
  "members": {
    "<repo-slug>": { "location": "<subdir under mono-repos/>", "role": "dev" }
  }
}
```

- **members** — keyed by workspace [slug](../../data/repo.md). The key set *is* the
  cluster's membership: it satisfies the [repo-set](../../data/repo-set.md)
  `members()` interface, so the layout doubles as the cluster's authored repo set.
- **location** — the subdir under `mono-repos/` where the member materializes; the
  same notion a [layout-target](../../data/layout-target.md) carries.
- **role** — `dev` or `dep`:
  - **dev** — a repo you actively develop in this cluster; its "latest" is a living
    branch head.
  - **dep** — a repo you consume at a pinned version; its "latest" comes from the
    snapshot ledger (or an explicit pin), never a floating branch.

  Role is the field a future state conform (`conform <state>`) keys on to decide
  *which* members advance and *how*. For now it is recorded but does not yet drive ref
  selection — applying the layout is placement-only.

Provenance (do we own / fork / merely consume a repo) is **not** a layout field: a
fork is already expressible as an `upstream` entry in the repo def's named
[sources](../../data/repo.md), so the layout does not re-declare it.

## How it's applied

The layout is consumed by [`conform`](conform.md) — chiefly `conform relayout`, which
reconciles the workspace to this document. Each member becomes a `present-as-is`
[layout-target](../../data/layout-target.md) at its declared `location`, and the set is
handed to the shared source → layout pipeline (`apply_target`) as **one exclusive
reconcile**: missing members are placed, ones no longer in the layout are retired, and
already-correct repos are left untouched. Placement only — no ref is checked out (ref
intent arrives later, with state conforms). Materialization is
[non-destructive](../../layout/README.md) and per-member independent, so one blocked member
never corrupts the others.

Bootstrapping order is inherent: the cluster is **acquired** (into offline if absent) and
its `default-layout.json` read *before* the members are reconciled — see
[`conform`](conform.md) for how `relayout` and `swap` build on it.

## Deferred for now

- **Ref policy** per member (`branch-head` / `patch-stack` / `pinned`) so a state
  conform can resolve refs, not just placement.
- A **`dev-branches`** declaration — which branch each `dev` member tracks.
- **Snapshot** storage in the cluster as the `dep` version ledger.
- The **`conform <state>`** ref-states (e.g. `dev-latest`) — logic over
  role + branches + snapshots; see [conform](conform.md).
- **Capture** (re-sync locations from disk) and **archived / alternative layouts**.
