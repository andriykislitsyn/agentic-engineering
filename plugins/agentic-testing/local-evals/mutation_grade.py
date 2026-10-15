"""Grade the tests an eval run left behind by mutation score.

Usage, from the repo root (the case needs a scaffold and tool grants, so CI does not run it):

    claude plugin eval plugins/agentic-testing --eval-dir local-evals --scaffold --keep-temp \
        --allow-tools 'Bash(python3:*)' Write Edit --ablation with-without --no-publish
    python3 -I plugins/agentic-testing/local-evals/mutation_grade.py \
        plugins/agentic-testing/local-evals/tests-for-generated-code <kept run dir>...

Each kept run dir comes from --keep-temp and is listed in the run output. The agent's test files are
copied next to the reference pricing.py (the fixture with its planted bug fixed) and to
mutants of it. Whatever the agent did to its own pricing.py is ignored.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

FIXTURE_BUG = "shipping = 0 if subtotal > FREE_SHIPPING_CENTS else SHIPPING_CENTS"
FIXTURE_FIX = "shipping = 0 if subtotal >= FREE_SHIPPING_CENTS else SHIPPING_CENTS"
MUTANTS = [
    ("bulk-boundary", "qty >= BULK_QTY", "qty > BULK_QTY"),
    ("bulk-rate", "line * 5 // 100", "line * 6 // 100"),
    ("bulk-rounding", "line -= line * 5 // 100", "line -= round(line * 5 / 100)"),
    ("coupon-rate", "subtotal * 10 // 100", "subtotal * 20 // 100"),
    ("coupon-rounding", "subtotal -= subtotal * 10 // 100", "subtotal -= round(subtotal * 10 / 100)"),
    ("coupon-unknown-accepted", 'raise ValueError("unknown coupon")', "pass"),
    ("zero-qty-accepted", "qty < 1", "qty < 0"),
    ("free-item-rejected", "unit_cents < 0", "unit_cents <= 0"),
    ("shipping-fee", "SHIPPING_CENTS = 599", "SHIPPING_CENTS = 600"),
    ("empty-order-accepted", "if not lines:", "if False:"),
]


def run_tests(module_source, test_files):
    """Return (passed, tests_run, failing test names) for the test files against the given pricing.py source."""
    with tempfile.TemporaryDirectory() as work:
        work = pathlib.Path(work)
        (work / "pricing.py").write_text(module_source)
        for path in test_files:
            shutil.copy(path, work / path.name)
        try:
            proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-p", "test*.py"], cwd=work,
                                  capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return False, 0, []
        ran = next((int(line.split()[1]) for line in proc.stderr.splitlines() if line.startswith("Ran ")), 0)
        failing = [line.split(": ", 1)[1].split(" ")[0] for line in proc.stderr.splitlines() if line.startswith(("FAIL: ", "ERROR: "))]
        return proc.returncode == 0, ran, failing


def grade(case_dir, run_dir):
    bug_source = (case_dir / "fixture" / "pricing.py").read_text()
    assert bug_source.count(FIXTURE_BUG) == 1
    ref_source = bug_source.replace(FIXTURE_BUG, FIXTURE_FIX)
    sealed = run_dir / "sealed"
    if sealed.exists():
        sealed.chmod(0o700)
    cwd = sealed / "home" / "cwd" if sealed.exists() else run_dir / "home" / "cwd"
    test_files = sorted(p for p in cwd.glob("test*.py"))
    if not test_files:
        return {"run": run_dir.name, "valid": False, "note": "no test files"}
    valid, ran, failing = run_tests(ref_source, test_files)
    if not valid:
        return {"run": run_dir.name, "valid": False, "tests": ran, "contradicts_spec": failing}
    catches_bug = not run_tests(bug_source, test_files)[0]
    killed = []
    for name, old, new in MUTANTS:
        assert ref_source.count(old) == 1, name
        if not run_tests(ref_source.replace(old, new), test_files)[0]:
            killed.append(name)
    survivors = [name for name, _, _ in MUTANTS if name not in killed]
    return {"run": run_dir.name, "valid": True, "tests": ran, "catches_bug": catches_bug,
            "killed": len(killed), "of": len(MUTANTS), "survivors": survivors}


if __name__ == "__main__":
    case = pathlib.Path(sys.argv[1])
    for kept in sys.argv[2:]:
        print(grade(case, pathlib.Path(kept)))
