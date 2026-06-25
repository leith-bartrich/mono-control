# Repo definition

A **repo definition** is the config-bound data object for a single managed
repository in the [mono project](mono-project.md) — its identity, where to fetch
it, and the roles it carries. It lives in the [config source](config-source.md)
(`mono-config`). It is the analogue of a Visual Studio *Project*, the *abstract*
kind: mono-control governs *which revision of each repo is present*, like a package
manager at the repository level — not a build system.

> This doc is the **definition** (declarative config). It is **not** the on-disk
> checkout — that is the [on-disk repo](on-disk-repo.md), which has a
> location, a commit, and (for aspect repos) readable contents. Same repo, two
> objects.

The definition is deliberately **content-agnostic**: it captures identity, sources,
branches, and aspects — never the repo's language, build system, or toolchain.
"Repo" is chosen over "project" to signal that opacity; a VS project implies a known
build, ours is intentionally generic. (mono-control reading a repo's *contents* is
the exception reserved for [aspect](../repo-aspects/README.md) repos — see the
[on-disk repo](on-disk-repo.md).)

## Identity, name, and source

These are three different things, and keeping them separate is what lets a
[snapshot](snapshot.md) stay valid as the world around a repo changes:

- **Identity — an immutable slug/key.** Set once, never changes. This is the
  durable key everything else references a repo by. It is *not* a description; it
  may drift from the display name over time, and that's fine.
- **Display name — mutable.** A free, human-facing label that can be renamed at
  will without affecting identity or any existing snapshot.
- **Source(s) — mutable named remotes.** A repo can have any number of remotes
  (URLs) — GitHub today, GitLab tomorrow, a local path the next. Following git,
  the source is **not part of the repo**; it's local/workspace metadata on the
  definition, keyed by the slug. Sources are **never serialized into a snapshot**.

This mirrors git's own split — immutable object hashes versus mutable refs and
remotes — with one deliberate choice: we use a **human-readable slug** as the
immutable key rather than an opaque hash, trading a little drift-from-name for
legible snapshots and config.

Both **sources** and **branches** are stored as *named maps* (`name → url` and
`name → branch`). The conventions for what a given name *means* — which source is
the default, which branch is `main` versus `dev` — are deferred; the model just
holds the maps.

## Aspects

A definition may declare one or more [aspects](../repo-aspects/README.md) — extra
roles a repo carries, such as being a
[product cluster](../repo-aspects/product-cluster.md). The *declaration* lives here
in config, so an aspect is discoverable without checking the repo out; the aspect's
*detailed* data lives inside the [on-disk repo](on-disk-repo.md). Aspects
**compose** — a repo may carry several.

## Storage and lifecycle

Each definition is one JSON file at `mono-config/repos/<slug>.json` — the directory
*is* the registry (adding a file adds a repo), and the filename is the slug,
cross-checked against the in-file `slug`. mono-control **authors** these files (via
`mono-control repo …` and the interactive `repo manage` UI); this is the first
place the tool writes config rather than only reading it.

Deletion is two-tiered, because a [snapshot](snapshot.md) may reference a repo by
slug:

- **Retire** (soft, default) — a tombstone flag; the slug stays reserved and the
  change is reversible. Retired repos are hidden from normal listings.
- **Purge** (hard, heavily guarded) — physically removes the definition. The
  guarded path that makes true deletion possible without making it easy.

Repo definitions are referenced by **slug** — the members of
[repo sets](repo-set.md), the things a [layout-target](layout-target.md) pins to a
desired ref, and a [snapshot](snapshot.md) records at an exact commit. The slug also
keys the repo's [on-disk](on-disk-repo.md) checkout.
