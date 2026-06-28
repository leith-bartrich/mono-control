# Product cluster

A **product cluster** is the first [repo aspect](README.md): a repo that holds a
coherent group of product/artifact configuration and the build records made
against it.

It is a **data repo** — one mono-control reads, writes, and understands the schema
of — the artifact-domain sibling of `mono-config` (the workspace-domain data
repo). Where opaque managed repos are only versioned, a product cluster is
deliberately *non-opaque*: mono-control knows its internal layout.

What it holds (kept deliberately light for now):

- **Named artifact configurations** — the authored, *declared* "these repos at
  these versions make this artifact." This is the home for what we'd otherwise
  have modeled as a standalone "product"; it lives in the cluster, **not** in
  `mono-config`.
- **[Snapshots](../data/snapshot.md)** — the *captured* build records, written
  back into the cluster.
- (likely) artifact **version history** tying the two together.

The cluster's internal layout is its own design problem and is **TBD** — this doc
fixes only the *aspect contract* and the *materialization convention*; the on-disk
schema for artifact configs and snapshot storage is deferred.

## Declaration & discovery

Per the [aspect contract](README.md), a repo declares the `product-cluster` aspect
in its [repo definition](../data/repo.md) in `mono-config`. That gives mono-control
an authoritative **list of available product clusters from config alone** — so it
can present them and pull all, or a chosen subset, without materializing anything
first. The cluster's *own* configuration (artifact configs, layout) is read only
after it is checked out.

## Default materialization location

A product cluster materializes, **by default**, under a products subdirectory:

```
mono-repos/products/<name>
```

This is a *default convenience location, not a contract* — nothing guarantees a
cluster lives exactly here, so the convention stays informal and may vary.
`<name>` is a **local, variable, friendly** name and is the one place we
deliberately do **not** use the full cluster slug: by default it's derived from
the repo's [slug](../data/repo.md) (proposed: the slug with any trailing
uniqueness/hash segment stripped). The slug remains the durable identity;
`<name>` is just the human-facing subdir [alias](README.md). The exact derivation
rule — and whether slugs carry a uniqueness suffix at all — is **TBD**.

Materialization is two engine steps, not a single clone: the
[source engine](../source/README.md) **acquires** the cluster into offline (clone or
init, stamped), then the [layout engine](../layout/README.md) **places** it at that
subdir. (The [git layer](../git/README.md) provides the primitives.)

## The manager

Its code lives in `src/mono_control/aspects/product_cluster/` and it is invoked as
`mproj control product-cluster <verb>` (per the
[aspect code & CLI layout](README.md)). The verbs:

- **list-available** — the repos declaring the aspect, from config (no checkout).
- **init / mark** — bring a new cluster into being (init via the source engine) or
  mark the aspect on an existing [repo def](../data/repo.md).
- **mat** — a sub-group of intent verbs that drive the source +
  [layout](../layout/README.md) engines:
  - `mat moveto <name> [<subdir>]` — place at
    `mono-repos/products/<subdir>` (defaults to the slugified repo name);
    placement only, no ref change.
  - `mat branchat <name> <branch>` — check out a branch's HEAD at the
    cluster's current location.
  - `mat commit <name> <sha>` — check out a specific commit (detached
    HEAD) at the cluster's current location.
  - `mat layout-target <name> --location L [--branch B | --commit C]` —
    declarative one-liner combining placement and ref intent.
- **demat** — retire the cluster (its `products/<subdir>` → offline) via the
  layout engine; non-destructive.

This was the first feature to drive the [source](../source/README.md) +
[layout](../layout/README.md) engines into a real, user-facing workflow.

## Observation (not yet a rule)
- The cluster's internal schema (artifact-config format, snapshot storage) is
  undesigned.
- Whether a cluster's snapshots reference workspace slugs or a cluster-local
  identity is open — the subdir alias resolves the *UX*, not this internal choice.
