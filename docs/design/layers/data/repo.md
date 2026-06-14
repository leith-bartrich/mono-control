# Repo

A **repo** is a single managed repository within the [mono project](mono-project.md)
— the concrete unit mono-control governs. It is the analogue of a Visual Studio
*Project*, specifically the *abstract* kind: mono-control treats a repo as an
**opaque, versioned unit** and never looks inside it.

What that opacity means:

- mono-control knows a repo's identity, where to fetch it, and which ref it
  should be at.
- It does **not** know or care about the repo's language, build system, dev
  container, or toolchain. Those belong to the repo itself.

This is the core boundary from the project README: mono-control governs *which
revision of each repo is present*, like a package manager operating at the
repository level — not a build system. "Repo" is deliberately chosen over
"project" to signal that opacity; a VS project implies a known language/build,
whereas ours is intentionally generic.

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
  repo definition, keyed by the slug. Sources are **never serialized into a
  snapshot**.

This mirrors git's own split — immutable object hashes versus mutable refs and
remotes — with one deliberate choice: we use a **human-readable slug** as the
immutable key rather than an opaque hash, trading a little drift-from-name for
legible snapshots and config.

Repos are the members of [repo sets](repo-set.md), and the things a
[target](target.md) pins to a desired ref and a [snapshot](snapshot.md) records
at an exact commit.
