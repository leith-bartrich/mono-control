# `repo list` should show declared aspects

The current `mono-control repo list` table renders columns
`slug | name | sources | branches | retired`, but **not** `aspects`. That
makes the aspect declaration — the cheap discovery half of the
[aspect contract](../design/layers/repo-aspects/README.md) — invisible at
the top-level listing. Users learn which repos carry which aspects either by
running aspect-specific verbs (e.g. `product-cluster list-available`) or by
opening `repo show`. Neither is a problem yet because there is one aspect
and most workspaces are tiny; both will be once a second aspect ships.

## When to do this

Pick this up when **any** of the following becomes true:

- A second aspect lands (today only `product-cluster` exists; with one
  aspect the field is rarely surprising). Once two or more aspects are
  declarable, scanning the workspace's mix needs a single view.
- A user asks "which repos have aspect X" outside the context of an
  aspect-specific verb (i.e. they want it from `repo list`).
- The `aspects` field gains parameters beyond the name (currently it is a
  bare `set[str]`); at that point the existence of an aspect on a repo
  matters more, and hiding it in `repo show` becomes annoying.

Until then this is cosmetic and the table is already at five columns —
adding a sixth that is empty for every repo would be friction.

## What to do

1. **Add a column.** In `list_repos` in
   [src/mono_control/cli/repo.py](../../src/mono_control/cli/repo.py), add
   an `aspects` column to the Rich table. Render it as a comma-joined
   sorted list (`"product-cluster, tool-suite"`) or an empty cell when
   `repo.aspects` is empty.
2. **Consider a filter.** Add `--aspect <name>` to `repo list` so
   `repo list --aspect product-cluster` shows only the marked repos. This
   is the generic counterpart to `product-cluster list-available` — useful
   once there are several aspects. Skip if the per-aspect command stays
   clearer.
3. **Don't add it to `repo show` separately** — `repo show` already lists
   `sources` and `branches`; mirror that for `aspects`, also sorted.
   (Cheap, do it in the same pass.)
4. **Tests.** Extend `tests/test_repo_cli.py` to assert the new column
   renders and (if added) that `--aspect` filters correctly.

## Related

- Repo def: [src/mono_control/config/models.py](../../src/mono_control/config/models.py)
  (the `aspects: set[str]` field on `Repo`).
- Aspect discovery helper:
  [`discover_repos`](../../src/mono_control/aspects/registry.py) — already
  filters by aspect; the `--aspect` flag can call it directly.
