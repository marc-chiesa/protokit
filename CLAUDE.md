# CLAUDE.md

## Session settings

Set reasoning effort to high (`/effort high`). Always use thorough analysis, never cut corners.

## gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__claude-in-chrome__*` tools.

### Available skills

- `/office-hours` - YC-style office hours
- `/plan-ceo-review` - CEO/founder-mode plan review
- `/plan-eng-review` - Eng manager-mode plan review
- `/plan-design-review` - Designer's eye plan review
- `/design-consultation` - Design system consultation
- `/design-shotgun` - Generate multiple design variants
- `/design-html` - Production-quality HTML/CSS generation
- `/review` - Pre-landing PR review
- `/ship` - Ship workflow (tests, review, PR)
- `/land-and-deploy` - Merge, deploy, and verify
- `/canary` - Post-deploy canary monitoring
- `/benchmark` - Performance regression detection
- `/browse` - Headless browser for QA and browsing
- `/connect-chrome` - Connect to running Chrome
- `/qa` - QA test and fix bugs
- `/qa-only` - QA test and report only
- `/design-review` - Visual QA and fix
- `/setup-browser-cookies` - Import browser cookies
- `/setup-deploy` - Configure deployment settings
- `/retro` - Weekly engineering retrospective
- `/investigate` - Systematic debugging
- `/document-release` - Post-ship docs update
- `/codex` - OpenAI Codex CLI wrapper
- `/cso` - Security audit
- `/autoplan` - Auto-review pipeline
- `/plan-devex-review` - DX plan review
- `/devex-review` - Live DX audit
- `/careful` - Destructive command warnings
- `/freeze` - Restrict edits to a directory
- `/guard` - Full safety mode
- `/unfreeze` - Clear freeze boundary
- `/gstack-upgrade` - Upgrade gstack
- `/learn` - Manage project learnings

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health

## Documented Solutions

`docs/solutions/` — documented solutions to past problems (bugs,
best practices, workflow patterns), organized by category with YAML
frontmatter (`module`, `tags`, `problem_type`). Relevant when
implementing or debugging in documented areas.
