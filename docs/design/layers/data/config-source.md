# Configuration data source

The workspace configuration for `mono-control`, held in the `mono-config` repo.

This document covers the *mechanism* of this source — how configuration is
stored, located, and loaded. It does **not** describe the configuration
abstractions themselves; each abstraction is documented in its own file in this
directory (see [Document map](#document-map)).

## Source of truth: the mono-config repo

The configuration data source is `mono-config`, a separate git repository that
sits alongside `mono-control` and `mono-repos`. `mono-config` is purely data —
it holds configuration and nothing else (no build logic, no knowledge of what
the managed repos contain).

`mono-control` is a **consumer** of this source: it reads `mono-config`, never
authoring it. The dev container bind-mounts the repo so the tooling can see it;
the mount location is recorded as `CONFIG_DIR` in `src/mono_control/paths.py`.

## Mechanism: pydantic models ⇄ JSON

Every configuration abstraction is defined as a [pydantic](https://docs.pydantic.dev/)
model. Its on-disk, persisted form is **JSON**:

- **Schema is the model.** The pydantic model *is* the schema — the source of
  truth for what a valid document looks like. JSON on disk is just its
  serialized representation.
- **Loading is deserialize-and-validate.** `mono-control` reads a JSON file and
  validates it against the corresponding model. Validation is **strict**
  (unknown keys are rejected), so typos and stale fields fail loudly rather than
  being silently ignored.
- **Mostly read, sometimes authored.** The primary flow is JSON → model
  (deserialize-and-validate). Some abstractions are also **authored** by
  mono-control — e.g. [repo](repo.md) definitions written via `mono-control
  repo …` — so model → JSON serialization lives here too for those.

JSON was chosen for zero-dependency parsing (stdlib `json`) and because the
manifest is machine-and-human readable. The validation/typing is what pydantic
provides on top.

## Location: relative to the config repo

Configuration files are located **relative to the root of the `mono-config`
repository**, not by hardcoded absolute paths and not relative to
`mono-control`. The container happens to mount that root at
`/workspaces/mono-config`, but the design contract is "relative to the config
repo root" — the absolute mount point is an implementation detail.

This keeps the source self-contained and portable: the same `mono-config`
checkout resolves identically regardless of where it is mounted.

The source is a **directory**, not a single file. It has a top-level entry point
(`SYSTEM_FILE` in `src/mono_control/paths.py`) and will grow a richer set of
named files — one per abstraction — as the layout is designed. The loader is
directory-oriented from the start.

## Loading and errors

`load_config()` (`src/mono_control/config/loader.py`) is the single entry point.
It takes the config directory (defaulting to the mounted `CONFIG_DIR`, and
overridable so callers and tests can point at any directory), reads the relevant
JSON file(s), and returns validated models.

Failures surface as a typed hierarchy (`src/mono_control/config/errors.py`) so
callers get a clear message instead of a raw traceback:

- `ConfigNotFoundError` — the config directory or a required file is missing.
- `ConfigParseError` — a file exists but is not valid JSON.
- `ConfigValidationError` — JSON parsed but did not match the model.
- `ConfigVersionError` — the document's `version` is missing, unknown, too new,
  or cannot be migrated (see below).
- `ConfigError` — base class for all of the above.

## Versioning and migration

Every document carries an integer `version` discriminator (`{"version": N, …}`).
Each document type declares a `CURRENT_VERSION`; loading is **migrate-up-then-
validate**:

1. Read the raw JSON to a dict and inspect its `version`.
2. Walk it up to `CURRENT_VERSION` by applying an ordered chain of migrations.
3. Validate the result against the (single, current) model.

A few deliberate properties:

- **One current model.** Only the latest shape is modeled. Downstream code always
  sees the current model and never tracks versions — there are no `ThingV1` /
  `ThingV2` types to thread through the codebase.
- **Migrations are pure `dict -> dict` functions**, one per version step (`v` →
  `v + 1`), registered in order. Pydantic validates the final shape and the
  current model pins `version` to a `Literal`, so a migration that produces the
  wrong shape fails loudly rather than passing silently. Pydantic does not write
  the migrations — that transform logic is ours.
- **Unknown / too-new / missing** versions are rejected with `ConfigVersionError`
  rather than guessed at. A file from a *newer* `mono-control` is an error, not a
  down-migration.
- **In-memory only.** Migration upgrades the loaded value; it does not rewrite the
  file on disk. (Explicit write-back may be added later.)
- **Per-document.** Versioning is independent per file/abstraction — each has its
  own `CURRENT_VERSION` and migration chain, not one global workspace version.

The machinery lives in `VersionedModel` (`src/mono_control/base_models.py`);
each document type subclasses it. Migrations are tested from static JSON fixtures
(old document text in, expected current model out).

## Document map

This file is the *how* (the mechanism); the concept files are the *what* (the
abstractions the configuration describes):

- **[README](README.md)** — the data layer overview and its index of sources.
- **This file** — the configuration data source: storage, location, loading.
- **Concept files** — one per abstraction:
  - [mono-project.md](mono-project.md) — the whole workspace.
  - [repo.md](repo.md) — an individual managed repository.
  - [repo-set.md](repo-set.md) — a named subset of repos.
  - [target.md](target.md) — a desired state.
  - [snapshot.md](snapshot.md) — a concrete state.
