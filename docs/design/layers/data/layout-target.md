# Layout-target

A **layout-target** is the [layout engine](../layout/README.md)'s input: a *desired
local layout* — the declarative intent for a [repo set](repo-set.md)'s
[repos](repo.md), where you want them to be. The engine observes the current state
and reconciles toward it. (It's named `layout-target` rather than just "target"
because it is specifically the *layout* engine's target; other engines have their
own inputs — e.g. the [source engine](../source/README.md)'s *source request* — so
"target" isn't monopolized.) In Visual Studio terms it is closest to a *Solution
Configuration*.

## Shape

A layout-target has two parts:

- **`pre_clear`** — a boolean. When **false** the target is *additive*: ensure the
  named repos reach their desired state, leave everything else alone. When **true**
  it is *exclusive*: the workspace should end up **exactly** these repos — every
  materialized repo *not* named is implicitly reconciled to *absent* (pruned).
  Unsafe removals (a dirty tree) are **blocked**, never forced. So one flag spans
  "just update what's changed" and "deterministically put the whole system into
  this state."
- **A map of `slug → desired state`** — the member repos by immutable
  [slug](repo.md), each with a **discriminated desired state**. The `kind`
  discriminator (cf. [repo-set](repo-set.md)) leaves room for state types we don't
  model yet. The kinds today:
  - **commit** — present at a location, pinned to a precise commit;
  - **branch-head** — present at a location, tracking the HEAD of a named branch
    (its latest, resolved at execution) — the "latest, loose" day-to-day intent;
  - **present-as-is** — present at a location, **no opinion on the current
    ref**: the engine will place/move but never check out (placement-only — the
    common manual-mat case);
  - **absent** — the repo should not be materialized.

  Each *present* kind names a desired **location** (a subdir under
  `mono-repos`, defaultable by convention/aspect). Placement and ref intent
  are *orthogonal* axes; `present-as-is` expresses one (placement),
  `commit`/`branch-head` express both. The CLI's intent verbs
  (`mat moveto` / `mat branchat` / `mat commit` / `mat layout-target`)
  reflect this split.

There is no separate "default branch" kind: "head of the default branch" is just a
`branch-head` whose name the **command** fills in (reading the repo's
[branch convention](repo.md)) when the user doesn't specify one. The smarts of
*which* branch live at construction; the engine only ever sees `branch-head(name)`.

These desired states are deliberately **high-level intent**; turning `branch-head`
into a concrete commit (resolve the branch, take its HEAD) is the
[layout engine](../layout/README.md)'s job — git wants specifics, the layout-target
speaks intent.

**Source-free, like a [snapshot](snapshot.md).** A layout-target names *what state*,
never *where to fetch from*: the source is resolved from the current
[repo def](repo.md), not pinned here. That keeps layout-target↔snapshot symmetric
and a layout-target valid as remotes change. (Fetching from those sources is the
[source engine](../source/README.md)'s job, driven by a separate *source request*.)

A **swap or relocation** (a different repo in a slot, or a repo moved to a new
location) is expressible, but is **runtime-gated**: the engine treats it as a
per-repo precondition when the action runs (see [one materialization per
repo](../layout/README.md)), not something the layout-target alone guarantees.

## Memory-only: constructed, never stored

A layout-target is **built in memory and never serialized** — the inverse of a
[snapshot](snapshot.md), which is the concept that persists. It is constructed from
one of:

- a **[snapshot](snapshot.md)** — "put the workspace back to exactly that state"
  (its `{slug → (commit, location)}` becomes precise desired state);
- a **development intent** — "work on repo set X at latest" — for example a named
  *artifact configuration* inside a
  [product cluster](../repo-aspects/product-cluster.md);
- or **ad-hoc** — a CLI verb constructing a one-off target (e.g. materialize or
  dematerialize a repo).

The [layout engine](../layout/README.md) consumes the layout-target and reconciles
to it; the durable record of what actually resulted is a [snapshot](snapshot.md).
Concrete fields are still TBD.
