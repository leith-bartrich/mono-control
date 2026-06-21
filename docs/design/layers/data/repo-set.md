# Repo set

A **repo set** is a named subset of the [mono project](mono-project.md)'s
[repos](repo.md) that together form a coherent unit — the repos you'd bring to a
common state to do real development work (build, test, deploy, dev/edit) on some
part of the workspace.

It is the layer between the mono project ("everything") and an individual repo
("one thing"). In Visual Studio terms it sits where a sub-solution or solution
folder would: a grouping that gives a slice of the workspace its own identity,
while the build/product meaning stays out of this layer.

Properties decided so far:

- **Membership is a subset of repos, referenced by slug.** A repo set names which
  repos participate, using each repo's immutable [slug](repo.md) — not its
  mutable display name.
- **It has its own immutable id.** Consistent with repos, a repo set carries a
  stable id, used for tracking (e.g. a [snapshot](snapshot.md) burns in the
  repo-set id it was taken from).
- **Overlap is allowed.** A repo may belong to multiple repo sets, just as a VS
  project can appear in multiple solutions. This is what keeps the top layer
  light while supporting many sets over a shared pool of repos.
- **It is a subclassable base.** `repo_set` is the base kind; specializations
  (for example a `product`, a repo set with product-oriented capabilities) are
  expected. To make that a non-breaking addition later, the model **reserves a
  `kind` discriminator** from the start (default `repo_set`).

The `kind` discriminator is **orthogonal** to the `version` discriminator
described in the [configuration data source](config-source.md): `version`
selects the schema revision of a document, `kind` selects the subtype. A document
can carry both.

## What a repo set *is*: enumerate + validate

At its core a repo set is an **enumerable set of member slugs** that is *resolved
against the current config*. That is the interface — `members()` plus
`validate(config)` — and **both a persisted authored set and a
[snapshot](snapshot.md) projection satisfy it** (a snapshot's member slugs *are* a
repo set's membership). The persisted, authored form is what gets a name, an id,
and a `kind`; the projected form is derived.

`validate(config)` is the one semantic check, and it is purely an **existence
gate**:

- A **retired** member passes — its slug and definition are still present (retire
  is a soft, reversible tombstone precisely so references survive).
- A **purged** member fails — its definition is gone, leaving a dangling
  reference. This is the "we didn't purge something we shouldn't have" check.

That is *all* `validate` asserts. Whether a member can actually be **materialized**
— a source is configured, the source is reachable, a given commit is present — is
a ladder of **per-verb preconditions** defined where each verb lives, not a
property of the set. (Schema validity — does a stored set parse into its model —
is the separate, universal pydantic concern.)

A repo set is also the thing a [target](target.md) references when declaring a
desired state. Concrete fields are still TBD.
