---
title: "Review Router: the GitHub Action that learned to review"
description: "A GitHub Action that routes pull requests to the right teams, and the AI reviewer bolted onto it. What works, what broke, and what is still unproven."
pubDate: 2026-09-29
tags: [github-actions, code-review, claude-code, agents]
category: field
---

Every pull request has the same first problem: nobody knows whose turn it is. The author waits, the reviewers don't know they're being waited on, and the PR ages like milk.

[Review Router](https://github.com/datarobot-oss/review-router) fixes that part. It's an open source GitHub Action written in TypeScript, and it's about four months old. It started as a label-and-ping bot. This month it started reviewing code, and that part is why you're reading this. The routing is proven. The reviewer is a working pipeline that hasn't earned anyone's trust yet. I'll say which is which.

## What it does

Someone adds the "Ready for Review" label, or a contributor comments `/review`. Then the action:

1. Reads `CODEOWNERS` from the base branch and maps the changed files to teams.
2. Adds a `Needs Review: <team>` label per team and requests their review.
3. Posts one comment that lists who owns what.
4. Pings each team's Slack channel.
5. Removes a team's label when one of its members approves.

Around that core, the action grew a few habits:

| Feature | What it does |
| --- | --- |
| Slack threads | The PR author gets an @-mention in the original thread when someone comments or approves. A `:mute:` reaction silences it |
| Reminders | A scheduled run re-pings PRs that still wait after 24 hours |
| Dependabot | Bot PRs get labeled automatically, and a companion workflow merges them once approved |
| External contributors | Fork PRs get a label and a welcome comment |
| Jira links | `[PROJ-123]` in a PR title becomes a link with the ticket title |

The rules live in a config file, not in code. The action loads it from a GitHub repo, from S3, or from a bundled default, in that order, and validates it against a JSON Schema. One org-level config governs many repos, and a reusable workflow keeps each repo's setup down to a few lines.

## The trigger that scares people

Review Router runs on `pull_request_target`. That trigger runs the workflow from the base branch with secrets available, which is why fork PRs work. It's also the trigger behind "pwn requests": check out the PR's code, run it, and the attacker's script now has your secrets.

So the rule is strict. The action never checks out PR code and never executes it. It reads the PR through the API and nothing else. The workflow file carries a comment that says `Do NOT add actions/checkout`, because the next person to edit it won't remember why. The full reasoning is in [the security doc](https://github.com/datarobot-oss/review-router/blob/main/docs/security/pull-request-target.md), and GitHub Security Lab has the [canonical write-up](https://securitylab.github.com/resources/github-actions-preventing-pwn-requests/) of the attack.

The trade-off is a platform limit. GitHub withholds secrets from review and comment events tied to fork PRs. Fork PRs still get routed and labeled, but they never get an approval reaction or a Slack thread reply. No config option fixes that, so it's in the troubleshooting doc instead.

## Teaching it to review

Routing tells humans where to look. I wanted something that reads the diff too. Cursor's [Bugbot](https://cursor.com/docs/bugbot) does that, and I wanted a reviewer of our own, running on infrastructure we control, that we can later tune on what our engineers accept and reject.

The pipeline runs inside the same action. It triggers on the ready label or an `/ai-review` comment:

```
ready label or /ai-review
  → gates: enabled repo, token, PR open, same repo, trusted author
  → download the PR as a tarball (never checked out, never run)
  → context/: diff, description, file history, caller map, repo rules
  → read-only Claude Code sessions, in parallel:
      claims pass   checks the PR's claims and the callers of changed functions
      rules pass    checks the diff against the repo's review rules
  → one scorer session per candidate finding, keep score >= 70
  → one review with inline comments (never approves, never requests changes)
```

A review takes about 5 minutes and costs about $1 to $1.50 at list price, with a hard-ish budget cap. Four decisions shaped it.

**Claude Code is the agent loop.** I run it headless with `claude -p` instead of writing my own loop. Tools, turn caps, budget caps, and JSON-schema output come free. The catch is that our LLM gateway speaks OpenAI-style chat, not the Anthropic Messages API, so a local LiteLLM proxy translates between the two.

**The reviewer reads a tarball, never a checkout.** Sessions get `Read`, `Grep`, and `Glob`, and nothing else. They can't leave the workspace. Symlinks and `.claude/` directories are stripped from the PR's files, since a PR could plant settings there. Review rules come from the base branch, so a PR can't rewrite the rules that judge it.

**Passes propose, a scorer disposes.** Each candidate finding goes to a fresh session that tries to disprove it. I use Sonnet for that job, not Haiku. In the spike, Haiku scored nearly everything 65 to 85. It gave a false positive and a confirmed bug the same 75. Sonnet spread the same candidates from 15 to 85.

**Failure never looks like a clean bill of health.** A timeout, a skipped budget, or a failed scorer posts "couldn't finish" with the reason. "No issues found" has to mean that no issues were found.

There's also a place for teaching it manners. A maintainer can drop a markdown file into `.github/ai-review/precedents/` that records a past ruling. Mark it `false-positive`, and the scorers give any matching finding a 0. Mark it `real`, and the passes look harder for that bug class. Like the rules, precedents come from the base branch, so a ruling gets reviewed like code.

## Three bugs I enjoyed

**The cache that wasn't.** My first spike runs showed zero cache-read tokens and 4 to 6 million uncached input tokens on big PRs. LiteLLM's native provider for our gateway stripped the `cache_control` markers. Routing through its `openai/*` provider kept them. The rerun read 3.87 million tokens from cache. Uncached, that input alone would have cost about $7.70, and the whole run cost $2.29. The same rerun also took 57 turns against 8 for the first, on the same PR. Turn count varied 7x between identical runs, so turn and budget caps are mandatory, not tuning.

**The Chinese Jira card.** A Jira link comment on one PR showed the issue type as 子任务 instead of Sub-task. The account locale was fine. Node's `fetch` sends `Accept-Language: *`, and Jira answers `*` in Chinese. The fix is one header: `Accept-Language: en`.

**The pass that ran out of turns.** The rules pass burned all 11 of its turns on a small formatting PR. A session that hits its turn cap returns no structured output at all. So the pipeline salvages it: resume the session with tools switched off and a "stop, answer now" prompt. My first attempt kept the tools on, and the model kept calling them.

## The scoreboard

The spike ran against [datarobot-oss/cli](https://github.com/datarobot-oss/cli), on five PRs. Three had seven bugs that Bugbot found and the authors confirmed. Two were clean PRs where Bugbot found nothing.

| Metric | Result |
| --- | --- |
| Bugbot's confirmed findings matched | 1 and 2 of 7, across two runs |
| False positives on clean PRs | 0 |
| Time per review | median about 5.5 minutes |
| Cost per review | about $1.20 at list price |

Read those numbers with two caveats. The sample favors Bugbot, because I picked PRs where it found something. And the same config on the same PR finds different bugs from run to run. The Sonnet scorer also rates one confirmed Bugbot bug, an aliased value, at 55 to 60 every single time. That's a steady blind spot, not noise, so it's going into the future benchmark as a test.

On the live side, the pipeline has reviewed Review Router's own PRs twice. Both runs found nothing, at $0.15 and $0.24. Real bugs caught in production so far: zero. The next phase exists to change that number, or to tell me why it can't change.

## What's next

These are ideas, ordered by how soon I want them:

- **Shadow Bugbot for two weeks.** Turn the reviewer on for a busy repo that Bugbot already covers, and keep a scoreboard: bugs both caught, bugs only we caught, bugs only Bugbot caught.
- **A feedback loop.** Reviewers react with 👍 or 👎 on each finding. A 👎 could open a draft precedent PR, and the reactions add up to a labeled dataset.
- **Suggestions and incremental reviews.** Post small fixes as one-click `suggestion` blocks, and review only the new commits after a push.
- **A benchmark harness.** Replay PRs with known bugs at their original commits and report recall, precision, cost, and time with one command. The spike did this by hand, and by hand it doesn't scale.
- **A smaller scorer.** With a labeled dataset, the scorer is the cheapest piece to swap for a fine-tuned model: it's small, it only judges, and it runs once per candidate.
- **A reviewer's copilot.** Instead of findings, post a guided tour of the PR: where to start, what changed behavior, and which callers to check.

## Try it

Review Router is Apache 2.0. Setup is one workflow file and a config, and the AI review is opt-in per repo.

- [Review Router on GitHub](https://github.com/datarobot-oss/review-router) and its [GitHub App](https://github.com/apps/datarobot-pr-review-router)
- [Basic setup](https://github.com/datarobot-oss/review-router/blob/main/docs/setup/basic.md) and [AI review setup](https://github.com/datarobot-oss/review-router/blob/main/docs/setup/ai-review.md)
- [About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners), the GitHub feature the routing builds on
- [Run Claude Code programmatically](https://code.claude.com/docs/en/headless), for `claude -p`, JSON schemas, and cost output
- [LiteLLM's OpenAI provider](https://docs.litellm.ai/docs/providers/openai), the route that kept prompt caching alive
