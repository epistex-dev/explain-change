#!/usr/bin/env python3
"""Collect the diff an agent will explain.

usage: collect.py [<base>..<head> | <commit>] [--repo PATH] [--v2] [--transcript FILE] [--format auto|claude|copilot|codex|opencode|gemini|cursor-cli|cursor-ide] [--path DIR_OR_FILE]... [--slug TEXT]
       collect.py --session [--transcript FILE] [--format ...] [--repo PATH]
--path (repeatable) limits the diff, the map and the validator to those repo-relative paths; the scope is stored in summary.json.
--slug TEXT names the run folder; without it the most common subject among the commits that touch the scope does.
Default range: uncommitted changes vs HEAD when there are any, else the last commit.
--v2 (implied by --transcript) adds what schema v2 needs: changed files mapped to modules (floorplan/architecture.json
or top directories), and the session transcripts that could ground the page (3 newest listed; with --transcript, a digest
of the user's messages and the test-like tool calls). A transcript is read only under the official folder of its harness:
~/.claude/projects (Claude Code), or that of Copilot CLI, Codex, OpenCode, Gemini CLI, Cursor CLI and Cursor IDE (see SKILL.md). The format is
detected from the file; --format names it. A file no supported format recognises exits 1 with one line naming the formats.
--session prints a digest of a whole session (numbered user turns, tool calls by turn, repos touched, outward actions) for an
explain-session/1 doc; it writes nothing and needs no diff. Without --transcript it lists the candidate sessions.
Creates <repo>/.explain/<YYYYMMDD-HHMM>-<slug>/ with summary.json and diff.patch, prints a summary plus
`RUN_DIR=<path>`. Exit 3 and no directory when the range has no changes.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import arch as archmod  # noqa: E402
from lib import collect, collect2, gitio, neutral, session, transcript  # noqa: E402


def session_digest(a):
    try:
        if not a.transcript:
            repo = os.path.abspath(a.repo)
            print(collect2.format_candidates(repo, transcript.candidates(repo), transcript.other_candidates(repo)))
            return 0
        text, warns = session.digest(transcript.safe_path(a.transcript, a.format))
        print(text)
        for w in warns:
            print('warning: ' + w, file=sys.stderr)
        return 0
    except gitio.ExplainError as e:
        print('error: %s' % e, file=sys.stderr)
        return 1 if isinstance(e, neutral.FormatError) else 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('range', nargs='?')
    ap.add_argument('--repo', default='.')
    ap.add_argument('--v2', action='store_true')
    ap.add_argument('--session', action='store_true', help='digest a whole session instead of a diff')
    ap.add_argument('--transcript')
    ap.add_argument('--format', default='auto', choices=neutral.CHOICES, help='transcript format (default: detected from the file)')
    ap.add_argument('--path', action='append', default=[], metavar='PATH', help='limit to this repo-relative folder or file (repeatable)')
    ap.add_argument('--slug', help='run folder name (after the timestamp)')
    a = ap.parse_args(argv)
    if a.session:
        return session_digest(a)
    try:
        repo = gitio.toplevel(os.path.abspath(a.repo))
        scope = gitio.normalize_scope(repo, a.path)
        rng = gitio.resolve_range(repo, a.range)
        summary, patch = collect.build_summary(repo, rng, scope)
        if not summary['files']:
            print('Không có thay đổi để giải thích (%s). Không tạo trang.' % rng['label'], file=sys.stderr)
            return 3
        subject = a.slug if a.slug and a.slug.strip() else collect.pick_slug(summary['messages'], 'worktree' if rng['mode'] == gitio.WORKTREE else 'change')
        v2 = a.v2 or bool(a.transcript)
        if v2:
            tpath = transcript.safe_path(a.transcript, a.format) if a.transcript else None
            arch, rep = collect2.module_report(repo, summary['files'])
            summary['modules'] = {k: v for k, v in rep.items() if k != 'status'}
        collect.ensure_excluded(repo)
        run_dir = collect.new_run_dir(repo, collect.slugify(subject))
        with open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8') as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=1)
        with open(os.path.join(run_dir, 'diff.patch'), 'wb') as fh:
            fh.write(patch)
        print(collect.format_text(summary, run_dir, v2))
        if v2:
            print('\n' + collect2.format_modules(repo, arch, rep))
            if tpath:
                text, warns = transcript.digest(tpath)
                print('\n' + text)
                for w in warns:
                    print('warning: ' + w, file=sys.stderr)
            else:
                print('\n' + collect2.format_candidates(repo, transcript.candidates(repo), transcript.other_candidates(repo)))
        print('\nRUN_DIR=%s' % run_dir)
        return 0
    except (gitio.ExplainError, archmod.ArchError) as e:
        print('error: %s' % e, file=sys.stderr)
        return 1 if isinstance(e, neutral.FormatError) else 2


if __name__ == '__main__':
    sys.exit(main())
