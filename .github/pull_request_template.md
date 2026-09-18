## Summary

<!-- 1–3 bullets: what changed and why. Focus on the "why" — the diff shows the "what". -->

## Public repo hygiene

This repo is public. Confirm before merging:

- [ ] No maintainer-side ops content (PyPI tokens, deploy scripts, release-monitoring config, internal automation) — those belong in the private `learnings/` repo
- [ ] No personal/internal references (private URLs, Slack threads, unredacted internal notes)
- [ ] No accidental secrets, credentials, or local-only paths

## Project hygiene

- [ ] CHANGELOG updated if this is user-facing
- [ ] Tests added or updated where applicable
- [ ] Docs (`docs/`, `README.md`) updated if behavior or surface changed
- [ ] Behavioral claims about a moving target (a pinned version, an external tool's behavior) in `docs/solutions/` are marked current-state or provenance per the [drift-defense convention](docs/solutions/best-practices/docs-code-drift-defense-convention-2026-06-13.md)
- [ ] CI green

## Test plan

<!-- How you verified this works. Commands run, scenarios covered, anything skipped. -->
