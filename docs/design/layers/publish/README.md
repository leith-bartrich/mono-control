# Publish engine

> **Stub** — a reserved place and purpose, not yet designed.

The **publish engine** is the **outbound** counterpart to the
[source engine](../source/README.md). Where the source engine brings state *in*
(clone / fetch), the publish engine would push mono-control-managed state *out* to
remotes.

It exists only as a deliberate, **explicit** operation — **never** part of
reconcile or acquisition. The [layout](../layout/README.md) and
[source](../source/README.md) engines stay one-directional and never publish on
their own; publishing is always something a user or automation asks for on purpose.

## Likely purpose (vague, TBD)

The clearest candidate is publishing mono-control's **own data-repo state** — for
example, committing and pushing the [snapshots](../data/snapshot.md) and artifact
records that mono-control writes into a
[product cluster](../repo-aspects/product-cluster.md) back to that cluster's remote.
That is publishing *mono-control's data*, which is distinct from pushing a
developer's source work in an opaque managed repo — that remains a **developer / CI**
concern and is **out of scope**.

Whether the publish engine ever touches opaque managed repos, how it handles auth
and partial failures, and what exactly is publishable are all **TBD**. This doc
reserves the name and the boundary so the place and purpose aren't lost.

## Relationships
- **[Source engine](../source/README.md)** — the inbound counterpart.
- **[Layout engine](../layout/README.md)** — local reconcile, no remote I/O.
