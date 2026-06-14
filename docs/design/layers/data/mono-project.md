# Mono project

The **mono project** is the whole workspace mono-control manages — the top-level
container for everything else. It is the analogue of a Visual Studio *Solution*:
a light organizing layer that holds many units and the configurations across
them, without itself being a build artifact.

A mono project is made of:

- **[Repos](repo.md)** — the individual managed repositories (the "projects").
- **[Repo sets](repo-set.md)** — named subsets of those repos that form coherent
  units of work.
- **[Targets](target.md)** and **[snapshots](snapshot.md)** — the desired and
  concrete states the repos are brought to.

The point of keeping this layer light is the same reason a monorepo keeps its
"solution" thin: it should comfortably contain many repos without the top level
itself carrying build or product logic. The mono project says *what belongs* and
*how it is organized*; it does not say what any repo contains or how it builds.

The workspace configuration that describes a mono project lives in the
[configuration data source](config-source.md) (the `mono-config` repo).
