# Product cluster

A **product cluster** is the first [repo aspect](../README.md): a repo that holds a
coherent group of product/artifact configuration and the build records made
against it.

It is a **data repo** — one mono-control reads, writes, and understands the schema
of — the artifact-domain sibling of `mono-config` (the workspace-domain data
repo). Where opaque managed repos are only versioned, a product cluster is
deliberately *non-opaque*: mono-control knows its internal layout.

Think of it as the artifact-domain analog of a **Visual Studio solution**: the
member repos are its "projects," and the cluster organizes them so some number of
related artifacts can be configured, developed, built, and packaged together. A
cluster expresses **one** such arrangement.

Its content lives — by aspect convention — under a `product-cluster/` subdirectory
inside the cluster repo, so multiple aspects on one repo stay out of each other's
way. That content grows over time; the **first and load-bearing piece is the
cluster's layout**:

- **[Layout](layout.md)** — the cluster's single, authored arrangement: which repo
  [slugs](../../data/repo.md) are members, *where* each sits under `mono-repos/`, and
  each member's **role** (`dev` vs `dep`). Persisted as
  `product-cluster/default-layout.json` (`default-` because a
  [snapshot](../../data/snapshot.md), which also carries a location per entry, is
  itself an alternative layout — leaving room for archived/derived layouts later).
- **Snapshots** *(future)* — the *captured* build records (concrete commit pins)
  written back into the cluster; the version ledger a `dep` member resolves against.
- **Named states** *(future)* — what a state conform like `conform dev-latest` means
  per member; resolved as **logic** over role + branches + snapshots, not stored as a
  document of their own.

## Declaration & discovery

Per the [aspect contract](../README.md), a repo declares the `product-cluster` aspect
in its [repo definition](../../data/repo.md) in `mono-config`. That gives mono-control
an authoritative **list of available product clusters from config alone** — so it
can present them and pull all, or a chosen subset, without materializing anything
first. The cluster's *own* configuration (artifact configs, layout) is read only
after it is checked out.

## Default materialization location

A product cluster materializes, **by default**, under a products subdirectory:

```text
mono-repos/products/<name>
```

This is a *default convenience location, not a contract* — nothing guarantees a
cluster lives exactly here, so the convention stays informal and may vary.
`<name>` is a **local, variable, friendly** name and is the one place we
deliberately do **not** use the full cluster slug: by default it's derived from
the repo's [slug](../../data/repo.md) (proposed: the slug with any trailing
uniqueness/hash segment stripped). The slug remains the durable identity;
`<name>` is just the human-facing subdir [alias](../README.md). The exact derivation
rule — and whether slugs carry a uniqueness suffix at all — is **TBD**.

Materialization is two engine steps, not a single clone: the
[source engine](../../source/README.md) **acquires** the cluster into offline (clone or
init, stamped), then the [layout engine](../../layout/README.md) **places** it at that
subdir. (The [git layer](../../git/README.md) provides the primitives.)

## The manager

Its code lives in `src/mono_control/aspects/product_cluster/` and it is invoked as
`mproj control product-cluster <verb>` (per the
[aspect code & CLI layout](../README.md)). The verbs:

- **list-available** — the repos declaring the aspect, from config (no checkout).
- **init / mark** — bring a new cluster into being (init via the source engine) or
  mark the aspect on an existing [repo def](../../data/repo.md).
- **mat** — a sub-group of intent verbs that drive the source +
  [layout](../../layout/README.md) engines:
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

The verbs above operate on the cluster *as a repo* — acquire it, place it, check it
out. Two further groups operate on the cluster's *content* and on the *workspace* it
describes, both following the same two-surface
[UI convention](../../../ui/README.md) (scriptable verbs plus an interactive `manage`).

**`layout`** — author and inspect the cluster's [layout](layout.md) document:

- **layout show** — render the authored layout (members, locations, roles).
- **layout manage** — interactive authoring (add / remove / relocate members, set a
  member's role), with scriptable counterparts under `layout`.
- **layout validate** — schema + existence checks (every member resolves to a live
  repo def).

**[`conform`](conform.md)** — make the *workspace* match a target (a peer of
`mat` / `demat`, but acting on the workspace rather than the cluster repo):

- **conform clear** — reset the whole workspace (members and pcs) to empty;
  non-destructive, and never forced — the layout engine refuses unsafe removals.
- **conform swap `<pc>`** — clear, then lay out `<pc>`'s default layout (placement
  only), ready for a state conform.
- **conform `<state>`** *(draft)* — advance the laid-out workspace to a named ref-state
  (e.g. `dev-latest`); awaits the named-state design.
- **conform to a snapshot** *(anticipated)* — reconstruct a captured
  [snapshot](../../data/snapshot.md) exactly (pinned commits + locations). Snapshots
  aren't a flat namespace — the intent likely names a *kind* then the snapshot
  (e.g. `conform artifact-version <name>`); mechanics not yet worked out.

Materializing the cluster itself was the first feature to drive the
[source](../../source/README.md) + [layout](../../layout/README.md) engines into a
real, user-facing workflow; `layout` + `conform` make the cluster's *own content*
drive them too.

## Open questions

Resolved since the first draft:

- **Member identity is the workspace [slug](../../data/repo.md)** — layouts and
  snapshots are slug-keyed, consistent with every durable record; there is no
  cluster-local identity. The subdir alias resolves *UX*, not identity.
- The cluster's **first internal schema is designed** — its [layout](layout.md).

Still open:

- **Snapshot storage** inside the cluster (the `dep` version ledger) — deferred for
  now.
- **Named-state resolution** (`conform dev-latest` and kin, patch-stack policies) —
  the metadata-driven interpretation of an intent; intended as *logic* over role +
  branches + snapshots, not as data. This is the next big design push; nothing is
  locked yet (no reserved source/branch names). See [conform](conform.md).
- The `<name>` subdir-derivation rule (and whether slugs carry a uniqueness suffix)
  — still TBD.
