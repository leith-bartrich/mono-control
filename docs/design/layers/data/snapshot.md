# Snapshot

A **snapshot** is a *concrete state*: the exact, reproducible resolution of a set
of [repos](repo.md) — each repo captured at both a specific **version and
location** — plus provenance (when and how it was produced). Where a
[target](target.md) says "where I want to be" (and may be loose), a snapshot
records "exactly where things are/were," and is always precise.

A snapshot may arise two ways, with the same shape either way:

- **Authored** — a hand- or tool-written pin committed for reproducibility (e.g.
  a release pinned to specific commits/tags).
- **Captured** — the resolved state a particular build or dev process actually
  ran against, recorded after the fact.

## What a snapshot references

Each entry is keyed by a repo's immutable **[slug](repo.md)** and captures two
things:

- **version** — the exact commit.
- **location** — the subdirectory the repo is checked out at, **relative to the
  `mono-repos` dir**.

It is deliberately **source-free**: a remote URL is mutable and not part of a
repo, so it is never stored here. Resolving *where to fetch* a slug from is the
job of the current repo definitions, not the snapshot.

A snapshot is **self-contained** — it embeds `{slug → (commit, location)}`, the
authoritative thing it executes against, and a [repo set](repo-set.md) can be
**projected** straight out of its member slugs. It *also* burns in the
originating **repo-set id** for tracking — non-authoritative provenance, not what
it executes against.

## Usability is a passthrough to the repo set

A snapshot is **self-contained data**: it always deserializes and always projects
a [repo set](repo-set.md) (its member slugs). So the only intrinsic question about
a snapshot is **schema validity** — does the JSON parse into the model — which is
universal (pydantic) and carries no snapshot-specific meaning.

A snapshot therefore has **no valid/invalid distinction of its own**. Whether it
is *usable* is two separate questions, neither owned by the snapshot:

- **Does its repo set still hold against current config?** Project the repo set
  and call its `validate(config)` — every member slug must still exist as a
  [repo](repo.md) definition. A **retired** member passes (its slug and definition
  are still present); only a **purged** member fails. This "we didn't purge
  something we shouldn't have" check lives on the [repo set](repo-set.md); the
  snapshot at most *delegates* to it.
- **Can each repo actually be materialized?** This is not one property but a
  **ladder of action-dependent preconditions** — a source is configured for the
  slug, the source is reachable, the required commit is present there — each rung
  more expensive than the last. Which rungs matter depends on the *verb*
  (`materialize` needs all of them; reading a local checkout needs none), so they
  are defined where each verb lives, not as a single property on the snapshot. A
  repo **swap or relocation** is allowed and lands among these per-verb checks.

## Observation (not yet a rule)

The snapshot is the concept that **gets serialized** — the durable, on-disk form
of workspace state. A [target](target.md) can be **constructed from** a snapshot
(to return the workspace to that exact state). This is the inverse of the usual
intuition: the concrete thing is what persists, while the desired thing (target)
may live only in memory.

It is a JSON-serializable model that mono-control constructs and passes to
machinery. **Where a snapshot lives is still undecided** — whether it is stored
in the [configuration data source](config-source.md), produced as an output
elsewhere, or both. Concrete fields are also still TBD.
