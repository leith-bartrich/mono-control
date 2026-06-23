# Repo aspects

A **repo aspect** is an optional capability or role a [repo](../data/repo.md) can
carry beyond being an opaque managed unit. Aspects **compose** — a repo may have
several — so an aspect is a *trait*, not an exclusive `kind`.

Most managed repos are opaque: mono-control only *versions* them and never looks
inside. An aspect is a declared, **understood** role that lets mono-control do
more with a repo — read structured data from it, materialize it specially, and so
on. The first aspect is the [product cluster](product-cluster.md).

## The contract: declared in config, detailed in the repo

An aspect has a two-layer existence, split between where it's cheap to know and
where the detail lives:

1. **Declaration — in the repo's config definition.** A repo declares the aspects
   it carries in its [repo definition](../data/repo.md) in `mono-config` (the repo
   model gains an `aspects` declaration to hold this). This is a lightweight marker
   plus any minimal parameters — enough to *know the aspect exists without
   materializing the repo*.
2. **Detail — inside the materialized repo.** The aspect's substantive
   configuration lives *inside the repo itself*, available only **after** it is
   checked out. The repo is self-describing for its own details (and may carry a
   sentinel that confirms the aspect).

This split is the whole contract, and it's what makes aspects usable:

- **Discovery from config alone.** Because the declaration is in config,
  mono-control can list the **available** repos carrying a given aspect — an
  authoritative roster — *without checking anything out*. (A repo-internal-only
  marker couldn't do this: you'd have to materialize first to discover it, a
  chicken-and-egg.)
- **Self-contained detail.** Because the detail lives in the repo, the repo is
  portable and owns its own configuration; consuming workspaces don't have to
  encode each repo's internals in their config.

So config answers *"which repos have this aspect, and how do I get them?"*; the
materialized repo answers *"what does this aspect actually contain or do?"*.

## Materialization is per-aspect-type

How a repo is brought to disk — and *where* — depends on the aspect. Each aspect
type defines its own materialization, including a **default subdirectory** under
`mono-repos`. That location is a convention, **not a contract** — nothing
guarantees a repo lives exactly there — so it stays informal and may vary. The
shared git mechanics (clone/checkout with host-correct stamping) come from the
[git layer](../git/README.md); the *policy* of where and how is the aspect's.
(The first: a [product cluster](product-cluster.md) materializes by default under
`mono-repos/products/`.)

## Reference: subdir as a friendly alias

Once materialized, an aspect repo is most naturally referenced by its
**subdirectory location** rather than its slug — that's the intuitive handle for
day-to-day use. But location is **mutable** while the [slug](../data/repo.md) is
the immutable identity, so a subdir is an *alias resolved to a slug* via the
current materialization layout (which slug is checked out where), never a durable
reference. Durable records — e.g. [snapshots](../data/snapshot.md) — stay
slug-keyed.

## Where an aspect's code and commands live

An aspect is **self-contained**: all of its code — model, logic, materialization,
and its CLI/interactive commands — lives in one package:

```
src/mono_control/aspects/<aspect_name>/
```

(`<aspect_name>` is the Python form, e.g. `product_cluster`.) This is *vertical*
organization — everything for one aspect in one place — in contrast to the core's
horizontal split (`config/` vs. `cli/`). An aspect **plugs into** the system
rather than threading through it.

Each aspect contributes a command group named after itself, surfaced through the
shim as:

```
mproj control <aspect-name> <verb> …
```

where `<aspect-name>` is the hyphenated form (e.g. `product-cluster`), so the
product-cluster manager reads `mproj control product-cluster list-available`. The
two-surface [UI convention](../../ui/README.md) still applies (scriptable commands
plus an interactive `manage`), just housed inside the aspect package rather than
the top-level `cli/`.

## Document map
- This file — the aspect contract (declaration vs. detail, discovery,
  per-aspect materialization, code/CLI layout).
- [product-cluster.md](product-cluster.md) — the first aspect.
