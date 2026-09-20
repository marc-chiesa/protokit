---
title: "A predicate over rendered output cannot be made sound: a differential check misses an unconditional lie, a vocabulary check misses a novel wording — record the rendering"
date: 2026-09-19
category: docs/solutions/best-practices
module: tests/meta/test_formatter_trust.py
problem_type: best_practice
component: testing_framework
severity: high
root_cause: incomplete_implementation
resolution_type: test_fix
applies_when:
  - "A test guard decides whether a renderer's output is acceptable by checking properties of the rendered text itself (a forbidden or required word list, a diff against a computed control rendering) instead of by recording the exact text and diffing future runs against that recording"
  - "The renderer under test produces free-form human- or machine-readable text (CLI prose, JSON message strings, JUnit failure bodies) where the same false claim can be phrased in wording the guard's author did not anticipate"
  - "A differential check compares a report's rendering against a control rendering of the made-trustworthy version of the same report, and is being trusted to always diverge when the report is untrustworthy"
  - "Guard coverage exercises only one fixture per report kind or verdict class, so a renderer could agree with the owner by coincidence, re-deriving a right-looking answer from whichever single signal that one fixture happens to carry"
  - "A machine-readable format carries the same verdict in more than one place (a boolean field and a separately-computed error count, or an exact error count alongside free-text error messages) with nothing pinning those copies to agree"
symptoms:
  - "A per-kind forbidden-success-word list is defeated by re-casing, re-spacing, or a synonym the list never enumerated"
  - "A control-rendering diff is defeated by an unconditional line the control also prints, by a footer keyed on a field that survives into the control, or by a refusal marker relocated inside a URL or made circular"
  - "The full test suite stays green on both Runtime backends while a reader can no longer tell from the rendered report whether the run actually finished"
  - "A machine-readable payload carries two top-level fields for the same verdict that can disagree on one distrusted report"
  - "A CI-facing format's failure and error counts stay correct while every failure's message text is replaced with generic, uninformative text"
related_components:
  - "tooling"
  - "development_workflow"
tags:
  - "trust-seam"
  - "golden-file-testing"
  - "differential-check"
  - "predicate-guard"
  - "renderer-verification"
  - "cross-model-verification"
  - "ci-gate"
  - "guard-soundness"
---

# A predicate over rendered output cannot be made sound: a differential check misses an unconditional lie, a vocabulary check misses a novel wording — record the rendering

## Context

`protokit._trust` is a Seam: it owns one question for the whole package — *can
this report be read as success?* — across five report kinds, and every built-in
renderer asks it before stating a verdict (`src/protokit/_trust.py:1-58`,
`is_trustworthy` at `src/protokit/_trust.py:361`). The failure mode it exists to
end is bypass drift. The facts were always on the report
(`DiffResult.truncated_paths`, `CompatibilityReport` error diagnostics,
`LintReport.runtime_warnings`) and each renderer decided for itself whether to
look, so one run printed `COMPATIBLE` on a terminal and an error in CI
(`src/protokit/_trust.py:5-15`). The seam fails closed: an unrecognised report
kind raises `TypeError` rather than defaulting to trustworthy
(`src/protokit/_trust.py:294-300`).

A seam is only a seam if reaching around it fails, so it ships with a guard.
`tests/meta/test_formatter_trust.py` renders every registered formatter against
a report that is untrustworthy in each way its kind can be, and walks the root
Click group for commands whose code never reaches the module.

**The guard was the hard part.** Over four review rounds — an in-house
multi-lens code review followed by three falsification sweeps, several run
against a second model — the guard's decision rule was rebuilt twice and beaten
both times: the second rule twice over, once in a way it could absorb and once
in a way no predicate could. The counterexamples were never oversights in a
rule. They were the same structural fact restated:

> A guard that decides whether rendered prose is acceptable **by predicate**
> cannot be made sound. Text can always be written that satisfies the predicate
> and tells the reader the opposite of the truth.

Two of the counterexamples left the whole suite green on both Runtime backends.

The resolution was to stop asking a question about the text and start recording
it. `tests/meta/trust_renderings.golden` holds 69 recorded human renderings —
each kind's trustworthy rendering, all 32 untrusted modes, and each mode's
control — regenerated only through `tests/meta/regen_trust_golden.py`. The
predicates were kept alongside, deliberately, and the guard file says why:

> The predicates stay because they say WHY a line is wrong when one fails; this
> says THAT something changed.
> — `tests/meta/test_formatter_trust.py:717-718`

Landed as PR #73 (the seam and its renderers) and PR #74 (the guard rewrite).

## Guidance

### 1. Record prose; predicate on values

Split the output by what it *is*, not by which formatter produced it.

- **Free prose a human reads** — a verdict sentence, a refusal line, a summary
  header. Record it. A predicate over it is unsound, and the gap is structural,
  not a matter of writing a better predicate.
- **A typed value a machine reads** — a JSON boolean, a JUnit `failures` count,
  a SARIF `executionSuccessful`. Predicate on it exactly, because the thing
  being checked *is* the value. `_MACHINE_VERDICTS`
  (`tests/meta/test_formatter_trust.py:591-613`) reads each format's verdict and
  `test_the_verdict_follows_the_seam`
  (`tests/meta/test_formatter_trust.py:791-799`) requires it to be `True` on the
  trustworthy fixture and `False` on every untrusted mode.

The gap for machine formats is not wording, it is **shape**: a second key that
contradicts the one the reader reads, or an explanation replaced with filler.
Pin the shape instead — see rule 5.

### 2. Record the control beside the subject

```python
def _all_renderings() -> str:
    """Render every fixture and every control, in a stable order."""
    out: list[str] = []
    for kind in FormatterKind:
        pairs: list[tuple[str, object]] = [("trusted", _TRUSTED[kind])]
        pairs += sorted(_UNTRUSTED[kind].items())
        for label, report in pairs:
            shapes = [(label, report)]
            if label != "trusted":
                shapes.append((f"{label} [control]", _made_trustworthy(report)))
            ...
```
— `tests/meta/test_formatter_trust.py:685-700`

Four properties make this a guard rather than a snapshot habit.

1. **The control is recorded beside the subject.** `_made_trustworthy(report)`
   is the same report with only its untrustworthiness removed
   (`tests/meta/test_formatter_trust.py:313-346`). Recording both means the diff
   shows not only that a line changed but which of the pair it changed in — a
   renderer that starts printing the same sentence for both is visible as a
   change to the untrusted rendering.
2. **The rendering is deterministic.** Styling is stripped via `click.unstyle`
   (`tests/meta/test_formatter_trust.py:295-296`), modes are sorted, and
   fixtures are built in-process from the real report dataclasses
   (`tests/_trust_reports.py:1-12`). Nothing recorded depends on a clock, a
   path, a locale or a Runtime backend.
3. **Regeneration is a deliberate act with its own module**, not a pytest flag:

   ```
   .venv/bin/python -m tests.meta.regen_trust_golden
   ```

   whose docstring reads "Run it only after reading the failing diff and
   agreeing with every line" (`tests/meta/regen_trust_golden.py:3`). The failure
   message prints the unified diff and repeats the instruction
   (`tests/meta/test_formatter_trust.py:725-736`). A golden regenerated
   reflexively guards nothing; the human reading the diff *is* the mechanism.
4. **It stays small enough to read.** 69 renderings of a handful of lines each
   is a diff a reviewer will actually read. That is a budget, not an accident.

### 3. Keep the predicates

A golden says *that* something changed. It never says *why* a line is wrong, and
it will happily record a wrong line the day someone regenerates without reading.
The predicates that survived the rounds stay, each doing the job the golden
cannot:

- `test_the_success_verdict_is_withheld`
  (`tests/meta/test_formatter_trust.py:396-419`) — the kind's success text, via
  `_states_success`, which matches as a whole word and is case- and
  whitespace-insensitive (`tests/meta/test_formatter_trust.py:299-310`).
- `test_a_refusal_is_stated` (`tests/meta/test_formatter_trust.py:436-453`) —
  the positive half. Going quiet is not refusing.
- `test_no_line_is_invented` (`tests/meta/test_formatter_trust.py:484-523`) —
  every line of an untrusted rendering is the control's, carries a reason, or is
  the kind's refusal marker.
- `test_every_reason_is_rendered`
  (`tests/meta/test_formatter_trust.py:421-433`) — counted with a `Counter`, not
  merely contained, so a de-duplication that renders one of two identical
  reasons is a dropped reason.

### 4. Two rules the defeats forced into the predicates

**Make the refusal marker the renderer's own verdict prose.** `_REFUSAL_TEXT`
(`tests/meta/test_formatter_trust.py:276-282`) lists per kind what a refusal
looks like: `INCOMPLETE`, `not trustworthy`, `diagnostic[`. A marker must not be
something a *reason* line already carries. `compat` prefixes every reason with
`"  ! "` (`src/protokit/formatters/_builtin_compat.py:90-92`), so a version of
the guard that used `"  ! "` as the refusal marker was circular — the presence
of any reason at all satisfied the check that a refusal had been stated. The
marker is now `INCOMPLETE`, which is the renderer's own verdict text
(`src/protokit/formatters/_builtin_compat.py:95-100`).

**Carrying a reason does not excuse the rest of the line.** Containment is not
accounting. `test_no_line_is_invented` removes the legitimately-present text and
requires what is left to be silent:

```python
remainder = line
for reason in reasons:
    remainder = remainder.replace(reason, " ")
if not any(ch.isalpha() for ch in remainder):
    continue
```
— `tests/meta/test_formatter_trust.py:514-518`

### 5. Pin the shape of machine output

- **Exact key set per payload.** `_JSON_KEYS`
  (`tests/meta/test_formatter_trust.py:617-639`) pins each format's top-level
  keys, and `test_a_json_payload_grows_no_key_unnoticed`
  (`tests/meta/test_formatter_trust.py:806-819`) asserts equality over the
  trustworthy fixture and every untrusted mode. A new key — especially a second
  verdict — cannot appear unreviewed.
- **"Verdict-free" is a check, not a declaration.** A format excused from the
  verdict table must contain no verdict-shaped value *anywhere*: `_verdict_shaped`
  walks the payload recursively and yields any `bool` or any `"true"`/`"false"`
  string at any depth (`tests/meta/test_formatter_trust.py:538-554`, asserted at
  `:880-892`). A check that looked only at top-level booleans let a nested one
  through.
- **A failing document has to say what failed, in the report's words.**
  `test_junit_error_text_comes_from_the_report`
  (`tests/meta/test_formatter_trust.py:826-873`) collects the report's own text —
  seam reasons, diagnostics, findings, a finding's rule id, a difference's path,
  an entry's commit SHA, the breaking commit — and requires each
  `<error>`/`<failure>`'s message-plus-body to contain some of it. Counts alone
  are not enough: they stayed correct while every explanation was replaced with
  generic filler.

### 6. Cover every mode, not one fixture per kind

The guard file states this lesson in its own module docstring:

> One fixture per kind was not enough, and this is the lesson worth keeping: a
> renderer that re-derives trust from the one signal that fixture happens to
> carry (``if result.errors``) passed the guard while ignoring every other
> signal.
> — `tests/meta/test_formatter_trust.py:16-19`

So `_UNTRUSTED` is a mode table, `kind -> {mode: report}`, covering every way the
seam can distrust that kind (`tests/meta/test_formatter_trust.py:152-257`) — 32
modes across the five kinds. It includes modes where the report *also* has
something legitimate to report (`error-with-findings`), two signals of different
kinds at once (`error-and-truncated`), repeated and multi-way reasons
(`repeated-error`, `six-errors`), a path-scoped error, and a two-entry walk whose
*second* entry is the broken one. The lint modes are generated from
`_trust.INCOMPLETE_ANALYSIS_CATEGORIES` itself
(`tests/meta/test_formatter_trust.py:240-243`), so widening that set in the seam
adds fixtures automatically instead of needing someone to remember.

`test_some_mode_carries_more_than_one_signal`
(`tests/meta/test_formatter_trust.py:1191-1201`) keeps the table honest: if every
mode yielded exactly one signal, "showed every reason" and "showed the first
reason" would be the same assertion.

### 7. Make the owner disagree with the report

Running a renderer against a report that really is untrustworthy cannot
distinguish a renderer that *asks the seam* from one that re-derives the answer
and happens to agree — and the second is the drift.
`TestNoRendererDecidesTrustForItself` patches `_trust.signals` alone, because
`reasons`, `is_trustworthy`, `signals_other_than` and `walk_level_reasons` all
derive from it, so a renderer holding a cached reference to any of them still
sees the lie (`tests/meta/test_formatter_trust.py:914-924`). The planted signals
carry a kind no format claims to render structurally (`_SENTINEL_KIND`,
`tests/meta/test_formatter_trust.py:905`), which models the day the seam learns a
new reason: every format must fail closed on it
(`tests/meta/test_formatter_trust.py:927-973`).

## Why This Matters

Two asymmetries are the whole reason a predicate over prose cannot be repaired by
making it stricter.

**A differential check cannot see an unconditional lie.** Comparing the untrusted
rendering against a control finds anything the renderer says *because* the report
is untrustworthy. It is structurally blind to anything the renderer says
regardless. `All checks passed; safe to deploy.` printed on every report — the
trustworthy one included — produces no difference for a differential check to
find, because there is no difference. The same blindness covers a footer keyed on
something the control keeps: `if report.findings: ...` survives
`_made_trustworthy` intact (`tests/meta/test_formatter_trust.py:313-346` removes
only error diagnostics, truncation and gated runtime warnings), so a verdict
printed from that branch appears in both renderings.

**A vocabulary check cannot see a novel wording.** A list of forbidden success
words, or of required refusal words, only knows the words on it. The guard file
names its own defeat:

> Enumerating forbidden success words is a blacklist a synonym walks through: a
> renderer that withholds ``Messages are equal.`` and prints ``The two messages
> match.`` instead passes every check built that way.
> — `tests/meta/test_formatter_trust.py:487-489`

Each asymmetry is covered by the *other* kind of check — a synonym **is** a
difference from the control; an unconditional sentence **can** contain a listed
word. That is why a guard built from both feels sound. It is not: **the
intersection is still open.** Text that is both unconditional and novel satisfies
both checks at once, and that is exactly what `All checks passed; safe to
deploy.` is.

Recording the output closes the intersection because it asks nothing about the
text at all. Any line added, removed or reworded lands in a diff in front of a
human — which is the review the predicates were standing in for all along.

Two more things follow, and they are why the predicates stay:

- **A golden reports a change, not a wrong.** When a predicate fails it names the
  rule that was broken; the golden hands you a diff and asks you to decide. They
  fail in different directions — the golden is loud about everything and specific
  about nothing.
- **A golden only records what the fixtures render.** Its coverage is exactly the
  mode table's coverage, which is why the mode table has its own vacuity checks
  (`tests/meta/test_formatter_trust.py:1191-1201`) and why the static walk over
  the Click group exists for commands no formatter fixture can reach
  (`tests/meta/test_formatter_trust.py:1153-1181`). The Limits section below
  carries a live instance of this exact caveat.

**Cross-model review earned its cost on this specific question.** Every defeated
version passed in-house review. Each was broken by a cross-model falsification
pass, usually within minutes of that pass starting. "Is this guard strong?" is a
question where a reviewer who shares the author's frame reliably agrees with the
author. One methodological note worth keeping (session history): neutrally worded
verification prompts — "verify whether this claim holds; report HELD or
COUNTEREXAMPLE" — ran clean, where combative wording tripped a provider content
filter and produced nothing at all.

## When to Apply

Record the rendering when **all** of these hold:

- The thing under test is **prose a human reads** and the property is semantic —
  "does this tell the reader the truth" — rather than structural.
- The rendering is **deterministic**: no clock, no absolute paths, no environment-
  or Runtime-backend-dependent ordering, styling stripped at the boundary.
- The recorded corpus is **small enough that a reviewer will read the diff**. The
  review is the mechanism; a diff nobody reads is a rubber stamp with a test id.
- The output **changes rarely and deliberately**. Verdict wording on a shipped CLI
  qualifies. Text under active iteration does not.
- Regeneration goes through a **named, documented step** a reviewer can see in the
  diff of a PR.

A golden file is **not** the right answer when:

- **The property is decidable on a value.** A JSON verdict boolean, an exit code,
  a JUnit failure count: assert them directly. Recording a payload to check a
  boolean buries the assertion in noise, and the noise is what makes goldens
  churn.
- **Output changes on most commits.** Then every PR carries a regeneration, diff
  review degenerates into reflex, and the guard is gone while the test is still
  green. The cost is real and it is paid on every *intentional* change, not only
  the wrong ones.
- **You need the test to explain the rule.** A golden cannot say "this line claims
  success on a report the seam distrusts". Keep a predicate for the rules you can
  state, precisely because it names them when it fails.
- **The output is not deterministic** and you would be tempted to normalise it
  into the golden. Every normalisation step is a predicate smuggled back in, with
  the same blind spots and none of the visibility.
- **The surface is large** — thousands of lines of generated output. Prefer a
  pinned shape (key sets, counts, an index of section headers) over a recorded
  body nobody reads.

Independently of the golden, apply the shape-pinning rules whenever a machine
format states a verdict: pin the exact key set, check a verdict-free format for
verdict-shaped values at every depth, and require a failing document to carry text
drawn from the report rather than filler.

Before trusting any of these guards, confirm the guard is not vacuous. A Mutation
proof is the instrument: write the plausible wrong renderer, run the guard, and
require it to fail. Every counterexample below was produced exactly that way, and
the verdict each time was that the guard stayed green.

## Examples

The defeated predicates, in the order they were defeated. Each bullet's text
defeated the stage above it.

### Stage 1 — a per-kind forbidden success word

`_SUCCESS_TEXT` names the text each kind's clean rendering prints
(`tests/meta/test_formatter_trust.py:356-362`):

```python
_SUCCESS_TEXT: dict[FormatterKind, str | None] = {
    FormatterKind.DIFF: "Messages are equal",
    FormatterKind.COMPAT: "COMPATIBLE",
    FormatterKind.COMPAT_HISTORY: "OK",
    FormatterKind.COMPAT_BISECT: "no break found",
    FormatterKind.LINT_REPORT: None,
}
```

An exact-substring check over that table was defeated by:

- **Different casing** — `Messages are EQUAL.`
- **Different spacing** — `Messages  are equal.`
  (both quoted at `tests/meta/test_formatter_trust.py:304-305`)
- **A synonym the list did not contain** — `The two messages match.`
  (`tests/meta/test_formatter_trust.py:489`)
- **The exemption.** `lint`'s clean rendering is empty, so its entry is `None` and
  the withholding check returns early for it
  (`tests/meta/test_formatter_trust.py:402-405`). With no success word to
  withhold, a renderer could print a sentence of its own — `lint: clean - no
  issues found`, per the session that produced this — on a run whose rule had
  crashed, and the check had nothing to say.

Casing and spacing were closed by making the match word-bounded and
case/whitespace-insensitive:

```python
flat = " ".join(out.split())
return bool(re.search(
    rf"(?<![A-Za-z]){re.escape(success)}(?![A-Za-z])", flat, re.IGNORECASE,
))
```
— `tests/meta/test_formatter_trust.py:307-310`

The bound on both sides matters for its own reason: `COMPATIBLE` is a substring of
`INCOMPATIBLE`, so a plain `in` reads the refusal as the claim. But the synonym
gap and the exemption gap are not reachable from here at all.

### Stage 2 — accounting against a control

Render the report; render `_made_trustworthy(report)`, the same report with only
its untrustworthiness removed; require every line of the untrusted rendering to be
justified by one of three things — the control prints it too, it carries one of the
seam's reasons, or it is the kind's refusal marker
(`tests/meta/test_formatter_trust.py:484-523`). Defeated by:

- **A line that contains a reason and appends its own verdict.**
  `All checks passed; safe to deploy. Advisory: <reason>` — containment excused
  the whole line (quoted at `tests/meta/test_formatter_trust.py:509-513`).
  *Fixed* by subtracting the reasons and requiring the remainder to be silent
  (`tests/meta/test_formatter_trust.py:514-518`).
- **An unconditional success line.** `All checks passed; safe to deploy.` printed
  for every report, trustworthy or not — the control prints it too, so a
  differential check sees no difference (quoted at
  `tests/meta/test_formatter_trust.py:710-712`). *Not fixable here.*
- **A footer keyed on findings.** `if report.findings: ...` — findings survive
  into the control (`tests/meta/test_formatter_trust.py:313-346` strips only
  errors, truncation and gated runtime warnings), so again no difference.
  *Not fixable here.*
- **The refusal marker placed inside a URL.**
  `Analysis completed successfully; all checks passed. Help: /statuses/INCOMPLETE`
  — the line contains `INCOMPLETE`, so the refusal branch waved it through. This
  wording is not in the tree; it was a proposed renderer, never committed, and the
  quote is from the session that produced this. The surviving guard narrows the
  exposure by keeping refusal markers to the renderer's own verdict prose
  (`tests/meta/test_formatter_trust.py:276-282`) and by forbidding the kind's
  success text anywhere, including on a refusal line
  (`tests/meta/test_formatter_trust.py:505-508`).
- **A circular refusal marker.** `compat`'s refusal marker had been the reason
  line's own `"  ! "` prefix, which every reason line carries
  (`src/protokit/formatters/_builtin_compat.py:90-92`), so "a refusal was stated"
  was satisfied by the presence of any reason at all. *Fixed* by making the marker
  the renderer's own verdict text (`tests/meta/test_formatter_trust.py:278`;
  `src/protokit/formatters/_builtin_compat.py:95-100`).

Two of these left the entire suite green on both Runtime backends.

### Stage 3 — record the output

```python
def test_human_renderings_match_the_golden_file() -> None:
    """Every line protokit prints about trust is recorded and reviewed.

    The checks around this one ask whether a rendering satisfies a predicate:
    does it avoid the success word, is each line accounted for, does a refusal
    appear. Four rounds of adversarial review found the same answer each time
    -- a sentence can satisfy any such predicate and still tell the reader the
    opposite of the truth. "All checks passed; safe to deploy." printed on
    every report passes them all, because a differential check sees no
    difference and a word list does not know the phrase.
    ...
```
— `tests/meta/test_formatter_trust.py:703-712` (excerpt; the docstring continues
to line 722)

Every counterexample above changes at least one recorded line, so every one of
them now lands in the diff of `tests/meta/trust_renderings.golden`. A recorded
entry is `kind :: mode`, the verbatim rendering, then the control:

```
### DIFF :: error
No differences found, but the comparison is not trustworthy:
  ✗ error[lint-fake]: analysis completed plugin crashed error[lint-fake]: analysis completed

### DIFF :: error [control]
Messages are equal.
```

### The same shape in machine output

**A second key contradicting the first.** The verdict reader for
`compat --format json` reads one key, `compatible`
(`tests/meta/test_formatter_trust.py:594`). A payload that also grew
`"success": true` on the same distrusted report satisfied the reader while telling
a consumer the opposite (`tests/meta/test_formatter_trust.py:808-814`). Fixed by
pinning the exact top-level key set per payload:

```python
_JSON_KEYS: dict[FormatterKind, set[str]] = {
    FormatterKind.COMPAT: {
        "compatible", "complete", "level", "findings", "diagnostics", "summary",
    },
    ...
}
```
— `tests/meta/test_formatter_trust.py:617-639`, asserted for the trustworthy
fixture and every untrusted mode at `:806-819`.

**Right counts, no cause.** The JUnit verdict reader checks whether a document
passes, not what it says (`_junit_passes`,
`tests/meta/test_formatter_trust.py:557-563`). Replacing every error's message
with generic text — `analysis failed` — kept the failure and error counts correct
and left a CI reader with a red build and no cause
(`tests/meta/test_formatter_trust.py:831-834`). Fixed by requiring each error's
message-plus-body to carry text drawn from the report itself:

```python
texts = [
    f"{e.get('message') or ''}\n{e.text or ''}"
    for e in root.iter() if e.tag in {"error", "failure"}
]
assert texts, (kind.name, mode)
for text in texts:
    assert any(
        src in text or _trust.one_line(src) in text
        for src in sources if src
    ), (kind.name, mode, text, sorted(sources))
```
— `tests/meta/test_formatter_trust.py:864-873`, where `sources` is built from the
report's own seam reasons, diagnostics, findings, rule ids, difference paths,
entry SHAs and breaking commit (`:838-861`).

### Coverage: one fixture per kind, and a renderer that agreed by coincidence

Before, each kind had a single untrustworthy fixture. A renderer that re-derived
trust from whichever signal that fixture happened to carry — `if result.errors` —
agreed with the seam by coincidence and passed
(`tests/meta/test_formatter_trust.py:16-19`).

After, each kind lists every mode the seam recognises for it
(`tests/meta/test_formatter_trust.py:152-257`), and two properties keep the table
from decaying: `test_some_mode_carries_more_than_one_signal`
(`:1191-1201`) and `test_every_formatter_kind_has_fixtures` (`:366-370`), which
fails a sixth report kind that lands without deciding how it is vouched for.

The per-entry case needed its own test rather than a mode, and the reason is the
first asymmetry again: in a two-entry walk with one broken entry, the control
legitimately prints `OK` for both entries, so a renderer that judged every entry
by the first one's report produces a line the control also prints. Both such
mutations left the whole suite green
(`tests/meta/test_formatter_trust.py:739-770`).

## Limits — what this does not close

**The golden's coverage is the mode table's coverage, and there is a live
instance.** A cross-model pass run against the seam branch (session history)
reported that `history --format sarif` deduplicates aggregate diagnostics on
`(level, commit, message)` while the seam keys restatements on
`(commit, path, message)`. Reproduced against `main` at the time of writing: an
aggregate `CommitDiagnostic` sharing a per-entry diagnostic's commit and message
but carrying a *different* path yields two seam reasons and two JUnit `<error>`
elements, but only **one** SARIF notification. The dedup key is
`(level, commit, message)` at `src/protokit/formatters/_builtin_history.py:219-229`,
and the message it keys on is the bare `d.message` with no path
(`src/protokit/formatters/_sarif_json.py:268-273`).

This is a fidelity gap, not a fail-open — `executionSuccessful` is still `false`,
so nothing claims success. But it is the caveat above demonstrating itself: no
mode in `_UNTRUSTED[COMPAT_HISTORY]` pairs a path-scoped entry diagnostic with a
path-distinct aggregate one, so neither the golden nor the predicates render the
case, and the JUnit sibling was fixed while the SARIF sibling was not. That is
[sibling blindness](sibling-blindness-fix-survives-review-structural-siblings-stay-broken.md)
in the dedup key, and the mode table is where it should be closed.

**A refusal line is taken whole**, so a synonym *inside* the refusal sentence
would pass the accounting test. The success-text check still forbids the kind's
own success wording anywhere, including there.

**`_verdict_shaped` looks for booleans and `"true"`/`"false"` strings at any
depth.** A numeric or enum-string verdict would escape it. Closing that properly
means pinning each verdict-free payload's key set, as `_JSON_KEYS` does for the
payloads that state a verdict.

**The accounting rule is deliberately over-strong.** It rejects a legitimate
informational line a renderer might want to add on failure; such a line has to
carry a reason or be a refusal. That is the intended trade, and it is a real
constraint on future renderers.

## Related

- [Sibling blindness: a fix lands at one call site while structurally identical siblings stay broken](sibling-blindness-fix-survives-review-structural-siblings-stay-broken.md)
  — the complementary failure. There the *fix* is incomplete across structurally
  identical sites; here the *guard* is incomplete across the ways one site can be
  wrong. Both are answered by deriving the set from the code — the call sites in
  that doc, the untrusted modes in this one — rather than from the case that was
  reported. Note that its section 4(c) prescribes
  `assert "COMPATIBLE" not in result.output` as a prevention rule; that is the
  Stage 1 shape above, sound only against literal reintroduction of that exact
  string.
- [The mutation-check harness can produce a false verdict of its own](../logic-errors/mutation-check-harness-stale-bytecode-and-nonverdict-exit-codes-produce-false-verdicts.md)
  — the same theme one level up: the instrument that certifies a test can itself
  report a verdict it has not earned. Relevant because the Mutation proof is what
  this doc leans on to show a guard is non-vacuous.
- [A formatter can bypass the CLI's exit code via SystemExit](../security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md)
  — the architectural predecessor. That is the same trust boundary at the
  *process exit code*; `_trust` formalises it for *rendered text*.
- [An empty selector parses to the root prefix and suppresses every finding](../security-issues/empty-selector-parses-to-root-prefix-suppresses-every-finding-2026-08-30.md)
  — a different fail-open, but its regression guard uses the same
  `assert "COMPATIBLE" not in result.output` idiom, with the same narrow
  guarantee.
- [Presence ratchet test pattern for prose substrings](presence-ratchet-test-pattern-for-prose-substrings-2026-05-14.md)
  — related vocabulary, different threat model, and *not* contradicted by this
  doc. A Presence ratchet pins known, authored prose against silent reversion by
  trusted authors; it never claimed to decide whether adversarial wording tells
  the truth.
