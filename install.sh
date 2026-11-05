#!/bin/sh
# Install the explain-change skill for Agent Skills harnesses (Claude Code, Codex, Gemini CLI,
# Copilot, Cursor, OpenCode, Goose, Amp, Kiro, Windsurf, Cline, Roo, ...).
# POSIX sh, standard tools only: ln, cp, rm, mkdir, readlink. See --help.

set -u

NAME=explain-change
MARKER=.installed-by-explain-change
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || exit 2
SRC=$HERE/skills/$NAME

# Every accepted --harness name. Harnesses that read ~/.agents/skills share the "agents" target.
VALID="agents claude codex gemini copilot cursor opencode goose amp kiro windsurf cline roo"
# What a bare run installs: ~/.agents/skills plus the harnesses that do not read it.
DEFAULT="agents claude kiro windsurf cline roo"

usage() {
  cat <<EOF
Usage: $0 [--harness NAME[,NAME...]] [--all] [--copy] [--project] [--uninstall] [--dry-run] [--force]

Installs the skill folder as <skills dir>/$NAME. The default is a symlink to this checkout
($SRC), so \`git pull\` updates every harness at once.

  --harness LIST  comma-separated harness names (repeatable). Valid: $VALID
  --all           the default set: $DEFAULT
  --copy          copy the folder instead of linking it (use it for --project, so teammates get the files)
  --project       install under the current directory (.agents/skills, .claude/skills, .kiro/skills)
                  instead of under \$HOME; harnesses with no documented project path are skipped
  --uninstall     remove what this script installed (our symlink, or a copy carrying $MARKER)
  --dry-run       print what would happen and change nothing
  --force         replace an existing directory that this script did not create
  -h, --help      this text

Without --harness the set is: $DEFAULT.
Exit status: 0 ok, 1 a path was refused, 2 bad usage.
EOF
}

die() { printf 'error: %s\n' "$*" >&2; exit 2; }

harnesses=
mode=link scope=user action=install dry=0 force=0
while [ $# -gt 0 ]; do
  case $1 in
    --harness) [ $# -ge 2 ] || die "--harness needs a value"; harnesses="$harnesses,$2"; shift ;;
    --harness=*) harnesses="$harnesses,${1#--harness=}" ;;
    --all) harnesses="$harnesses,$(echo "$DEFAULT" | tr ' ' ',')" ;;
    --copy) mode=copy ;;
    --project) scope=project ;;
    --uninstall) action=uninstall ;;
    --dry-run) dry=1 ;;
    --force) force=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
  shift
done

[ -n "$harnesses" ] || harnesses=$(echo "$DEFAULT" | tr ' ' ',')

# skills directory of one canonical target for the scope; empty = no documented path
dir_for() {
  if [ "$scope" = project ]; then
    case $1 in
      agents) echo ".agents/skills" ;;
      claude) echo ".claude/skills" ;;
      kiro)   echo ".kiro/skills" ;;
      *)      echo "" ;;
    esac
  else
    [ -n "${HOME:-}" ] || die "HOME is not set"
    case $1 in
      agents)   echo "$HOME/.agents/skills" ;;
      claude)   echo "$HOME/.claude/skills" ;;
      kiro)     echo "$HOME/.kiro/skills" ;;
      windsurf) echo "$HOME/.codeium/windsurf/skills" ;;
      cline)    echo "$HOME/.cline/skills" ;;
      roo)      echo "$HOME/.roo/skills" ;;
    esac
  fi
}

# harness name -> canonical target
canon() {
  case $1 in
    agents|codex|gemini|copilot|cursor|opencode|goose|amp) echo agents ;;
    claude|claude-code) echo claude ;;
    kiro|windsurf|cline|roo) echo "$1" ;;
    *) return 1 ;;
  esac
}

targets=
old_ifs=$IFS; IFS=,
for h in $harnesses; do
  IFS=$old_ifs
  [ -n "$h" ] || { IFS=,; continue; }
  c=$(canon "$h") || { printf 'error: unknown harness: %s\nvalid names: %s\n' "$h" "$VALID" >&2; exit 2; }
  case " $targets " in *" $c "*) ;; *) targets="$targets $c" ;; esac
  IFS=,
done
IFS=$old_ifs

[ -f "$SRC/SKILL.md" ] || die "skill folder not found at $SRC"

rc=0
say() { printf '%-8s %s\n' "$1" "$2"; }

is_ours() { # symlink to this checkout, or a copy that carries the marker
  if [ -L "$1" ]; then [ "$(readlink "$1")" = "$SRC" ]; else [ -d "$1" ] && [ -f "$1/$MARKER" ]; fi
}

do_install() {
  dest=$1
  parent=$(dirname -- "$dest")
  if [ "$mode" = link ] && [ -L "$dest" ] && [ "$(readlink "$dest")" = "$SRC" ] && [ -e "$dest" ]; then
    say ok "$dest (already linked)"; return
  fi
  if [ -d "$dest" ] && [ ! -L "$dest" ]; then
    real=$(CDPATH= cd -- "$dest" && pwd -P)
    case "$SRC/" in "$real"/*)
      say refuse "$dest contains this checkout ($SRC); clone elsewhere"
      rc=1; return ;;
    esac
  fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if is_ours "$dest" || [ ! -e "$dest" ]; then  # ours, or a dangling symlink
      say replace "$dest"
    elif [ "$force" -eq 1 ]; then
      say force "$dest (replacing a directory this script did not create)"
    else
      say refuse "$dest exists and was not created by this script; use --force to replace it"
      rc=1; return
    fi
    [ "$dry" -eq 1 ] || rm -rf -- "$dest"
  fi
  if [ "$mode" = link ]; then
    say link "$dest -> $SRC"
    [ "$dry" -eq 1 ] || { mkdir -p -- "$parent" && ln -s -- "$SRC" "$dest"; } || { rc=1; return; }
  else
    say copy "$SRC -> $dest"
    if [ "$dry" -eq 0 ]; then
      { mkdir -p -- "$dest" && cp -R -- "$SRC/." "$dest/" \
        && find "$dest" -name __pycache__ -type d -prune -exec rm -rf -- {} + \
        && : > "$dest/$MARKER"; } || { rc=1; return; }
    fi
  fi
}

do_uninstall() {
  dest=$1
  if [ ! -e "$dest" ] && [ ! -L "$dest" ]; then say absent "$dest"; return; fi
  if is_ours "$dest"; then
    say remove "$dest"
    [ "$dry" -eq 1 ] || rm -rf -- "$dest"
  else
    say skip "$dest (not installed by this script)"
  fi
}

for t in $targets; do
  d=$(dir_for "$t")
  if [ -z "$d" ]; then say skip "$t: no documented project-level path"; continue; fi
  if [ "$action" = install ]; then do_install "$d/$NAME"; else do_uninstall "$d/$NAME"; fi
done

[ "$dry" -eq 1 ] && echo "dry run: nothing was changed"
exit "$rc"
