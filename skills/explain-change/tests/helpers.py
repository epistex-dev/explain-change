import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL, 'scripts'))

from lib import gitio  # noqa: E402

SVC_BASE = '''<?php
class Svc
{
    public function run(int $limit): int
    {
        $n = 0;
        foreach ($this->items() as $item) {
            if ($n >= $limit) {
                break;
            }
            $n++;
        }
        return $n;
    }

    public function gone(): void
    {
    }
}
'''
SVC_HEAD = '''<?php
class Svc
{
    public function run(int $limit): int
    {
        $n = 0;
        foreach ($this->items() as $item) {
            if ($item->skip() || $n >= $limit) {
                break;
            }
            $n++;
        }
        return $n > 0 ? $n : -1;
    }
}
'''
TEST_HEAD = '''<?php
class SvcTest
{
    public function test_run_stops_at_limit(): void
    {
        $this->assertSame(2, (new Svc)->run(2));
    }
}
'''


def run(cwd, *args, env=None):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if p.returncode != 0:
        raise RuntimeError('%s: %s' % (args, p.stderr))
    return p.stdout.strip()


class RepoCase(unittest.TestCase):
    """A throwaway git repo: base commit, then a head commit that edits, adds, deletes, adds a binary and a Vietnamese path."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='explain-test-')
        self.addCleanup(self._tmp.cleanup)
        self.repo = os.path.realpath(self._tmp.name)
        run(self.repo, 'git', 'init', '-q', '-b', 'main')
        run(self.repo, 'git', 'config', 'user.email', 't@example.com')
        run(self.repo, 'git', 'config', 'user.name', 'T')
        self.write('app/Svc.php', SVC_BASE)
        self.write('app/Old.php', '<?php\n// legacy helper that is removed\nfunction oldHelper() { return 1; }\n')
        self.commit('base')
        self.base = self.rev('HEAD')
        self.write('app/Svc.php', SVC_HEAD)
        self.write('tests/SvcTest.php', TEST_HEAD)
        self.write('tài-liệu/ghi-chú.md', '# Ghi chú\nGiới hạn mỗi module.\n')
        os.remove(os.path.join(self.repo, 'app/Old.php'))
        with open(os.path.join(self.repo, 'logo.png'), 'wb') as fh:
            fh.write(b'\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0')
        self.commit('head: đổi giới hạn')
        self.head = self.rev('HEAD')

    def write(self, rel, text):
        p = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(text)

    def commit(self, msg):
        run(self.repo, 'git', 'add', '-A')
        run(self.repo, 'git', 'commit', '-q', '-m', msg)

    def rev(self, r):
        return run(self.repo, 'git', 'rev-parse', r)

    # ---- a valid explain.json for base..head
    def ref(self, file, line, snippet, **kw):
        return {'file': file, 'line': line, 'snippet': snippet, **kw}

    def good_doc(self):
        loop = self.ref('app/Svc.php', 7, 'foreach ($this->items() as $item)')
        cond = self.ref('app/Svc.php', 8, '$item->skip() || $n >= $limit')
        return {
            'schema': 'explain-change/1', 'lang': 'vi', 'title': 'Giới hạn theo module',
            'range': {'base': self.base, 'head': self.head, 'label': 'base..head'},
            'why': {'conclusion': 'Một nhóm làm đói nhóm khác.', 'lines': ['Dòng một.', 'Dòng hai.'], 'refs': [cond]},
            'changes': {'conclusion': '3 thay đổi.', 'items': [
                {'id': 'c1', 'title': 'Đổi điều kiện dừng', 'summary': 'Dừng khi item.skip().', 'files': ['app/Svc.php'], 'refs': [cond]},
                {'id': 'c2', 'title': 'Test và ghi chú', 'summary': 'Thêm test.', 'files': ['tests/SvcTest.php', 'tài-liệu/ghi-chú.md'],
                 'refs': [self.ref('tests/SvcTest.php', 7, 'assertSame(2, (new Svc)->run(2))')]},
                {'id': 'c3', 'title': 'Dọn', 'summary': 'Xóa Old, thêm logo.', 'files': ['app/Old.php', 'logo.png'],
                 'refs': [self.ref('app/Old.php', 3, 'function oldHelper()')]},
            ]},
            'flows': {'conclusion': 'Một luồng.', 'items': [{
                'id': 'f1', 'title': 'Chạy run', 'summary': 'Gọi run.',
                'actors': [{'id': 'a', 'label': 'Người gọi'}, {'id': 's', 'label': 'Svc::run'}],
                'steps': [{'from': 'a', 'to': 's', 'label': 'run(limit)', 'changed': False, 'ref': self.ref('app/Svc.php', 5, 'public function run(int $limit)')},
                          {'from': 's', 'to': 's', 'label': 'dừng khi skip', 'changed': True, 'ref': cond}]}]},
            'logic': {'conclusion': 'Một hàm.', 'items': [{
                'id': 'l1', 'file': 'app/Svc.php', 'function': 'run', 'title': 'run dừng sớm', 'summary': 'Đếm tới limit.',
                'kind': 'trace', 'refs': [loop],
                'trace': {'input': [{'name': 'limit', 'value': '2'}],
                          'steps': [{'text': 'n=0', 'value': '0', 'ref': self.ref('app/Svc.php', 6, '$n = 0;')}],
                          'result': 'trả 2',
                          'origin': {'kind': 'test', 'cite': self.ref('tests/SvcTest.php', 7, 'assertSame(2, (new Svc)->run(2))')}}}]},
            'risks': {'conclusion': 'Ít rủi ro.', 'items': [{'kind': 'break', 'text': 'Trả -1 khi rỗng.', 'refs': [self.ref('app/Svc.php', 13, 'return $n > 0 ? $n : -1')]}]},
            'quiz': {'items': [
                {'q': 'run(2) trả gì?', 'a': '2.', 'refs': [loop]},
                {'q': 'Vì sao có skip?', 'a': 'Để dừng.', 'refs': [cond]}]},
        }

    def doc(self, mutate=None):
        d = self.good_doc()
        if mutate:
            mutate(d)
        return d

    def validate(self, mutate=None):
        from lib import check
        return check.validate(self.doc(mutate), self.repo)

    def assertValid(self, mutate=None):
        errs, stats = self.validate(mutate)
        self.assertEqual(errs, [])
        return stats

    def assertInvalid(self, mutate, needle):
        errs, _ = self.validate(mutate)
        self.assertTrue(any(needle in e for e in errs), 'expected %r in %r' % (needle, errs))
