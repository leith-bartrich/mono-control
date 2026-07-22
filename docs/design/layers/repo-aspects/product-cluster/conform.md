# conform

`conform` brings the **workspace** into agreement with a declared **target**. It is a
top-level product-cluster verb-group — a peer of [`mat` / `demat`](README.md), but where
those act on the cluster *repo*, `conform` acts on the *workspace* the cluster describes.

Every sub-intent names a different target; the verb is always "make reality match it"
(the surface syntax below is illustrative — see [Grammar](#grammar-open), which is open):

```text
mproj control product-cluster conform relayout [pc] # target: a cluster's layout — the core verb
mproj control product-cluster conform clear         # target: empty workspace
mproj control product-cluster conform swap <pc>     # target: <pc>'s layout from a clean slate (clear + relayout)
mproj control product-cluster conform <state> [pc]  # target: a named ref-state (draft)
mproj control product-cluster conform artifact-version <name>  # target: a snapshot, by kind (anticipated)
```

## Sub-intents

### conform relayout \[pc]

The **core verb**: incrementally reconcile the workspace to a cluster's
[layout](layout.md) — pull in members that are missing, retire members no longer in the
layout, and **leave everything already correct untouched**. It is a single exclusive
reconcile (`pre_clear=True` over `{cluster ∪ members}`): no teardown, minimal churn. Reach
for it after editing a layout, or any time you want the workspace to match what the cluster
declares. `[pc]` defaults to the sole materialized cluster; naming one that isn't placed
yet materializes it first.

### conform clear

Reset the **whole workspace** — member repos *and* product clusters — to empty. It builds
the exclusive target `LayoutTarget(pre_clear=True, targets={})`: every materialized repo
reconciles to absent.

Retire is [non-destructive of committed work](../../layout/README.md): it **removes the
worktree** (`git worktree remove`), leaving the bare repo — and every commit in it — under
`mono-repos-bare/`, so re-placing later restores the committed history intact. Uncommitted
worktree edits are the exception: the layout engine's retire is **dirty-gated** and refuses
a dirty worktree rather than discarding it. On top of that leaf guard, `clear` adds the
[dirty-cluster gate](#the-dirty-cluster-gate): it is refused if any materialized product
cluster has uncommitted changes.

### conform swap \<pc>

Switch to a **different** cluster from a clean slate — **`clear` then `relayout <pc>`**,
with `<pc>` **acquired up front (fail-early)** so an unreachable cluster aborts *before*
anything is torn down. The `clear` removes the current cluster (and everything else)
*before* the new one lands, so two clusters are never placed at once — a guarantee
`relayout` alone can't make while *switching*. (For the *same* cluster there's no switch
and no window, so just use `relayout`.) Placement only, no refs.

### conform \<state>  *(draft concept)*

Advance the laid-out workspace to a named ref-state — e.g. `dev-latest` would track the dev
branch heads of `dev`-role members while holding `dep` members at their pins. This is
**draft only**: it depends on a role/metadata-driven *interpretation* layer (which named
source and branch a repo's "dev" resolves to), which is the next design push and is **not
yet settled** — no reserved source/branch names are locked. Documented here so the verb
shape is known, not to fix its behavior.

### conform to a snapshot  *(anticipated)*

Conform the workspace to a captured [snapshot](../../data/snapshot.md) — its
`{slug → (commit, location)}` reconstructed exactly: each member placed at its recorded
location *and* checked out at its recorded commit. This is the reproducible-restore
operation — re-establish a past dev or release state.

A snapshot is **fully concrete** (literal commits → a `commit`-kind
[layout-target](../../data/layout-target.md), no role/metadata interpretation), so the open
questions are all about *addressing* one. Snapshots are **not a flat namespace**: they come
from different kinds/sources and live in more than one place. The first obvious kind is an
**artifact-version** snapshot — a build state captured as an artifact's origin, in the
cluster's (deferred) snapshot store — but others may exist. So the intent likely names the
*kind* and then the specific snapshot, e.g.

```text
mproj control product-cluster conform artifact-version <version-snapshot-name>
```

— an example shape, not a decision. How snapshot kinds, sources, and storage are addressed
is unworked; laid out here as a **likely** intent.

## The dirty-cluster gate

`clear`, `relayout`, and `swap` reconcile or tear down the workspace, and
[`demat`](README.md) retires one cluster. All **refuse when a product cluster they would
retire has uncommitted changes**.

A product cluster is a non-opaque *data* repo whose **committed** state is the
reproducibility anchor — the layout you're in is only durably reproducible if the cluster is
committed. Tearing it down dirty would pin the current state to nothing but an uncommitted
working tree. Member repos are treated differently: their **committed** work lives in the
bare repo and is restored on re-place, so retiring a *clean* member is always safe; a member
with uncommitted edits is caught by the layout engine's own leaf-level dirty gate, not this
aspect gate. Commit (or stash) the cluster first. (This gate lives in the aspect, not the
layout engine — only the aspect knows a repo is a reproducibility-bearing cluster.)

Because the gate guards *reproducibility* specifically — the cluster's committed history is
safe in the bare repo regardless — it has an **escape hatch**: `--allow-dirty` on the CLI
proceeds regardless (accepting that the cluster's uncommitted, unreproducible edits are
discarded), and the interactive manager prompts *"cluster X is dirty — proceed anyway?"*
when it would trip. Overriding just accepts "this teardown isn't reproducibly pinned."

## The implied cluster

When a sub-intent needs a cluster and one isn't given, it resolves to the **sole
materialized product cluster** when exactly one is present. With **zero, or more than
one**, mono-control errors and asks you to name it — it never guesses. `clear` needs no
cluster. (`relayout` defaults to the sole materialized cluster; `swap` names its target
explicitly, since it's switching to one that may not be present yet. The `layout` verbs use
the same implied resolution via their `--cluster` default.)

## Grammar *(open)*

The exact command grammar is **not settled** — what follows is a sketch, not a decision.
A natural shape is *mode-first* (`conform <mode> [args]`, with `relayout` / `clear` / `swap`
as keywords and any other leading token read as a state name), but that presumes things we
haven't worked out: a shared namespace between reserved sub-intents and state names, and
that a cluster is targeted via `swap` rather than by being named bare. How states,
pc-names, and reserved words share the command line falls out of the named-state design
push, still to come.

## Primitives vs. draft

`relayout` and `clear` are the two primitives; `swap` is their composition (`clear` +
`relayout`). All rest on the [layout](layout.md) document, the `pre_clear` flag on
[layout-target](../../data/layout-target.md), a source-only `acquire`, and the shared
`apply_target` pipeline — no new engine work. `conform <state>` and the snapshot targets
remain **draft**, awaiting the named-state / convention design.
