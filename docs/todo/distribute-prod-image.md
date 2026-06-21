# Distribute the prod image (ghcr.io) and define image refresh

`mproj control` runs mono-control in one of two backends depending on whether a
`mono-control/` checkout sits beside `mono-config/`:

- **dev** — Docker Compose against the live source;
- **prod** — the prebuilt `mono-control:latest` image, run directly.

Today the prod image only ever exists **locally**, built by hand from a checkout
(`docker build -t mono-control:latest -f .devcontainer/Dockerfile .`). The shim
hardcodes that ref in `MONO_CONTROL_IMAGE`
(`mono-control-shim/mono_control_shim/cli.py`) and, when the image is absent,
prints those build instructions and exits.

That is fine for a developer who already has the source, but it leaves two gaps
for a real prod user — someone running `mproj control` against a workspace with
**no** mono-control checkout:

1. **No distribution.** They cannot obtain the image without cloning mono-control
   and building it — which defeats the "mono-control is a system-wide docker
   artifact, no source required" premise.
2. **No refresh story.** A local `mono-control:latest` silently goes stale as the
   tool evolves; nothing pulls a newer build or warns that one exists.

## When to do this

Pick this up when **any** of these becomes true:

- There is a first real **prod consumer** — someone (or some machine/CI) running
  `mproj control` in artifact mode without a mono-control checkout.
- mono-control's feature set has **stabilized** enough to cut a versioned release
  (it is `0.0.0` today; a meaningful version implies something worth publishing).
- Local-image **staleness** starts causing confusion (a prod run executing an old
  build because nobody rebuilt `mono-control:latest`).

Until then the local-build path is sufficient and publishing would be premature.

## What to do

1. **Publish to a registry.** Build and push to `ghcr.io/fiemono/mono-control`,
   tagged with the mono-control version **and** `latest`. Automate it in CI
   (GitHub Actions) on tag/release so the published image always matches a known
   source revision. `.devcontainer/Dockerfile` is already a standalone build, so
   CI just runs the same `docker build`. `mproj build-control` already wraps that
   local build (`_run_build_control` in the shim) — it is the natural place to add
   a `--push` flag for the manual/interactive path.
2. **Point the shim at the registry ref.** Change `MONO_CONTROL_IMAGE` to the
   ghcr.io ref (keep it overridable for local/offline use). In artifact mode, on a
   missing image, `docker pull` it rather than failing — falling back to the
   build-from-source instructions only when the pull fails.
3. **Define the refresh mechanism.** Decide how prod users get a newer image.
   Options, roughly in order of preference:
   - an explicit `mproj control --pull` (and/or `mproj pull` / `mproj update`)
     that re-pulls the ref on demand;
   - **version pinning via the manifest** — let `mono-config` declare which
     mono-control version a workspace expects, and have the shim pull/run that
     exact tag. This mirrors how mono-control already pins *repo* revisions and
     makes prod runs reproducible per workspace; likely the right end state.
4. **Keep the local build as the dev/offline fallback**, with its command kept
   identical in `README.md` and the shim's error message so the two never drift.
5. **Update docs** — `README.md` ("Building the image") and any design docs once
   the manifest-version-pin decision is made.

## Related

- Shim backends + hardcoded ref: `mono-control-shim/mono_control_shim/cli.py`
  (`_control_prod`, `MONO_CONTROL_IMAGE`).
- Image build: `.devcontainer/Dockerfile`; see `README.md` ("Building the image").
- Manifest/version-pinning idea ties into the config model under
  `docs/design/layers/data/` (e.g. `mono-project.md`, `repo.md`).
