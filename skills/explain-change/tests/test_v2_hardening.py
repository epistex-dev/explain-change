"""Review fixes B1 to B4 (type crashes, false evidence, compaction summary as the user, secrets on the page) and the two
follow-ups (badge when no session was checked, malformed architecture file)."""
import copy
import json
import os
import re
import secrets
import unittest
from unittest import mock

from helpers2 import ARCH, PHPUNIT_OUT, URL, USER_1, V2Case, main_records, rec, tool_result, tool_use, worker_records, write_jsonl
from lib import arch as archmod
from lib import check, collect2, gitio, page2, transcript
from test_guard import at, paths

SECRET_VALUE = 'Zq7!synthetic-Secret-91'  # synthetic; the real credential never appears in a test
SECRET_LINE = 'Pass chung: ' + SECRET_VALUE
LINE = re.compile(r'^[\w$.\[\]]+: \S.*')


def memo_git(case):
    """The repo does not change during a fuzz run: memoise the pure git readers."""
    for name in ('git', 'resolve_rev', 'changed_files', 'read_version'):
        real, cache = getattr(gitio, name), {}

        def cached(*a, _real=real, _cache=cache, **kw):
            k = repr((a, sorted(kw.items())))
            if k not in _cache:
                _cache[k] = _real(*a, **kw)
            return _cache[k]
        p = mock.patch.object(gitio, name, cached)
        p.start()
        case.addCleanup(p.stop)


# ------------------------------------------------------------------------------------------------ B1
class WrongTypes(V2Case):
    """validate never raises and prints `path: reason`; whatever it accepts, the page draws."""

    def setUp(self):
        super().setUp()
        self.bad = []
        memo_git(self)

    def tearDown(self):
        self.assertEqual(self.bad[:12], [], '%d problems' % len(self.bad))

    def rich_doc(self):
        d = self.good_doc()
        d['logic']['after'][0]['visual'] = {'kind': 'form', 'rows': [{'label': 'a', 'value': 'b', 'state': 'new'}]}
        d['logic']['before'][1]['visual'] = {'kind': 'dialog', 'tone': 'bad', 'title': 't', 'subtitle': 's'}
        d['requests'][0]['see'] = 'logic'
        d['map']['modules'][0]['kind'] = 'external'
        d['logic']['cases'] = [{'title': 'Ca', 'text': 'Một nhánh.', 'inferred': True}]
        return d

    def check_doc(self, doc, what):
        try:
            errs, _ = check.validate(doc, self.repo, self.transcript)
        except Exception as e:  # noqa: BLE001
            self.bad.append('validate raised %r for %s' % (e, what))
            return []
        for e in errs:
            if not LINE.match(e):
                self.bad.append('malformed error %r for %s' % (e, what))
        if not errs:
            try:
                page2.render(doc, self.repo)
            except Exception as e:  # noqa: BLE001
                self.bad.append('validate accepted but render raised %r for %s' % (e, what))
        return errs

    def test_the_rich_doc_is_valid(self):
        self.assertEqual(check.validate(self.rich_doc(), self.repo, self.transcript)[0], [])

    def test_wrong_types_anywhere(self):
        n = 0
        base = self.rich_doc()
        for p in paths(base):
            if not p:
                continue
            for bad in ([], {}, ['x'], 7, None, 'x', True):
                doc = copy.deepcopy(base)
                at(doc, p[:-1])[p[-1]] = bad
                n += 1
                self.check_doc(doc, 'set %s = %r' % ('/'.join(map(str, p)), bad))
        self.assertGreater(n, 1500)

    def test_deleting_any_key_in_turn(self):
        n = 0
        base = self.rich_doc()
        for p in paths(base):
            if not p or not isinstance(p[-1], str):
                continue
            doc = copy.deepcopy(base)
            del at(doc, p[:-1])[p[-1]]
            n += 1
            self.check_doc(doc, 'deleted %s' % '/'.join(map(str, p)))
        self.assertGreater(n, 150)

    def test_the_shapes_that_crashed_the_review(self):
        cases = [
            ('visual rows is not a list', lambda d: d['logic']['after'][0].update(visual={'kind': 'form', 'rows': 5}), 'logic.after[0].visual.rows'),
            ('visual rows hold strings', lambda d: d['logic']['after'][0].update(visual={'kind': 'form', 'rows': ['x']}), 'logic.after[0].visual.rows[0]'),
            ('visual form without rows', lambda d: d['logic']['after'][0].update(visual={'kind': 'form'}), 'logic.after[0].visual.rows'),
            ('visual dialog without title', lambda d: d['logic']['after'][0].update(visual={'kind': 'dialog', 'tone': 'good'}), 'logic.after[0].visual.title'),
            ('visual dialog with a wrong tone', lambda d: d['logic']['after'][0].update(visual={'kind': 'dialog', 'tone': 'x', 'title': 't'}), 'logic.after[0].visual.tone'),
            ('visual kind is a list', lambda d: d['logic']['after'][0].update(visual={'kind': ['form']}), 'logic.after[0].visual'),
            ('module kind is a list', lambda d: d['map']['modules'][0].update(kind=['x']), 'map.modules[0].kind'),
            ('outside is a string', lambda d: d['map']['modules'][1].update(outside='yes'), 'map.modules[1].outside'),
            ('edge from is a list', lambda d: d['map']['edges'][0].update({'from': [1]}), 'map.edges[0]'),
            ('evidence id is a list', lambda d: d['evidence']['ran'][0].update(id=['x']), 'evidence.ran[0].id'),
            ('example evidence_id is a list', lambda d: d['logic']['examples'][0].update(evidence_id=['x']), 'logic.examples[0].evidence_id'),
            ('cases is a number', lambda d: d['logic'].update(cases=5), 'logic.cases'),
            ('examples is a bool', lambda d: d['logic'].update(examples=True), 'logic.examples'),
            ('edges is a number', lambda d: d['map'].update(edges=5), 'map.edges'),
            ('notes is a number', lambda d: d['rationale'].update(notes=7), 'rationale.notes'),
            ('file path is a list', lambda d: d['map']['modules'][1]['files'][0].update(path=['x']), 'map.modules[1].files[0]'),
            ('see is unknown', lambda d: d['requests'][0].update(see='map'), 'requests[0].see'),
        ]
        for what, mutate, path in cases:
            doc = self.good_doc()
            mutate(doc)
            errs = self.check_doc(doc, what)
            self.assertTrue(any(e.startswith(path) for e in errs), '%s: expected an error at %s, got %s' % (what, path, errs))

    def test_valid_visuals_render(self):
        out = page2.render(self.rich_doc(), self.repo)
        self.assertIn('class="mf"', out)
        self.assertIn('class="dlg bad"', out)

    def test_validator_and_page_agree_that_outside_means_true(self):
        doc = self.good_doc()
        doc['map']['modules'][1]['outside'] = 'yes'  # not valid: the validator says so, but the page must not draw it as an actor either
        out = page2.render(doc, self.repo)
        node = re.search(r'<article class="([^"]*)"[^>]*data-real="app.svc"', out).group(1)
        self.assertNotIn(' out', ' ' + node)
        doc['map']['modules'][1]['outside'] = True
        node = re.search(r'<article class="([^"]*)"[^>]*data-real="app.svc"', page2.render(doc, self.repo)).group(1)
        self.assertIn('out', node.split())


# ------------------------------------------------------------------------------------------------ B2
BRIEF_CMD = 'pytest -q tests/brief_only.py'
WRITTEN_CMD = 'pytest -q tests/written_only.py'
FAILED_CMD = 'pytest -q tests/failing.py'
NOT_BASH_CMD = 'pytest -q tests/not_bash.py'


def raw_use(tid, name, inp):
    return rec('assistant', [{'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}])


class FalseEvidence(V2Case):
    def setUp(self):
        super().setUp()
        extra = [
            raw_use('d1', 'mcp__t3-code__delegate_task', {'prompt': 'Chạy giúp: %s rồi báo cáo. Đọc %s' % (BRIEF_CMD, 'https://example.com/brief-only')}),
            tool_result('d1', 'brief 7 passed only-in-brief'),
            raw_use('w1', 'Write', {'file_path': '/tmp/x.sh', 'content': WRITTEN_CMD + '\n# https://example.com/written-only'}),
            tool_result('w1', 'File created 9 passed only-in-write'),
            raw_use('n1', 'mcp__x__run', {'command': NOT_BASH_CMD}),
            tool_result('n1', '11 passed only-in-other-tool'),
            tool_use('e1', FAILED_CMD),
            tool_result('e1', '2 failed, 3 passed in 0.1s', err=True),
            raw_use('f1', 'WebFetch', {'url': 'https://example.com/fetched-only', 'prompt': 'read it'}),
            tool_result('f1', 'a page'),
        ]
        write_jsonl(self.transcript, main_records() + extra)

    def ran(self, command, excerpt, result='passed', **kw):
        def mut(d):
            d['evidence']['ran'].append({'what': 'Chạy thêm', 'result': result, 'detail': 'Có chạy.',
                                         'source': {'kind': 'tool_call', 'command': command, 'excerpt': excerpt}, **kw})
        return mut

    def test_a_command_inside_a_worker_brief_is_not_a_run(self):
        self.assertInvalid(self.ran(BRIEF_CMD, '7 passed only-in-brief'), 'command not found in any tool call')

    def test_a_command_inside_written_content_is_not_a_run(self):
        self.assertInvalid(self.ran(WRITTEN_CMD, '9 passed only-in-write'), 'command not found in any tool call')

    def test_only_bash_calls_run_commands(self):
        self.assertInvalid(self.ran(NOT_BASH_CMD, '11 passed only-in-other-tool'), 'command not found in any tool call')

    def test_a_real_bash_run_still_grounds(self):
        self.assertValid(self.ran(PHPUNIT_CMD, 'OK (1 test, 1 assertion)'))

    def test_an_errored_run_cannot_back_passed(self):
        self.assertInvalid(self.ran(FAILED_CMD, '2 failed, 3 passed'), 'is_error')
        errs = self.assertInvalid(self.ran(FAILED_CMD, '2 failed, 3 passed'), 'evidence.ran[4].result')
        self.assertEqual(len([e for e in errs if 'is_error' in e]), 1)

    def test_an_errored_run_backs_failed_and_mixed(self):
        self.assertValid(self.ran(FAILED_CMD, '2 failed, 3 passed', result='failed'))
        self.assertValid(self.ran(FAILED_CMD, '2 failed, 3 passed', result='mixed'))

    def test_a_pass_needs_one_run_that_did_not_error(self):
        def mut(d):
            d['evidence']['ran'].append({'what': 'Đỏ rồi xanh', 'result': 'passed', 'detail': 'Hai lần chạy.', 'source': [
                {'kind': 'tool_call', 'command': FAILED_CMD, 'excerpt': '2 failed'},
                {'kind': 'tool_call', 'command': PHPUNIT_CMD, 'excerpt': 'OK (1 test'}]})
        self.assertValid(mut)

    def test_a_user_report_may_back_a_pass_beside_an_errored_run(self):
        def mut(d):
            d['evidence']['ran'].append({'what': 'Tự chạy', 'result': 'passed', 'detail': 'Người dùng xác nhận.', 'source': [
                {'kind': 'tool_call', 'command': FAILED_CMD, 'excerpt': '2 failed'}, {'kind': 'user_reported', 'quote': USER_1}]})
        self.assertValid(mut)

    def test_a_url_in_a_brief_or_written_file_is_not_seen(self):
        for u in ('https://example.com/brief-only', 'https://example.com/written-only'):
            self.assertInvalid(lambda d: d['rationale']['chosen'].update(source={'kind': 'url', 'url': u}), 'URL not found')

    def test_a_fetched_or_curled_url_is_seen(self):
        self.assertValid(lambda d: d['rationale']['chosen'].update(source={'kind': 'url', 'url': 'https://example.com/fetched-only'}))
        self.assertValid(lambda d: d['rationale']['chosen'].update(source={'kind': 'url', 'url': URL}))

    def test_the_digest_agrees_with_the_validator(self):
        text, _ = transcript.digest(self.transcript)
        self.assertIn(FAILED_CMD, text)
        self.assertIn('ERROR', text)
        for gone in (BRIEF_CMD, WRITTEN_CMD, NOT_BASH_CMD):
            self.assertNotIn(gone, text)


PHPUNIT_CMD = 'vendor/bin/phpunit tests/SvcTest.php'


# ------------------------------------------------------------------------------------------------ B3
SUMMARY = 'This session is being continued from a previous conversation that ran out of context. Summary: người dùng đã yêu cầu "thêm cột trạng thái cho bảng đơn hàng".'


class CompactionSummary(V2Case):
    def put(self, *extra):
        write_jsonl(self.transcript, main_records() + list(extra))

    def quote(self, q):
        return lambda d: d['requests'][0].update(quote=q)

    def test_the_real_record_shape_is_refused(self):
        # shape read from a compacted Claude Code session: a user record, string content, both flags set
        self.put(rec('user', SUMMARY, isCompactSummary=True, isVisibleInTranscriptOnly=True, turnOrigin='task_notification'))
        self.assertInvalid(self.quote('thêm cột trạng thái cho bảng đơn hàng'), 'quote not found')

    def test_either_flag_alone_is_enough(self):
        for flag in ('isCompactSummary', 'isVisibleInTranscriptOnly'):
            self.put(rec('user', 'Tóm tắt riêng: cột trạng thái cho bảng đơn hàng', **{flag: True}))
            self.assertInvalid(self.quote('cột trạng thái cho bảng đơn hàng'), 'quote not found')

    def test_the_opening_words_are_enough_without_flags(self):
        self.put(rec('user', SUMMARY))
        self.assertInvalid(self.quote('thêm cột trạng thái cho bảng đơn hàng'), 'quote not found')
        self.put(rec('user', [{'type': 'text', 'text': SUMMARY}]))
        self.assertInvalid(self.quote('thêm cột trạng thái cho bảng đơn hàng'), 'quote not found')

    def test_a_real_message_after_the_summary_still_counts(self):
        self.put(rec('user', SUMMARY, isCompactSummary=True), rec('user', 'tiếp tục làm phần lọc theo ngày nhé'))
        self.assertValid(self.quote('phần lọc theo ngày'))

    def test_ide_blocks_are_not_what_the_user_typed(self):
        self.put(rec('user', [
            {'type': 'text', 'text': '<ide_opened_file>The user opened the file /x/y.py in the IDE. mục-từ-tệp-mở</ide_opened_file>'},
            {'type': 'text', 'text': '<ide_selection>đoạn chọn trong IDE</ide_selection>\nlời thật của người dùng đây'}]))
        self.assertInvalid(self.quote('mục-từ-tệp-mở'), 'quote not found')
        self.assertInvalid(self.quote('đoạn chọn trong IDE'), 'quote not found')
        self.assertValid(self.quote('lời thật của người dùng đây'))

    def test_the_digest_and_the_candidates_skip_the_summary(self):
        self.put(rec('user', SUMMARY, isCompactSummary=True, isVisibleInTranscriptOnly=True))
        text, _ = transcript.digest(self.transcript)
        self.assertNotIn('This session is being continued', text)
        self.assertNotIn('thêm cột trạng thái', text)
        write_jsonl(self.transcript, [rec('user', SUMMARY, isCompactSummary=True)] + main_records())
        first = transcript.first_user_message(self.transcript)
        self.assertIn(USER_1, first)
        self.assertNotIn('This session is being continued', first)


# ------------------------------------------------------------------------------------------------ B4
class Secrets(V2Case):
    def setUp(self):
        super().setUp()
        write_jsonl(self.transcript, main_records() + [
            rec('user', 'đăng nhập giúp mình\n' + SECRET_LINE + '\nrồi làm tiếp'),
            tool_use('s1', 'login-tool password=%s --go' % SECRET_VALUE),
            tool_result('s1', 'logged in\ntoken: %s\nbye' % SECRET_VALUE)])

    def assertRejectsSecret(self, mutate, path):
        errs, _ = self.validate(mutate)
        hit = [e for e in errs if e.startswith(path) and 'password, token or key' in e]
        self.assertTrue(hit, 'expected a credential error at %s, got %s' % (path, errs))
        self.assertNotIn(SECRET_VALUE, '\n'.join(errs), 'an error line printed the secret')

    def test_the_whole_message_with_the_secret_cannot_be_quoted(self):
        self.assertRejectsSecret(lambda d: d['requests'][0].update(quote='đăng nhập giúp mình ' + SECRET_LINE), 'requests[0].quote')

    def test_the_part_before_the_secret_can_be(self):
        self.assertValid(lambda d: d['requests'][0].update(quote='đăng nhập giúp mình'))

    def test_every_quoted_or_shown_field_is_checked(self):
        for path, mutate in [
            ('rationale.chosen.source.quote', lambda d: d['rationale']['chosen'].update(source={'kind': 'transcript', 'quote': SECRET_LINE})),
            ('evidence.ran[3].source.quote', lambda d: d['evidence']['ran'][3]['source'].update(quote=SECRET_LINE)),
            ('evidence.ran[0].source.command', lambda d: d['evidence']['ran'][0].update(source={'kind': 'tool_call', 'command': 'login-tool password=%s' % SECRET_VALUE, 'excerpt': 'logged in'})),
            ('evidence.ran[0].source.excerpt', lambda d: d['evidence']['ran'][0].update(source={'kind': 'tool_call', 'command': 'login-tool password', 'excerpt': 'token: %s' % SECRET_VALUE})),
            ('evidence.ran[0].detail', lambda d: d['evidence']['ran'][0].update(detail='Đăng nhập bằng ' + SECRET_LINE)),
            ('requests[0].result', lambda d: d['requests'][0].update(result='Dùng %s để vào.' % SECRET_LINE)),
            ('logic.after[0].text', lambda d: d['logic']['after'][0].update(text='Mật khẩu: %s' % SECRET_VALUE)),
            ('map.modules[1].what_changed', lambda d: d['map']['modules'][1].update(what_changed='token=%s' % SECRET_VALUE)),
            ('evidence.not_checked[0].why', lambda d: d['evidence']['not_checked'][0].update(why='api_key=%s' % SECRET_VALUE)),
        ]:
            self.assertRejectsSecret(mutate, path)

    def test_an_error_about_something_else_never_prints_the_secret(self):
        errs, _ = self.validate(lambda d: d['requests'][0].update(quote='quote không có trong phiên ' + SECRET_LINE))
        self.assertTrue(errs)
        self.assertNotIn(SECRET_VALUE, '\n'.join(errs))

    def test_the_cli_never_prints_the_secret(self):
        doc = self.doc(lambda d: d['requests'][0].update(quote='đăng nhập giúp mình ' + SECRET_LINE))
        path = os.path.join(self.repo, 'doc.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False)
        for script in ('validate.py', 'render.py'):
            r = self.script(script, path, '--transcript', self.transcript)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertNotIn(SECRET_VALUE, r.stdout + r.stderr)
            self.assertIn('password, token or key', r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.repo, 'index.html')))

    def test_the_candidates_list_hides_the_secret(self):
        text = collect2.format_candidates(self.repo, [{'path': 'p', 'first_user': 'mở đầu\n' + SECRET_LINE, 'start': 'a', 'end': 'b', 'size': 10, 'subagents': 0}])
        self.assertNotIn(SECRET_VALUE, text)
        self.assertIn('mở đầu', text)

    def test_a_secret_that_got_past_validation_still_stays_off_the_page(self):
        doc = self.doc(lambda d: d['requests'][0].update(result='Vào bằng %s xong' % SECRET_LINE))  # not validated: the archived-doc path
        out = page2.render(doc, self.repo)
        self.assertNotIn(SECRET_VALUE, out)
        self.assertNotIn(SECRET_VALUE, page2.page_text(out))

    def test_ordinary_text_is_not_flagged(self):
        self.assertValid(lambda d: d['requests'][0].update(result='Đổi mật khẩu xong, token hết hạn thì đăng nhập lại.'))


# ------------------------------------------------------------------------------------------------ follow-ups
class NoSessionBadge(V2Case):
    BADGE = 'Chưa đối chiếu với phiên làm việc'

    def run_render(self, doc, *args):
        path = os.path.join(self.repo, 'doc.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False)
        r = self.script('render.py', path, *args)
        html = ''
        if r.returncode == 0:
            with open(os.path.join(self.repo, 'index.html'), encoding='utf-8') as fh:
                html = fh.read()
        return r, html

    def test_a_doc_with_no_session_shows_the_badge(self):
        r, html = self.run_render(self.doc(lambda d: d.update(transcript_unavailable='phiên đã bị xoá')))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn(self.BADGE, html)
        self.assertIn('class="chip warn unchecked"', html)

    def test_a_checked_doc_has_no_badge(self):
        r, html = self.run_render(self.doc(), '--transcript', self.transcript)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertNotIn(self.BADGE, html)

    def test_an_unvalidated_archive_says_it_too(self):
        r, html = self.run_render(self.doc(), '--no-validate', '--arch', os.path.join(self.repo, 'floorplan', 'architecture.json'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(self.BADGE, html)

    def test_english_page_says_it_in_english(self):
        r, html = self.run_render(self.doc(lambda d: d.update(transcript_unavailable='gone', lang='en')))
        self.assertIn('Not checked against the session', html)


class BadArchitecture(V2Case):
    def bad_arch(self, mutate):
        a = copy.deepcopy(ARCH)
        mutate(a)
        self.write_arch(a)
        return os.path.join(self.repo, 'floorplan', 'architecture.json')

    CASES = [
        ('bad glob in paths', lambda a: a['nodes'][0].update(paths=['src/[z-a]x'])),
        ('bad glob in exclude', lambda a: a['nodes'][0].update(exclude=['src/[z-a]x'])),
        ('bad glob in ignore', lambda a: a.update(ignore=['src/[z-a]x'])),
        ('parent is a list', lambda a: a['nodes'][1].update(parent=['app'])),
        ('kind is a list', lambda a: a['nodes'][0].update(kind=['service'])),
        ('label is a number', lambda a: a['nodes'][0].update(label=5)),
        ('paths is a string', lambda a: a['nodes'][0].update(paths='app/**')),
        ('paths holds a list', lambda a: a['nodes'][0].update(paths=[['app/**']])),
        ('edge from is a list', lambda a: a['edges'][0].update({'from': ['app.svc']})),
        ('edges is a number', lambda a: a.update(edges=5)),
        ('ignore is a string', lambda a: a.update(ignore='x')),
    ]

    def test_a_malformed_architecture_raises_arch_error_not_a_raw_exception(self):
        for what, mutate in self.CASES:
            path = self.bad_arch(mutate)
            with self.assertRaises(archmod.ArchError, msg=what):
                archmod.Architecture(path)

    def test_validate_reports_it_as_an_error_line(self):
        for what, mutate in self.CASES:
            self.bad_arch(mutate)
            errs, _ = self.validate()
            self.assertTrue(any(e.startswith('map:') for e in errs), '%s: %s' % (what, errs[:3]))

    def test_the_cli_prints_one_line_and_no_traceback(self):
        doc_path = os.path.join(self.repo, 'doc.json')
        for what, mutate in self.CASES:
            self.bad_arch(mutate)
            with open(doc_path, 'w', encoding='utf-8') as fh:
                json.dump(self.doc(), fh, ensure_ascii=False)
            for args in (('render.py', doc_path, '--transcript', self.transcript), ('validate.py', doc_path, '--transcript', self.transcript),
                         ('collect.py', '--v2', '%s..%s' % (self.base, self.head), '--repo', self.repo)):
                r = self.script(*args)
                self.assertNotIn('Traceback', r.stderr, '%s %s: %s' % (what, args[0], r.stderr[-300:]))
                self.assertNotEqual(r.returncode, 0, '%s %s' % (what, args[0]))
        self.assertFalse(os.path.exists(os.path.join(self.repo, 'index.html')))

    def test_a_good_architecture_still_loads(self):
        self.write_arch(ARCH)
        a = archmod.Architecture(os.path.join(self.repo, 'floorplan', 'architecture.json'))
        self.assertIn('app.svc', a.nodes)


if __name__ == '__main__':
    unittest.main()


# ------------------------------------------------------------------------------------------------ D2
class EachFactOnce(V2Case):
    LONG = 'Người dùng thấy ô mật khẩu cũ không còn bị Chrome điền sẵn vào form đổi mật khẩu nữa'

    def warns(self, mutate):
        d = self.good_doc()
        mutate(d)
        errs, stats = check.validate(d, self.repo, self.transcript)
        self.assertEqual(errs, [])
        return stats['warnings']

    def test_a_result_that_repeats_a_logic_step_warns(self):
        def m(d):
            d['logic']['after'][0]['text'] = self.LONG + '.'
            d['requests'][0]['result'] = self.LONG
        w = self.warns(m)
        self.assertTrue(any('requests[0].result repeats' in x and 'logic.after[0]' in x for x in w), w)

    def test_a_result_that_repeats_an_evidence_detail_warns(self):
        def m(d):
            d['evidence']['ran'][0]['detail'] = self.LONG + '.'
            d['requests'][0]['result'] = self.LONG
        w = self.warns(m)
        self.assertTrue(any('requests[0].result repeats' in x and 'evidence.ran[0]' in x for x in w), w)

    def test_a_short_outcome_does_not_warn(self):
        def m(d):
            d['logic']['after'][0]['text'] = self.LONG + '.'
            d['requests'][0]['result'] = 'Đã sửa xong, xem chi tiết ở tab Logic.'
        self.assertFalse([x for x in self.warns(m) if 'repeats' in x])

    def test_a_long_result_warns(self):
        w = self.warns(lambda d: d['requests'][0].update(result='Một câu rất dài. ' * 20))
        self.assertTrue(any('requests[0].result' in x and 'characters' in x for x in w), w)

    def test_a_wrongly_typed_result_does_not_crash_the_check(self):
        for bad in (5, ['x'], {'a': 1}, None):
            d = self.good_doc()
            d['requests'][0]['result'] = bad
            check.validate(d, self.repo, self.transcript)


# ------------------------------------------------------------------------------------------------ round 2
def synthetic_secret():
    """A fresh mixed-symbol value per run: the real credential never appears in a test."""
    return 'Qx%s#Lm_%s!' % (secrets.token_hex(3), secrets.token_hex(2))


CODE_LINES = [
    'password: z.string().min(8),',
    'password: user.password,',
    'const token = parts[1];',
    'secret: process.env.JWT_SECRET,',
    'bypass: skip_auth_2024x,',
    'TOKEN=$GITLAB_TOKEN',
]


class SecretsRound2(V2Case):
    def setUp(self):
        super().setUp()
        self.value = synthetic_secret()
        write_jsonl(self.transcript, main_records() + [
            rec('user', 'đăng nhập giúp mình\nPass chung: ' + self.value + '\nrồi làm tiếp'),
            rec('user', 'thử lại với ' + self.value + ' nhé'),
            tool_use('s1', 'ls'), tool_result('s1', 'ok')])
        write_jsonl(os.path.join(self.root, '-fixture', 'sess1', 'subagents', 'agent-abc123.jsonl'), worker_records() + [
            raw_use('w1', 'mcp__x__login', {'body': {'password': 'x', 'note': 'password=' + self.value + ' --go'}})])

    def rejects(self, mutate, path):
        errs, _ = self.validate(mutate)
        self.assertTrue([e for e in errs if e.startswith(path) and 'password, token or key' in e], (path, errs))
        self.assertNotIn(self.value, '\n'.join(errs))

    def test_a_quote_of_the_bare_value_is_rejected(self):
        self.rejects(lambda d: d['requests'][0].update(quote='thử lại với ' + self.value), 'requests[0].quote')

    def test_the_bare_value_is_rejected_in_every_text_field_and_in_a_snippet(self):
        v = self.value
        self.rejects(lambda d: d['logic']['after'][0].update(text='Dùng %s để vào.' % v), 'logic.after[0].text')
        self.rejects(lambda d: d['evidence']['ran'][0].update(detail=v), 'evidence.ran[0].detail')
        self.rejects(lambda d: d['logic']['after'][0]['refs'][0].update(snippet='x = "%s"' % v), 'logic.after[0].refs[0].snippet')
        self.rejects(lambda d: d['rationale']['tradeoff']['source']['ref'].update(snippet=v), 'rationale.tradeoff.source.ref.snippet')

    def test_a_value_learned_from_a_worker_transcript_counts_too(self):
        write_jsonl(self.transcript, main_records())  # the value is now only in the worker's tool call
        transcript.forget()
        self.rejects(lambda d: d['logic']['after'][0].update(text='bare %s' % self.value), 'logic.after[0].text')

    def test_a_labelled_value_is_caught_with_its_label_even_with_no_transcript(self):
        transcript.forget()
        errs, _ = self.validate(lambda d: d['requests'][0].update(result='Pass chung: ' + self.value), transcript=None)
        self.assertTrue([e for e in errs if e.startswith('requests[0].result') and 'password, token or key' in e], errs)

    def test_code_is_not_flagged(self):
        for line in CODE_LINES:
            self.assertFalse(transcript.has_secret(line), line)
            self.assertEqual(transcript.redact(line), line)
            self.assertEqual(transcript.secret_values(line), set(), line)
        self.assertValid(lambda d: d['logic']['after'][0].update(text=' '.join(CODE_LINES)))

    def test_a_snippet_is_not_label_swept_but_a_label_in_text_is(self):
        errs, _ = self.validate(lambda d: d['logic']['after'][0]['refs'][0].update(snippet='password: Abc12345x!'))
        self.assertFalse([e for e in errs if 'password, token or key' in e], errs)
        self.rejects(lambda d: d['logic']['after'][0].update(text='password: Abc12345x!'), 'logic.after[0].text')

    def test_a_bare_word_with_a_digit_after_a_label_is_still_a_secret(self):
        self.assertTrue(transcript.has_secret('Pass chung: Abc12345'))

    def test_a_word_that_merely_contains_pass_is_not_a_label(self):
        self.assertFalse(transcript.has_secret('bypass: abc123def, compass=north_2'))
        self.assertFalse(transcript.has_secret('risk-assessment-model and task-runner-config'))
        self.assertTrue(transcript.has_secret('db_password=Abc12345!'))

    def test_page_text_and_candidates_hide_the_bare_value(self):
        doc = self.doc(lambda d: d['requests'][0].update(result='Vào bằng %s xong' % self.value))
        transcript.learn(self.transcript)
        out = page2.render(doc, self.repo)
        self.assertNotIn(self.value, out)
        self.assertNotIn(self.value, page2.page_text(out))
        transcript.forget()
        text = collect2.format_candidates(self.repo, [{'path': self.transcript, 'first_user': 'thử ' + self.value + ' đi', 'start': 'a', 'end': 'b', 'size': 10, 'subagents': 0}])
        self.assertNotIn(self.value, text)
        self.assertIn('thử', text)

    def test_the_digest_hides_the_bare_value(self):
        transcript.forget()
        text, _ = transcript.digest(self.transcript)
        self.assertNotIn(self.value, text)
        self.assertIn('thử lại với', text)

    def test_a_labelled_secret_in_a_tool_result_is_hidden_in_the_digest(self):
        other = synthetic_secret()  # only in a result
        write_jsonl(self.transcript, main_records() + [
            rec('user', 'chạy giúp'), tool_use('r1', 'pytest -q tests/test_login.py'), tool_result('r1', '1 passed\nlogin used token: %s\ndone' % other)])
        transcript.forget()
        text, _ = transcript.digest(self.transcript)
        self.assertIn('1 passed', text)
        self.assertNotIn(other, text)
        transcript.forget()  # nothing learned: the label alone must still hide the value
        self.assertNotIn(other, transcript.redact('login used token: %s' % other))

    def test_render_of_an_archived_doc_learns_from_the_transcript(self):
        doc = self.doc(lambda d: d['requests'][0].update(result='Vào bằng %s xong' % self.value))
        path = os.path.join(self.repo, 'doc.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False)
        r = self.script('render.py', path, '--no-validate', '--transcript', self.transcript, '--text')
        self.assertEqual(r.returncode, 0, r.stderr)
        for f in ('index.html', 'index.html.txt'):
            with open(os.path.join(self.repo, f), encoding='utf-8') as fh:
                self.assertNotIn(self.value, fh.read(), f)


class UrlSources(V2Case):
    def setUp(self):
        super().setUp()
        write_jsonl(self.transcript, main_records() + [
            raw_use('u1', 'mcp__exa__web_fetch_exa', {'urls': ['https://example.com/a-list', 'https://example.com/b-list']}),
            tool_result('u1', 'page'),
            raw_use('u2', 'mcp__t3-code__preview_navigate', {'url': 'https://example.com/navigated'}),
            tool_result('u2', 'page'),
            raw_use('u3', 'mcp__t3-code__preview_open', {'url': 'https://example.com/opened'}),
            tool_result('u3', 'page'),
            raw_use('u4', 'mcp__x__other', {'url': 'https://example.com/not-a-fetch'}),
            tool_result('u4', 'page')])

    def url(self, u):
        return lambda d: d['rationale']['chosen'].update(source={'kind': 'url', 'url': u})

    def test_a_url_in_a_list_or_opened_in_the_preview_is_seen(self):
        for u in ('https://example.com/a-list', 'https://example.com/b-list', 'https://example.com/navigated', 'https://example.com/opened'):
            self.assertValid(self.url(u))

    def test_a_url_of_an_unrelated_tool_is_not(self):
        self.assertInvalid(self.url('https://example.com/not-a-fetch'), 'URL not found')
