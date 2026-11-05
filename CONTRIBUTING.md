# Contributing

## Setup

Python 3 and git. The scripts use the standard library only, so there is nothing to install.

```bash
git clone https://github.com/epistex-dev/explain-change
cd explain-change
python3 -m unittest discover -s tests
```

The full suite takes about 80 seconds. CI runs it on every push and pull request (Python 3.12). The tests create throwaway git repositories, so `git config user.name` and `user.email` must be set.

A change that adds a guard should also be covered by `python3 tests/red_check.py`, which removes each guard in a copy and requires its test to fail.

## Pull requests

- One change per pull request, from a branch off `main`.
- Add a line under `## [Unreleased]` in `CHANGELOG.md`.
- Keep the manifest versions (`plugin.json`, `gemini-extension.json`, `.claude-plugin/`) equal to the newest released section of the changelog; a test pins this.
- Pull requests are squash-merged.

Security problems: see [SECURITY.md](SECURITY.md).
