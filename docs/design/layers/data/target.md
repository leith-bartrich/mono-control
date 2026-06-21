# Target

A **target** is a *desired state*: the declarative intent for a
[repo set](repo-set.md)'s [repos](repo.md) — where you want them to be. It is the
thing handed to the machinery that brings the workspace into that state. In
Visual Studio terms it is closest to a *Solution Configuration*: a named
selection that, per repo, says which ref to be at, with a git ref standing in for
"(configuration, platform)."

A target references a repo set and carries, per member repo, a **desired ref
spec**, which may be:

- **Loose** — e.g. "the HEAD of each repo's default branch" (resolves
  differently over time; day-to-day development).
- **Precise** — a specific branch, tag, or commit.

A target may also imply a **repo swap or relocation** (a different repo filling a
slot, or a repo moving to a new checkout location). That is presumed possible,
but is **runtime-gated for safety** — it is a per-verb materialization
precondition, checked when the swap is actually performed, rather than something
the target alone can guarantee.

## Observation (not yet a rule)

A target may be **constructed in memory** rather than authored and stored. It can
be built from a [snapshot](snapshot.md) ("put the workspace back to exactly that
state") or from a *development intent* ("I want to work on repo set X at latest").
That suggests a target might **never be serialized** — unlike a snapshot, which is
the concept that gets persisted.

This also hints at a possible future concept, **development intent**, as one
source a target is constructed from. It is noted here only as an observation; it
is not yet its own abstraction, and this directionality is not yet a rule.

Separately: just as a [snapshot](snapshot.md) captures both version *and*
location, a target's desired state *could* express a desired location too, not
only a desired version. Also an observation, not a rule.

Concrete fields are still TBD.
