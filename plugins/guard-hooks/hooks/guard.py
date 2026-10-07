#!/usr/bin/env python3
"""PreToolUse guard for rules that a glob in permissions.deny can't express.

Reads the hook payload on stdin. A violation exits 2 with the fix on stderr, which
Claude Code feeds back to the model. A rule that needs a human call prints a JSON
"ask" decision instead. An internal error exits 1 (non-blocking) so a bug in this
file never wedges a session.

Rules:
  Bash       gh api writes (GraphQL queries and GET reads pass), git reset --hard,
             GIT_DIR and GIT_WORK_TREE overrides, a commit when origin is ahead,
             an amend of a pushed commit, and printing secrets (token variables,
             token files, environment dumps).
  Read/Grep  token files, and shell profiles (ask).

Why globs are not enough: deny rules match command text. `git -C repo push`,
`env GIT_DIR=x git push`, and a `gh api` call that turns into a POST because of `-f`
all slip past a pattern. This script parses the command instead.
"""
import json
import os
import re
import shlex
import subprocess
import sys
from collections import namedtuple

HEREDOC_RE = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1")
# A token file under a dot directory in the home folder, such as ~/.cloud/staging.token.
SECRET_FILE_PATTERN = r"(?:~|\$HOME|/Users/[^/\s]+|/home/[^/\s]+)/\.[\w-]+/[^/\s]*token[^/\s]*"
SECRET_FILE_RE = re.compile(SECRET_FILE_PATTERN, re.I)
SENSITIVE_DOTFILE_RE = re.compile(r"(?:^|/)\.(?:zshrc|zshenv|bashrc|bash_profile|netrc)$")
SECRET_VAR_RE = re.compile(r"\$\{?(?!#)[A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_?KEY)[A-Za-z0-9_]*(?![A-Za-z0-9_])(?!:\+)", re.I)
SECRET_NAME_RE = re.compile(r"token|secret|password|api_?key", re.I)
ECHO_CAT_SECRET_RE = re.compile(r"\b(?:echo|printf)\b[^;&|\n]*\$\(\s*cat\b[^)]*(?:%s)" % SECRET_FILE_PATTERN, re.I)
PRINTERS = {"cat", "head", "tail", "less", "more", "bat", "xxd", "od", "strings", "base64", "nl", "tac", "rev", "sed", "awk", "grep", "egrep", "rg", "cut"}
LEAK_HINT = (
    "This would print a secret into the transcript. Use the variable or file without printing it "
    "(`$MY_API_TOKEN` in a header is fine), or ask the user to check it."
)
ENV_DUMP_HINT = "Dumping the environment prints every token in it. Ask for one non-secret variable, for example `printenv HOME`."
GIT_ENV_OVERRIDE_RE = re.compile(r"(?:^|[\s;&|(])(?:export\s+)?GIT_(?:DIR|WORK_TREE)=")
SEPARATOR_CHARS = set(";&|()<>\n")
GH_API_VALUE_FLAGS = {"-H", "--header", "-q", "--jq", "-t", "--template", "--hostname", "--cache", "-p", "--preview"}
GH_API_FIELD_FLAGS = {"-f", "-F", "--field", "--raw-field"}
GH_API_HINT = (
    "gh api calls that write post under the user's name. Reads work: use `--jq`, and GraphQL queries "
    "(`-f query='query {...}'`) are allowed. Mutations, POST/PUT/PATCH/DELETE, and --input are not. Hand the command over instead."
)


class Violation(Exception):
    """A rule was broken. `ask` prompts the user instead of denying outright."""

    def __init__(self, message, ask=False):
        super().__init__(message)
        self.ask = ask


def strip_heredoc_bodies(command):
    """Drop heredoc bodies that sit outside quotes, so script text is not read as shell commands.

    A heredoc inside a quoted string, such as a `git commit -m "$(cat <<'EOF' ...)"` message, is kept.
    """
    out, i, quote = [], 0, None
    while i < len(command):
        char = command[i]
        if quote:
            out.append(char)
            if char == "\\" and quote == '"' and i + 1 < len(command):
                out.append(command[i + 1])
                i += 1
            elif char == quote:
                quote = None
            i += 1
        elif char in "'\"":
            quote = char
            out.append(char)
            i += 1
        elif char == "\\" and i + 1 < len(command):
            out.append(command[i:i + 2])
            i += 2
        elif command.startswith("<<", i) and not command.startswith("<<<", i):
            match = HEREDOC_RE.match(command, i)
            if not match:
                out.append(char)
                i += 1
                continue
            out.append(match.group(0))
            i = match.end()
            newline = command.find("\n", i)
            if newline == -1:
                out.append(command[i:])
                break
            out.append(command[i:newline + 1])
            i = newline + 1
            end = re.search(r"^[ \t]*%s[ \t]*$" % re.escape(match.group(2)), command[i:], re.M)
            i = i + end.end() if end else len(command)
        else:
            out.append(char)
            i += 1
    return "".join(out)


# tokens: argv of one command. sep: the operator that follows it ("|", "&&", ">", ...).
# captured: the command runs inside $( ), so its output is consumed, not shown.
Call = namedtuple("Call", "tokens sep captured")


def tokenize(command):
    """Split a shell command into Calls. Returns None if unparseable."""
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
        lex.whitespace = " \t\r"
        lex.whitespace_split = True
        lex.commenters = ""
        tokens = list(lex)
    except ValueError:
        return None
    calls, current, substitutions, previous = [], [], [], ""
    for token in tokens:
        if set(token) <= SEPARATOR_CHARS:
            if current:
                calls.append(Call(current, token, any(substitutions)))
            current = []
            for char in token:
                if char == "(":
                    substitutions.append(previous.endswith("$"))
                elif char == ")" and substitutions:
                    substitutions.pop()
        else:
            current.append(token)
        previous = token
    if current:
        calls.append(Call(current, "", any(substitutions)))
    return calls


def strip_env_prefix(call):
    """Drop leading `env` and VAR=value tokens."""
    i = 0
    while i < len(call) and (call[i] == "env" or re.match(r"^\w+=", call[i])):
        i += 1
    return call[i:]


def parse_git(call):
    """Return (repo_dir, subcommand, args) for a git call, or None for any other command."""
    call = strip_env_prefix(call)
    if not call or os.path.basename(call[0]) != "git":
        return None
    repo, i = None, 1
    while i < len(call) and call[i].startswith("-"):
        if call[i] == "-C" and i + 1 < len(call):
            repo = call[i + 1]
        i += 2 if call[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
    if i >= len(call):
        return None
    return repo, call[i], call[i + 1:]


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=10)


def check_push_state(repo, amend):
    """Deny a commit when origin/<branch> is ahead, or an amend would rewrite a pushed commit."""
    try:
        branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if not branch or branch == "HEAD":
            return
        git(repo, "fetch", "origin", branch)
        remote_ref = f"refs/remotes/origin/{branch}"
        if git(repo, "rev-parse", "--verify", "--quiet", remote_ref).returncode == 0:
            behind = int(git(repo, "rev-list", "--count", f"HEAD..{remote_ref}").stdout.strip() or 0)
            if behind:
                raise Violation(
                    f"origin/{branch} has {behind} commit(s) you lack (bots push to PR branches). "
                    f"Run `git fetch origin {branch}` then `git merge --ff-only origin/{branch}` as a separate command first. "
                    f"If the branches diverged, run `git merge origin/{branch}` instead."
                )
        if amend and git(repo, "branch", "-r", "--contains", "HEAD").stdout.strip():
            raise Violation(
                "HEAD is already on a remote. Do not amend a pushed commit. Add a new commit instead. "
                "If a past amend already diverged from the pushed tip: `git reset --soft origin/<branch>`, "
                "commit the staged delta, and hand over a plain push."
            )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return


def gh_api_violation(args):
    """Return a Violation for a `gh api` call that writes, else None. GraphQL queries and GET reads pass."""
    method, fields, endpoint, has_input, i = None, [], None, False, 0
    while i < len(args):
        arg = args[i]
        value = args[i + 1] if i + 1 < len(args) else ""
        if arg in ("-X", "--method"):
            method, i = value, i + 1
        elif arg.startswith("--method="):
            method = arg.split("=", 1)[1]
        elif arg.startswith("-X") and len(arg) > 2:
            method = arg[2:]
        elif arg in GH_API_FIELD_FLAGS:
            fields.append(value)
            i += 1
        elif arg.startswith(("--field=", "--raw-field=")):
            fields.append(arg.split("=", 1)[1])
        elif arg == "--input" or arg.startswith("--input="):
            has_input = True
            i += arg == "--input"
        elif arg in GH_API_VALUE_FLAGS:
            i += 1
        elif not arg.startswith("-") and endpoint is None:
            endpoint = arg
        i += 1

    if has_input or (method and method.upper() not in ("GET", "HEAD")):
        return Violation(GH_API_HINT)
    if fields and not method:
        if (endpoint or "").strip("/") != "graphql":
            return Violation(GH_API_HINT)  # REST fields turn the call into a POST
        for field in fields:
            key, _, text = field.partition("=")
            if key != "query":
                continue
            if text.startswith("@"):
                try:
                    with open(os.path.expanduser(text[1:])) as f:
                        text = f.read()
                except OSError:
                    return Violation(GH_API_HINT)
            if re.search(r"\bmutation\b", text, re.I):
                return Violation(GH_API_HINT)
    return None


def is_env_dump(call):
    """True for a bare command that lists every environment variable."""
    name, args = os.path.basename(call.tokens[0]), call.tokens[1:]
    if call.sep in (">", ">>"):
        return False
    return (name in ("env", "printenv", "set") and not args) or (name in ("export", "declare", "typeset") and args in ([], ["-p"]))


def secret_violations(calls, command):
    """Flag commands that print a token into the transcript. Catches accidents, not adversaries."""
    found = []
    if ECHO_CAT_SECRET_RE.search(command):
        found.append(Violation(LEAK_HINT))
    for call in calls:
        if call.captured:
            continue
        bare = strip_env_prefix(call.tokens)
        name, args = (os.path.basename(bare[0]), bare[1:]) if bare else ("", [])
        if name in ("echo", "printf") and any(SECRET_VAR_RE.search(a) for a in args):
            found.append(Violation(LEAK_HINT))
        elif name in PRINTERS and any(SECRET_FILE_RE.search(a) for a in args):
            found.append(Violation(LEAK_HINT))
        elif name in PRINTERS and any(SENSITIVE_DOTFILE_RE.search(a) for a in args):
            found.append(Violation("This prints a shell profile that holds tokens. Confirm it is intended.", ask=True))
        elif name == "printenv" and any(SECRET_NAME_RE.search(a) for a in args):
            found.append(Violation(LEAK_HINT))
        elif is_env_dump(call):
            found.append(Violation(ENV_DUMP_HINT))
    return found


def check_bash(payload):
    command = payload["tool_input"].get("command", "")
    cwd = payload.get("cwd") or os.getcwd()
    violations = []

    if GIT_ENV_OVERRIDE_RE.search(command):
        violations.append(Violation("GIT_DIR and GIT_WORK_TREE overrides bypass the permission deny rules. Use `git -C <dir>`."))

    calls = tokenize(strip_heredoc_bodies(command)) or []
    violations.extend(secret_violations(calls, command))
    for c in calls:
        call = c.tokens
        bare = strip_env_prefix(call)
        if bare and os.path.basename(bare[0]) == "gh" and bare[1:2] == ["api"]:
            try:
                found = gh_api_violation(bare[2:])
            except Exception:  # fail closed: an allow rule for `gh api` would otherwise let a write through
                found = Violation("Could not verify this gh api call. " + GH_API_HINT)
            if found:
                violations.append(found)
        parsed = parse_git(call)
        if not parsed:
            continue
        repo, sub, args = parsed
        repo = os.path.expanduser(repo) if repo else cwd
        if not os.path.isabs(repo):
            repo = os.path.join(cwd, repo)

        if sub == "commit":
            try:
                check_push_state(repo, amend="--amend" in args)
            except Violation as v:
                violations.append(v)
        if sub == "reset" and "--hard" in args:
            violations.append(Violation("git reset --hard discards work. Hand the command over, or use `git stash` or `git restore` instead."))

    return violations


def check_read(payload):
    tool_input = payload["tool_input"]
    paths = [tool_input.get(key, "") for key in ("file_path", "path", "glob")]
    if any(SECRET_FILE_RE.search(p) for p in paths):
        return [Violation(LEAK_HINT)]
    if any(SENSITIVE_DOTFILE_RE.search(p) for p in paths):
        return [Violation("This reads a shell profile that holds tokens. Confirm it is intended.", ask=True)]
    return []


CHECKS = {
    "Bash": check_bash,
    "Read": check_read,
    "Grep": check_read,
}


def main():
    payload = json.load(sys.stdin)
    check = CHECKS.get(payload.get("tool_name"))
    violations = check(payload) if check else []
    denials = [v for v in violations if not v.ask]
    if denials:
        sys.stderr.write("\n".join(str(v) for v in denials) + "\n")
        sys.exit(2)
    if violations:
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": " ".join(str(v) for v in violations),
        }}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # fail open, visibly
        sys.stderr.write(f"guard.py error, rule check skipped: {exc!r}\n")
        sys.exit(1)
