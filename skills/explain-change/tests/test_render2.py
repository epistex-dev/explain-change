import json
import os
import re
import unittest

from helpers2 import DECISION, PHPUNIT, PHPUNIT_OUT, USER_1, V2Case
from lib import collect2, page2

EVIL = '<script>alert(1)</script>'


def block(out, start, end):
    i = out.index(start)
    return out[i:out.index(end, i)]


class RenderV2(V2Case):
    def page(self, mutate=None, **kw):
        return page2.render(self.doc(mutate), self.repo, **kw)

    def data(self, out):
        return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', out, re.S).group(1))

    def cli(self, doc, *args):
        path = os.path.join(self.repo, 'x.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False)
        return path, self.script('render.py', path, '--transcript', self.transcript, *args)

    # ---- dispatch
    def test_cli_renders_a_v2_doc_to_the_layout_2_page(self):
        path, r = self.cli(self.doc())
        self.assertEqual(r.returncode, 0, r.stderr)
        out = os.path.join(self.repo, 'index.html')
        self.assertEqual(r.stdout.strip(), out)
        with open(out, encoding='utf-8') as fh:
            html = fh.read()
        self.assertIn('explain-change v2; validated=yes', html)
        self.assertIn('id="stage"', html)
        self.assertNotIn('mermaid', html.lower())

    def test_cli_still_renders_a_v1_doc_with_the_v1_page(self):
        from helpers import RepoCase
        _, r = self.cli(RepoCase.good_doc(self))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.repo, 'index.html'), encoding='utf-8') as fh:
            html = fh.read()
        self.assertNotIn('id="stage"', html)
        self.assertIn('mermaid', html.lower())

    def test_invalid_v2_doc_writes_nothing(self):
        d = self.doc(lambda d: d['requests'][0].update(quote='một câu chưa ai nói'))
        _, r = self.cli(d)
        self.assertEqual(r.returncode, 1)
        self.assertIn('quote not found', r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.repo, 'index.html')))

    def test_no_validate_renders_an_archived_doc_and_says_so(self):
        d = self.doc(lambda d: d['range'].update(base='0' * 40))  # the range is gone
        path = os.path.join(self.repo, 'x.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(d, fh)
        r = self.script('render.py', path, '--no-validate', '--arch', os.path.join(self.repo, 'floorplan', 'architecture.json'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('not validated', r.stderr)
        with open(os.path.join(self.repo, 'index.html'), encoding='utf-8') as fh:
            self.assertIn('validated=no', fh.read())

    def test_text_flag_writes_the_words_of_the_page(self):
        _, r = self.cli(self.doc(), '--text')
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.repo, 'index.html.txt'), encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn('Kết luận requests.', text)
        self.assertNotIn('<', text)
        self.assertNotIn('font-face', text)
        self.assertNotIn('function', text)

    def test_page_over_the_preview_limit_is_refused(self):
        d = self.doc(lambda d: d['requests'][0].update(result='x ' * 300000))
        _, r = self.cli(d, '--no-validate')
        self.assertEqual(r.returncode, 2)
        self.assertIn('over the 512 KB limit', r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.repo, 'index.html')))

    # ---- the five blocks
    def test_every_block_is_present_in_order_and_opens_with_its_conclusion(self):
        out = self.page()
        marks = [out.index('id="map-h">Kết luận map.')] + [out.index('class="concl">Kết luận %s.' % k) for k in ('requests', 'logic', 'rationale', 'evidence')]
        self.assertEqual(marks, sorted(marks))
        for k in ('req', 'logic', 'why', 'evidence'):
            self.assertIn('id="p-%s" role="tabpanel"' % k, out)
        # each panel starts with its conclusion
        for panel, key in (('p-req', 'requests'), ('p-logic', 'logic'), ('p-why', 'rationale'), ('p-evidence', 'evidence')):
            self.assertRegex(out, r'id="%s" role="tabpanel"[^>]*><p class="concl">Kết luận %s\.' % (panel, key))

    def test_block_contents(self):
        out = self.page()
        req = block(out, 'id="p-req"', 'id="p-logic"')
        self.assertEqual(req.count('<li class="card'), 3)
        for chip in ('Xong', 'Sai lần đầu', 'Chưa làm được'):
            self.assertIn(chip, req)
        logic = block(out, 'id="p-logic"', 'id="p-why"')
        self.assertEqual(logic.count('class="step stp"'), 4)  # 2 before + 2 after
        self.assertIn('Trước', logic)
        self.assertIn('Sau', logic)
        self.assertIn('Ví dụ đã đo', logic)
        why = block(out, 'id="p-why"', 'id="p-evidence"')
        self.assertIn('Đã chọn', why)
        self.assertEqual(why.count('class="g-rej card"'), 2)
        self.assertIn('Đánh đổi', why)
        chk = block(out, 'id="p-evidence"', '<script type="application/json"')
        self.assertEqual(chk.count('class="g-ran card'), 4)
        self.assertEqual(chk.count('class="g-no card'), 1)

    def test_changed_nodes_glow_and_unchanged_do_not(self):
        out = self.page()
        nodes = re.findall(r'<article class="(node[^"]*)"', out)
        self.assertEqual(len(nodes), 7)
        lit = [n for n in nodes if ' lit' in n]
        self.assertEqual(len(lit), 5)  # app.svc, app, tests, docs, _other
        self.assertEqual(len([n for n in nodes if ' out' in n]), 1)
        self.assertIn('Không đổi', out)

    def test_verdict_pill_is_derived(self):
        out = self.page()
        self.assertIn('<span class="w">2/3</span> yêu cầu', out)
        self.assertIn('test đạt', out)
        self.assertIn('1 lưu ý', out)
        full = self.page(lambda d: d['requests'].pop())
        self.assertIn('<span class="g">2/2</span>', full)

    def test_failed_run_makes_the_pill_say_so(self):
        out = self.page(lambda d: d['evidence']['ran'][0].update(result='failed'))
        pill = block(out, 'class="verdict"', '</header>')
        self.assertIn('test hỏng', pill)
        self.assertNotIn('test đạt', pill)

    def test_names_come_from_the_architecture_and_the_note_counts_hidden_modules(self):
        out = self.page()
        self.assertIn('Dịch vụ', out)  # app.svc label from the architecture
        self.assertIn('+1 phần không liên quan', out)  # 6 architecture nodes, 5 listed
        self.assertNotIn('Không liên quan</', out)  # the hidden node itself is not drawn

    def test_no_architecture_no_hidden_note(self):
        out = page2.render(self.doc(lambda d: d['map']['modules'].__setitem__(slice(None), [
            {'id': 'a', 'name': 'Phần A', 'summary': 'Một.', 'changed': True, 'what_changed': 'Đổi A.', 'files': []}])), None)
        self.assertNotIn('phần không liên quan', out)
        self.assertIn('Phần A', out)

    # ---- what the page must not show
    def test_refs_commands_and_excerpts_never_reach_the_page(self):
        out = self.page()
        for secret in ('app/Svc.php:8', '$item->skip() || $n >= $limit', 'if ($n >= $limit)', PHPUNIT, 'composer lint', 'OK (1 test, 1 assertion)',
                       DECISION, PHPUNIT_OUT, 'return $n > 0 ? $n : -1', WORKER_CMD_TEXT):
            self.assertNotIn(esc(secret), out, secret)
        self.assertNotIn('<pre', out)
        self.assertNotIn('<code', out)
        self.assertNotIn('diff --git', out)
        self.assertNotRegex(out, r'\.php:\d+')

    def test_file_names_appear_only_as_map_labels(self):
        out = self.page().replace('<wbr>', '')
        panel = block(out, '<aside class="panel"', '<script type="application/json"')
        for name in ('Svc.php', 'SvcTest.php', 'ghi-chú.md', 'logo.png'):
            self.assertIn(name, out)
            self.assertNotIn(name, panel, name)

    def test_backticks_in_doc_text_do_not_become_code(self):
        out = self.page(lambda d: d['conclusions'].update(logic='Hàm `run` dừng sớm.'))
        self.assertIn('Hàm run dừng sớm.', out)
        self.assertNotIn('`', block(out, 'id="p-logic"', 'id="p-why"'))

    # ---- untrusted text
    def test_script_in_a_title_renders_as_text(self):
        out = self.page(lambda d: d.update(title=EVIL))
        self.assertNotIn(EVIL, out)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', out)
        self.assertEqual(out.count('</script>'), 3)  # the theme head script, the data block and the page's own script

    def test_every_doc_string_is_escaped(self):
        def m(d):
            d['subtitle'] = EVIL
            d['conclusions'].update({k: EVIL for k in d['conclusions']})
            d['requests'][0].update(quote=USER_1, result=EVIL, note=EVIL)
            d['map']['modules'][1].update(what_changed=EVIL)
            d['map']['modules'][0].update(name=EVIL, summary=EVIL)
            d['map']['edges'][0]['label'] = '</script>' + EVIL
            d['logic']['before'][0].update(label=EVIL, text=EVIL, visual={'kind': 'form', 'rows': [{'label': EVIL, 'value': EVIL, 'state': 'none'}]})
            d['logic']['after'][0].update(visual={'kind': 'dialog', 'tone': 'good', 'title': EVIL, 'subtitle': EVIL})
            d['rationale']['chosen']['text'] = EVIL
            d['rationale']['rejected'][0].update(option=EVIL, why_not=EVIL)
            d['evidence']['ran'][0].update(what=EVIL, detail=EVIL)
            d['evidence']['not_checked'][0].update(what=EVIL, why=EVIL)
        out = page2.render(self.doc(m), self.repo)  # rendering does not validate: hostile text must still be inert
        self.assertNotIn('<script>alert', out)
        self.assertNotIn('<img', out)
        self.assertEqual(out.count('</script>'), 3)
        self.assertEqual(self.data(out)['edges'][0]['label'], '</script>' + EVIL)  # JSON survives the round trip

    def test_attribute_values_cannot_break_out(self):
        evil = '"><img src=x onerror=1>'
        out = self.page(lambda d: d['map']['modules'][1].update(id=evil))
        self.assertNotIn('<img src=x', out)
        out2 = page2.render(self.doc(lambda d: d['map']['modules'][1].update(name=evil)), self.repo)
        self.assertNotIn('<img src=x', out2)

    # ---- grounding labels
    def test_inferred_items_say_suy_luan_and_grounded_ones_do_not(self):
        out = self.page()
        self.assertIn('Suy luận', block(out, 'id="p-logic"', 'id="p-why"'))  # inferred step in "before"
        rej = re.findall(r'<div class="g-rej card".*?</div>', out, re.S)
        self.assertIn('Suy luận', rej[0])  # inferred rejected option
        self.assertNotIn('Suy luận', rej[1])  # the one grounded in code
        grounded = self.page(lambda d: (d['logic']['before'].pop(1), d['rationale']['rejected'].pop(0), d['rationale'].pop('notes')))
        self.assertNotIn('Suy luận', grounded)

    def test_a_workers_report_is_labelled_as_a_report_not_a_tool_output(self):
        def m(d):
            d['evidence']['ran'][2]['source'] = {'kind': 'report', 'quote': DECISION}
            d['evidence']['ran'][1]['source'] = [d['evidence']['ran'][1]['source'], {'kind': 'report', 'quote': DECISION}]  # mixed: has a tool call
        out = self.page(m)
        chk = block(out, 'id="p-evidence"', '<script type="application/json"')
        self.assertEqual(chk.count('Lời báo cáo của worker'), 1)
        self.assertIn('1 mục chỉ dựa trên lời báo cáo của worker, không phải kết quả lệnh chạy.', chk)
        self.assertIn('Chỉ dựa trên lời báo cáo của worker', chk)
        none = self.page()
        self.assertNotIn('báo cáo của worker', none)

    def test_example_links_to_the_evidence_it_cites(self):
        out = self.page()
        self.assertIn('data-goto="evidence" data-target="ev0"', out)
        self.assertIn('id="ev0"', out)
        self.assertIn('class="g-ran card ev ok hl"', out)  # the cited run stands out

    def test_items_are_tied_to_map_nodes(self):
        out = self.page()
        toks = {m['id']: m['tok'] for m in page2.describe(self.doc(), collect2.load_arch(self.repo), page2.STR2['vi'])}
        self.assertRegex(out, r'<li class="card" data-nodes="%s" id="rq0">' % toks['app.svc'])
        self.assertIn('data-nodes=""', out)  # items with no module show only in the full view

    def test_english_page(self):
        out = self.page(lambda d: d.update(lang='en'))
        self.assertIn('<html lang="en"', out)
        self.assertIn('Requests', out)
        self.assertIn('Not checked', out)
        self.assertNotIn('Yêu cầu', out)

    # ---- map layout
    def test_edges_are_data_and_flow_edges_into_changed_modules_are_lit(self):
        e = self.data(self.page())['edges']
        self.assertEqual([(x['k'], x['label']) for x in e], [('lit', 'gọi'), ('', 'đọc/ghi')])
        e = self.data(self.page(lambda d: d['map']['edges'].append({'from': 'app.svc', 'to': 'db', 'kind': 'flow'})))['edges']
        self.assertEqual(e[2]['k'], '')  # changed -> unchanged is not a lit edge
        e = self.data(self.page(lambda d: d['map']['edges'].append({'from': 'tests', 'to': 'app.svc', 'kind': 'tests'})))['edges']
        self.assertEqual(e[2]['k'], 'test')

    def test_architecture_edge_label_is_used_when_the_doc_has_none(self):
        e = self.data(self.page(lambda d: d['map']['edges'][1].pop('label', None)))['edges']
        self.assertEqual(e[1]['label'], 'đọc/ghi')
        self.assertTrue(e[1]['mono'])

    def test_a_page_with_real_content_is_small_and_self_contained(self):
        out = self.page()
        self.assertLess(len(out.encode('utf-8')), 512 * 1024)
        self.assertIn('data:font/woff2;base64,', out)
        self.assertEqual(out.count('@font-face'), 3)
        self.assertNotRegex(out, r'(src|href)="https?://')

    def test_changed_modules_come_first_inside_a_zone(self):
        def m(d):
            ms = d['map']['modules']
            ms.insert(0, ms.pop(next(i for i, x in enumerate(ms) if x['id'] == 'db')))
        mods = page2.describe(self.doc(m), collect2.load_arch(self.repo), page2.STR2['vi'])
        cols = page2.layout(mods, [])
        for col in cols:
            for z in col:
                flags = [x['changed'] for x in z['mods']]
                self.assertEqual(flags, sorted(flags, reverse=True), z['label'])


WORKER_CMD_TEXT = 'pytest -q tests/test_worker.py'


def esc(s):
    return page2.esc(s)


def mod(i, zone, changed=True, kind=None, outside=False):
    return {'i': i, 'id': 'm%d' % i, 'tok': 'n%d' % i, 'name': 'M%d' % i, 'summary': '', 'what': '', 'changed': changed, 'outside': outside, 'files': [],
            'icon': 'x', 'k': kind, 'zone': '__out' if outside else zone, 'zlabel': zone, 'is_test': kind == 'test' and not outside,
            'state': 'out' if outside else 'changed' if changed else 'same'}


class Layout(unittest.TestCase):
    def place(self, mods, edges):
        cols = page2.layout(mods, edges)
        return {m['id']: c for c, col in enumerate(cols) for z in col for m in z['mods']}, cols

    def edge(self, a, b, kind='flow'):
        return {'from': a, 'to': b, 'kind': kind}

    def test_one_module_is_one_zone_in_one_column(self):
        where, cols = self.place([mod(0, 'Z')], [])
        self.assertEqual(where, {'m0': 0})
        self.assertEqual(len(cols), 1)

    def test_twelve_modules_in_five_groups_make_at_most_three_columns_and_lose_none(self):
        mods = [mod(i, 'G%d' % (i // 3 if i < 12 else 4), changed=i % 3 == 0) for i in range(12)]
        edges = [self.edge('m%d' % (3 * g), 'm%d' % (3 * g + 3)) for g in range(3)]
        where, cols = self.place(mods, edges)
        self.assertEqual(sorted(where), sorted(m['id'] for m in mods))
        self.assertLessEqual(len(cols), 3)
        self.assertEqual(sum(len(z['mods']) for c in cols for z in c), 12)

    def test_flow_order_decides_the_column(self):
        mods = [mod(0, 'A'), mod(1, 'B'), mod(2, 'C')]
        where, _ = self.place(mods, [self.edge('m0', 'm1'), self.edge('m1', 'm2')])
        self.assertEqual([where['m0'], where['m1'], where['m2']], [0, 1, 2])

    def test_a_cycle_between_groups_still_lays_out(self):
        mods = [mod(0, 'A'), mod(1, 'B')]
        where, cols = self.place(mods, [self.edge('m0', 'm1'), self.edge('m1', 'm0')])
        self.assertEqual(where, {'m0': 0, 'm1': 1})  # the edge that closes the loop is dropped
        self.assertLessEqual(len(cols), 3)

    def test_outside_actor_is_in_the_first_column_and_tests_sit_under_it(self):
        mods = [mod(0, 'Web'), mod(1, 'Out', changed=False, outside=True), mod(2, 'Tests', kind='test'), mod(3, 'Srv')]
        where, cols = self.place(mods, [self.edge('m1', 'm0'), self.edge('m0', 'm3'), self.edge('m2', 'm0', 'tests')])
        self.assertEqual((where['m1'], where['m2']), (0, 0))
        self.assertEqual([z['key'] for z in cols[0]], ['__out', 'Tests'])
        self.assertGreater(where['m0'], 0)
        self.assertGreater(where['m3'], where['m0'])

    def test_tests_without_an_outside_actor_share_the_column_of_what_they_test(self):
        mods = [mod(0, 'Web'), mod(1, 'Srv'), mod(2, 'Tests', kind='test')]
        where, _ = self.place(mods, [self.edge('m0', 'm1'), self.edge('m2', 'm1', 'tests')])
        self.assertEqual(where['m2'], where['m1'])

    def test_unconnected_groups_spread_over_columns(self):
        mods = [mod(i, 'G%d' % i) for i in range(3)]
        where, _ = self.place(mods, [])
        self.assertEqual(sorted(where.values()), [0, 1, 2])

    def test_changed_first_inside_a_zone(self):
        mods = [mod(0, 'Z', changed=False), mod(1, 'Z', changed=True)]
        _, cols = self.place(mods, [])
        self.assertEqual([m['id'] for m in cols[0][0]['mods']], ['m1', 'm0'])


if __name__ == '__main__':
    unittest.main()


class ReviewFixes(V2Case):
    """D2 (each fact once, linked), D3 (one name), and the design follow-ups."""

    def page(self, mutate=None):
        return page2.render(self.doc(mutate), self.repo)

    def test_a_request_links_to_the_tab_that_holds_its_detail(self):
        out = self.page(lambda d: d['requests'][0].update(see='logic'))
        req = block(out, 'id="p-req"', 'id="p-logic"')
        self.assertEqual(req.count('class="more"'), 1)
        self.assertIn('data-goto="logic">Chi tiết ở tab Logic</button>', req)
        out = self.page(lambda d: d['requests'][1].update(see='evidence'))
        self.assertIn('data-goto="evidence">Chi tiết ở tab Bằng chứng</button>', block(out, 'id="p-req"', 'id="p-logic"'))
        self.assertNotIn('class="more"', block(self.page(), 'id="p-req"', 'id="p-logic"'))

    def test_an_unknown_see_value_draws_no_link(self):
        self.assertNotIn('class="more"', self.page(lambda d: d['requests'][0].update(see='map')))

    def test_the_node_card_has_the_module_name_as_heading_and_never_repeats_what_changed(self):
        out = self.page()
        self.assertIn('<h3 id="nc-name">', out)
        self.assertNotIn('nc-what', out)
        self.assertNotIn('data-what=', out)

    def test_a_filter_line_in_the_sticky_header_names_the_node_and_clears_it(self):
        out = self.page()
        head = block(out, 'class="p-head"', 'class="p-body"')
        self.assertIn('id="filterbar" hidden', head)
        self.assertIn('id="fb-name"', head)
        self.assertIn('id="fb-clear"', head)
        self.assertIn('Xem tất cả', head)

    def test_the_tab_is_called_bang_chung_and_kiem_tra_is_gone(self):
        out = self.page()
        self.assertRegex(out, r'data-tab="evidence">Bằng chứng</button>')
        self.assertNotIn('Kiểm tra', out)
        self.assertIn('Kiểm thử', out)  # the test module keeps its name
        self.assertIn('data-goto="evidence"', out)
        en = page2.render(self.doc(lambda d: d.update(lang='en')), self.repo)
        self.assertIn('data-tab="evidence">Evidence</button>', en)

    def test_file_names_break_only_after_a_separator(self):
        b = page2.Builder(self.doc(), None, True)
        li = b.file_li({'path': 'src/features/auth/ChangePasswordPage.jsx', 'add': 2, 'del': 0}, {})
        self.assertIn('ChangePasswordPage.<wbr>jsx', li)
        self.assertNotIn('Change<wbr>', li)
        self.assertIn('users-<wbr>password-<wbr>autofill.<wbr>test.<wbr>jsx', b.file_li({'path': 'tests/users-password-autofill.test.jsx', 'add': 1, 'del': 0}, {}))
        css = page2.css()
        self.assertRegex(css, r'\.files li\{display:flex;flex-wrap:wrap')

    def test_the_page_gives_the_router_the_zones(self):
        js = page2.page_js() if hasattr(page2, 'page_js') else open(os.path.join(page2.UI, 'page2.js'), encoding='utf-8').read()
        self.assertIn("qa('.zone',stage)", js)
        self.assertIn('stage.clientWidth,stage.clientHeight,zones)', js)
        self.assertIn('zones,edges:jobs', js)  # recorded with the boxes, so the recorded layouts can be audited for zone borders

    def test_prose_in_a_node_breaks_only_after_a_separator(self):
        out = self.page(lambda d: d['map']['modules'][1].update(what_changed='Ô email có autocomplete=username và users-password-autofill.test.jsx, a/b'))
        what = ' '.join(re.findall(r'<p class="n-what">(.*?)</p>', out))
        self.assertIn('autocomplete=<wbr>username', what)
        self.assertIn('users-<wbr>password-<wbr>autofill.<wbr>test.<wbr>jsx', what)
        self.assertIn('a/<wbr>b', what)
        self.assertNotIn('autocomp<wbr>', what)
        self.assertNotIn('-<wbr> ', what)  # a separator before a space is not a place to break
        self.assertIn('autocomplete=username', page2.page_text(out))  # the words are the same with the break hints removed
        self.assertRegex(page2.css(), r'\.n-what\{[^}]*overflow-wrap:break-word')
        self.assertNotRegex(page2.css(), r'\.n-what\{[^}]*anywhere')

    def test_nodes_are_as_tall_as_their_content(self):
        self.assertRegex(page2.css(), r'\.zone-grid\{[^}]*align-items:start')

    def test_unrelated_nodes_stay_readable_when_one_is_selected(self):
        css = page2.css()
        op = float(re.search(r'\.stage\.filtering \.node:not\(\.sel\):not\(\.rel\)\{opacity:([.\d]+)\}', css).group(1))

        def lin(c):
            c /= 255
            return c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4

        def lum(rgb):
            r, g, b = (lin(x) for x in rgb)
            return .2126 * r + .7152 * g + .0722 * b

        def mix(fg, bg):
            return tuple(op * f + (1 - op) * b for f, b in zip(fg, bg))
        node_bg, text, ground = (0x18, 0x1f, 0x51), (0xa3, 0xab, 0xe0), (0x14, 0x19, 0x45)  # --surface-solid, --text-3, page ground
        a, b = lum(mix(text, ground)), lum(mix(node_bg, ground))
        self.assertGreaterEqual((max(a, b) + .05) / (min(a, b) + .05), 3.0)
        self.assertGreaterEqual(op, .7)

    def test_a_dimmed_edge_stays_visible(self):
        self.assertRegex(page2.css(), r'\.e\.dim\{opacity:\.[4-9]')

    def test_the_router_is_inlined_and_the_old_straight_edges_are_gone(self):
        out = self.page()
        self.assertIn('const EdgeRouter', out)
        self.assertIn('EdgeRouter.route(', out)
        self.assertNotIn('labelPoint', out)


class DocsStateTheRule(V2Case):
    def read(self, rel):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel), encoding='utf-8') as fh:
            return fh.read()

    def test_schema_and_skill_state_each_fact_once_and_the_see_field(self):
        schema, skill = self.read('references/explain-schema.md'), self.read('SKILL.md')
        for text in (schema, skill):
            self.assertRegex(text, r'(?i)each fact (appears )?in full in one|each fact once|một lần')
        self.assertIn('"see?"', schema)
        self.assertIn('`see`', skill)
        self.assertIn('Bằng chứng', skill)
        self.assertNotIn('Kiểm tra', skill)


class PluralCounts(unittest.TestCase):
    """en pages say "1 file" and "1 caveat"; vi has no plural form and keeps one string."""

    def test_en_singular_and_plural(self):
        from lib.i18n2 import STR2, count
        t = STR2['en']
        self.assertEqual(count(t, 'files_n', 1), '1 file')
        self.assertEqual(count(t, 'files_n', 2), '2 files')
        self.assertEqual(count(t, 'caveats', 1), '1 caveat')
        self.assertEqual(count(t, 'caveats', 3), '3 caveats')
        self.assertEqual(count(t, 'files_more', 1), '+1 more file')
        self.assertEqual(count(t, 'hidden_note', 1), '+1 unrelated part of the system, not drawn here')
        self.assertTrue(count(t, 'reported_summary', 1).startswith('1 item rests'))

    def test_vi_is_unchanged(self):
        from lib.i18n2 import STR2, count
        t = STR2['vi']
        self.assertEqual(count(t, 'files_n', 1), '1 file')
        self.assertEqual(count(t, 'caveats', 1), '1 lưu ý')
        self.assertEqual(count(t, 'caveats', 2), '2 lưu ý')

    def test_rendered_en_page_never_says_1_files_or_1_caveats(self):
        here = os.path.dirname(os.path.abspath(__file__))
        sample = os.path.join(here, '..', 'reference', 'examples', 'password-autofill.v2.json')
        with open(sample, encoding='utf-8') as fh:
            doc = json.load(fh)
        doc['lang'] = 'en'
        out = page2.render(doc, None, validated=False, session_checked=False)
        self.assertNotRegex(out, r'\b1 (files|caveats|requests)\b')
