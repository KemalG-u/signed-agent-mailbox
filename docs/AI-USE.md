# AI use in kutu

This is the maintainer's own statement of how AI tools were used to build this project, what the human did, and what was verified. Raw agent transcripts (`*.jsonl`) are **not** published: they can contain private paths, personal data and secrets. This record is a curated summary; its claims point to files and commands you can inspect.

Maintainer: Kemal (KarıncaAI) · Record: reconstructed on 2026-11-24 from the repository contents and the preparation run, not from a contemporaneous log · Last reviewed: 2026-11-24

## Summary

Default declaration (the maintainer's standing statement; it holds for this project unless a line below says otherwise): the maintainer does not write code. The code and the documents are written by AI tools. The maintainer sets the direction and the rules, reviews every change and checks it. This is a personal project: no employer or client code, data or working time is used.

## Tools and models

| Tool / model (version) | Role | Which parts of the project |
|---|---|---|
| AI coding agents: Claude Code with Claude Sonnet 5.5 and Claude Opus 5.5 (per the `Co-Authored-By` trailers of the private source history: most commits name Sonnet 5.5; the two commits `d26cde2` and `a485808` name Opus 5.5; per-change model versions in the squashed public history are not separable) | Wrote the code, tests and documents under the maintainer's direction | The whole repository |
| Independent AI reader(s): none recorded in this file | No independent AI read of this repository is recorded here | Findings only |

## What the human did

- Decided: direction, scope and rules.
- Reviewed: every change was reviewed and checked by the maintainer before it was accepted (maintainer's statement; the depth of the review per change is not recorded).
- Ran and checked: the unit tests, and the end-to-end script against the real tools whose results are in OKU.tr.md.

## What the AI did

Wrote the Python modules (`kutu.py`, `kutu_imza.py`, `kutu_adaptor.py`, `kutu_gecis.py`), the unit tests, the end-to-end scripts and the README/OKU/GECIS documents, and ran the tests and the end-to-end script during development.

## What was verified, and how

| Claim | Verification | Evidence |
|---|---|---|
| Unit tests pass | `python -m unittest discover` from the repository root; run again on 2026-11-24 for the release copy on Windows 11 (Python 3.12) and on Ubuntu 24.04 under WSL (Python 3.12.3) | CI run on the public repository |
| Adapters for the Claude Code, Codex, Antigravity (`agy`) and Hermes one-shot modes work | End-to-end script `uctan-uca.py` against the real tools on 2026-11-18 | Results table in [OKU.tr.md](../OKU.tr.md); raw run output is not published |

## What was not verified

- The depth of the maintainer's review of each change is not measured; the statement above is the maintainer's own.
- `hermes-http` was only tested against a fake server (the real API server was off). `opencode`, `gemini`, `copilot` and `cursor` adapters were written from each tool's documented one-shot command and were never run against the real tool.
- Signatures catch label spoofing and tampered lines but not an attacker with the same user rights; replay of an identical signed line is not prevented (documented in the README).
- Windows is the platform the tool was developed and run on; Linux was exercised only through the unit tests.

## Authorship in commits

AI involvement is marked with an `Assisted-by: TOOL:MODEL` trailer in commits ([convention from the LLVM policy](https://llvm.org/docs/AIToolPolicy.html)). `Signed-off-by` appears only for the human maintainer; AI tools never sign off ([Linux kernel guidance](https://docs.kernel.org/process/coding-assistants.html)). The private source history used `Co-Authored-By: Claude ...` trailers (the form Claude Code writes by default), not `Assisted-by`; the public commits carry the same kind of trailer. The public history starts with a single squashed commit; this file is the record of AI involvement for the earlier private history.

## Copyright note

Copyright rests on human creative contribution: here the maintainer's design direction, requirements, selection and arrangement, and review edits. `Interpretation:` Purely machine-generated passages may not be protected by copyright; this project does not claim otherwise.

## Limits of this record

`Interpretation:` The share of AI-written code is not measured. Readers cannot verify the tool and model list independently because the raw transcripts are not published. This document is not a quality guarantee; the tests and the code are the evidence.
