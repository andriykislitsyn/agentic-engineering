# guard-hooks

A PreToolUse hook for rules that a glob in `permissions.deny` can't express. It's the generic core of the guard described in [How I set up Claude Code](https://andriykislitsyn.github.io/agentic-engineering/articles/how-i-set-up-claude-code/).

## Install

```bash
claude plugin marketplace add andriykislitsyn/agentic-engineering
claude plugin install guard-hooks@agentic-engineering
```

## What it blocks

| Tool | Rule | Decision |
| --- | --- | --- |
| Bash | `gh api` calls that write: `-X POST` and friends, `-f` or `-F` on a REST endpoint, `--input`, GraphQL mutations. GET reads and GraphQL queries pass | deny |
| Bash | `git reset --hard`, in any argument position | deny |
| Bash | `GIT_DIR=` and `GIT_WORK_TREE=` overrides | deny |
| Bash | `git commit` when `origin/<branch>` has commits you lack | deny |
| Bash | `git commit --amend` when HEAD is already on a remote | deny |
| Bash | Printing a secret: `echo $MY_TOKEN`, `printenv MY_TOKEN`, `cat ~/.cloud/staging.token`, a bare `env` or `export -p` | deny |
| Bash, Read, Grep | Reading a shell profile such as `~/.zshrc` | ask |
| Read, Grep | Token files under a dot directory in the home folder | deny |

A denial prints the fix on stderr, and Claude reads it and retries. The `ask` rules show the usual permission prompt.

## Why a hook and not a deny rule

A deny rule matches command text. `git -C repo push` and `env GIT_DIR=x git push` slip past `Bash(git push *)`. A `gh api` call turns into a POST as soon as it has `-f`, and a GraphQL query is a POST that only reads. No pattern separates those cases, so the hook tokenizes the command, drops heredoc bodies, and decides per call.

## Limits

- It catches accidents, not adversaries. A command built from an encoded string gets through.
- The token-file rule is a heuristic: a file whose name contains `token`, in a dot directory under `~`, `$HOME`, `/Users/<name>`, or `/home/<name>`. Edit `SECRET_FILE_PATTERN` in `hooks/guard.py` for your layout.
- A crash in the hook exits 1, which doesn't block. The tests are what show the guard still denies.
- Commands run through `bash -c`, `eval`, or a script file aren't parsed.

## Test

From the repository root:

```bash
python3 -m unittest discover -s plugins/guard-hooks/tests -v
```

CI runs the same command on every PR that touches this plugin. The tests cover each rule with an allow case and a deny case, build real git repositories for the push-state rules, and check that `hooks.json` points at the script and its matcher covers every tool the script handles.
