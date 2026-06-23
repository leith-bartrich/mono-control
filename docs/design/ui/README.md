# UI & interaction patterns

How mono-control presents itself to users — the conventions every command and
interactive flow should follow, so the surface stays consistent as features land.

## Two surfaces over shared logic

Every capability is offered two ways, and the split is a naming convention inside
the `cli/` package:

- **Pure CLI** — `cli/<name>.py`: scriptable [Typer](https://typer.tiangolo.com/)
  commands (flags, args, exit codes).
- **Interactive** — `cli/<name>_ui.py`: a menu-driven
  [questionary](https://github.com/tmbo/questionary) flow, entered via
  `<group> manage` (needs a TTY).

Both are **thin presentation over the shared mutation logic in the data layer**
(stores, `load_*` / `save_*`) — never duplicating it. The `repo` and `config`
groups are the established reference pair.

## Tooling

- **Typer** — command groups, args, options; compiles to Click (so a group can be
  driven programmatically, as the REPL does).
- **Rich** — a shared `Console`; `Table` for list/status output; markup for color.
- **questionary** — interactive menus, prompts, and confirmations.

## Output conventions

- **Tables** for lists and status (e.g. `slug`, `name`, … columns) via Rich
  `Table`.
- **Status color**: `[green]` ok / created / success, `[yellow]` retired /
  warning, `[red]` error / destructive.
- **Errors**: a typed error (e.g. `ConfigError`, `GitError`) is caught at the
  command boundary and surfaced as `[red]error:[/red] <message>` with a non-zero
  exit (the `_fail` → `typer.Exit(1)` helper). Never leak a raw traceback to the
  user.

## Guarding destructive or risky actions

Friction escalates with danger:

- **Soft + reversible** (e.g. `retire`) — a simple confirm prompt.
- **Hard + irreversible** (e.g. `purge`) — explicit `--yes` *and* re-typing the
  identity to confirm.
- **Footgun inputs** (e.g. a relative `--config-dir`) — reject loudly with a clear
  message rather than silently doing the wrong thing.

## Command naming

Verb-first and consistent across groups: `list`, `show`, `add`, `init`, `rename`,
`retire` / `restore` / `purge`, `manage`, plus capability verbs such as
`materialize`. The interactive entry point is always `manage`.

## Invocation through the host shim

User-facing invocation goes through the host `mproj` shim, which forwards into
mono-control's container. Flags bound for mono-control follow `--`
(e.g. `mproj control -- repo list`). The shim's own command conventions live in
its repo (`mono-control-shim/docs/design/command-conventions.md`).

## Observation (not yet a rule)

- `mono-control repl` runs multiple commands in one container session; its norms
  (history, completion, prompt) are still emerging.
- As richer aspects land (e.g. the
  [product-cluster](../layers/repo-aspects/product-cluster.md) manager), these
  conventions should be extended here rather than reinvented per feature.
