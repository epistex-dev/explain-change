# Security policy

## Reporting a vulnerability

Report it privately through GitHub: <https://github.com/epistex-dev/explain-change/security/advisories/new>. Please do not open a public issue.

## What counts

- A secret (token, key, password) from the code, a diff or a session log that ends up in a rendered page or in `validate.py` / `render.py` output.
- Path traversal in the source checks: a doc that makes `validate.py` or `render.py` read a file outside the repo or outside the doc's commit.
- Script injection in the generated HTML: text from a doc, a diff or a transcript that runs as script, or loads anything from the network, when the page is opened.

## Supported versions

Only the latest release.
