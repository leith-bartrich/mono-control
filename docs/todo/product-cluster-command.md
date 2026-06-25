# Product-cluster aspect command

The first user-facing aspect manager — `mproj control product-cluster …` —
shelved until the engine + target abstraction lands, because its verbs are really
**targets the engine executes** and their checks are the engine's job.

## When

Pick this up once the **[layout](../design/layers/layout/README.md)** +
**[source](../design/layers/source/README.md)** engines and
**[layout-target](../design/layers/data/layout-target.md)** are built (the reconcile machinery
that observes current state and executes a desired state, failing carefully). At
that point the verbs below become thin **target-constructors**, and the per-verb
checks become the engine's pre-emption logic rather than hand-coded guards.

## What

Build the `product-cluster` aspect as a self-contained vertical package
`src/mono_control/aspects/product_cluster/` (manager / cli / ui / errors), per
[repo-aspects](../design/layers/repo-aspects/README.md). Supporting changes:

- `config/models.py`: add `aspects: set[str] = set()` to `Repo` (backward-compatible
  defaulted field; canonical aspect string `"product-cluster"`).
- `git/repo.py`: `GitRepo.is_dirty()` for the layout engine's observe / dirty-blocked
  checks (likely already added when the engine's observe phase needs it).
- `cli/app.py`: register `app.add_typer(product_cluster_app, name="product-cluster")`.

Verbs (each expressed as an engine target / pre-emption, not hand-coded checks):

- **list-available** — repos declaring the aspect, from config (no checkout);
  annotate *materialized?* + location.
- **mark** — add the aspect to an existing repo def.
- **init** — new cluster: write the repo def (with aspect), source-engine **init**
  into offline, then layout-engine **place** at `mono-repos/products/<name>`.
- **mat** — get a declared cluster placed at `products/<name>`: source acquires it
  (clone) into offline if absent, layout places it. Source resolution: 0 → error,
  1 → use, >1 → `--source`.
- **demat** — layout-engine **retire** (`products/<name>` → offline); non-destructive,
  not a delete.
- interactive **manage** (questionary), mirroring `cli/repo_ui.py`.

`<name>` is the friendly slug derivation (strip trailing uniqueness/hash segment;
rule TBD).

## Related
- [repo-aspects](../design/layers/repo-aspects/README.md) — the aspect contract and
  the [product-cluster](../design/layers/repo-aspects/product-cluster.md) aspect.
- [layout](../design/layers/layout/README.md) + [source](../design/layers/source/README.md)
  engines — the reconcile machinery these verbs target.
