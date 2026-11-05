import json
import os
import re
import subprocess
import sys
import unittest

from helpers import SKILL, RepoCase, run
from lib import page

RENDER = os.path.join(SKILL, 'scripts', 'render.py')
EVIL = '</script><img src=x onerror=alert(1)>'


def html_of(case, mutate=None):
    return page.render(case.doc(mutate), case.repo, with_mermaid=False)


class Rendering(RepoCase):
    def test_verified_and_inferred_badges(self):
        def m(d):
            d['why']['refs'].append({'file': 'app/Svc.php', 'line': 8, 'inferred': True})
        out = html_of(self, m)
        self.assertIn('đã xác minh', out)
        self.assertIn('suy luận', out)
        self.assertIn('Suy luận của agent', out)

    def test_all_verified_page_has_no_inferred_label(self):
        out = html_of(self)
        self.assertIn('đã xác minh', out)
        self.assertNotIn('suy luận', out)

    def test_english_labels(self):
        out = html_of(self, lambda d: d.update(lang='en'))
        self.assertIn('verified', out)
        self.assertIn('Why it changed', out)
        self.assertNotIn('Vì sao đổi', out)

    def test_snippet_and_text_are_escaped(self):
        with open(os.path.join(self.repo, 'app/Svc.php'), encoding='utf-8') as fh:
            cur = fh.read()
        self.write('app/Svc.php', cur + '// %s\n' % EVIL)
        self.commit('evil')
        head = self.rev('HEAD')
        n = cur.count('\n') + 1

        def m(d):
            d['range']['head'] = head
            d['why']['refs'][0].update(snippet=EVIL, line=n)
            d['title'] = EVIL
            d['why']['lines'][0] = 'text ' + EVIL
        out = html_of(self, m)
        self.assertNotIn('<img src=x', out)
        self.assertNotIn('onerror=alert(1)><', out)
        self.assertIn('&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;', out)
        self.assertEqual(out.count('</script>'), 1)  # only the page's own script tag

    def test_diagram_label_cannot_break_out(self):
        def m(d):
            d['flows']['items'][0]['steps'][0]['label'] = 'x"] --> evil[<img src=x onerror=1>; #'
        out = html_of(self, m)
        self.assertNotIn('<img', out)
        src = re.search(r'<pre class="mermaid-src">(.*?)</pre>', out, re.S).group(1)
        line = re.sub(r'#\w+;', '', src.split('p1: ', 1)[1].split('\n')[0])
        for ch in ';"<>':
            self.assertNotIn(ch, line)

    def test_vietnamese_text_and_paths_render(self):
        out = html_of(self)
        self.assertIn('tài-liệu/ghi-chú.md', out)
        self.assertIn('Giới hạn theo module', out)

    def test_deleted_file_citation_is_marked_old_version(self):
        self.assertIn('bản cũ', html_of(self))

    def test_every_file_is_listed_with_counts(self):
        out = html_of(self)
        for f in ['app/Svc.php', 'tests/SvcTest.php', 'app/Old.php', 'logo.png']:
            self.assertIn(f, out)
        self.assertIn('nhị phân', out)

    def test_sections_in_order(self):
        out = html_of(self)
        pos = [out.index('<section id="%s"' % k) for k in ['why', 'changes', 'flows', 'logic', 'risks', 'quiz']]
        self.assertEqual(pos, sorted(pos))

    def test_sub_change_and_logic_item_link_to_each_other(self):
        out = html_of(self, lambda d: d['logic']['items'][0].update(change='c1'))
        self.assertIn('href="#logic-l1"', out)
        self.assertIn('href="#change-c1"', out)
        self.assertIn('id="logic-l1"', out)
        self.assertIn('id="change-c1"', out)

    def test_each_section_opens_with_its_conclusion(self):
        out = html_of(self)
        for k in ['why', 'changes', 'flows', 'logic', 'risks']:
            self.assertRegex(out, r'<section id="%s"><h2>[^<]*</h2><p class="lede">' % k)

    def test_cli_refuses_invalid_and_writes_nothing(self):
        d = self.good_doc()
        d['why']['refs'][0]['snippet'] = 'not in the code'
        p = os.path.join(self.repo, 'explain.json')
        with open(p, 'w') as fh:
            json.dump(d, fh)
        r = subprocess.run([sys.executable, RENDER, p, '--repo', self.repo], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('snippet not found', r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.repo, 'index.html')))

    def test_cli_renders_valid_doc_with_mermaid_inlined(self):
        p = os.path.join(self.repo, 'explain.json')
        with open(p, 'w') as fh:
            json.dump(self.good_doc(), fh)
        r = subprocess.run([sys.executable, RENDER, p, '--repo', self.repo], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(r.stdout.strip(), encoding='utf-8') as fh:
            out = fh.read()
        self.assertIn('mermaid', out)
        self.assertNotRegex(out, r'<script[^>]+src=')
        self.assertNotRegex(out, r'<link[^>]+href=')


if __name__ == '__main__':
    unittest.main()
