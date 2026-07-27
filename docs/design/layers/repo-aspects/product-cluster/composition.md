# Composition — more than one cluster at a time

> **Status.** The model below is implemented: `requires` on the layout (v2), the
> closure, the merge, and `conform relayout` / `swap` reconciling over the union.
> Still deferred: `conform add` / `conform drop`, `--prefer` for location conflicts,
> and authoring `requires` through the `layout` verbs (edit the document directly for
> now). Snapshots do not yet capture an active *set* — see
> [consequences](#consequences-to-carry-into-deferred-designs).

A [product cluster](README.md) expresses **one** arrangement, and for a long time
one arrangement per workspace was the whole story. Two questions break that:

- A **library-shaped cluster** — one whose product is a library rather than an
  application — that several unrelated clusters want as a dependency.
- A **consumer** that wants another cluster's *product* rather than its *source*.

They have different answers. The second one isn't a layout question at all.

## The two planes

mono-control governs the **source plane**: which revision of which repo is present
on disk. A cluster's *products* — an installed CLI, a container image, a published
package — live on the **artifact plane**, which mono-control deliberately knows
nothing about ("it does not build anything and does not know or care what's inside
the repos it manages").

So: **a cluster's products are never another cluster's members.** A product
consumed as a built artifact is obtained the way any tool is obtained — installed,
found on `PATH`, invoked across a process boundary — and appears in no layout. That
holds whether the artifact is a CLI today or a local RPC service later; both are
process boundaries, and a service is if anything *more* clearly a deployed thing.

Composition, below, is only about the source plane: several clusters that genuinely
need source co-present.

## Co-activation, not composition

A cluster does **not** include another cluster. Instead:

> The workspace holds a **set of active clusters**, and a layout may declare
> `requires: [<cluster-slug>]` — a statement of **co-activation** that carries no
> location, no ref, and imports no members.

The required cluster owns its own arrangement; the requirer never restates it.
This is the whole of the relationship — deliberately much weaker than inclusion.

[`conform relayout`](conform.md) then reconciles over the **union** of the active
clusters rather than over one. The active set needs no new persisted state: it is
the set of *materialized* clusters read from disk, which `product-cluster current`
already computes for the sole-cluster case. `swap` keeps its meaning — "make this
the only one" — and gains peers in `conform add` / `conform drop`.

### Why not inclusion

An `includes` that pulled in the required cluster's *members* would make
mono-control a dependency resolver: transitive closure over members, diamonds,
conflicting locations, and a version-solving problem it has no model for. Worse, it
would make the source graph mirror the artifact graph — every developer of a
consumer would materialize a dependency's full source for something they only ever
invoke as a built artifact.

It also breaks the framing: a cluster is the analogue of a Visual Studio
**solution**, and solutions contain projects, not other solutions.

## Evaluation is unordered

The active set is a **transitive closure** from the named roots, computed with a
visited set — not an ordered fold. This is a deliberate choice, and it is what
makes the rest of the model simple.

**Precedence would require a root, and co-activation is symmetric.** A requiring a
B does not make A superior to B in any sense this model defines. So any evaluation
order would have to be derived from something arbitrary — which cluster was named
on the command line, or a tiebreak on slug — and the resulting workspace state
would depend on **invocation history rather than on committed documents**. That
contradicts the reproducibility anchor the [dirty-cluster gate](conform.md#the-dirty-cluster-gate)
exists to protect. Ordered evaluation is inclusion smuggled back in through
precedence.

### Cycles are therefore harmless

Under closure semantics an `A → B → C → A` cycle simply means those three are
always co-active. That is a meaningful answer, not a failure, and the visited set
terminates the traversal.

`layout validate` should still **report** a cycle: mutual requirement means neither
cluster can activate alone, which suggests they are really one cluster. It is a
design smell worth surfacing, not an error worth refusing.

### Acquire order is not evaluation order

Closure needs each required cluster checked out before its layout can be read, so
the resolver iterates acquire → read → expand to a fixpoint. That is a *fetch*
sequence, not a precedence one. An unreachable required cluster fails **early**,
before anything is touched — the same fail-early posture `swap` already takes by
acquiring its target up front.

## The merge

Members are keyed by [slug](../../data/repo.md), so a slug named by two active
clusters must resolve to **one** materialization. Commutativity is what makes order
irrelevant and cycles safe, so every rule below preserves it.

| Field | Rule |
| --- | --- |
| `location` | must be **equal** — one worktree, one place, and no principled winner otherwise |
| `role` | a **join**: `dev ⊔ dep = dev` |
| ref / pin *(once refs exist)* | must be **equal**; moot for any member whose joined role is `dev` |

This is *fail on unsatisfiable*, not *fail on any overlap*. A shared member is the
normal case and should be silent.

**The role join is the one collision with a principled answer.** If any active
cluster develops L, L materializes as `dev` and the co-active consumers get the
development copy — which is the entire point of having them co-active. Join is
commutative and associative, so it introduces no ordering. Every other field has
two candidates and no reason to prefer either, so it refuses.

A `dev` join must be **reported loudly**: a consumer's declared pin is being set
aside in favour of a floating branch head, and that is exactly the kind of thing
that is obvious while you are doing it and baffling a week later.

Conflicts name both clusters and the field. The escape hatch, if one is wanted, is
a per-invocation `--prefer <pc>` — never derived, never persisted, the same posture
as `--allow-dirty`.

## Git already encodes the dev/dep distinction

"[One materialization per repo](../../layout/README.md)" is a mono-control policy,
not a git limitation: one bare repo natively backs many worktrees. But git does
impose one rule, and it is the right one — **the same branch cannot be checked out
in two worktrees**, while detached HEADs at one commit are fine.

That maps exactly onto the roles:

- **`dep`** — pinned, detached → shareable across co-active clusters.
- **`dev`** — a living branch head → inherently exclusive, enforced by git itself
  rather than by anything mono-control has to check.

Which is not a coincidence. It is the same distinction seen from the filesystem.

## `dep` means source you read, not an artifact you consume

Worth stating plainly, because the word invites the other reading. A `dep` member
is a repo whose **source** you want present but do not author. It is not a
declaration that anything builds against it.

The live `pc-ltx2` layout in the fiemono-ltx2 workspace is the proof: it places
`ltx2-61df` at `mono-work/ltx-2` from `Lightricks/LTX-2`, while
the member that consumes LTX-2 fetches `leith-bartrich/LTX-2 @ fie-main` from git in
its own lockfile. The placed source and the consumed dependency are not even the
same repository. The worktree is a reading room.

The corollary matters for everything above: **the benefit of co-materializing a
library — edit once, every consumer sees it — is not real in any cluster today.**
The `dev ⊔ dep = dev` join is correct by design but inert until a member's build
actually references the placed worktree. See [layout](layout.md#location-is-a-build-interface-contract)
for why mono-control cannot close that gap itself.

## Consequences to carry into deferred designs

- **[Snapshots](../../data/snapshot.md)** must capture the active *set*, not one
  cluster, or a multi-cluster workspace is not reconstructible. And a snapshot taken
  while a `dev` join is in effect is not reproducible from the layouts alone — the
  pin that lost is not recorded anywhere.
- **The [dirty-cluster gate](conform.md#the-dirty-cluster-gate)** multiplies across
  active clusters: any of them being dirty blocks a reconcile that would retire it.
- **The [implied cluster](conform.md#the-implied-cluster)** already errors when more
  than one is materialized and asks you to name one. That rule survives unchanged —
  it just stops being a rare case.
- **"A cluster expresses one arrangement"** weakens to "one *contribution* to an
  arrangement." That is a real concession to the solution analogy and should be made
  knowingly.

## Rejected

- **Nested sub-clusters** (`includes` importing members) — see
  [above](#why-not-inclusion).
- **Ordered evaluation with precedence rules** — presupposes a root the model does
  not have; makes workspace state depend on invocation history.
- **Per-cluster subtrees with duplicated worktrees.** Coherent: make `location`
  cluster-relative, give each cluster its own copy off the shared bare repo, and no
  conflict can ever arise. Rejected because edits stop propagating — which defeats
  the only reason to co-activate — and because a shared `dev` member becomes
  impossible (two worktrees cannot hold one branch).

## Activating a required cluster is an intent question

A required cluster is always **acquired** — a bare clone is free, and doing it here
means an unreachable remote fails before anything moves. Whether its *worktree* is
then placed is a different matter: it is a statement of intent, and intent is
expressed differently by different surfaces. So the logic layer supports both
behaviors and the surfaces decide, per the
[two-surface convention](../../../ui/README.md):

| Surface | How intent is expressed |
| --- | --- |
| `actions.relayout` / `swap` | an `on_missing_required` callback; absent ⇒ refuse |
| scriptable CLI | `--activate-required` |
| interactive manager | *"cluster(s) X are required but not placed — place them too?"* |

Refusing by default is what keeps `requires` from quietly behaving like inclusion:
naming one cluster never silently materializes another's whole arrangement. The
steady-state case stays quiet, since a required cluster that is already placed
prompts nothing.

This mirrors the [dirty-cluster gate](conform.md#the-dirty-cluster-gate) exactly —
one gate in the logic, `--allow-dirty` on the CLI, a prompt in the manager — which is
the same reason both exist: the decision is the user's, not the engine's.

## Open questions

- **Whether `requires` belongs in the layout at all.** It is a statement about the
  *workspace*, not about an arrangement of members, so it may want its own document
  under `product-cluster/` rather than a field on
  [`default-layout.json`](layout.md).
- **Retiring a shared member.** When one of two clusters naming L is dropped, L
  should survive; the exclusive-reconcile logic currently has no notion of a member
  still being claimed elsewhere.
