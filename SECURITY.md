# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| latest commit on `main` | yes |
| older | no |

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Report it privately with GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability** (https://github.com/KemalG-u/signed-agent-mailbox/security/advisories/new).

Include: affected version, a description, steps to reproduce, and the impact you see. Never include real secrets or personal data in a report; describe where they appear instead.

## What to expect

This is a one-person project maintained on a best-effort basis. The maintainer aims to send an initial response within **14 days** of a report (the threshold the OpenSSF Best Practices "passing" criteria use). A fix date is not promised; the maintainer will tell you what is planned.

## Scope

In scope: the `kutu` command-line tool and its Python modules (message storage, signing, adapters, the generated chat page). Out of scope: weaknesses of the third-party agent tools it calls, and attacks that require control of the user account that holds the signing keys (the README states this limit).

## Repository hygiene

If you find a secret or personal data that was missed in this repository, report it through the private channel above.
