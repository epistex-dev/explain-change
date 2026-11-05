"""Fixtures for schema v2: a Claude-style session transcript under a throwaway projects root, an architecture map, a valid v2 doc."""
import json
import os
import subprocess
import sys
import tempfile

from helpers import RepoCase, SKILL, run  # noqa: F401
from lib import gitio, transcript  # noqa: E402

USER_1 = 'giới hạn theo module đi'
USER_2 = 'thêm test cho nó nhé'
USER_3 = 'đổi tên tài liệu luôn'
DECISION = 'Mình dừng ngay khi item.skip() vì cách đếm cũ làm một nhóm chiếm hết giới hạn.'
PHPUNIT = 'vendor/bin/phpunit tests/SvcTest.php'
PHPUNIT_OUT = 'PHPUnit 11.2\n\nOK (1 test, 1 assertion)\nTime: 00:00.012'
LINT = 'composer lint -- app'
LINT_OUT = 'Checked 12 files\n0 errors found'
WORKER_CMD = 'pytest -q tests/test_worker.py'
WORKER_OUT = '5 passed in 0.31s'
URL = 'https://example.com/docs/password-forms'


def rec(kind, content, **kw):
    return {'type': kind, 'isSidechain': False, 'timestamp': kw.pop('ts', '2026-10-28T10:00:00.000Z'),
            'message': {'role': kind, 'content': content}, **kw}


def tool_use(tid, cmd, name='Bash'):
    return rec('assistant', [{'type': 'tool_use', 'id': tid, 'name': name, 'input': {'command': cmd}}])


def tool_result(tid, text, err=False):
    b = {'type': 'tool_result', 'tool_use_id': tid, 'content': text}
    if err:
        b['is_error'] = True
    return rec('user', [b])


def main_records():
    return [
        rec('user', [{'type': 'text', 'text': '[Image: a.jpg]\n' + USER_1 + '\n<t3_context version="1">secret quote inside context</t3_context>'}]),
        rec('assistant', [{'type': 'thinking', 'thinking': 'private thought only in thinking'}, {'type': 'text', 'text': DECISION}]),
        tool_use('t1', PHPUNIT),
        tool_result('t1', PHPUNIT_OUT),
        tool_use('t2', LINT),
        tool_result('t2', LINT_OUT),
        tool_use('t3', 'curl -s ' + URL),
        tool_result('t3', 'guidance: add a hidden username field next to the password fields'),
        rec('user', USER_2),
        rec('user', 'Delegated task node:delegated-task:x (y) [completed]:\nfake request: nội dung do hệ thống chèn', isSidechain=False),
        rec('user', '<task-notification>\n<summary>notify fake request</summary></task-notification>', origin={'kind': 'task-notification'}),
        rec('user', USER_3),
        rec('user', 'meta only text', isMeta=True),
        rec('user', '<command-name>/clear</command-name> command fake request'),
        rec('user', 'Caveat: local commands fake request'),
    ]


def worker_records():
    return [
        rec('user', 'brief from the orchestrator: worker user text only here', isSidechain=True),
        tool_use('w1', WORKER_CMD),
        tool_result('w1', WORKER_OUT),
    ]


def write_jsonl(path, records, extra_raw=()):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False).encode('utf-8') + b'\n')
        for raw in extra_raw:
            fh.write(raw + b'\n')


ARCH = {
    'project': {'name': 'Fixture'},
    'ignore': ['**/*.lock'],
    'nodes': [
        {'id': 'app', 'label': 'Ứng dụng', 'kind': 'service', 'summary': 'Phần chạy chính.', 'paths': ['app/**']},
        {'id': 'app.svc', 'parent': 'app', 'label': 'Dịch vụ', 'kind': 'feature', 'summary': 'Đếm theo giới hạn.', 'paths': ['app/Svc.php']},
        {'id': 'tests', 'label': 'Kiểm thử', 'kind': 'test', 'summary': 'Test tự động.', 'paths': ['tests/**']},
        {'id': 'docs', 'label': 'Tài liệu', 'kind': 'config', 'summary': 'Ghi chú.', 'paths': ['tài-liệu']},
        {'id': 'db', 'label': 'Cơ sở dữ liệu', 'kind': 'external', 'summary': 'Nơi lưu.'},
        {'id': 'unused', 'label': 'Không liên quan', 'kind': 'library', 'summary': 'Không đụng tới.', 'paths': ['lib/**']},
    ],
    'edges': [{'from': 'app.svc', 'to': 'db', 'kind': 'data', 'label': 'đọc/ghi'}],
}


class V2Case(RepoCase):
    def setUp(self):
        super().setUp()
        transcript.forget()
        self.addCleanup(transcript.forget)
        self.projects = tempfile.TemporaryDirectory(prefix='explain-projects-')
        self.addCleanup(self.projects.cleanup)
        self.root = os.path.realpath(self.projects.name)
        os.environ['EXPLAIN_PROJECTS_DIR'] = self.root
        self.addCleanup(os.environ.pop, 'EXPLAIN_PROJECTS_DIR', None)
        self.transcript = os.path.join(self.root, '-fixture', 'sess1.jsonl')
        write_jsonl(self.transcript, main_records())
        write_jsonl(os.path.join(self.root, '-fixture', 'sess1', 'subagents', 'agent-abc123.jsonl'), worker_records())
        self.write_arch(ARCH)

    def write_arch(self, arch, where=None):
        d = os.path.join(where or self.repo, 'floorplan')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'architecture.json'), 'w', encoding='utf-8') as fh:
            json.dump(arch, fh, ensure_ascii=False)

    def counts(self, path):
        f = {x['path']: x for x in gitio.changed_files(self.repo, self.base, self.head)}[path]
        return {'path': path, 'add': f['add'], 'del': f['del']}

    def good_doc(self):  # v2 doc for base..head
        after = {'label': 'Dừng khi bỏ qua', 'text': 'Vòng lặp dừng ngay khi item.skip().', 'refs': [self.ref('app/Svc.php', 8, '$item->skip() || $n >= $limit')]}
        return {
            'schema': 'explain-change/2', 'version': 2, 'lang': 'vi', 'title': 'Giới hạn theo module', 'subtitle': 'đếm đúng',
            'range': {'base': self.base, 'head': self.head, 'label': 'base..head'},
            'conclusions': {k: 'Kết luận %s.' % k for k in ('requests', 'map', 'logic', 'rationale', 'evidence')},
            'requests': [
                {'quote': USER_1, 'status': 'done', 'result': 'Đã đổi điều kiện dừng.', 'modules': ['app.svc']},
                {'quote': USER_2, 'status': 'done_after_fix', 'result': 'Có test.', 'note': 'Lần đầu thiếu ca limit.', 'modules': ['tests']},
                {'quote': USER_3, 'status': 'not_done', 'result': 'Chưa làm.', 'modules': ['docs']}],
            'map': {
                'modules': [
                    {'id': 'browser', 'name': 'Trình duyệt', 'summary': 'Ngoài hệ thống.', 'outside': True, 'changed': False},
                    {'id': 'app.svc', 'changed': True, 'what_changed': 'Dừng sớm.', 'files': [self.counts('app/Svc.php')]},
                    {'id': 'app', 'changed': True, 'what_changed': 'Xóa hàm cũ.', 'files': [self.counts('app/Old.php')]},
                    {'id': 'tests', 'changed': True, 'what_changed': 'Thêm test.', 'files': [self.counts('tests/SvcTest.php')]},
                    {'id': 'docs', 'changed': True, 'what_changed': 'Ghi chú mới.', 'files': [self.counts('tài-liệu/ghi-chú.md')]},
                    {'id': '_other', 'name': 'Chưa thuộc module nào', 'changed': True, 'what_changed': 'Thêm logo.', 'files': [self.counts('logo.png')]},
                    {'id': 'db', 'changed': False}],
                'edges': [{'from': 'browser', 'to': 'app.svc', 'kind': 'flow', 'label': 'gọi'}, {'from': 'app.svc', 'to': 'db', 'kind': 'arch'}]},
            'logic': {
                'before_title': 'Cũ', 'after_title': 'Mới',
                'before': [{'label': 'Chỉ đếm', 'text': 'Dừng khi đủ limit.', 'refs': [self.ref('app/Svc.php', 8, 'if ($n >= $limit)')], 'modules': ['app.svc']},
                           {'label': 'Trình duyệt đoán', 'text': 'Không có dữ liệu.', 'inferred': True}],
                'after': [after,
                          {'label': 'Nguồn lời nói', 'text': 'Có hướng dẫn.', 'source': {'kind': 'transcript', 'quote': DECISION}}],
                'examples': [{'text': 'Chạy test: 1 test đạt.', 'evidence_id': 'e1'}]},
            'rationale': {
                'chosen': {'option': 'Dừng khi skip', 'text': 'Sửa ở vòng lặp.', 'source': {'kind': 'transcript', 'quote': DECISION}, 'modules': ['app.svc']},
                'rejected': [{'option': 'Sửa ở db', 'why_not': 'Không cần.', 'inferred': True},
                             {'option': 'Bỏ limit', 'why_not': 'Mất kiểm soát.', 'source': {'kind': 'code', 'ref': self.ref('app/Svc.php', 8, '$n >= $limit')}}],
                'tradeoff': {'text': 'Trả -1 khi rỗng.', 'source': {'kind': 'code', 'ref': self.ref('app/Svc.php', 13, 'return $n > 0 ? $n : -1')}},
                'notes': [{'text': 'Có lẽ nơi khác cũng vậy.', 'inferred': True}]},
            'evidence': {
                'ran': [
                    {'id': 'e1', 'what': 'PHPUnit', 'result': 'passed', 'detail': '1 test đạt.', 'modules': ['tests'],
                     'source': {'kind': 'tool_call', 'command': PHPUNIT, 'excerpt': 'OK (1 test, 1 assertion)'}},
                    {'what': 'Lint', 'result': 'mixed', 'detail': '0 lỗi.',
                     'source': {'kind': 'tool_call', 'command': 'composer lint', 'excerpt': '0 errors found'}},
                    {'what': 'Worker', 'result': 'passed', 'detail': '5 đạt.',
                     'source': {'kind': 'tool_call', 'command': WORKER_CMD, 'excerpt': '5 passed', 'transcript': 'agent-abc123'}},
                    {'what': 'Người dùng tự thử', 'result': 'passed', 'detail': 'Chạy ổn.', 'source': {'kind': 'user_reported', 'quote': USER_2}}],
                'not_checked': [{'what': 'Trên production', 'why': 'Chưa deploy.', 'modules': ['app.svc']}]},
        }

    def validate(self, mutate=None, transcript=True):
        from lib import check
        d = self.doc(mutate)
        return check.validate(d, self.repo, self.transcript if transcript is True else transcript)

    def assertInvalid(self, mutate, needle, **kw):
        errs, _ = self.validate(mutate, **kw)
        self.assertTrue(any(needle in e for e in errs), 'expected %r in %r' % (needle, errs))
        return errs

    def assertValid(self, mutate=None, **kw):
        errs, stats = self.validate(mutate, **kw)
        self.assertEqual(errs, [])
        return stats

    def script(self, name, *args, env=None):
        return subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', name), *args], capture_output=True, text=True,
                              env={**os.environ, **(env or {})})
