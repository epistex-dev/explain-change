"""explain-flow/1: validate.py grounds each source in `git show <commit>:<path>`; collect.py --flow needs no diff.
The fixture is a tiny git repo built in a temp dir: nothing here reads this repo's history (CI checks out with depth 1)."""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'skills', 'explain-change')
sys.path.insert(0, os.path.join(SKILL, 'scripts'))
VALIDATE = os.path.join(SKILL, 'scripts', 'validate.py')
COLLECT = os.path.join(SKILL, 'scripts', 'collect.py')
EXAMPLES = os.path.join(SKILL, 'references', 'examples')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sample_env import without_transcript  # noqa: E402

PARSE = ['def load(path):', '    text = open(path).read()', '    return text', '', 'def check(doc):', '    if not doc:', '        raise ValueError("empty")',
         '    return True', '', 'def show(doc):', '    print(doc)']
BIG = ['line %d of a long file' % i for i in range(1, 101)]
WIDE = 'word ' * 90  # 449 characters on one line


def sh(cwd, *args):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError('%s: %s' % (args, p.stderr))
    return p.stdout.strip()


def src(path='src/app.py', lines=(5, 8), excerpt='if not doc: raise ValueError("empty")'):
    return {'path': path, 'lines': list(lines), 'excerpt': excerpt}


class FlowCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='flow-test-')
        self.addCleanup(self._tmp.cleanup)
        self._docs = tempfile.TemporaryDirectory(prefix='flow-doc-')  # the doc lives outside the repo
        self.addCleanup(self._docs.cleanup)
        self.repo = os.path.realpath(self._tmp.name)
        sh(self.repo, 'git', 'init', '-q', '-b', 'main')
        sh(self.repo, 'git', 'config', 'user.email', 't@example.com')
        sh(self.repo, 'git', 'config', 'user.name', 'T')
        self.put('src/app.py', '\n'.join(PARSE) + '\n')
        self.put('src/big.txt', '\n'.join(BIG) + '\n')
        self.put('src/wide.txt', WIDE.strip() + '\n')
        self.put('lib/util.py', 'x = 1\n')
        with open(os.path.join(self.repo, 'src', 'blob.dat'), 'wb') as fh:
            fh.write(b'\x00\x01\x02 binary data here\n')
        with open(os.path.join(self.repo, 'src', 'latin.txt'), 'wb') as fh:
            fh.write(b'caf\xe9 au lait is not utf-8 text\n')
        os.symlink('app.py', os.path.join(self.repo, 'src', 'link.py'))
        sh(self.repo, 'git', 'add', '-A')
        sh(self.repo, 'git', 'commit', '-q', '-m', 'fixture')
        self.sha = sh(self.repo, 'git', 'rev-parse', 'HEAD')
        # edit the working copy after the commit: sources must be read from the commit, not from here
        self.put('src/app.py', 'changed\n')

    def put(self, rel, text):
        p = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(text)

    def good(self):
        return {
            'kind': 'explain-flow/1', 'lang': 'en', 'title': 'How a document is checked',
            'question': 'How does a doc get checked? (asked as: `check()` ?)',
            'summary': 'A document is accepted only when it is not empty, and an empty one stops the check with an error.',
            'commit': self.sha,
            'parts': [
                {'id': 'caller', 'name': 'Caller', 'where': 'outside', 'role': 'Hands a document to the checker.', 'sources': []},
                {'id': 'checker', 'name': 'Checker', 'where': 'inside', 'role': 'Loads and judges the document.', 'sources': [src('src/app.py', (1, 3), 'text = open(path).read()')]}],
            'steps': [
                {'id': 's1', 'name': 'Load the document', 'part': 'checker', 'takes_in': 'A file path.', 'gives_back': 'The text of the file.',
                 'sources': [src('src/app.py', (1, 3), 'text = open(path).read()')], 'branches': [], 'errors': []},
                {'id': 's2', 'name': 'Judge it', 'part': 'checker', 'takes_in': 'The text (for example a short note).', 'gives_back': 'A yes, or an error.',
                 'sources': [src()], 'branches': [{'when': 'The text is empty', 'to': 'problems'}, {'when': 'The text has content', 'to': 's3'}],
                 'errors': [{'id': 'e1', 'name': 'Empty document', 'result': 'The check stops with an error.', 'sources': [src()]}]},
                {'id': 's3', 'name': 'Show the result', 'part': 'caller', 'takes_in': 'The yes.', 'gives_back': 'The text on screen.',
                 'sources': [src('src/app.py', (10, 11), 'print(doc)')], 'branches': [], 'errors': []}]}

    def run_validate(self, doc, *extra):
        path = os.path.join(self._docs.name, 'doc.flow.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh)
        return subprocess.run([sys.executable, VALIDATE, path, '--repo', self.repo, *extra], capture_output=True, text=True)

    def doc(self, mutate=None):
        d = self.good()
        if mutate:
            mutate(d)
        return d

    def assertRejected(self, mutate, needle):
        p = self.run_validate(self.doc(mutate))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertTrue(any(needle in ln for ln in p.stdout.splitlines()), 'expected %r in %r' % (needle, p.stdout))
        self.assertNotIn('Traceback', p.stderr)
        return p.stdout

    def src_of(self, d, **kw):
        d['steps'][0]['sources'] = [src(**kw)]


class Sources(FlowCase):
    def test_good_doc_is_ok_and_reads_the_commit_not_the_working_copy(self):
        p = self.run_validate(self.good())
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.splitlines()[0], 'ok')
        self.assertIn('flow | parts 2 (1 outside) | steps 3, 1 with branches | error exits 1 | sources 5', p.stdout)

    def test_absolute_path(self):
        self.assertRejected(lambda d: self.src_of(d, path='/etc/passwd', lines=(1, 1)), 'repo-relative path')

    def test_dotdot_path(self):
        self.assertRejected(lambda d: self.src_of(d, path='../outside.py', lines=(1, 1)), 'must not hold ".."')

    def test_symlink_in_the_tree(self):
        self.assertRejected(lambda d: self.src_of(d, path='src/link.py', lines=(1, 1), excerpt='app.py app.py'), 'is a symlink in the tree')

    def test_path_missing_at_the_commit(self):
        self.assertRejected(lambda d: self.src_of(d, path='src/nope.py'), 'no such file at commit')

    def test_folder_is_not_a_file(self):
        self.assertRejected(lambda d: self.src_of(d, path='src'), 'not a file')

    def test_lines_start_at_one(self):
        self.assertRejected(lambda d: self.src_of(d, lines=(0, 1)), 'lines start at 1')

    def test_first_line_after_last(self):
        self.assertRejected(lambda d: self.src_of(d, lines=(5, 3)), 'is after last line')

    def test_span_past_end_of_file(self):
        self.assertRejected(lambda d: self.src_of(d, lines=(5, 12)), 'has 11 lines at this commit, not 12')

    def test_span_over_eighty_lines(self):
        self.assertRejected(lambda d: self.src_of(d, path='src/big.txt', lines=(1, 81), excerpt='line 3 of a long file'), 'spans 81 lines')

    def test_span_of_eighty_lines_is_fine(self):
        p = self.run_validate(self.doc(lambda d: self.src_of(d, path='src/big.txt', lines=(1, 80), excerpt='line 3 of a long file')))
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_lines_must_be_two_numbers(self):
        self.assertRejected(lambda d: self.src_of(d, lines=[5]), 'two whole numbers')

    def test_excerpt_empty(self):
        self.assertRejected(lambda d: self.src_of(d, excerpt='   '), 'required non-empty string')

    def test_excerpt_too_short(self):
        self.assertRejected(lambda d: self.src_of(d, excerpt='doc'), 'it must be 8 to 300')

    def test_excerpt_over_three_hundred_characters(self):
        self.assertRejected(lambda d: self.src_of(d, path='src/wide.txt', lines=(1, 1), excerpt=WIDE), 'it must be 8 to 300')

    def test_excerpt_not_in_the_span(self):
        self.assertRejected(lambda d: self.src_of(d, lines=(1, 3), excerpt='raise ValueError("empty")'), 'not found in src/app.py lines 1-3')

    def test_excerpt_whitespace_is_squeezed(self):
        p = self.run_validate(self.doc(lambda d: self.src_of(d, excerpt='if   not doc:\n   raise ValueError("empty")')))
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_binary_file(self):
        self.assertRejected(lambda d: self.src_of(d, path='src/blob.dat', lines=(1, 1), excerpt='binary data here'), 'is a binary file')

    def test_invalid_utf8(self):
        self.assertRejected(lambda d: self.src_of(d, path='src/latin.txt', lines=(1, 1), excerpt='au lait is not'), 'is not valid UTF-8')

    def test_unknown_commit(self):
        out = self.assertRejected(lambda d: d.update(commit='1' * 40), 'unknown commit')
        self.assertNotIn('no such file', out)

    def test_commit_must_be_the_full_sha(self):
        self.assertRejected(lambda d: d.update(commit=self.sha[:12]), 'full 40-character SHA')

    def test_all_problems_come_back_together(self):
        def bad(d):
            d['steps'][0]['sources'] = [src(path='src/nope.py'), src(lines=(0, 1)), src(excerpt='not in the code at all')]
        p = self.run_validate(self.doc(bad))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len(p.stdout.splitlines()), 3, p.stdout)
        self.assertTrue(all(ln.startswith('steps[0].sources[') for ln in p.stdout.splitlines()))


class WrongTypes(FlowCase):
    """A field of the wrong type is one `path: reason` line and exit 1, never a traceback (an unhashable value hit a dict lookup)."""
    WRONG = (['x'], {'a': 1}, 7, None)
    OPTIONAL = ('branches', 'errors', 'sources', 'icon', 'reads')  # absent or null is the same as not given

    def test_step_part_that_is_a_list_or_dict(self):
        for v in (['x'], {'a': 1}):
            with self.subTest(v):
                out = self.assertRejected(lambda d: d['steps'][0].update(part=v), 'steps[0].part: must be the id of a part of this doc')
                self.assertEqual(len(out.splitlines()), 1, out)

    def test_branch_target_that_is_a_list_or_dict(self):
        for v in (['a'], {'a': 1}):
            with self.subTest(v):
                out = self.assertRejected(lambda d: d['steps'][1]['branches'][0].update(to=v), 'steps[1].branches[0].to: must be a step id')
                self.assertTrue(all(ln.startswith(('steps[1].branches[0].to:', 'steps')) for ln in out.splitlines()), out)

    def test_source_path_with_a_lone_surrogate(self):
        out = self.assertRejected(lambda d: d['steps'][0]['sources'][0].update(path='a\ud800b'), 'steps[0].sources[0].path: must be a repo-relative path')
        self.assertEqual(len(out.splitlines()), 1, out)

    def test_visible_text_with_a_lone_surrogate(self):
        for setter in (lambda d, v: d.update(title=v), lambda d, v: d.update(question=v), lambda d, v: d['parts'][0].update(role=v),
                       lambda d, v: d['steps'][0].update(takes_in=v), lambda d, v: d['steps'][1]['branches'][0].update(when=v),
                       lambda d, v: d['steps'][1]['errors'][0].update(result=v)):
            with self.subTest(setter):
                out = self.assertRejected(lambda d: setter(d, 'bad \ud800 text'), 'cannot be written as UTF-8')
                self.assertEqual(len(out.splitlines()), 1, out)

    def paths(self, node, here=()):
        yield here
        if isinstance(node, dict):
            for k, v in node.items():
                yield from self.paths(v, here + (k,))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from self.paths(v, here + (i,))

    def test_every_field_given_a_list_dict_number_or_null_is_a_line_not_a_crash(self):
        from lib import check_flow
        base = self.good()
        base['parts'][0]['icon'] = 'user'
        base['steps'][2]['reads'] = ['checker']
        self.assertEqual(check_flow.validate(copy.deepcopy(base), self.repo)[0], [])  # the starting point is clean, so every line below comes from the change
        seen = 0
        for path in self.paths(base):
            if not path or path == ('kind',):
                continue
            for v in self.WRONG:
                d = copy.deepcopy(base)
                node = d
                for k in path[:-1]:
                    node = node[k]
                node[path[-1]] = copy.deepcopy(v)
                with self.subTest(path=path, value=v):
                    errs, _ = check_flow.validate(d, self.repo)  # a crash here is the failure
                    seen += 1
                    ok_empty = (v is None and path[-1] in self.OPTIONAL) or (v == 7 and path[-2:-1] == ('lines',))  # 7 is a fine line number
                    self.assertTrue(errs or ok_empty, 'accepted %r at %s' % (v, path))
                    for e in errs:
                        self.assertRegex(e, r'^[A-Za-z_$][\w\[\].]*: \S', e)
                        self.assertNotIn('\n', e)
        self.assertGreater(seen, 200)


class PartIcons(FlowCase):
    def test_a_known_icon_passes_and_an_unknown_one_is_one_line(self):
        p = self.run_validate(self.doc(lambda d: d['parts'][1].update(icon='shield-check')))
        self.assertEqual(p.returncode, 0, p.stdout)
        out = self.assertRejected(lambda d: d['parts'][1].update(icon='rocket'), 'parts[1].icon: must be one of')
        self.assertEqual(len(out.splitlines()), 1, out)

    def test_the_allowlist_is_the_sprite_plus_the_flow_icons(self):
        import re
        from lib import check_flow
        ui = os.path.join(SKILL, 'assets', 'ui')
        have = set()
        for f in ('icons.svg', 'session-icons.svg', 'flow-icons.svg'):
            with open(os.path.join(ui, f), encoding='utf-8') as fh:
                have |= set(re.findall(r'<symbol id="i-([a-z0-9-]+)"', fh.read()))
        self.assertEqual(set(check_flow.ICONS), have)


class Reads(FlowCase):
    def test_reads_a_part_is_fine(self):
        p = self.run_validate(self.doc(lambda d: d['steps'][0].update(reads=['caller'])))
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_reads_must_be_a_list_of_part_ids(self):
        self.assertRejected(lambda d: d['steps'][0].update(reads='caller'), 'steps[0].reads: must be a list of part ids')
        self.assertRejected(lambda d: d['steps'][0].update(reads=['nobody']), 'steps[0].reads[0]: must be the id of a part of this doc')

    def test_reads_its_own_part_is_refused(self):
        self.assertRejected(lambda d: d['steps'][0].update(reads=['checker']), 'steps[0].reads[0]: is the part of the step itself')

    def test_reads_twice_is_refused(self):
        self.assertRejected(lambda d: d['steps'][0].update(reads=['caller', 'caller']), 'steps[0].reads[1]: duplicate')


class Structure(FlowCase):
    def test_empty_steps(self):
        self.assertRejected(lambda d: d.update(steps=[]), 'steps: needs at least 1')

    def test_empty_parts(self):
        self.assertRejected(lambda d: d.update(parts=[]), 'parts: needs at least 1')

    def test_duplicate_id(self):
        self.assertRejected(lambda d: d['steps'][2].update(id='s1'), "duplicate id 's1'")

    def test_id_shared_across_kinds_is_a_duplicate(self):
        self.assertRejected(lambda d: d['steps'][1]['errors'][0].update(id='checker'), "duplicate id 'checker'")

    def test_reserved_id(self):
        self.assertRejected(lambda d: d['steps'][2].update(id='end'), 'reserved for a branch target')

    def test_part_reference_dangles(self):
        self.assertRejected(lambda d: d['steps'][0].update(part='ghost'), 'steps[0].part: must be the id of a part')

    def test_dangling_branch_target(self):
        self.assertRejected(lambda d: d['steps'][1]['branches'][1].update(to='s9'), "'s9' is neither")

    def test_unreachable_step(self):
        def cut(d):
            d['steps'][1]['branches'][1]['to'] = 'end'
        self.assertRejected(cut, "unreachable from step 1: no step or branch leads to 's3'")

    def test_no_path_to_end(self):
        def loop(d):
            d['steps'][2]['branches'] = [{'when': 'Always', 'to': 'problems'}]
        self.assertRejected(loop, 'no path from step 1 reaches "end"')

    def test_a_cycle_that_can_leave_is_fine(self):
        def retry(d):
            d['steps'][2]['branches'] = [{'when': 'Try again', 'to': 's1'}, {'when': 'Done', 'to': 'end'}]
        self.assertEqual(self.run_validate(self.doc(retry)).returncode, 0)

    def test_a_next_step_with_a_bad_id_is_not_the_end(self):
        def bad(d):
            d['steps'][2]['id'] = 'bad id'
            d['steps'][1]['branches'] = []
        out = self.assertRejected(bad, 'steps[2].id: required')
        self.assertIn('no path from step 1 reaches "end"', out)

    def test_error_needs_a_source(self):
        self.assertRejected(lambda d: d['steps'][1]['errors'][0].update(sources=[]), 'steps[1].errors[0].sources: needs at least 1')

    def test_step_needs_a_source(self):
        self.assertRejected(lambda d: d['steps'][0].update(sources=[]), 'steps[0].sources: needs at least 1')

    def test_inside_part_needs_a_source(self):
        self.assertRejected(lambda d: d['parts'][1].update(sources=[]), 'parts[1].sources: needs at least 1')

    def test_outside_part_may_have_none(self):
        self.assertEqual(self.run_validate(self.good()).returncode, 0)

    def test_where_is_inside_or_outside(self):
        self.assertRejected(lambda d: d['parts'][0].update(where='nearby'), 'parts[0].where')


# Each item is one test case. BENIGN must pass the visible-text rule; CODE must be refused.
BENIGN = ['Node.js', 'Vue.js', 'README.md', 'CHANGELOG.md', 'example.com', 'github.com/epistex-dev', '$5.50', 'v1.2.3', '3.14', 'e.g.', 'i.e.', 'claim(s)',
          "the user's id", 'CI/CD', 'TCP/IP', 'A \u2192 B', '2 of 5', '50%', 'Q&A', 'Checks the file: if it is missing, it stops; otherwise it goes on.',
          'Reads README.md, then Node.js runs the check', 'See docs.example.com for the page', 'Opens check_flow.py first',
          'A note (e.g. a short one), i.e. one line; claim(s) with 3.5 points - well, etc.', 'Takes in a path (for example, the file the user named).',
          'Reads GitHub issues and the v2 page, then replies in 2 steps.', 'Return the list of claims', 'If it goes wrong, say so']
CODE = ['x = y + 1', 'a == b', 'a != b', 'x += 1', 'lambda x: x+1', 'x => x + 1', 'if x > 0:', 'x > 0', 'a < b', 'return foo', 'foo(bar)', 'obj.method()', 'user_id', 'file.py:12',
        'src/app.py:40', '<div>', '`code`', '{a: 1}', '[1, 2]', 'arr[0]', 'a && b', 'a || b', '->', '::', 'x => x + 1', 'if (a == b) { go }',
        'the result of load(path) or doc.text', 'the check_session module', 'it returns self.rows[0]', 'a -> b', 'see app.py:12', 'a <div class="x"> tag',
        'Calls `run_all` first', 'reads $HOME first', 'it uses self.rows', 'else:']


class CodeRule(unittest.TestCase):
    """The visible-text rule itself (check_flow.code_reason), item by item."""
    def test_benign_prose_passes(self):
        from lib import check_flow
        for t in BENIGN:
            with self.subTest(t):
                self.assertIsNone(check_flow.code_reason(t))

    def test_code_is_refused(self):
        from lib import check_flow
        for t in CODE:
            with self.subTest(t):
                self.assertIsNotNone(check_flow.code_reason(t))


class VisibleText(FlowCase):
    def test_code_in_takes_in(self):
        self.assertRejected(lambda d: d['steps'][0].update(takes_in='the result of load(path) or doc.text'), 'steps[0].takes_in: reads as code')

    def test_code_in_every_visible_field(self):
        for field, setter in (('title', lambda d, v: d.update(title=v)), ('summary', lambda d, v: d.update(summary=v)),
                              ('role', lambda d, v: d['parts'][0].update(role=v)), ('name', lambda d, v: d['steps'][0].update(name=v)),
                              ('gives_back', lambda d, v: d['steps'][0].update(gives_back=v)), ('when', lambda d, v: d['steps'][1]['branches'][0].update(when=v)),
                              ('result', lambda d, v: d['steps'][1]['errors'][0].update(result=v))):
            with self.subTest(field):
                self.assertRejected(lambda d: setter(d, 'Calls `run_all` first'), 'reads as code')

    def test_other_code_shapes(self):
        for shape in ('x => x + 1', 'if (a == b) { go }', 'the check_session module', 'it returns self.rows[0]', 'a -> b', 'see app.py:12', 'a <div class="x"> tag'):
            with self.subTest(shape):
                self.assertRejected(lambda d: d['steps'][0].update(takes_in=shape), 'reads as code')

    def test_benign_prose_passes(self):
        prose = ['A note (e.g. a short one), i.e. one line; claim(s) with 3.5 points - well, etc.', 'Takes in a path (for example, the file the user named).',
                 'Reads GitHub issues and the v2 page, then replies in 2 steps.']
        for t in prose:
            with self.subTest(t):
                p = self.run_validate(self.doc(lambda d: d['steps'][0].update(takes_in=t)))
                self.assertEqual(p.returncode, 0, p.stdout)

    def test_visible_text_rule_is_the_same_for_every_field(self):
        """One rule for every visible field: prose passes and code is refused in each of them."""
        setters = (('title', lambda d, v: d.update(title=v)), ('summary', lambda d, v: d.update(summary=v)),
                   ('role', lambda d, v: d['parts'][0].update(role=v)), ('name', lambda d, v: d['steps'][0].update(name=v)),
                   ('takes_in', lambda d, v: d['steps'][0].update(takes_in=v)), ('gives_back', lambda d, v: d['steps'][0].update(gives_back=v)),
                   ('when', lambda d, v: d['steps'][1]['branches'][0].update(when=v)), ('result', lambda d, v: d['steps'][1]['errors'][0].update(result=v)))
        for field, setter in setters:
            with self.subTest(field, text='Node.js'):
                p = self.run_validate(self.doc(lambda d: setter(d, 'Reads README.md with Node.js')))
                self.assertEqual(p.returncode, 0, p.stdout)
            with self.subTest(field, text='x = y + 1'):
                self.assertRejected(lambda d: setter(d, 'Sets x = y + 1 first'), 'reads as code')

    def test_question_is_shown_as_asked(self):
        p = self.run_validate(self.doc(lambda d: d.update(question='what does `check()` do?')))
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_secret_in_summary(self):
        out = self.assertRejected(lambda d: d.update(summary='It works once you set token: Zx9!hunter2abc first.'), 'summary: contains what looks like a password')
        self.assertNotIn('hunter2', out)

    def test_secret_in_question(self):
        self.assertRejected(lambda d: d.update(question='my key is sk-abcdefgh12345678'), 'question: contains what looks like a password')


class Collect(FlowCase):
    def run_collect(self, *args, cwd=None):
        return subprocess.run([sys.executable, COLLECT, '--flow', '--repo', self.repo, *args], capture_output=True, text=True, cwd=cwd or self.repo)

    def test_lists_head_modules_files_and_run_dir_without_a_diff(self):
        sh(self.repo, 'git', 'checkout', '-q', '--', '.')  # clean tree and an unchanged HEAD: nothing to diff
        p = self.run_collect('--path', 'src', '--path', 'lib/util.py', '--slug', 'my flow')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('HEAD=%s' % self.sha, p.stdout)
        self.assertIn('## Modules', p.stdout)
        self.assertIn('  src/app.py  [', p.stdout)
        self.assertIn('  lib/util.py  [', p.stdout)
        self.assertNotIn('  README', p.stdout)
        run_dir = [ln for ln in p.stdout.splitlines() if ln.startswith('RUN_DIR=')][0][8:]
        self.assertTrue(os.path.basename(run_dir).endswith('-my-flow'), run_dir)
        with open(os.path.join(run_dir, 'summary.json'), encoding='utf-8') as fh:
            s = json.load(fh)
        self.assertEqual((s['mode'], s['commit'], s['scope']), ('flow', self.sha, ['src', 'lib/util.py']))
        self.assertIn('src/app.py', s['files'])
        self.assertFalse(os.path.exists(os.path.join(run_dir, 'diff.patch')))

    def test_never_exits_3_even_with_nothing_changed(self):
        sh(self.repo, 'git', 'checkout', '-q', '--', '.')
        self.assertEqual(self.run_collect().returncode, 0)

    def test_warns_about_uncommitted_changes(self):
        self.assertIn('uncommitted changes', self.run_collect().stdout)

    def test_modules_come_from_the_architecture_when_there_is_one(self):
        self.put('floorplan/architecture.json', json.dumps({'nodes': [{'id': 'core', 'label': 'Core', 'kind': 'service', 'summary': 'The checker.', 'paths': ['src/**']}]}))
        sh(self.repo, 'git', 'add', '-A')
        sh(self.repo, 'git', 'commit', '-q', '-m', 'arch')
        p = self.run_collect('--path', 'src')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('source A', p.stdout)
        self.assertIn('core  Core [service] - The checker.', p.stdout)

    def test_path_with_no_file_is_refused(self):
        p = self.run_collect('--path', 'nowhere')
        self.assertEqual(p.returncode, 2)
        self.assertIn('no tracked file at HEAD', p.stderr)

    def test_existing_mode_still_exits_3_with_no_changes(self):
        sh(self.repo, 'git', 'checkout', '-q', '--', '.')
        sh(self.repo, 'git', 'commit', '-q', '--allow-empty', '-m', 'empty')
        p = subprocess.run([sys.executable, COLLECT, '--v2', '--repo', self.repo], capture_output=True, text=True)
        self.assertEqual(p.returncode, 3)


class OtherKinds(FlowCase):
    """The other doc kinds keep their output byte for byte (captured from origin/main before explain-flow)."""

    def test_session_example_without_a_transcript(self):
        """The no-transcript path of a session doc keeps its output byte for byte (the sample, with its transcript swapped for a reason)."""
        with open(os.path.join(EXAMPLES, 'portal-day.session.json'), encoding='utf-8') as fh:
            doc = without_transcript(json.load(fh))
        with tempfile.TemporaryDirectory(prefix='flow-session-') as tmp:
            path = os.path.join(tmp, 'day.session.json')
            shutil.copy(os.path.join(EXAMPLES, 'password-autofill.v2.json'), tmp)  # the change doc its `login` theme links
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(doc, fh)
            p = subprocess.run([sys.executable, VALIDATE, path], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, 'warning: transcript checks off (synthetic sample): quotes, commands and outward counts are not compared with a session\nok\n'
                         'session | themes 8 (done 5, done_by_user 1, done_needs_you 1, in_progress 1) | events 28 | needs you 3 | decided 6 (1 irreversible) | '
                         'outward repo_created 2, push 2, force_push 2, history_rewrite 1, delete 3 | grounded in transcript 0 (11 of them worker reports), not compared 39, '
                         'inferred 5 | transcript checks off\n')

    def test_change_example_in_a_repo_without_its_range_names_the_range(self):
        with open(os.path.join(EXAMPLES, 'password-autofill.v2.json'), encoding='utf-8') as fh:
            rng = json.load(fh)['range']
        p = subprocess.run([sys.executable, VALIDATE, os.path.join(EXAMPLES, 'password-autofill.v2.json'), '--repo', self.repo], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout.splitlines()[:2], ['range.base: unknown revision: ' + rng['base'], 'range.head: unknown revision: ' + rng['head']])

    def test_a_doc_without_the_flow_kind_is_not_checked_as_a_flow(self):
        p = self.run_validate({'schema': 'explain-change/1', 'kind': 'explain-change/2'})
        self.assertNotIn('flow |', p.stdout)
        self.assertNotIn('steps: needs at least 1', p.stdout)


class Example(unittest.TestCase):
    def test_bundled_example_validates_clean(self):
        here = os.path.join(EXAMPLES, 'claim-check.flow.json')
        with open(here, encoding='utf-8') as fh:
            doc = json.load(fh)
        root = subprocess.run(['git', '-C', SKILL, 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
        have = root.returncode == 0 and subprocess.run(['git', '-C', SKILL, 'cat-file', '-e', doc['commit'] + '^{commit}'], capture_output=True).returncode == 0
        if not have:
            self.skipTest('the pinned commit %s is not in this checkout (shallow clone or no git)' % doc['commit'][:12])
        p = subprocess.run([sys.executable, VALIDATE, here], capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout.splitlines()[:1]), (0, ['ok']), p.stdout)

    def test_bundled_example_has_the_documented_shape(self):
        with open(os.path.join(EXAMPLES, 'claim-check.flow.json'), encoding='utf-8') as fh:
            doc = copy.deepcopy(json.load(fh))
        self.assertEqual((doc['kind'], doc['lang']), ('explain-flow/1', 'en'))
        self.assertEqual((len(doc['parts']), len(doc['steps']), sum(len(s['errors']) for s in doc['steps'])), (7, 11, 12))
        self.assertEqual(sum(1 for s in doc['steps'] if s['branches']), 5)


if __name__ == '__main__':
    unittest.main()
