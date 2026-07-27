# Deliver a versioned source tree (so a consumer can build from one)

mono-control can place a repo at a location. It cannot yet hand anyone a
**specific, named version** of a repo's source — and that turns out to be the thing
standing between the current design and a real request.

The request: a product that consumes another product's CLI needs some way to obtain
it. One candidate is "drive `mproj` to check out the producer at a known version
and build it." That is plausible — the build requirement is only a host Python with
uv, plus docker — but it needs a version to check out, and there isn't one.

## What's actually missing

The pieces are not scattered; they sit together in the deferred pile, and they are
the same design push:

- **No version-shaped branch purposes.** [`repo`](../design/layers/data/repo.md)
  standardizes exactly two: `dev` and `dev-upstream`. There are no stable / release
  / version purposes, and the doc says outright that how pinned versions are handled
  is unresolved and not yet decided.
- **`dep` resolves to the same thing `dev` does.** Stated as a consequence in the
  same doc: a `dep`-role member "has exactly one choice when brought from source —
  `dev`." Role is recorded but does not drive ref selection.
- **`conform relayout` carries no ref intent.** It emits only `present-as-is`
  targets — placement, nothing else (see
  [conform](../design/layers/repo-aspects/product-cluster/conform.md)).
- **The snapshot store is deferred.** [Snapshots](../design/layers/data/snapshot.md)
  are designed and nothing writes one; the cluster-side ledger that a `dep` member
  would resolve against is explicitly future work.
- **Named states are unstarted.** `conform <state>` is the next big design push, with
  no reserved source or branch names locked.

So "give me repo X at version V" has no answer at any layer today.

## When to do this

Pick this up when **any** of these becomes true:

- A consumer's install/remediation path wants an **mproj strategy** — i.e. someone
  is ready to write "check out the producer at V and build it" and needs V to mean
  something.
- **Named states** get designed for their own sake. This work is a subset; doing it
  separately would fork the ref model.
- A **snapshot** needs to be captured for reproducibility — the ledger and the
  version vocabulary are the same problem seen from two directions.

Until then, a consumer probing for an installed CLI and printing install
instructions on failure is the lower bar and the better one — it needs none of this
and forecloses none of it. See
[composition](../design/layers/repo-aspects/product-cluster/composition.md) for why
consuming a *product* is not a source-plane concern in the first place.

## What to do

1. **Decide the version vocabulary** — how a pinned version is named at all. This is
   the open question in [`repo`](../design/layers/data/repo.md), and it gates
   everything else. It likely means either version-shaped branch purposes, tag
   support, or accepting that concrete pins only ever come from a snapshot.
2. **Make `role` drive ref selection**, so `dep` resolves against a pin or ledger
   rather than falling through to `dev`.
3. **Give `conform` ref intent** — `relayout` currently builds `present-as-is`;
   resolved refs would make it emit `commit`- or `branch-head`-kind
   [layout-targets](../design/layers/data/layout-target.md), which the engines
   already accept.
4. **Land the snapshot store** in the cluster as the `dep` ledger.

## A caution about the primitive

A build wants a **throwaway export at a ref** — no history, no remotes, disposable.
mono-control's primitive is the opposite: a managed worktree off a bare repo, slug-
stamped, capability-profiled, and tracked as workspace state. Placing a repo into
`mono-work` just to build it would pollute the workspace with something no one is
developing, and it would collide with whatever cluster is currently active.

If this work is picked up for the consumer-install case specifically, the right
primitive is probably closer to `git archive` (or a detached export directory
outside `mono-work`) than to `mat` — which is a different feature than the one the
list above describes, and worth deciding deliberately rather than by reflex.

## Related

- [`repo`](../design/layers/data/repo.md) — sources, branch purposes, the open
  pinned-version question.
- [snapshot](../design/layers/data/snapshot.md) — the concrete `{slug → (commit,
  location)}` record.
- [conform](../design/layers/repo-aspects/product-cluster/conform.md) — named states
  and snapshot targets, both draft.
- [composition](../design/layers/repo-aspects/product-cluster/composition.md) — the
  source-plane / artifact-plane boundary this item sits against.
- [distribute-prod-image](distribute-prod-image.md) — the same problem for
  mono-control's own artifact.
