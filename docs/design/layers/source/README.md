# Source engine

The **source engine** brings repos into **local availability** so the
[layout engine](../layout/README.md) has something to arrange. It is the only engine
that **creates** a repo — `absent → offline` by **clone `--bare`** (from a remote
source) or **init `--bare`** (a brand-new repo with no remote yet) — and the only one
that touches the **network** (clone/fetch, operating a repo's named
[sources](../data/repo.md)). Created bare repos always land in
`mono-repos-bare/<slug>` (offline: a bare repo with no worktree).

## Input: a source request (not a target)

The source engine's input is **not** a [layout-target](../data/layout-target.md). A
target is a *convergent desired state* ("make the workspace exactly this", with
`pre_clear` pruning). What the source engine is asked to do is **additive**: *ensure
these repos and refs are available locally.* There's no exclusivity and no
"un-acquire" — acquisition only ever adds availability. So its input is a **source
request**: per repo, the **refs that must be locally present**.

A source request is typically **derived from a layout-target** — its
`branch-head` / `commit` desired states imply which refs each repo needs — but it is
its own, simpler thing (a flat "make available" list), not a state to converge to.

## What it does, per repo

Additively and idempotently — re-running is always safe:

1. **Resolve the source and the ref.** The *remote* comes from the repo's governed
   [sources](../data/repo.md#sources) — the canonical (`origin` if it's ours, else
   `upstream`), or our writable `fork-ours` where our own work is involved. The *ref* is
   the repo's **`dev`** line ([its `dev` branch](../data/repo.md#branches) — the remote's
   default branch unless overridden). For now `dev` is the **only** ref the engine
   resolves; **failing to resolve or check out `dev` is an error**, never a silent
   fallback.
2. **absent locally → create** into `mono-repos-bare/<slug>` — **clone `--bare`** the
   source with its default set to **`dev`**, or **init `--bare`** a brand-new repo with
   no remote (where the stamps are applied — see below). No worktree exists yet; the
   [layout engine](../layout/README.md)'s `worktree add` produces the `dev` checkout at
   placement.
3. **Conform the remotes** to the repo's declared [sources](../data/repo.md#sources) —
   a remote per source under its governed name, plus `origin` aliasing the default, each
   with the remote-tracking refspec. Done on *both* the create and already-present paths,
   so it is self-healing: a definition edited since the last run is applied on the next
   operation.
4. **Fetch `origin`** to refresh the requested refs. This runs after a fresh clone too —
   `clone --bare` creates no remote-tracking refs, so fetching gives an acquired repo the
   same ref layout however it got here, and it is nearly free when the objects have just
   arrived.
5. **Verify** the requested refs now exist; a missing source or ref fails *that
   repo* — reported, **per-repo independent**, never half-failing the whole request.

A fetch updates `refs/remotes/<name>/*` and never `refs/heads/*` — local branches are the
developer's, and divergence surfaces as ahead/behind rather than being silently resolved.
Advancing a local branch is **not** something the source engine does; see
[conform](../repo-aspects/product-cluster/conform.md) for where that question lives.

It only ever *adds* availability — create (clone/init) or refresh (fetch). It never
**mats (places)** or **demats (retires)** a checkout — that's the
[layout engine](../layout/README.md)'s job — and never pushes (the
[publish engine](../publish/README.md)'s). Output: the requested repos + refs are
present in offline (and any already-materialized checkouts have been fetched), ready
for the layout engine.

## Scope: inbound only

**Clone and fetch (pulls) only — no push, no publish:**

- Publishing local work is a **developer / CI** concern, done with their own git, not
  a workspace-state operation. A state manager pushing on your behalf would be
  surprising and risky.
- The bare repo already removes the only internal reason to push (unpushed commits
  survive removal in the bare repo — see the layout engine's non-destructive retire).

Pushing state out is the [publish engine](../publish/README.md)'s reserved territory
— a separate, explicit operation, never part of acquisition. Keeping this engine
one-directional avoids the sprawl of a bidirectional sync.

## Stamping lives here

Because **clone** (and init) is the source engine's job, two stamps into the new
bare repo's config are applied *here*, not by the
[layout engine](../layout/README.md) (which only adds/removes/checks-out worktrees
off already-stamped bare repos):

- the host filesystem **FS-capability profile** (see
  [host-platform](../../host-platform.md)), so later git behaves consistently; and
- the repo's **identity** — its slug, written as `mono-control.slug` — so the
  checkout is self-identifying and reverse-lookup (location → slug) needs no external
  index (see [on-disk repo](../data/on-disk-repo.md)).

## Orchestration

A high-level command runs the source engine **first** (fulfill the source request —
make the [layout-target](../data/layout-target.md)'s repos and needed refs local),
then the [layout engine](../layout/README.md) (arrange the local layout). The
layout-target is the shared origin: the source engine derives *what to acquire* from
it, the layout engine reconciles *how to arrange* against it.

Source resolution follows the governed [sources](../data/repo.md#sources) vocabulary, and
the ref is always [`dev`](../data/repo.md#branches) (above). (The current implementation
resolves the **first-declared** source entry; the [fork transition](../data/repo.md#sources)
deliberately appends `fork-ours` *after* the canonical so acquisition is unchanged, and
conforming a checkout's declared named remotes into `.git/config` — beyond the eager
stamp done at transition time — is engine work, TBD.) Leaving every bare repo
defaulted **to `dev`** hands the [layout engine](../layout/README.md) a clean,
correctly-reffed repo to simply *place* (its `worktree add` checks out `dev`) —
placement-only. More opinionated ref work (advancing to a pinned
commit, pulls) is a **later layer that runs after the layout engine**, not part of
acquisition. Fetch policy remains **TBD**. Acquisition is a broker effect: the clone
/ fetch runs host-side, so it uses the host's own git credentials and no token ever
enters the container.
