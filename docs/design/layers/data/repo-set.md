# Repo set

A **repo set** is an enumerable set of [repo](repo.md) slugs that together form a
coherent unit — the repos you'd bring to a common state to do real work on some
slice of the workspace. It is the layer between the [mono project](mono-project.md)
("everything") and an individual repo ("one thing") — the Visual Studio
solution-folder spot.

## Just an interface (memory-only)

A bare repo set is **not a persisted, authored document of its own** — it is the
in-memory **`members()` interface** (`RepoSetLike`). It comes into existence by
*projection* from something else that already carries a membership:

- a **[snapshot](snapshot.md)** — its `{slug → …}` is a repo set's membership;
- a **product** — the authored, named set housed *inside* a
  [product cluster](../repo-aspects/product-cluster/README.md), with build/artifact
  meaning attached (the persisted form of "a named subset of repos that matter").

So the authored form lives in a product-cluster repo (under that aspect's schema —
TBD), not in `mono-config` as a standalone document. The bare repo set is the
shared, in-memory currency both implementers (snapshot, product) expose.

Membership is **by slug** (the repo's immutable identity); **overlap is allowed** —
the same repo may belong to multiple sets — which keeps the top layer light.

## The one semantic check: existence against config

`validate(config)` is purely an **existence gate** against the current repo defs:

- A **retired** member passes — its slug and definition are still present (retire
  is a soft, reversible tombstone precisely so references survive).
- A **purged** member fails — its definition is gone, leaving a dangling
  reference. This is the "we didn't purge something we shouldn't have" check.

That is *all* `validate` asserts. Whether a member can actually be **materialized**
— a source is configured, the source is reachable, a given commit is present — is
a ladder of **per-verb preconditions** defined where each verb lives, not a
property of the set. (Schema validity — does a stored set parse into its model — is
the separate, universal pydantic concern that applies wherever the set is housed,
e.g. inside a product cluster.)

A repo set is what a [layout-target](layout-target.md) references when declaring a
desired state.
