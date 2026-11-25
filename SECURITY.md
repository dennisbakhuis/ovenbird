# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub security advisories: use the
"Report a vulnerability" button on the repository's Security tab. Do not open a public issue.

Include the affected version, deployment mode and steps to reproduce. You can expect an
acknowledgement within a few days.

## Why this matters

ovenbird drives physical equipment: a heat pump heating a home. A flaw that allows unauthorised
or out-of-range commands can cause discomfort, equipment wear or damage. Please treat anything
that could affect command safety (authentication, MQTT topic allowlists, value clamps) as
high severity.

## Supported versions

The project is pre-alpha; only the latest commit on `main` is supported.
