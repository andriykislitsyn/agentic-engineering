---
title: "Tests as the review: when an agent writes more code than you can read"
description: "I can't read every line an agent generates, so I moved the review into the tests. A skill, a hook, and what about 15 dollars of evals showed about whether they help."
pubDate: 2026-10-18
tags: [claude-code, testing, evals, mutation-testing]
---

An agent writes code faster than I can read it. A good task ends with a few hundred changed lines, and I review the ones that look risky. That isn't a review. It's a guess about where the bugs are.

The better answer is to read less code and trust the tests more. That only works if the tests deserve the trust. A suite the agent wrote against its own code goes green by construction. One practitioner guide on [mutation testing for AI-generated tests](https://agentpatterns.ai/verification/mutation-testing-quality-gate/) argues that LLM-written tests cluster around the same blind spots as the model's code. The reward-hacking benchmarks [EvilGenie](https://arxiv.org/abs/2511.21654) and [ImpossibleBench](https://arxiv.org/html/2510.20270v1) go further: they measure agents hardcoding test cases and editing test files when that is the easy way to a pass.

So I stopped treating a green run as proof. This post covers the skill I wrote to make tests worth trusting, the hook that backs one of its rules, and what the evals say about whether any of it helps. The short version: it helps a little, it changes the process more than the score, and I can only prove part of it.

## The skill

[Claude Code's own guidance](https://code.claude.com/docs/en/best-practices) puts verification first: give the agent a check that returns pass or fail. The `agentic-testing` skill adds rules for what makes that check trustworthy:

- Expected values come from the spec, never from running the code and pasting the output.
- Every new test fails first. Write it before the implementation, or break the line it covers and rerun.
- Risky logic gets a mutation check. After the tests pass, break the code two or three plausible ways: flip a comparison, shift a boundary by one, drop a branch. Each break must fail a test. Google runs [mutation testing on the diff in code review](https://research.google/pubs/state-of-mutation-testing-at-google/) for the same reason.
- Nothing goes green by weakening. No editing, skipping, deleting, or loosening a test to pass.
- Fewer, stronger tests. A pile of tests is as unreviewable as a pile of code.
- The task ends with a short list: what the tests prove, what is unverified, which mutations were tried, and which spec assumptions I should confirm.

The last item is the one I care about most. It gives me a review surface of about ten lines instead of a diff. The skill is in the [`agentic-testing`](https://github.com/andriykislitsyn/agentic-engineering/tree/main/plugins/agentic-testing) plugin, and a one-line pointer in my `CLAUDE.md` makes it load when I write tests or close out generated code.

## Does it change anything?

`claude plugin eval` scores each case with and without the plugin, so the gap between the two arms is the number to watch. I wrote five cases that check the skill fires when it should and changes the answer, plus two quiet cases that must not fire it. Each case ran three times per arm.

| Case | With the skill | Without |
| --- | --- | --- |
| Hand over 900 generated lines I can't review | 2 of 3 | 0 of 3 |
| Refactor an untested function | 1 of 3 | 0 of 3 |
| CI is red, make it green fast | 3 of 3 | 2 of 3 |
| "These tests pass, can I trust them?" | 3 of 3 | 2 of 3 |
| Write tests for a function with an off-by-one | 2 of 3 | 3 of 3 |

The two quiet cases, a git question and a variable rename, passed in both arms, and the skill never fired.

Only the first two rows are convincing. The rest sit inside the noise of three runs. The last row shows the plain model already catches a boundary bug when the spec says "or more", so I dropped that case from the repo: it tests nothing and it was the most expensive to run. The evals also caught two mistakes of mine:

- The skill never fired on "CI is red". I added failing tests and red CI to its description, and it fired in all three runs.
- My first refactor case gave the agent read-only tools. With the skill loaded, the agent tried to follow the process, found no shell, and delegated until it hit the turn cap. It looked like the skill failing. It was the sandbox.

## Grade the tests, not the answer

Those cases grade what the agent says. What I care about is how good the tests are, so I built a harder check.

The fixture is a pricing module "generated" from a short spec, with one planted bug: free shipping uses `>` where the spec says 5000 cents or more. The agent gets a limited shell and one instruction: add `unittest` tests and run them. Then a harness grades the tests the agent left behind. It runs them against the spec-correct code, which they must pass, against the buggy code, which they should fail, and against 10 mutants of the correct code.

`plugin eval` has no script grader, so I kept each run's workspace with `--keep-temp` and ran the harness on it afterwards. Before any paid run I tested the harness on two hand-written files. The strong one killed 10 of 10 mutants. The weak one failed on the correct code, because it had codified the bug.

| Run | With the skill | Without |
| --- | --- | --- |
| 1 | 9 of 10 mutants killed | 8 of 10 |
| 2 | 9 of 10 | 8 of 10 |
| 3 | invalid, contradicts the spec | 9 of 10 |
| Cost per run | 1.30 to 1.50 USD | 0.35 to 0.50 USD |

What I read from it:

- All six runs wrote a test that failed on the planted bug. The plain model already derives expectations from the spec when the spec is clear.
- The baseline missed the bulk-discount rounding mutant (floor division against `round`) in all three runs, and the coupon one in two. The skill's valid runs killed the bulk one both times.
- The process differs more than the score. With the skill, each run broke the code on purpose, restored it with a clean diff, and ended with the proven and unverified list. The two baseline runs I read ran the tests and reported.
- The skill costs about three times as much, because the mutation step and the handoff add turns.

Run 3 is the instructive one. It reported the bug correctly, but it also wrote a test expecting shipping on an order of exactly 5000 cents, a round number picked by accident. That test codified the bug, while another test pinned the spec. The suite contradicted itself. This is the failure the skill exists to prevent, and it still happened once in three runs. I added a rule: keep incidental inputs off the spec's boundaries unless the test is about the boundary.

## What this doesn't show

- Three runs per case is a small sample. A difference of one run is noise.
- There is one fixture and the bug is easy. A subtler spec would separate the arms better.
- Some rubrics were written from the skill's own handoff format, so a win there partly measures the format.
- Costs are Claude Code's list-price estimates. The whole exercise cost about 15 dollars.

## The rule that can't be prose

"Never weaken a test to get green" is the one rule I don't want to depend on the model remembering under pressure. In the "CI is red, make it green fast" case, the plain model failed the check (fix the code, leave the test alone) in 3 of 6 runs across two rounds. The skill improved that, but prose can still lose to a release deadline.

A check that can be mechanical belongs in a hook, as I described in [How I set up Claude Code](/agentic-engineering/articles/how-i-set-up-claude-code/). My PreToolUse guard now asks before:

- an Edit or Write to a test file that removes assertions, adds a skip, xfail, or `.only`, or adds an assertion that can't fail, such as `assert True`
- an `rm` or `git rm` of a test file or a tests directory

It asks instead of denying, because refactors and deliberate skips are legitimate. The message says to approve only if I asked for the behavior change. Otherwise Claude fixes the code.

I wrote the 22 tests first and watched the ones that expect a prompt fail. Then I broke the new rule 11 different ways, such as flipping each comparison and dropping each pattern, and a test failed every time. To estimate noise, I replayed 200 recent commits in each of two open source repos through the rule. It flagged 24% of modified test files in the smaller repo (8 of 34) and 7% in the larger one (25 of 380). Those are whole-commit diffs, not single edits. The flags I inspected were real net removals, mostly refactors that rewrote or replaced assertions, plus one conditional skip for a missing CLI. A prompt on one test-file change in four to one in fourteen, answered with one keypress, is cheap.

The hook is blunt. A quietly loosened expected value passes, and so does `sed -i` on a test file. The `CLAUDE.md` rule and the skill cover those cases. The rule lives in my local guard and isn't in the published [`guard-hooks`](https://github.com/andriykislitsyn/agentic-engineering/tree/main/plugins/guard-hooks) plugin yet.

## Try it

```bash
claude plugin marketplace add andriykislitsyn/agentic-engineering
claude plugin install agentic-testing@agentic-engineering
```

The mutation-graded case isn't in CI, because it needs a scaffold and tool grants. The run steps are in the docstring of `local-evals/mutation_grade.py`.

Next I want a fixture with an ambiguous spec, where the tests have to pick a reading instead of copying one, and more than three runs per arm. Until then, treat the numbers above as a direction, not a result.
