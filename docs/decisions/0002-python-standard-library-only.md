---
status: "accepted"
date: 2026-11-18
decision-makers: the repository maintainer
consulted: AI coding agents (Claude Code) did the preliminary search; they did not decide
informed: none
---

# Use only the Python standard library

Record: reconstructed on 2026-11-24 from the first commit, an internal search note dated 2026-11-18 (not published) and the code.

## Context and Problem Statement

The box has to run on a Windows 11 machine next to Codex Desktop and Claude Code, from Git Bash and PowerShell, and has to be easy to copy to another machine. Existing projects that solve parts of the problem (a Node daemon with a database, an MCP server) are heavier. Should the tool depend on third-party packages?

## Decision Drivers

* Nothing to install, no environment to maintain: copy the folder and run it.
* A tool that handles messages between agents should have a small supply-chain surface.
* The tool is small enough that the standard library is sufficient.

## Considered Options

* Python standard library only.
* Python with third-party packages (a web framework or a client library).
* Adopt an existing project (a Node daemon with sqlite, or an MCP server) instead of writing a small tool.

## Decision Outcome

Chosen option: "Python standard library only", because the search note found no existing candidate that was both light and covered the needs (a durable log, a page a human can read, two delivery paths, sender identity). The note lists three candidates: one is heavy (a Node daemon with sqlite) and its Windows and Desktop support is undocumented, so it was kept as a reference for the Claude Code pipe format only and was not installed; one lacks a human interface and identity and was kept as a reference; one is an MCP server, heavy, with no identity or human interface, and was not used. The note concludes: write a small tool of our own, one file, standard library, and use the two official delivery mechanisms.

### Consequences

* Good, because there is no dependency to install, pin or audit. The repository's Dependabot file watches only GitHub Actions, because there are no package dependencies.
* Good, because the generated chat page needs no JavaScript and no template engine.
* Bad, because the project implements small things itself (a log follower, an HTTP client for one adapter, the HTML page).
* Bad, because the standard library has no asymmetric signature primitive, which narrowed the signing choice (see [0001](0001-hmac-sha256-signatures.md)).

### Confirmation

A static check of every import in the root modules and in `tests/`, run on 2026-11-24 with Python 3.12:

```python
import ast, pathlib, sys
local = {p.stem for p in pathlib.Path(".").glob("*.py")} | {p.stem for p in pathlib.Path("tests").glob("*.py")} | {"tests"}
bad = set()
for p in list(pathlib.Path(".").glob("*.py")) + list(pathlib.Path("tests").glob("*.py")):
    for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
        mods = [a.name for a in n.names] if isinstance(n, ast.Import) else \
               [n.module] if isinstance(n, ast.ImportFrom) and n.level == 0 else []
        bad |= {(str(p), m) for m in mods if m.split(".")[0] not in sys.stdlib_module_names | local}
print(sorted(bad))
```

The result was an empty list. The CI workflow installs nothing except Python itself.

## Pros and Cons of the Options

### Python standard library only

* Good, because the whole tool is readable and runs anywhere Python 3 runs.
* Bad, because it is more code to maintain than a library-based tool.

### Python with third-party packages

* Good, because less code to write.
* Bad, because it adds installation steps and a dependency list to keep current, for a small gain.

### Adopt an existing project

* Good, because no new code.
* Bad, because the candidates found needed a daemon and a database, or did not cover human readability and sender identity (per the search note).

## More Information

* First commit `0f80172` and the search note, both in the private source repository.
* The pipe format learned from the open-source `fujibee/agmsg` project is not officially documented; this is recorded in the README.
