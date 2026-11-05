#!/usr/bin/env python3
"""Check explain.json: schema, file coverage, and that every cited snippet really occurs in the code.

usage: validate.py <explain.json> [--repo PATH] [--transcript FILE] [--format auto|claude|copilot|codex|opencode|gemini|cursor-cli|cursor-ide]
Schema v1 (version absent or 1), v2 (version 2), explain-session/1 (a whole session; see references/session-schema.md) and explain-flow/1 (a flow of existing code, each source read from the doc's commit; see references/explain-flow-schema.md) are checked; v2 also grounds quotes and tool calls in the session
transcript (a file under ~/.claude/projects, or a session of Copilot CLI, Codex, OpenCode, Gemini CLI or Cursor under that harness's own folder; the
format is detected unless --format names it; the doc's "transcript" field is used when the flag is absent).
Prints one `path: reason` line per problem (exit 1), or `ok` plus per-section counts (exit 0).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import check, check_flow, check_session, gitio, neutral  # noqa: E402


def load_and_validate(path, repo=None, transcript=None, fmt='auto'):
    try:
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        return None, ['$: cannot read %s: %s' % (path, e)], {}
    here = os.path.dirname(os.path.abspath(path))
    if check_session.is_session(doc):  # a whole-session doc has no repo and no git range
        errs, stats = check_session.validate(doc, transcript, base_dir=here, fmt=fmt)
        return doc, errs, stats
    repo = repo or gitio.toplevel(here)
    if check_flow.is_flow(doc):  # a flow of existing code: no diff, no session; every source is read from the doc's own commit
        errs, stats = check_flow.validate(doc, repo)
        return doc, errs, stats
    errs, stats = check.validate(doc, repo, transcript, scope=read_scope(here, repo), fmt=fmt)
    return doc, errs, stats


def read_scope(run_dir, repo):
    """The --path scope collect.py stored in summary.json next to the doc ([] = the whole range)."""
    try:
        with open(os.path.join(run_dir, 'summary.json'), encoding='utf-8') as fh:
            scope = json.load(fh).get('scope')
    except (OSError, ValueError, AttributeError):
        return []
    return gitio.normalize_scope(repo, scope) if isinstance(scope, list) else []


def report_session(s):
    for w in s['warnings']:
        print('warning: ' + w)
    print('ok')
    st = s['statuses']
    print('session | themes %d (%s) | events %d | needs you %d | decided %d (%d irreversible) | outward %s | '
          'grounded in transcript %d (%d of them worker reports), not compared %d, inferred %d | transcript %s' % (
              s['themes'], ', '.join('%s %d' % (k, v) for k, v in st.items() if v) or 'none', s['events'], s['needs_you'], s['decided'], s['irreversible'],
              ', '.join('%s %d' % kv for kv in s['outward'].items()) or 'none', s['verified_in_transcript'], s['reported'], s['not_compared'], s['inferred'],
              'checked' if s['transcript'] else 'checks off'))
    return 0


def report_flow(s):
    print('ok')
    print('flow | parts %d (%d outside) | steps %d, %d with branches | error exits %d | sources %d, each excerpt found in its lines at the commit' % (
        s['parts'], s['outside'], s['steps'], s['branch_points'], s['errors'], s['sources']))
    return 0


def report_v2(s):
    for w in s['warnings']:
        print('warning: ' + w)
    v = s['verdict']
    print('ok')
    print('v2 | requests %d/%d done | tests %s | map %s: %d of %d modules changed, files %d/%d covered | logic before %d, after %d | '
          'rejected %d | ran %d, not checked %d | grounded in transcript %d (%d of them worker reports, not tool output), unverified %d | refs verified %d, inferred %d (%d inferred items render "suy luận")' % (
              v['requests']['done'], v['requests']['total'], 'passed' if v['tests_passed'] else 'not passed', s['map_source'],
              *s['modules'], *s['files'], *s['steps'], s['rejected'], s['ran'], s['not_checked'], s['verified_in_transcript'], s.get('reported', 0), s['unverified'],
              s['refs']['verified'], s['refs']['inferred'], len(s.get('inferred', []))))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('explain_json')
    ap.add_argument('--repo')
    ap.add_argument('--transcript')
    ap.add_argument('--format', default='auto', choices=neutral.CHOICES, help='transcript format (default: detected from the file)')
    a = ap.parse_args(argv)
    try:
        _, errs, stats = load_and_validate(a.explain_json, a.repo, a.transcript, a.format)
    except gitio.ExplainError as e:
        print('error: %s' % e, file=sys.stderr)
        return 2
    if errs:
        print('\n'.join(errs))
        return 1
    if stats.get('kind') == 'session':
        return report_session(stats)
    if stats.get('kind') == 'flow':
        return report_flow(stats)
    if stats.get('version') == 2:
        return report_v2(stats)
    print('ok')
    print('files %d, covered %d | flows %d (steps %d) | functions to explain %d, explained %d | risks %d | quiz %d | refs verified %d, inferred %d' % (
        *stats['files'], *stats['flows'], *stats['functions'], stats['risks'], stats['quiz'],
        stats['refs']['verified'], stats['refs']['inferred']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
