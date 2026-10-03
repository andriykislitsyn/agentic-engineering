---
name: permission-rules
description: Use when adding, debugging, or reasoning about Claude Code permission rules in settings.json. Explains why a Bash command prompted, how allow and deny patterns match (`:*`, space before `*`, compound commands), and which commands prompt regardless of rules (`source`, `curl`, `cd` inside a compound command). Use the `update-config` skill to make the settings.json edit itself.
---

# Claude Code permission rules

- Compound commands split on `&&`, `||`, `;`, `|`, and every part must match an allow rule. `workon myenv && black file.py` needs both `Bash(workon myenv)` and `Bash(black:*)`.
- `:*` is a wildcard only at the end of a pattern and equals a trailing ` *`. Mid-pattern wildcards use the space form: `Bash(git -C * push *)` works, `Bash(git -C * push:*)` doesn't.
- A space before `*` enforces a word boundary: `Bash(ls *)` matches `ls -la` but not `lsof`; `Bash(ls*)` matches both.
- Read-only commands need no rules: `ls`, `cat`, `echo`, `pwd`, `head`, `tail`, `grep`, `find`, `wc`, `which`, `diff`, `stat`, `du`, standalone `cd`, and read-only `git`.
- `cd` inside a compound command always prompts, as do `pushd`, `popd`, subshells, `env -C`, and `sh -c`. Use the tool's own directory flag (`npm run --prefix`, `task --dir`, `make -C`, `git -C`).
- `source` and `curl` prompt regardless of rules; no pattern allows them. Call the venv Python directly (`.venv/bin/python -m pytest`) instead of `source activate && pytest`, and use `WebFetch` instead of `curl`.
- One-liners that differ on every run (`python3 -c '...'`) can't be allowlisted safely: `Bash(python3 -c *)` allows arbitrary code. Move the code into a script at a fixed path and allow only that invocation, `Bash(python3 /tmp/cluster-probe.py)`. Rewrite the script between runs, and the one rule keeps covering it.
