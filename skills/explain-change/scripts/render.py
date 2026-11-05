#!/usr/bin/env python3
"""Validate explain.json and render index.html next to it (self-contained, works offline).

usage: render.py <explain.json> [--repo PATH] [--out FILE] [--transcript FILE] [--format auto|claude|copilot|codex|opencode|gemini|cursor-cli|cursor-ide] [--arch FILE] [--no-validate] [--text] [--theme ID]
Schema v1 renders the report page, schema v2 the layout-2 page, explain-session/1 the swimlane page of a whole session (one file, fonts inlined, under 512 KB).
A session theme with a change_doc also gets its v2 page, written next to the session page (<change_doc without .json>.html) and linked from the theme's panel.
A validation problem prints the same lines as validate.py, writes nothing, exits 1.
On success prints the absolute path of the page. --text also writes <page>.txt, the words of a v2 page, for the cold-read gate.
--theme ID sets the colour theme a session page opens in (navy, ocean, plum, graphite or pearl; default navy); the reader can still pick another on the page.
An unknown id exits 1 with one line naming the valid ids. Other pages ignore it.
--arch and --no-validate (v2 only) render an archived doc whose git range is gone: nothing is checked, the page says validated=no.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import arch as archmod  # noqa: E402
from lib import check2, check_session, collect2, gitio, neutral, page, page2, page_session, transcript  # noqa: E402
from validate import load_and_validate  # noqa: E402


def v2(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return check2.is_v2(json.load(fh))
    except (OSError, ValueError):
        return False


def session_doc(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return check_session.is_session(json.load(fh))
    except (OSError, ValueError):
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('explain_json')
    ap.add_argument('--repo')
    ap.add_argument('--out')
    ap.add_argument('--transcript')
    ap.add_argument('--format', default='auto', choices=neutral.CHOICES, help='transcript format (default: detected from the file)')
    ap.add_argument('--arch')
    ap.add_argument('--no-validate', action='store_true')
    ap.add_argument('--text', action='store_true')
    ap.add_argument('--theme', default=page_session.THEMES[0], metavar='ID')
    a = ap.parse_args(argv)
    if a.theme not in page_session.THEMES:
        print('error: unknown theme %r; valid ids: %s' % (a.theme, ', '.join(page_session.THEMES)), file=sys.stderr)
        return 1
    try:
        here = os.path.dirname(os.path.abspath(a.explain_json))
        out = os.path.abspath(a.out or os.path.join(here, 'index.html'))
        if session_doc(a.explain_json):
            return render_session(a, out)
        if v2(a.explain_json):
            return render_v2(a, out)
        doc, errs, stats = load_and_validate(a.explain_json, a.repo)
        if errs:
            print('\n'.join(errs))
            print('not rendered: fix the problems above and rerun', file=sys.stderr)
            return 1
        repo = a.repo or gitio.toplevel(here)
        with open(out, 'w', encoding='utf-8') as fh:
            fh.write(page.render(doc, repo))
        print(out)
        return 0
    except (gitio.ExplainError, archmod.ArchError) as e:
        print('error: %s' % e, file=sys.stderr)
        return 2


def render_session(a, out):
    here = os.path.dirname(os.path.abspath(a.explain_json))
    with open(a.explain_json, encoding='utf-8') as fh:
        doc = json.load(fh)
    if a.no_validate:
        problems = page_session.shape_problems(doc)
        if problems:
            print('\n'.join(problems))
            print('not rendered: the doc lacks fields the page needs', file=sys.stderr)
            return 1
        learn_from = a.transcript or doc.get('transcript')
        if isinstance(learn_from, str) and learn_from:
            transcript.learn(learn_from, a.format)  # an archived doc is still kept clear of the session's credentials
        else:
            transcript.learn_quotes(doc)
        print('warning: not validated (--no-validate); nothing was checked against the transcript', file=sys.stderr)
        stats = {'transcript': bool(learn_from)}
    else:
        errs, stats = check_session.validate(doc, a.transcript, base_dir=here, fmt=a.format)
        if errs:
            print('\n'.join(errs))
            print('not rendered: fix the problems above and rerun', file=sys.stderr)
            return 1
        for w in stats.get('warnings', []):
            print('warning: ' + w, file=sys.stderr)
    links = {}
    for i, th in enumerate(doc['themes']):
        cd = th.get('change_doc')
        if not cd:
            continue
        name = page_session.change_page_name(cd)
        sub = argparse.Namespace(explain_json=os.path.join(here, cd), repo=a.repo, out=os.path.join(os.path.dirname(out), name), transcript=None, format=a.format,
                                 arch=a.arch, no_validate=a.no_validate, text=a.text)
        try:
            code = render_v2(sub, sub.out)
        except (OSError, ValueError) as e:  # the doc is missing or is not JSON
            print('error: cannot render the change page of theme %d from %s: %s' % (i + 1, cd, e), file=sys.stderr)
            return 2
        if code:
            return code
        links[i] = name
    body = page_session.render(doc, links, a.theme, session_checked=bool(stats.get('transcript')))
    if len(body.encode('utf-8')) > page2.MAX_BYTES:
        print('error: page is %d KB, over the %d KB limit of html_preview' % (len(body.encode('utf-8')) // 1024, page2.MAX_BYTES // 1024), file=sys.stderr)
        return 2
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(body)
    if a.text:
        with open(out + '.txt', 'w', encoding='utf-8') as fh:
            fh.write(page2.page_text(body))
    print(out)
    return 0


def render_v2(a, out):
    here = os.path.dirname(os.path.abspath(a.explain_json))
    if a.no_validate:
        with open(a.explain_json, encoding='utf-8') as fh:
            doc = json.load(fh)
        problems = page2.shape_problems(doc)
        if problems:
            print('\n'.join(problems))
            print('not rendered: the doc lacks fields the page needs', file=sys.stderr)
            return 1
        learn_from = a.transcript or doc.get('transcript')
        if isinstance(learn_from, str) and learn_from:
            transcript.learn(learn_from, a.format)  # an archived doc is still kept clear of the session's credentials
        else:
            transcript.learn_quotes(doc)
        print('warning: not validated (--no-validate); nothing was checked against git or the transcript', file=sys.stderr)
        arch = archmod.Architecture(a.arch) if a.arch else None
        repo = a.repo
    else:
        from validate import load_and_validate as lv
        doc, errs, stats = lv(a.explain_json, a.repo, a.transcript, a.format)
        if errs:
            print('\n'.join(errs))
            print('not rendered: fix the problems above and rerun', file=sys.stderr)
            return 1
        for w in stats.get('warnings', []):
            print('warning: ' + w, file=sys.stderr)
        repo = a.repo or gitio.toplevel(here)
        arch = archmod.Architecture(a.arch) if a.arch else collect2.load_arch(repo)
    body = page2.render(doc, repo, arch=arch, validated=not a.no_validate, session_checked=False if a.no_validate else bool(stats.get('transcript')))
    if len(body.encode('utf-8')) > page2.MAX_BYTES:
        print('error: page is %d KB, over the %d KB limit of html_preview' % (len(body.encode('utf-8')) // 1024, page2.MAX_BYTES // 1024), file=sys.stderr)
        return 2
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(body)
    if a.text:
        with open(out + '.txt', 'w', encoding='utf-8') as fh:
            fh.write(page2.page_text(body))
    print(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
