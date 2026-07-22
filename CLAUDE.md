# mono-control — working agreement

## NEVER run mono-control (or its tests) on the host. This is not negotiable.

mono-control imports a large tree of third-party (PyPI) dependencies whose job is
to manage git. The **entire reason** this project exists in a container is to keep
that untrusted code away from your machine. Running mono-control on the host —
including running its **test suite** on the host — executes those dependencies with
your full user privileges. That is the exact supply-chain attack the design
prevents, and doing it defeats the whole architecture. It is unacceptable developer
(and agent) behavior.

A single compromised or typosquatted dependency is enough. "It's just the tests" is
not an exception — pytest imports and runs the same code.

## The ONLY correct way to run anything is through `mproj` (it runs in the container)

- Run the tool: `mproj control -- <args>` (e.g. `mproj control -- product-cluster conform relayout pc-ltx2`)
- **Run the tests: `mproj test-control`** ← this is the source of truth for test results
- Interactive shell in the container: `mproj shell-control`
- Build the image: `mproj build-control`

## Do NOT do any of these — they run untrusted code on the host

- ❌ `uv run pytest` / `python -m pytest` / `pytest` in the mono-control checkout
- ❌ `uv run mono-control ...` / `python -m mono_control ...` on the host
- ❌ `uv sync` / `pip install` of mono-control on the host
- ❌ Setting `MONO_CONTROL_IN_CONTAINER=1` (or any env var) to get past a gate
- ❌ Creating/forging the container marker file to get past a gate

## The gates refuse on the host BY DESIGN

The build backend, the CLI, and the test suite all refuse to run unless the
container **marker file** (`/etc/mono-control-container`, baked only by the image
build) is present. A refusal on the host is the system working correctly — it is
**not** a problem to work around. If you hit one, you are trying to run in the wrong
place: use `mproj`. The marker is a file, not an env var, precisely because an env
var was a one-line bypass; do not look for a new bypass.

## If a test "fails" on the host

It doesn't count. Host runs give both false failures (container-path assumptions
like an absolute `/workspaces/...` config dir, or `/` vs `\` separators) and, worse,
can mask real failures. Re-run with `mproj test-control` before believing any result.
