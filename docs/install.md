# Install

The skill is a folder with a `SKILL.md`, the [Agent Skills](https://agentskills.io/specification) format, so one install script puts it where each harness looks.

```bash
git clone https://github.com/epistex-dev/explain-change.git
cd explain-change
./install.sh                          # ~/.agents/skills + Claude Code, Kiro, Windsurf, Cline, Roo
./install.sh --harness codex,gemini   # only the folders these harnesses read
```

## Every harness

| Harness | Skills folder | Command |
| --- | --- | --- |
| Claude Code | `~/.claude/skills` | `./install.sh --harness claude`, or the [plugin](#claude-code-plugin) |
| Codex | `~/.agents/skills` | `./install.sh --harness codex` |
| Gemini CLI | `~/.agents/skills` | `./install.sh --harness gemini`, or `gemini extensions install https://github.com/epistex-dev/explain-change` |
| GitHub Copilot | `~/.agents/skills` | `./install.sh --harness copilot` |
| Cursor | `~/.agents/skills` | `./install.sh --harness cursor` |
| OpenCode | `~/.agents/skills` | `./install.sh --harness opencode` |
| Goose, Amp | `~/.agents/skills` | `./install.sh --harness goose` (or `amp`) |
| Kiro | `~/.kiro/skills` | `./install.sh --harness kiro` |
| Windsurf | `~/.codeium/windsurf/skills` | `./install.sh --harness windsurf` |
| Cline | `~/.cline/skills` | `./install.sh --harness cline` |
| Roo Code | `~/.roo/skills` | `./install.sh --harness roo` |

Harnesses that share `~/.agents/skills` get one link between them. `install.sh` links to the checkout, so `git pull` updates every harness; every path it touches is printed.

## Flags

| Flag | Effect |
| --- | --- |
| `--copy` | copy the folder instead of linking it |
| `--project` | install under the current directory (`.agents/skills`, `.claude/skills`, `.kiro/skills`); use it with `--copy` to commit the skill |
| `--uninstall` | remove what the script installed, nothing else |
| `--dry-run` | print the paths and change nothing |
| `--force` | replace an existing folder the script did not create (it refuses without this) |

## Claude Code plugin

```text
/plugin marketplace add epistex-dev/explain-change
/plugin install explain-change@explain-change
```

The skill is then available as `explain-change` (namespaced `/explain-change:explain-change`).

## Manually

```bash
mkdir -p ~/.agents/skills
ln -s "$PWD/skills/explain-change" ~/.agents/skills/explain-change   # or: cp -r
```

## With the `skills` CLI

```bash
npx skills add epistex-dev/explain-change
```

The [`skills` CLI](https://github.com/vercel-labs/skills) installs a repo's skills into the agent you pick (`-a <agent>`).

## Requirements

Python 3 with the standard library only (no packages to install) and `git`. Tests of the edge router also use `node` when it is on `PATH`. The cold-read gate (step 6 of [SKILL.md](../skills/explain-change/SKILL.md)) uses a fresh subagent when the harness has one; otherwise set `EXPLAIN_COLDREAD_CMD` to a command that reads a prompt on stdin and prints its answer, for example `claude -p --tools "" --no-session-persistence`.
