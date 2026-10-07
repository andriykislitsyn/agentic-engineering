---
title: How I set up Claude Code
description: Five layers, each rule where it gets enforced. Permissions and hooks for hard stops, an output style for tone, CLAUDE.md for judgment, skills for depth.
pubDate: 2026-09-26
updatedDate: 2026-10-07
tags: [claude-code, permissions, hooks, workflow]
---

I use Claude Code every day for platform work: CI/CD, infrastructure as code, and the services behind AI agents. My first setup was one long `CLAUDE.md` that grew a rule every time something annoyed me. It worked, but it got long, and a long list of rules is a list the model follows most of the time.

The current setup is built on one idea. Put each rule where it gets enforced. The settings, output style, and `CLAUDE.md` are in my [dotfiles](https://github.com/andriykislitsyn/dotfiles/tree/main/claude-code). The hooks described below aren't published yet.

| Layer | File | What it holds |
| --- | --- | --- |
| Hard stops | `settings.json` | Things Claude must never do, matched by command text |
| Checks | `hooks/` | Rules that need to parse a command or read the session |
| Tone | `output-styles/direct.md` | How Claude talks to me |
| Judgment | `CLAUDE.md` | How I want work done |
| Depth | `skills/` | Detail that loads only when a task needs it |

## Hard stops live in permissions, not prose

A rule in `CLAUDE.md` is a request. A deny rule in `settings.json` is a wall. So anything destructive or outward-facing goes in the deny list:

```json
"deny": [
  "Bash(git push *)",
  "Bash(git -C * push *)",
  "Bash(env * git push *)",
  "Bash(git reset --hard *)",
  "Bash(git clean *)",
  "Bash(gh pr create *)",
  "Bash(gh pr comment *)",
  "Bash(gh api -X *)"
],
"ask": [
  "Bash(git reset *)"
]
```

Claude never pushes, never hard-resets, and never posts to GitHub under my name. When it's time to push, it hands me the exact command and I run it. That one habit made me comfortable letting it do everything else on its own. Deny beats ask, so `git reset --hard` stays blocked while a soft reset only prompts.

Deny rules match command text, so `git -C repo push` and `env GIT_DIR=... git push` slip past a plain `git push *` rule. Each variant needs its own pattern. That's where globs run out.

## Hooks check what globs can't read

A glob sees a string. It can't tell a read from a write when both use the same command. `gh api` is the clear case. A GraphQL query is a POST that only reads, while a `-f` flag turns a plain call into a POST that creates a comment. No pattern separates them.

So a PreToolUse hook parses the command. It strips heredoc bodies, splits the rest into calls, and decides. Exit code 2 with a message on stderr denies the call, and Claude reads the message and fixes it instead of guessing. The same hook checks what a rule can't express: commit message format and length, branch names, whether origin is ahead before a commit, and whether a ticket or PR draft loaded my drafting skill first.

Four things I learned the hard way:

- A hook that crashes exits 1, and exit 1 doesn't block. A bug can't wedge a session, but it can also turn the guard off without anyone noticing. Tests are the only thing that proves it still denies.
- Hooks run as `python3 -I`, so a script can't import its siblings. Each file stands alone.
- The first version read a heredoc body as shell. `set(...)` inside my own analysis script looked like a bare `set` command, and the guard blocked it. Stripping heredoc bodies before tokenizing fixed it.
- In auto mode, the permission classifier refused my edit that loosened a deny rule, because it counts as self-modification. Claude gave me the exact lines and I applied them by hand. That's the outcome I want.

## State lives on disk, not in the conversation

A long session ends in a compaction or a new session, and both lose whatever isn't on disk. I keep three things there:

- A `PROGRESS.md` per project under `.claude/projects/<ticket>-<name>/`. A short `## Current state` comes first, then next steps, decisions, learnings, and a dated log.
- Memory files for gotchas that outlive the ticket and can't be read from the code.
- A `checkpoint` skill that writes both when I say I'm compacting or wrapping up.

Hooks make it stick. On startup, resume, compact, and clear, a SessionStart hook injects only the Current state and Next sections of the matching `PROGRESS.md`. A PreCompact hook blocks a manual `/compact` once when no checkpoint was saved in the last 45 minutes. A second try within five minutes goes through, and auto-compaction is never blocked. A PostToolUse hook flags a `PROGRESS.md` with no Current state or a memory file with no index line. A Stop hook rejects a handoff that has a push command but no PR command.

The prompt cache expires while I'm away, so a resumed session pays full price for its whole context. With the state on disk, `/clear` plus the injected Current state is cheaper than a compaction summary. That's my default when I step away.

The SessionStart injection has fired after a compact in a live session. The PreCompact block and the injection after `/clear` are unit-tested only so far.

## Permission gotchas that cost me prompts

The allow list is the other half: read-only commands, linters, and test runners run without asking. These are the rules I wish I'd known on day one:

- Compound commands split on `&&`, `||`, `;`, and `|`, and every part must match an allow rule.
- `cd` inside a compound command always prompts, whatever your rules say. Use the tool's own directory flag instead: `git -C`, `make -C`, `npm run --prefix`.
- `:*` works as a wildcard only at the end of a pattern. In the middle, use the space form: `Bash(git -C * push *)`.
- `gh api ... | python3 -c ...` is two commands, and the second one prompts. `gh api ... --jq '...'` is one command with full jq syntax.
- For repeated investigations, keep a script at a fixed path and rewrite its contents between runs. One allow rule for `python3 /tmp/probe.py` covers every version of it.

I keep these in a small [`permission-rules`](https://github.com/andriykislitsyn/agentic-engineering/tree/main/plugins/permission-rules) plugin, so Claude can explain its own prompts.

## Tone lives in an output style

The output style is the persona layer. Mine is called Direct, and it's short:

> Tell me what you actually think. Push back hard on bad ideas, including mine, and point out weak spots and blind spots even when I didn't ask. If I seem to want validation more than truth, say so.

It also asks for the conclusion first, and for discussion before any decision that matters. With `keep-coding-instructions: true`, Claude Code's built-in engineering instructions stay in place, so I only change how it talks, not how it codes.

## Judgment lives in CLAUDE.md

Current models have strong judgment, and a pile of rigid rules makes them worse. So my `CLAUDE.md` follows a few principles:

- Prefer judgment over rules. "Match the surrounding comment style" beats a list of banned patterns. Save NEVER and MUST for secrets, destructive operations, and formats other tools parse.
- Keep only what Claude can't infer. Repo gotchas and team conventions belong. Anything it can learn from the code or from training doesn't.
- Move depth out. Checklists, API references, and long procedures go into skills that load on demand.
- Delete what a hook enforces. The commit format, the handoff steps, and the draft structure moved into a hook or a skill, and the file keeps a one-line pointer. It shrank from 28 KB to 20 KB.

The rest of the file is how I want work done. Minimal diffs, no speculative abstractions, no error handling for cases that can't happen. Check live git state before judging a branch, because I push and open PRs outside the session. Amend only commits that were never pushed. Ask "Ready to commit?" and wait.

## Writing rules surprised me the most

The biggest quality jump came from rules about text, not code. Claude writes a lot for me: commit messages, PR descriptions, ticket comments, review replies. All of it goes out under my name.

Every comment or document gets two passes. The first pass deletes anything the diff already shows, any narration of how the work was done, and baseline effort like "linters pass." The second pass compresses: one idea per sentence, no hedges.

Voice rules came next. I'm not a native English speaker. Polished, essay-grade prose doesn't read like me, and colleagues notice. So the rules ask for short sentences, simple words, rounded numbers, and no em dashes. They also ban a pattern I kept seeing: phrases like "the honest answer is" or "worth noting" that announce candor instead of just saying the thing.

Length targets have a source. People stop reading somewhere between 50 and 125 words, and working memory holds about four items. So a PR comment aims for about 50 words, and a PR description for about 150.

## Depth lives in skills and plugins

Skills are markdown files that load when a task matches their description. I install third-party skills by symlink, so a `git pull` updates them. These plugins are always on:

- **superpowers**: brainstorming before building, systematic debugging, TDD, and verification before claiming anything works.
- **pr-review-toolkit**: specialized reviewers for comments, tests, types, and silent failures.
- **remember**: session memory that carries context across days.
- **claude-md-management** and **skill-creator**: keep `CLAUDE.md` and skills in shape as they grow.

Every skill's description sits in the prompt of every session, fired or not. `skillOverrides` in `settings.json` can switch a skill off or leave only its name. I turned off 27 I don't use, which saved about 2,300 prompt tokens per session. I measured it.

Subagents cost tokens and context, so a hook prompts me on every spawn. Before any push, Claude offers a code review in a fresh context, and I pick whether it runs.

## Test the config like code

Config drifts without any error. A typo in a `skillOverrides` key is ignored. A deny rule can hide an ask rule. A hook can point at a script that moved. So the config has tests.

Each hook has unit tests with a positive and a negative case. A lint test reads the live `settings.json` and checks for duplicate rules, shadowed asks, hooks that point at missing scripts, and overrides that name skills that don't exist. It's more than 170 tests in total.

Skill triggering is the part a unit test can't reach. I run headless probes with `claude -p`, expose only the Skill tool, and record which skill fires on each prompt. The probes found one real gap. "Write a new skill" fired the right skill 1 time in 5 with my prompt-reminder hook off. After I rewrote the description it fired 8 times in 8.

## Keep work rules private

Half my real setup is about my employer: internal tools, ticket conventions, environment access. None of that belongs in public. The published files are a sanitized copy with placeholders like `PROJ-1234` and `your-org`.

One gotcha if you publish yours. If your global gitignore excludes `CLAUDE.md` (mine did, to keep personal notes out of work repos), your dotfiles copy is ignored too. You need `git add -f`. My README linked to that file for months before I noticed it was never committed.

## What actually changed

The config matters less than the habits it enables:

1. I review more than I type. Claude drafts, I direct and decide.
2. I'm the last gate on anything irreversible. Claude does the work, and I run the push.
3. The rules keep evolving. When Claude does something I don't like, I add a rule. When a rule stops earning its place, I delete it.

The skills in this repo's plugins come with eval suites you can run yourself. Skills, MCP servers, and RAG pipelines are code, and they deserve tests and CI like any other code.
