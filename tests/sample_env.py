#!/usr/bin/env python3
"""The environment in which the bundled samples are checked: a synthetic git repo that holds the change sample's range, and a throwaway
HOME whose ~/.claude/projects holds the two synthetic transcripts. The readers accept a transcript only inside the harness's own folder, so
the samples are checked through the real path (no flag, no override), only with HOME pointing at a temp dir.

    python3 tests/sample_env.py OUT [--theme ID]   builds OUT/env and renders both checked pages: OUT/change/index.html and OUT/session/index.html
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), 'skills', 'explain-change')
EXAMPLES = os.path.join(SKILL, 'references', 'examples')
SCRIPTS = os.path.join(SKILL, 'scripts')
CHANGE = os.path.join(EXAMPLES, 'password-autofill.v2.json')
SESSION = os.path.join(EXAMPLES, 'portal-day.session.json')
SLUG = '-work-acme-portal'  # the folder Claude Code names after the working directory
TRANSCRIPTS = ('password-autofill.v2.transcript.jsonl', 'portal-day.session.transcript.jsonl')
GIT_ENV = {'GIT_AUTHOR_NAME': 'Sample', 'GIT_AUTHOR_EMAIL': 'sample@example.test', 'GIT_COMMITTER_NAME': 'Sample', 'GIT_COMMITTER_EMAIL': 'sample@example.test',
           'GIT_AUTHOR_DATE': '2026-10-28T09:00:00+00:00', 'GIT_COMMITTER_DATE': '2026-10-28T09:00:00+00:00'}

RESET_BASE = 'export function ResetPasswordModal({ user }) {\n  return (\n    <form>\n      <input type="password" name="newPassword" />\n    </form>\n  );\n}\n'
RESET_HEAD = RESET_BASE.replace('      <input type="password"', '      <input type="text" name="username" value={user.email} autoComplete="username" hidden readOnly />\n      <input type="password"')
RESET_HEAD = RESET_HEAD.replace('hidden readOnly />', 'hidden readOnly />\n      {/* the browser pairs the new password with this person */}', 1)
FORM_BASE = 'export function UserForm() {\n  return <input name="email" />;\n}\n'
FORM_HEAD = 'export function UserForm() {\n  return <input name="email" autoComplete="username" />;\n}\n'
CHANGE_BASE = 'export function ChangePasswordPage({ me }) {\n  return (\n    <form>\n      <input type="password" name="current" />\n    </form>\n  );\n}\n'
CHANGE_HEAD = CHANGE_BASE.replace('      <input type="password"', '      <input type="text" name="username" value={me.email} autoComplete="username" hidden readOnly />\n      {/* same pairing as the reset form */}\n      <input type="password"')
TEST_HEAD = 'import { describe, it, expect } from "vitest";\n' + ''.join(
    'describe("password forms %02d", () => {\n  it("carries a username", () => {\n    expect(%d).toBe(%d);\n  });\n});\n' % (i, i, i) for i in range(1, 12)) + '\n\n\n'
PATHS = {'web.admin': ['src/features/users/**'], 'web.auth': ['src/features/auth/**'], 'tests': ['tests/**'], 'web.api': ['src/api/**'], 'server': ['server/**']}
KINDS = {'browser': 'external', 'web.admin': 'feature', 'web.auth': 'feature', 'tests': 'test', 'web.api': 'library', 'server': 'service'}


def architecture():
    """floorplan/architecture.json of the synthetic repo, taken from the change sample's own map so the module ids cannot drift."""
    with open(CHANGE, encoding='utf-8') as fh:
        m = json.load(fh)['map']
    nodes = []
    for x in (x for x in m['modules'] if not x.get('outside')):  # a module marked outside is not in the code base
        n = {'id': x['id'], 'parent': 'acme', 'label': x['name'], 'kind': KINDS[x['id']], 'summary': x['summary']}
        if x['id'] in PATHS:
            n['paths'] = PATHS[x['id']]
        nodes.append(n)
    nodes.insert(0, {'id': 'acme', 'label': 'System', 'kind': 'service', 'summary': 'The whole made-up web app.', 'paths': ['src/**', 'server/**', 'tests/**']})
    return {'project': {'name': 'Acme Portal'}, 'nodes': nodes, 'edges': [{'from': e['from'], 'to': e['to'], 'kind': 'data', 'label': e.get('label', 'uses')} for e in m['edges'] if 'browser' not in (e['from'], e['to'])]}


FILES_BASE = {'src/features/users/ResetPasswordModal.jsx': RESET_BASE, 'src/features/users/UserForm.jsx': FORM_BASE, 'src/features/auth/ChangePasswordPage.jsx': CHANGE_BASE}
FILES_HEAD = {'src/features/users/ResetPasswordModal.jsx': RESET_HEAD, 'src/features/users/UserForm.jsx': FORM_HEAD, 'src/features/auth/ChangePasswordPage.jsx': CHANGE_HEAD,
              'tests/users-password-autofill.test.jsx': TEST_HEAD}


def _git(repo, *args):
    subprocess.run(['git', '-C', repo, *args], check=True, capture_output=True, env={**os.environ, **GIT_ENV, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull})


def _head(repo):
    return subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()


def build_repo(repo):
    """Create the synthetic repo at `repo` with the change sample's two commits; returns (base, head). The commit ids do not depend on the run."""
    os.makedirs(repo)
    subprocess.run(['git', 'init', '-q', '-b', 'main', repo], check=True, capture_output=True, env={**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull})
    os.makedirs(os.path.join(repo, 'floorplan'))
    with open(os.path.join(repo, 'floorplan', 'architecture.json'), 'w', encoding='utf-8') as fh:
        json.dump(architecture(), fh, indent=1)
    ids = []
    for files, msg in ((FILES_BASE, 'chore: acme portal password forms'), (FILES_HEAD, 'fix(users): add username field to password forms')):
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(repo, rel)), exist_ok=True)
            with open(os.path.join(repo, rel), 'w', encoding='utf-8') as fh:
                fh.write(text)
        _git(repo, 'add', '-A')
        _git(repo, 'commit', '-q', '-m', msg)
        ids.append(_head(repo))
    return ids[0], ids[1]


def build_home(home):
    """Copy the two transcripts into <home>/.claude/projects/<slug>/ and return that folder."""
    folder = os.path.join(home, '.claude', 'projects', SLUG)
    os.makedirs(folder)
    for name in TRANSCRIPTS:
        shutil.copy(os.path.join(EXAMPLES, name), os.path.join(folder, name))
    return folder


def without_transcript(doc, reason='synthetic sample'):
    """A copy of a sample doc that declares no session (for the tests of the no-transcript path)."""
    d = {k: v for k, v in doc.items() if k != 'transcript'}
    d['transcript_unavailable'] = reason
    return d


def env_for(home):
    env = {k: v for k, v in os.environ.items() if k not in ('EXPLAIN_PROJECTS_DIR',)}
    env['HOME'] = home
    return env


def script(name, *args, home, check=False):
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, name), *args], capture_output=True, text=True, env=env_for(home))
    if check and p.returncode:
        sys.exit(p.stdout + p.stderr)
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('out')
    ap.add_argument('--theme', default=None)
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    home, repo = os.path.join(out, 'env', 'home'), os.path.join(out, 'env', 'repo')
    shutil.rmtree(os.path.join(out, 'env'), ignore_errors=True)
    build_repo(repo)
    build_home(home)
    theme = ['--theme', a.theme] if a.theme else []
    for doc, sub in ((CHANGE, 'change'), (SESSION, 'session')):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
        page = os.path.join(out, sub, 'index.html')
        p = script('render.py', doc, '--repo', repo, '--out', page, '--text', *theme, home=home, check=True)
        print(p.stdout.strip())


if __name__ == '__main__':
    main()
