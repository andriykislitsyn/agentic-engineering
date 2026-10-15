---
name: agentic-testing
description: Use when writing, adding, changing, or reviewing tests, when a test or CI run is failing and you are about to change code or tests to get it green, when refactoring code that has no tests, when closing out code you generated (a feature, fix, or refactor), and when the user says they can't review all the generated code or asks if a change is safe to ship. Makes the tests a trustworthy stand-in for line-by-line review: spec-derived expectations, red before green, mutation spot checks, no weakening tests, and a short list of what is and isn't proven.
---

# Tests as the review

The user can't read every line you generate, so the tests are what they rely on. A green suite you wrote against your own code proves little: the same model that made the bug tends to make the matching test. Treat green as a claim that needs evidence.

- **Expected values come from the spec, not from the code.** Take them from the ticket, the docstring, a domain rule, or an independent oracle, and never from running the code and pasting the output. When a test written after the code disagrees with the code, suspect the code first. When the spec is silent, ask, or state the assumption in the test name.
- **Keep incidental inputs off the spec's boundaries.** A round number that happens to land on a threshold bakes the code's behavior into a test that isn't about that threshold. Use a boundary value only in a test written for it.
- **See red first.** Every new test fails against missing or broken behavior before it passes. Write it before the implementation, or break the line it covers and rerun. A test you never saw fail may assert nothing.
- **Break it on purpose.** For risky logic (money, auth, parsing, branches, data writes), mutate the implementation two or three plausible ways after the tests pass: flip a comparison, shift a boundary by one, drop a branch, swallow an error. Each mutation must fail a test. A survivor means a missing or weak assertion. Use the repo's mutation tool on the diff if one is configured, otherwise do it by hand, then restore the code and confirm the diff is clean.
- **Never go green by weakening.** Don't edit, skip, xfail, delete, or loosen an existing test or assertion to pass a suite, and don't special-case inputs from the tests in the implementation. A failing test means fix the code. If the test encodes outdated behavior, say so and show the changed expectation on its own, because that is a behavior change the user must see.
- **Fewer, stronger tests.** Volume is unreviewable too. Each test pins a spec line or kills a mutant. Use parametrized cases for boundaries. Use a property or round-trip test for pure logic with a wide input space (parsers, serializers, invariants), since one property replaces dozens of cases.
- **Pin behavior before a refactor or a large rewrite.** Write characterization tests against the public API first and keep them unchanged to the end. Any edit to them is a declared behavior change.
- **Test the seams between code you wrote in the same session.** Callers and callees tend to agree on shapes that the real boundary doesn't (serialization, nullability, ordering, retries, idempotency). Test the contract across the boundary with real objects.
- **Coverage finds unverified code, it doesn't grade tests.** Run coverage scoped to the diff. A changed line no test executes goes on the unverified list below. Don't chase a percentage.

## Handoff

End a task that leaves generated code with a short block in chat, not in the PR description (the Documentation standard still governs that):

1. Behaviors the tests prove, one line each. Test names should already read this way.
2. Unverified: changed code no test reaches, boundaries only CI can exercise, and anything mocked that sits at a risk boundary.
3. Mutations tried and which test caught each.
4. Assumptions about the spec the user should confirm.

Point the user at the tests and that list first, and at the implementation second. For high-stakes changes, offer a separate verification pass that tries to break the change. Spawn it only when the user says so.
