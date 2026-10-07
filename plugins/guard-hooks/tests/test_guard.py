"""Tests for hooks/guard.py. Run from the repo root: python3 -m unittest discover -s plugins/guard-hooks/tests -v"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(PLUGIN, "hooks", "guard.py")
BRANCH = "feature"


def run_guard(tool_name, tool_input, cwd="/tmp"):
    """Run the hook. Returns (decision, text): decision is allow, deny, or ask."""
    payload = {"tool_name": tool_name, "tool_input": tool_input, "cwd": cwd}
    proc = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(payload), capture_output=True, text=True)
    if proc.returncode == 2:
        return "deny", proc.stderr
    assert proc.returncode == 0, proc.stderr
    if proc.stdout:
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        return out["permissionDecision"], out["permissionDecisionReason"]
    return "allow", ""


def bash(command, cwd="/tmp"):
    return run_guard("Bash", {"command": command}, cwd)


def sh(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class PluginManifestTest(unittest.TestCase):
    def test_hooks_json_runs_the_guard_script_that_exists(self):
        with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as f:
            config = json.load(f)
        entries = config["hooks"]["PreToolUse"]
        commands = [hook["command"] for entry in entries for hook in entry["hooks"]]
        self.assertEqual(len(commands), 1)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/guard.py", commands[0])
        self.assertTrue(os.path.isfile(GUARD))

    def test_matcher_covers_every_tool_the_guard_checks(self):
        with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as f:
            matcher = json.load(f)["hooks"]["PreToolUse"][0]["matcher"]
        with open(GUARD) as f:
            checked = re.search(r"CHECKS = \{(.*?)\n\}", f.read(), re.S).group(1)
        self.assertEqual(set(re.findall(r'"(\w+)":', checked)) - set(matcher.split("|")), set())


class PushStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.remote = os.path.join(root, "remote.git")
        self.work = os.path.join(root, "work")
        self.other = os.path.join(root, "other")
        sh("git", "init", "--bare", "-b", "main", self.remote, cwd=root)
        sh("git", "clone", self.remote, self.work, cwd=root)
        sh("git", "config", "user.name", "t", cwd=self.work)
        sh("git", "config", "user.email", "t@t", cwd=self.work)
        sh("git", "checkout", "-b", BRANCH, cwd=self.work)
        self.commit(self.work, "base")
        sh("git", "push", "-u", "origin", BRANCH, cwd=self.work)

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, repo, name):
        with open(os.path.join(repo, name), "w") as f:
            f.write(name)
        sh("git", "add", name, cwd=repo)
        sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", f"Add {name}", cwd=repo)

    def push_from_other_clone(self):
        sh("git", "clone", "-b", BRANCH, self.remote, self.other, cwd=self.tmp.name)
        self.commit(self.other, "bot-change")
        sh("git", "push", "origin", BRANCH, cwd=self.other)

    def test_commit_allowed_when_up_to_date(self):
        self.assertEqual(bash('git commit -m "Add thing"', cwd=self.work)[0], "allow")

    def test_commit_denied_when_remote_ahead(self):
        self.push_from_other_clone()
        decision, text = bash('git commit -m "Add thing"', cwd=self.work)
        self.assertEqual(decision, "deny")
        self.assertIn("merge --ff-only", text)

    def test_commit_with_dash_c_checks_that_repo_not_the_cwd(self):
        self.push_from_other_clone()
        self.assertEqual(bash(f'git -C {self.work} commit -m "Add thing"')[0], "deny")

    def test_commit_allowed_when_only_local_is_ahead(self):
        self.commit(self.work, "local-only")
        self.assertEqual(bash('git commit -m "Add thing"', cwd=self.work)[0], "allow")

    def test_amend_denied_for_pushed_commit(self):
        decision, text = bash("git commit --amend --no-edit", cwd=self.work)
        self.assertEqual(decision, "deny")
        self.assertIn("pushed", text)

    def test_amend_allowed_for_unpushed_commit(self):
        self.commit(self.work, "local-only")
        self.assertEqual(bash("git commit --amend --no-edit", cwd=self.work)[0], "allow")

    def test_repo_without_remote_allowed(self):
        solo = os.path.join(self.tmp.name, "solo")
        sh("git", "init", "-b", "main", solo, cwd=self.tmp.name)
        self.assertEqual(bash('git commit -m "Add thing"', cwd=solo)[0], "allow")


class CommandRulesTest(unittest.TestCase):
    def test_git_dir_override_denied(self):
        self.assertEqual(bash("GIT_DIR=/tmp/x git status")[0], "deny")
        self.assertEqual(bash("env GIT_WORK_TREE=/tmp/x git status")[0], "deny")

    def test_git_dash_c_allowed(self):
        self.assertEqual(bash("git -C /tmp status")[0], "allow")

    def test_ordinary_commands_allowed(self):
        self.assertEqual(bash("ls -la && echo done")[0], "allow")

    def test_unrelated_tool_allowed(self):
        self.assertEqual(run_guard("Glob", {"pattern": "*"})[0], "allow")


class HeredocBodyTest(unittest.TestCase):
    def test_script_body_is_not_read_as_shell(self):
        script = "python3 -I - <<'EOF'\nimport os\nprint(len(set([1, 2])))\nx = {'a': 1}\nEOF"
        self.assertEqual(bash(script)[0], "allow")

    def test_unbalanced_quote_in_body_does_not_disable_checks(self):
        script = "cat <<'EOF'\nit's a note with an unbalanced quote\nEOF\necho $MY_API_TOKEN"
        self.assertEqual(bash(script)[0], "deny")

    def test_command_after_heredoc_is_still_checked(self):
        script = "cat <<'EOF' > /tmp/note.txt\nhello\nEOF\nprintenv"
        self.assertEqual(bash(script)[0], "deny")

    def test_heredoc_inside_quotes_is_still_checked(self):
        script = 'echo "$(cat <<\'EOF\'\nhello\nEOF\n)" && printenv'
        self.assertEqual(bash(script)[0], "deny")

    def test_here_string_is_not_a_heredoc(self):
        self.assertEqual(bash("grep -c a <<< 'banana'")[0], "allow")


class GhApiTest(unittest.TestCase):
    def test_reads_and_graphql_queries_allowed(self):
        for command in (
            "gh api repos/o/r/pulls --jq '.[].number'",
            "gh api graphql -f query='query { viewer { login } }' --jq .data.viewer.login",
            "gh api graphql -F owner=o -f query='query($owner:String!){ repositoryOwner(login:$owner){ login } }'",
            "gh api graphql --paginate -f query='query { viewer { login } }'",
            "gh api repos/o/r/issues --method GET -f per_page=5",
            "gh api -H 'Accept: application/vnd.github+json' repos/o/r",
        ):
            self.assertEqual(bash(command)[0], "allow", command)

    def test_writes_denied_wherever_the_flag_sits(self):
        for command in (
            "gh api repos/o/r/issues/1/comments -f body=hi",
            "gh api repos/o/r/issues/1/comments -X POST",
            "gh api -X DELETE repos/o/r/git/refs/heads/x",
            "gh api repos/o/r --method=PATCH",
            "gh api repos/o/r -XPUT",
            "gh api repos/o/r/x --input body.json",
            "gh api repos/o/r/issues -F title=x",
        ):
            decision, text = bash(command)
            self.assertEqual(decision, "deny", command)
            self.assertIn("--jq", text)

    def test_graphql_mutation_denied(self):
        self.assertEqual(bash("gh api graphql -f query='mutation { addStar(input:{starrableId:\"x\"}) { clientMutationId } }'")[0], "deny")

    def test_graphql_query_from_file_is_inspected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".graphql") as query, tempfile.NamedTemporaryFile("w", suffix=".graphql") as mutation:
            query.write("query { viewer { login } }")
            query.flush()
            mutation.write("mutation { addStar(input:{starrableId:\"x\"}) { clientMutationId } }")
            mutation.flush()
            self.assertEqual(bash(f"gh api graphql -F query=@{query.name}")[0], "allow")
            self.assertEqual(bash(f"gh api graphql -F query=@{mutation.name}")[0], "deny")

    def test_unreadable_graphql_query_file_denied(self):
        self.assertEqual(bash("gh api graphql -F query=@/nonexistent/q.graphql")[0], "deny")


class ResetTest(unittest.TestCase):
    def test_hard_reset_denied_in_any_position(self):
        for command in ("git reset --hard HEAD~1", "git reset HEAD~1 --hard", "git -C /tmp reset --hard origin/x"):
            self.assertEqual(bash(command)[0], "deny", command)

    def test_soft_and_mixed_reset_not_denied_by_the_hook(self):
        for command in ("git reset --soft origin/x", "git reset HEAD file.txt"):
            self.assertEqual(bash(command)[0], "allow", command)


class SecretPrintingTest(unittest.TestCase):
    def assertLeak(self, command):
        self.assertEqual(bash(command)[0], "deny", command)

    def test_echo_of_token_variable_denied(self):
        self.assertLeak("echo $MY_API_TOKEN")
        self.assertLeak('echo "${GITHUB_TOKEN}"')
        self.assertLeak("printf '%s' $MY_SECRET")

    def test_echo_of_non_secret_variable_allowed(self):
        self.assertEqual(bash("echo $API_ENDPOINT")[0], "allow")

    def test_presence_check_without_printing_value_allowed(self):
        self.assertEqual(bash('echo "${GITHUB_TOKEN:+set}"')[0], "allow")
        self.assertEqual(bash('echo "${#GITHUB_TOKEN}"')[0], "allow")

    def test_printenv_of_secret_denied_and_of_endpoint_allowed(self):
        self.assertLeak("printenv MY_API_TOKEN")
        self.assertEqual(bash("printenv API_ENDPOINT")[0], "allow")

    def test_environment_dump_denied(self):
        for command in ("env", "printenv", "env | grep -i token", "env | grep AWS", "export -p", "declare -p", "set"):
            self.assertEqual(bash(command)[0], "deny", command)

    def test_environment_uses_that_do_not_dump_allowed(self):
        for command in ("env FOO=1 true", "set -euo pipefail", "export FOO=bar", "env > /tmp/env-snapshot"):
            self.assertEqual(bash(command)[0], "allow", command)

    def test_printing_token_files_denied(self):
        for command in ("cat ~/.cloud/staging.token", "head -c 8 ~/.cloud/.api_token", "grep . $HOME/.cloud/prod.token",
                        "cat /Users/me/.tool/api-token", 'echo "$(cat ~/.cloud/staging.token)"'):
            self.assertEqual(bash(command)[0], "deny", command)

    def test_token_files_used_without_printing_allowed(self):
        for command in ("wc -c ~/.cloud/staging.token", "ls -l ~/.cloud/.api_token", "cat ~/.cloud/staging.api_endpoint"):
            self.assertEqual(bash(command)[0], "allow", command)

    def test_source_files_with_token_in_the_name_allowed(self):
        for command in ("cat src/token_utils.py", "grep -n parse docs/tokenizer.md", "cat ./.github/token-rotation.yml"):
            self.assertEqual(bash(command)[0], "allow", command)

    def test_token_captured_into_variable_allowed(self):
        self.assertEqual(bash("export MY_API_TOKEN=$(cat ~/.cloud/staging.token)")[0], "allow")

    def test_token_in_authorization_header_allowed(self):
        cmd = 'curl -H "Authorization: Bearer $MY_API_TOKEN" "https://api.example.com/v2/items/"'
        self.assertEqual(bash(cmd)[0], "allow")

    def test_shell_profile_asks(self):
        self.assertEqual(bash("cat ~/.zshrc")[0], "ask")
        self.assertEqual(run_guard("Read", {"file_path": "/Users/x/.zshrc"})[0], "ask")

    def test_read_and_grep_of_token_files_denied(self):
        self.assertEqual(run_guard("Read", {"file_path": "/Users/x/.cloud/staging.token"})[0], "deny")
        self.assertEqual(run_guard("Read", {"file_path": "/home/x/.cloud/.api_token"})[0], "deny")
        self.assertEqual(run_guard("Grep", {"pattern": ".", "path": "/Users/x/.cloud/staging.token"})[0], "deny")

    def test_read_of_non_secret_files_allowed(self):
        self.assertEqual(run_guard("Read", {"file_path": "/Users/x/.cloud/staging.api_endpoint"})[0], "allow")
        self.assertEqual(run_guard("Grep", {"pattern": "def ", "path": "/Users/x/src"})[0], "allow")


class FailureModeTest(unittest.TestCase):
    def test_invalid_json_fails_open_visibly(self):
        proc = subprocess.run([sys.executable, "-I", GUARD], input="not json", capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("guard.py error", proc.stderr)

    def test_unparseable_command_is_not_denied_by_the_secret_rules(self):
        self.assertEqual(bash("echo 'unterminated")[0], "allow")

    def test_known_limit_commands_wrapped_in_a_shell_string_are_not_parsed(self):
        """Documents the README's Limits section. If this starts failing, update that section."""
        for command in ("bash -c 'printenv'", "eval 'printenv'", "sh -c 'echo $MY_API_TOKEN'"):
            self.assertEqual(bash(command)[0], "allow", command)


if __name__ == "__main__":
    unittest.main()
