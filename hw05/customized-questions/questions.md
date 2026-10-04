# HW05 — Individual Understanding Questions (yluo9)

Your generated suite produced 28 unit tests that all passed on your original
ATC. Your main finding was that two of them passed for shallow reasons: they
checked the order of commands, or used broken JSON, instead of the behaviour
that actually mattered. You fixed `_on_message` to ignore payloads that
aren't objects, and changed resuming so that a drone found on the ground is
re-armed and taken off first.

---

**1.** Your interrupt-then-resume test passed even though, on the real fleet,
the resumed drone never flew again. Why wasn't a passing test enough here?

**2.** A drone was interrupted, came down and disarmed while it waited. Trace
what your Version 2 ATC now does when the conflict clears and it resumes that
drone.

**3.** Your original malformed-message test sent broken JSON and passed. Why
did it miss the bug where a message like `[1, 2, 3]` could later crash your
ATC?
