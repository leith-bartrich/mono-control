# Mono project

The **mono project** is the whole workspace mono-control manages — the top-level
container for everything else. It is the analogue of a Visual Studio *Solution*: a
light organizing layer, not itself a build artifact.

It has two parts, with two different natures:

- **Config — additive and declarative.** The workspace manifest in the
  [config source](config-source.md) (`mono-config`): the declared [repos](repo.md)
  (the managed pool) and workspace-level settings. You *accumulate* this over time
  and it persists; it says *what belongs* and *how it's organized*. Adding a repo
  is an additive edit to config.
- **Repos — dynamic.** The actual managed repositories. Their on-disk presence is
  not declared-and-fixed but *reconciled*: which repos are materialized, where, and
  at what commit changes over time, brought into line by the
  [layout engine](../layout/README.md). A repo may also carry
  [aspects](../repo-aspects/README.md) — extra roles such as being a
  [product cluster](../repo-aspects/product-cluster.md) — that mono-control
  understands beyond treating the repo as opaque.

So config is the steady, growing statement of *what exists*, and the materialized
repos are the moving picture of *what's checked out right now*.

The point of keeping this layer light is the same reason a monorepo keeps its
"solution" thin: it should comfortably hold many repos without the top level itself
carrying build or product logic. The mono project says what belongs and how it's
organized; it never says what a repo contains or how it builds.
