# GitHub authentication

mono-control clones and fetches the repos it manages. When a remote is private —
as `mono-config`'s own `sources` entries usually are — git needs a credential. The
container has none, and cannot get one.

This document covers how a GitHub credential is **supplied** to the container, why
it takes the shape it does, and what the resulting exposure actually is. It does
*not* cover the git commands that consume it; that is the
[git operations layer](layers/git/README.md).

## Why it must be supplied, not obtained

The same reason as the [host platform](host-platform.md): the container cannot
know. A host credential lives in an OS keyring — Windows Credential Manager,
macOS Keychain, `gh`'s keyring — and a Linux container cannot reach any of them.
Mounting the host's `~/.gitconfig` does not help either: on Windows it merely names
`credential.helper=manager`, a helper that does not exist in the container.

So the credential must be **handed in**, per invocation, by the one component that
sits on the host: the [shim](https://github.com/leith-bartrich/mono-control-shim).

## The declaration: `MONO_CONTROL_GITHUB_TOKEN`

A GitHub token, supplied in the environment. The shim resolves it host-side (a
scoped PAT if you have configured one, otherwise `gh auth token`) and injects it.

Absent is **not** an error. Public remotes need no credential, and most of
mono-control needs no network at all. A private remote without a token fails at the
point of use, loudly — see *Failure is loud* below.

## A third injected variable — and the only *secret* one

This is the third variable the container is told about, and it differs from both
predecessors in the way that matters most: it is a **secret**.

| | `MONO_CONTROL_IN_CONTAINER` | `MONO_CONTROL_HOST_PLATFORM` | `MONO_CONTROL_GITHUB_TOKEN` |
|---|---|---|---|
| Question | "am I inside the container?" | "what host filesystem is this?" | "who am I to GitHub?" |
| Value | **constant** (`1`) | **variable**, small known set | **secret**, opaque |
| Baked in image | **never** (must be absent on the host) | yes — `generic` default | **never** (it is a secret) |
| Absent means | refuse to run | assume `generic` | no credential; public remotes still work |
| Security meaning | the host-isolation gate | none | **yes — it is the credential** |

Note the two "never baked" cells are never-baked for *opposite* reasons. The
container sentinel must be absent on the host so host-copied code refuses to run.
The token must be absent from the *image* so it is not committed into a layer that
could be pushed, shared, or inspected. Do not conflate them.

## It never touches disk

The token is read **from the environment** by a credential helper
(`/usr/local/bin/git-credential-mono`, written in the Dockerfile) that echoes it to
git on a `get` and does nothing on `store`/`erase`.

This is the crux of the design. The obvious shortcut — `url.insteadOf` with the
token embedded in the remote URL — would write the credential into **every clone's
`.git/config`**. Those files live on the **host**, via the bind mounts. A token
written there outlives the container, survives `--rm`, and sits in plain text in a
directory the user has long since stopped thinking about. The environment-only
helper is what keeps a credential from becoming a credential *at rest*.

## It is scoped to github.com

The helper is registered for one host and one host only:

```
git config --system credential."https://github.com".helper mono
```

This is load-bearing, not hygiene. Repo definitions are data — they come from
`mono-config`, which is itself a git repo that can be edited, mis-typed, or receive
a bad pull request. Without host scoping, a `sources` URL pointing anywhere would
cause git to offer the user's GitHub token to that host. With it, git will not hand
the token to `evil.example.com` no matter what any repo definition says.

## Failure is loud

The image sets `GIT_TERMINAL_PROMPT=0`. Without it, git's response to a missing
credential is to **prompt on the TTY** — which is precisely how this gap first
presented itself: not as an error, but as an unexplained
`Username for 'https://github.com':` in the middle of a re-layout.

Instead, git fails, and the [git layer](layers/git/README.md) classifies the stderr
and raises `GitAuthError` — a `GitCommandError` subclass whose message names both
ways out (`MONO_CONTROL_GITHUB_TOKEN`, or `gh auth login`).

One wrinkle drives that classifier: **GitHub answers an unauthenticated request for
a private repo with `404 Not Found`, never `403 Forbidden`.** "Repository not found"
is therefore an auth symptom at least as often as it is a real typo, and the two are
indistinguishable from outside. `GitAuthError` says so rather than guessing.

## What the token can actually do — and why scope is the whole game

mono-control **never writes to a remote.** Its complete git verb set is `clone`,
`ls-remote`, `config`, `checkout`, `rev-list`, `rev-parse`, `status`. There is no
`push`. A **read-only, repo-scoped** token is therefore not a hardening tax; it is
exactly the capability the tool needs, and every scope beyond it is pure downside.

That matters because of what the container is. The token sits in the environment of
a process whose dependencies could, in principle, be compromised — and a token in an
environment is exactly what such a package would try to exfiltrate. Gating *when* it
is injected would be theatre: the adversary is a dependency of mono-control itself,
co-resident with the very code that legitimately needs the credential. There is no
moment when the token is needed and the attacker is not present. **Scope, not
timing, is the only lever.**

And scope collapses the problem almost entirely. Consider a stolen read-only token
scoped to the repos mono-control manages. Those repos are already cloned into
`mono-repos`, which is already bind-mounted into the container — an attacker in
there can already read every byte. The token grants them the ability to keep reading
repos they were already reading. Its marginal value is close to nil.

Contrast a `gh` OAuth token: `repo` + `workflow` + `gist`, **write**, across every
repo you own, no expiry. `workflow` reaches GitHub Actions and therefore your CI
secrets — blast radius well beyond the machine. That is a genuine prize.

Hence the policy: **a scoped PAT is supported and preferred; `gh auth token` is the
convenience fallback, and the shim warns when it uses it.** The gap between those two
tokens is the entire security question here, and it is settled by one choice when the
PAT is minted.

## Known residual: the container writes to bind-mounted `.git/`

Not solved here, and worth stating plainly. mono-control (and any *other* dev
container sharing these trees — a future `mono-dev-npm`, or a managed project's own
container running arbitrary `npm`/`uv` dependencies) has read-write access to
bind-mounted `.git/` directories. Anything with that access can plant
`.git/hooks/post-checkout` or an exec-capable `.git/config` key, which then executes
on the **host** the next time native git touches that repo — or inside mono-control's
own `git checkout`, where the token now lives.

That is a bigger hole than the token, it is not created by this change, and it is
tracked as an integrity-audit issue against the shim (the only host-side,
dependency-free component that sees every tree).

## Relationship to other documents

- [Host platform](host-platform.md) — the injected-variable pattern this follows.
- [Git operations layer](layers/git/README.md) — consumes the credential; raises
  `GitAuthError`.
- [Source layer](layers/source/README.md) — the acquisition path that clones.
