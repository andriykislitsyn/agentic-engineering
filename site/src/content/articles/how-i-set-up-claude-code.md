---
title: How I set up Claude Code
description: Four layers, each rule where it gets enforced. Permissions for hard stops, an output style for tone, CLAUDE.md for judgment, skills for depth.
pubDate: 2026-09-26
---

I use Claude Code every day for platform work: CI/CD, infrastructure as code, and the services behind AI agents. My first setup was one long `CLAUDE.md` that grew a rule every time something annoyed me. It worked, but it got long, and a long list of rules is a list the model follows most of the time.

The current setup is built on one idea. Put each rule where it gets enforced. The full config is in my [dotfiles](https://github.com/andriykislitsyn/dotfiles/tree/main/claude-code).

| Layer | File | What it holds |
| --- | --- | --- |
| Hard stops | `settings.json` | Things Claude must never do, enforced by the harness |
| Tone | `output-styles/direct.md` | How Claude talks to me |
| Judgment | `CLAUDE.md` | How I want work done |
| Depth | `skills/` | Detail that loads only when a task needs it |

## Hard stops live in permissions, not prose

A rule in `CLAUDE.md` is a request. A deny rule in `settings.json` is a wall. So anything destructive or outward-facing goes in the deny list:

```json
"deny": [
  "Bash(git push *)",
  "Bash(git reset *)",
  "Bash(git clean *)",
  "Bash(git -C * push *)",
  "Bash(env * git push *)",
  "Bash(gh pr create *)",
  "Bash(gh pr comment *)",
  "Bash(gh api -X *)",
  "Bash(gh api * -f *)"
]
```

Claude never pushes, never rewrites history, and never posts to GitHub under my name. When it's time to push, it hands me the exact command and I run it. That one habit made me comfortable letting it do everything else on its own.

Two details took me a while to get right. Deny rules match command text, so `git -C repo push` and `env GIT_DIR=... git push` slip past a plain `git push *` rule. Each variant needs its own pattern. Also, `gh api` switches to POST as soon as you pass `-f` or `--field`, so a read-only-looking call can create a comment. The deny list covers those flags too.

## Permission gotchas that cost me prompts

The allow list is the other half: read-only commands, linters, and test runners run without asking. These are the rules I wish I'd known on day one:

- Compound commands split on `&&`, `||`, `;`, and `|`, and every part must match an allow rule.
- `cd` inside a compound command always prompts, whatever your rules say. Use the tool's own directory flag instead: `git -C`, `make -C`, `npm run --prefix`.
- `:*` works as a wildcard only at the end of a pattern. In the middle, use the space form: `Bash(git -C * push *)`.
- `gh api ... | python3 -c ...` is two commands, and the second one prompts. `gh api ... --jq '...'` is one command with full jq syntax.
- For repeated investigations, keep a script at a fixed path and rewrite its contents between runs. One allow rule for `python3 /tmp/probe.py` covers every version of it.

I keep these in a small [`claude-permissions`](https://github.com/andriykislitsyn/dotfiles/tree/main/claude-code/skills/claude-permissions) skill, so Claude can explain its own prompts.

## Tone lives in an output style

The output style is the persona layer. Mine is called Direct, and it's short:

> Tell me what you actually think. Push back hard on bad ideas, including mine, and point out weak spots and blind spots even when I didn't ask. If I seem to want validation more than truth, say so.

It also asks for the conclusion first, and for discussion before any decision that matters. With `keep-coding-instructions: true`, Claude Code's built-in engineering instructions stay in place, so I only change how it talks, not how it codes.

## Judgment lives in CLAUDE.md

Current models have strong judgment, and a pile of rigid rules makes them worse. So my `CLAUDE.md` follows a few principles:

- Prefer judgment over rules. "Match the surrounding comment style" beats a list of banned patterns. Save NEVER and MUST for secrets, destructive operations, and formats other tools parse.
- Keep only what Claude can't infer. Repo gotchas and team conventions belong. Anything it can learn from the code or from training doesn't.
- Move depth out. Checklists, API references, and long procedures go into skills that load on demand.

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

Subagents cost tokens and context, so my `CLAUDE.md` says to ask before spawning one. Before any push, Claude offers a code review in a fresh context, and I pick whether it runs.

## Keep work rules private

Half my real setup is about my employer: internal tools, ticket conventions, environment access. None of that belongs in public. The published files are a sanitized copy with placeholders like `PROJ-1234` and `your-org`.

One gotcha if you publish yours. If your global gitignore excludes `CLAUDE.md` (mine did, to keep personal notes out of work repos), your dotfiles copy is ignored too. You need `git add -f`. My README linked to that file for months before I noticed it was never committed.

## What actually changed

The config matters less than the habits it enables:

1. I review more than I type. Claude drafts, I direct and decide.
2. I'm the last gate on anything irreversible. Claude does the work, and I run the push.
3. The rules keep evolving. When Claude does something I don't like, I add a rule. When a rule stops earning its place, I delete it.

Next up: testing all of this. Skills, MCP servers, and RAG pipelines are code, and they deserve tests and CI like any other code.
