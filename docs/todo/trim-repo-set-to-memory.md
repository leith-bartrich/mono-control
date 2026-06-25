# Trim the repo-set code to the memory layer

The `repo_set/` package (committed in "Model snapshot + repo-set") includes a
**persisted `RepoSet(VersionedModel)`** with a `product` kind. The design has since
firmed: bare repo-sets are **memory-only** (the `members()` interface), and the
**authored** form is a **product living inside a
[product cluster](../design/layers/repo-aspects/product-cluster.md) repo** — not a
standalone config-bound document. So the persisted model is **orphaned**: unused,
nothing breaks, but it contradicts the docs.

## When

Anytime — it's a safe code↔design cleanup (the persisted `RepoSet` is wired into
nothing, tests pass). Do it **before** designing the product / artifact-configuration
(so the persisted form is reintroduced correctly then, inside the cluster's schema),
and ideally soon, so the code matches
[repo-set.md](../design/layers/data/repo-set.md).

## What

- **`src/mono_control/repo_set/models.py`** — keep `RepoSetLike` (Protocol) and
  `missing_members`; **remove** `RepoSet(VersionedModel)` and `load_repo_set`. Update
  the module docstring (drop "persisted, authored RepoSet").
- **`src/mono_control/repo_set/errors.py`** — `RepoSetValidationError` /
  `RepoSetVersionError` exist only for `load_repo_set`; remove them (and the file, if
  nothing still needs `RepoSetError`).
- **`src/mono_control/repo_set/__init__.py`** — re-export only `RepoSetLike` and
  `missing_members`.
- **`tests/test_repo_set.py`** — drop the persisted-model tests (load round-trip,
  `kind` default, version errors); keep `missing_members`, exercised against a
  `Snapshot` and a trivial `RepoSetLike` stand-in (e.g. a small frozenset-backed
  object).
- **`docs/design/layers/data/repo-set.md`** — trim to the `members()` interface plus
  the `validate` / existence-gate; drop the standalone "persisted authored repo_set /
  kind / product" framing; note the authored form is a product inside a product
  cluster (cross-ref).

## Related
- [data layer README](../design/layers/data/README.md) — where repo-set lives
  (memory + product clusters).
- [product-cluster](../design/layers/repo-aspects/product-cluster.md) — home of the
  authored form.
