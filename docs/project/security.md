---
description: How to report a security vulnerability in dpm-xbrl, and what counts as one.
---

# Security policy

dpm-xbrl reads files from outside the trust boundary, so security bugs in
it matter. [The security model](../concepts/security.md) describes what it
protects against.

## Supported versions

Security fixes are released for the latest minor version of the latest
major version.

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue: use
[GitHub's private vulnerability reporting](https://github.com/luukhopman/dpm-xbrl/security/advisories/new)
for the repository, or e-mail github@luukhopman.nl. Include the dpm-xbrl
and Python versions, and, if you can, a small input that shows the problem.

The fix is released as a patch version and described in the changelog.

## What counts

- Reading a report raises anything other than `ReportError`, hangs, or uses
  memory or time far beyond what its size and the `Limits` allow.
- Reading a report reads or writes files outside the input, makes a network
  request, or resolves an XML entity.
- A written report differs from the `Report` it was written from in a way
  that changes its meaning.
