# Tests passed with `-s tests` but not from the repository root

Date: 2026-11-18 · Record: reconstructed on 2026-11-24 from the commit message and the repository; the original failure output was not recorded

## Problem

The test modules import each other by bare module name (`from test_kutu import ...`). That works when the test folder is the discovery start directory (`python -m unittest discover -s tests`) but not for `python -m unittest discover` run from the repository root, where the test folder is a package and its siblings are not on the import path. The commit that fixed this is titled "tests: make unittest discover work from the root"; the exact error text was not recorded in the source repository.

`Interpretation:` The root-level command is what a newcomer, and the CI workflow, will run, so a suite that only passes with `-s tests` would have looked broken to everyone but the author.

## Diagnosis

Cause: bare-name imports between test modules, which depend on the test folder being on `sys.path`. The fixing commit changed only `tests/__init__.py`; no test was edited.

## Attempts that failed

No record.

## Resolution

`tests/__init__.py` adds its own folder to `sys.path` once, so the bare-name imports resolve for both ways of running the tests. No test was changed. The README and the CI workflow use the root-level command, and the same command is the one in [METRICS.md](../METRICS.md).

## Evidence

- Commit: `51d5159` (private source repository; not resolvable here)
- File: `tests/__init__.py` (the whole fix)
- Command: `python -m unittest discover` from the repository root, exit code and test counts in [METRICS.md](../METRICS.md) (test section)
- Related decision: none
