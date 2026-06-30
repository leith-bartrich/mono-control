# conform

`conform` brings the **workspace** into agreement with a declared **target**. It is a
top-level product-cluster verb-group — a peer of [`mat` / `demat`](README.md), but where
those act on the cluster *repo*, `conform` acts on the *workspace* the cluster describes.

Every sub-intent names a different target; the verb is always "make reality match it"
(the surface syntax below is illustrative — see [Grammar](#grammar-open), which is open):

```text
mproj control product-cluster conform clear         # target: empty workspace
mproj control product-cluster conform swap <pc>     # target: <pc>'s layout (structure)
mproj control product-cluster conform <state> [pc]  # target: a named ref-state (draft)
mproj control product-cluster conform artifact-version <name>  # target: a snapshot, by kind (anticipated)
```

## Sub-intents

### conform clear

Reset the **whole workspace** — member repos *and* product clusters — to empty. It builds
the exclusive target `LayoutTarget(pre_clear=True, targets={})`: every materialized repo
reconciles to absent.

It is **not a force**. Clearing is [non-destructive](../../layout/README.md) — repos
retire to `mono-repos-offline/`, preserving unpushed work — and the
[layout engine](../../layout/README.md) **refuses** any removal it cannot do safely (e.g. a
dirty working tree) rather than discarding work. There is no `--force`.

### conform swap \<pc>

Switch the workspace to a different cluster: `clear`, then materialize `<pc>` and conform
the workspace to its [`default-layout.json`](layout.md) — **placement only**, no refs. It
deliberately stops at structure, leaving a clean stage for a subsequent state conform.
Bootstrapping order is inherent: the cluster materializes first (so its layout is
readable), then its members are laid out.

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

## The implied cluster

When a sub-intent needs a cluster and one isn't given, it resolves to the **sole
materialized product cluster** when exactly one is present. With **zero, or more than
one**, mono-control errors and asks you to name it — it never guesses. `clear` needs no
cluster.

## Grammar *(open)*

The exact command grammar is **not settled** — what follows is a sketch, not a decision.
A natural shape is *mode-first* (`conform <mode> [args]`, with `clear` / `swap` as
keywords and any other leading token read as a state name), but that presumes things we
haven't worked out: a shared namespace between reserved sub-intents and state names, and
that a cluster is targeted via `swap` rather than by being named bare. How states,
pc-names, and reserved words share the command line falls out of the named-state design
push, still to come.

## Buildable now vs. next

`clear` and `swap` rest entirely on what already exists — the [layout](layout.md) document,
the `pre_clear` exclusivity flag on [layout-target](../../data/layout-target.md), and the
shared `apply_target` pipeline — so they can land without new engine work. `conform
<state>` waits on the named-state / convention design and stays a draft until then.
