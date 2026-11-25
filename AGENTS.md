# tietai-symthea: assistant instructions

Synthetic patient generation and export.

## Ecosystem and task guidance

Read the [canonical ecosystem overview](https://github.com/TIET-AI/tietai-hip-platform/blob/dev/docs/architecture/ECOSYSTEM.md)
before changing a service boundary. Identify affected producers, consumers and
contracts. Keep the overview in the parent repository; do not copy it here.

Use the [shared task skill index](https://github.com/TIET-AI/tietai-hip-platform/blob/dev/docs/engineering/ASSISTANT_SKILLS.md)
to select and read the relevant SKILL.md before its task. In an umbrella checkout,
these documents are under `../docs/`; for standalone clones or worktrees, use
`TIETAI_PLATFORM_ROOT` when configured or locate the reviewed parent checkout.
During local work, use the parent documentation revision associated with the
change. The GitHub links become usable when that revision is promoted to `dev`.
A link does not imply the assistant has loaded a document: open it explicitly.

The UI design authority is [TIET-AI/tietai-design-workspace](https://github.com/TIET-AI/tietai-design-workspace).
Use its current page templates, tokens and components through `tietai-ui-change`.
Read the parent's [development controls](https://github.com/TIET-AI/tietai-hip-platform/blob/dev/docs/governance/DEVELOPMENT_CONTROLS.md)
for changes governed by the project's quality and risk processes.

## Working rules

- Work and verify locally before reviewed promotion to `dev`. `dev-rc` is the
  generic local candidate name; an exact branch name is not compulsory in every
  repository. Base related work on the current candidate and preserve it.
- Local candidate merges within the authorised task are allowed. Test combined
  changes and record repository revisions and dirty state. Protected `dev`/`main`
  merges and production releases retain human review.
- Preserve unrelated work; use isolated worktrees when needed. Do not create,
  push or merge branches across unrelated repositories automatically.
- Inspect manifests, scripts and CI for current tool versions and commands.
  Do not infer a running version from a branch name, README or health constant.
- Preserve tenant isolation, authentication, PHI handling and audit controls.
  Use synthetic fixtures and isolated local databases for tests; no live clinical
  or LLM endpoints in unit tests. Do not bypass controls, tests or linters to pass.
- Keep changes traceable to the requested requirement and report verification
  limits. Use the configured human author; do not add AI attribution trailers.


## Skill discovery in this checkout

The shared skill source is the parent repository. Codex and Claude adapters link
to the same files; `.agents/platform` is a local, ignored pointer, not a copy.
For a service clone/worktree, configure it with:

```sh
python3 "$TIETAI_PLATFORM_ROOT/scripts/assistant_skills.py" --repo . --platform "$TIETAI_PLATFORM_ROOT"
```

Set `TIETAI_PLATFORM_ROOT` to the reviewed parent checkout first. Verify with the
same command plus `--check`. If a host cannot follow skill symlinks, explicitly
read the canonical SKILL.md through the parent index. Never treat a broken link
as a loaded skill. AGENTS.md remains the sole project instruction entry point.
