#!/usr/bin/env python3
"""Validate explain.json and render index.html next to it (self-contained, works offline).

usage: render.py <explain.json> [--repo PATH] [--out FILE] [--transcript FILE] [--arch FILE] [--no-validate] [--text]
Schema v1 renders the report page, schema v2 the layout-2 page (one file, fonts inlined, under 512 KB).
A validation problem prints the same lines as validate.py, writes nothing, exits 1.
On success prints the absolute path of the page. --text also writes <page>.txt, the words of a v2 page, for the cold-read gate.
--arch and --no-validate (v2 only) render an archived doc whose git range is gone: nothing is checked, the page says validated=no.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import arch as archmod  # noqa: E402
from lib import check2, collect2, gitio, page, page2, transcript  # noqa: E402
from validate import load_and_validate  # noqa: E402


def v2(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return check2.is_v2(json.load(fh))
    except (OSError, ValueError):
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('explain_json')
    ap.add_argument('--repo')
    ap.add_argument('--out')
    ap.add_argument('--transcript')
    ap.add_argument('--arch')
    ap.add_argument('--no-validate', action='store_true')
    ap.add_argument('--text', action='store_true')
    a = ap.parse_args(argv)
    try:
        here = os.path.dirname(os.path.abspath(a.explain_json))
        out = os.path.abspath(a.out or os.path.join(here, 'index.html'))
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
            transcript.learn(learn_from)  # an archived doc is still kept clear of the session's credentials
        print('warning: not validated (--no-validate); nothing was checked against git or the transcript', file=sys.stderr)
        arch = archmod.Architecture(a.arch) if a.arch else None
        repo = a.repo
    else:
        from validate import load_and_validate as lv
        doc, errs, stats = lv(a.explain_json, a.repo, a.transcript)
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
