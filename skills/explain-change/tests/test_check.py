import unittest

from helpers import RepoCase


class SnippetGrounding(RepoCase):
    def test_baseline_is_valid(self):
        stats = self.assertValid()
        self.assertEqual(stats['files'], (5, 5))

    def test_snippet_not_found_fails(self):
        self.assertInvalid(lambda d: d['why']['refs'][0].update(snippet='this text is nowhere'), 'snippet not found')

    def test_snippet_three_lines_off_is_accepted(self):
        self.assertValid(lambda d: d['why']['refs'][0].update(line=11))  # real line 8

    def test_snippet_more_than_three_lines_off_fails(self):
        self.assertInvalid(lambda d: d['why']['refs'][0].update(line=12), 'snippet not found')

    def test_snippet_matches_ignoring_indentation(self):
        self.assertValid(lambda d: d['why']['refs'][0].update(snippet='  if ($item->skip()   || $n >= $limit)  '))

    def test_line_outside_file_fails(self):
        self.assertInvalid(lambda d: d['why']['refs'][0].update(line=999), 'outside file')

    def test_unknown_file_fails(self):
        self.assertInvalid(lambda d: d['why']['refs'][0].update(file='nope.php'), 'file not found')

    def test_head_version_is_checked_not_base(self):
        # `$item->skip() ||` exists only in the head version
        self.assertValid(lambda d: d['why']['refs'][0].update(snippet='$item->skip() ||'))
        self.assertInvalid(lambda d: d['why']['refs'][0].update(snippet='public function gone()', line=16), 'snippet not found')

    def test_deleted_file_is_cited_from_the_base_version(self):
        self.assertValid()  # c3 cites app/Old.php:3, which exists only at base
        self.assertInvalid(lambda d: d['changes']['items'][2]['refs'][0].update(snippet='not in the old file'), 'snippet not found')

    def test_inferred_needs_no_snippet(self):
        self.assertValid(lambda d: d['why']['refs'].append({'file': 'app/Svc.php', 'line': 8, 'inferred': True}))

    def test_missing_snippet_without_inferred_fails(self):
        self.assertInvalid(lambda d: d['why']['refs'].append({'file': 'app/Svc.php', 'line': 8}), 'snippet')

    def test_binary_file_cannot_be_cited_as_text(self):
        self.assertInvalid(lambda d: d['why']['refs'][0].update(file='logo.png', snippet='PNG', line=1), 'binary')

    def test_every_diagram_step_needs_a_ref(self):
        self.assertInvalid(lambda d: d['flows']['items'][0]['steps'][0].pop('ref'), 'every step needs a ref')


class Coverage(RepoCase):
    def test_changed_file_missing_from_sub_changes_fails(self):
        self.assertInvalid(lambda d: d['changes']['items'][1]['files'].remove('tài-liệu/ghi-chú.md'),
                           'not covered by any sub-change: tài-liệu/ghi-chú.md')

    def test_file_in_two_sub_changes_fails(self):
        self.assertInvalid(lambda d: d['changes']['items'][0]['files'].append('logo.png'), 'also in sub-change')

    def test_unchanged_file_listed_fails(self):
        self.assertInvalid(lambda d: d['changes']['items'][0]['files'].append('README.md'), 'not a changed file')

    def test_binary_and_deleted_files_must_be_covered_too(self):
        self.assertInvalid(lambda d: d['changes']['items'][2]['files'].remove('logo.png'), 'logo.png')
        self.assertInvalid(lambda d: d['changes']['items'][2]['files'].remove('app/Old.php'), 'app/Old.php')


class Structure(RepoCase):
    def test_flowchart_needs_three_branches(self):
        def m(d):
            it = d['logic']['items'][0]
            r = it['refs'][0]
            it.pop('trace')
            it['kind'] = 'flowchart'
            it['flow'] = {'nodes': [{'id': 's', 'label': 'start', 'type': 'start'}, {'id': 'q', 'label': 'skip?', 'type': 'decision'},
                                    {'id': 'e', 'label': 'end', 'type': 'end'}],
                          'edges': [{'from': 's', 'to': 'q', 'ref': r}, {'from': 'q', 'to': 'e', 'label': 'yes', 'ref': r},
                                    {'from': 'q', 'to': 'e', 'label': 'no', 'ref': r}]}
        self.assertInvalid(m, 'flowchart only for 3 or more branches')

        def m3(d):
            m(d)
            f = d['logic']['items'][0]['flow']
            f['nodes'].append({'id': 'z', 'label': 'other', 'type': 'end'})
            f['edges'].append({'from': 'q', 'to': 'z', 'label': 'other', 'ref': d['logic']['items'][0]['refs'][0]})
        self.assertValid(m3)

        def loop(d):
            m3(d)
            d['logic']['items'][0]['flow']['edges'].append({'from': 'e', 'to': 'q', 'ref': d['logic']['items'][0]['refs'][0]})
        self.assertInvalid(loop, 'loop back')

    def test_trace_from_a_test_must_cite_it(self):
        self.assertInvalid(lambda d: d['logic']['items'][0]['trace']['origin'].pop('cite'), 'origin.cite')
        self.assertInvalid(lambda d: d['logic']['items'][0]['trace']['origin']['cite'].update(snippet='made up'), 'snippet not found')
        self.assertInvalid(lambda d: d['logic']['items'][0]['trace']['origin']['cite'].update(inferred=True), 'verified ref')

    def test_illustrative_trace_is_allowed(self):
        self.assertValid(lambda d: d['logic']['items'][0]['trace'].update(origin={'kind': 'illustrative'}))

    def test_run_trace_needs_command_and_output(self):
        self.assertInvalid(lambda d: d['logic']['items'][0]['trace'].update(origin={'kind': 'run', 'command': 'x'}), 'command and output')

    def test_function_with_branches_must_be_explained_or_skipped(self):
        self.assertInvalid(lambda d: d['logic'].update(items=[]) or d['logic'].update(none_reason='n/a'), 'changed function with')
        self.assertValid(lambda d: d['logic'].update(items=[], none_reason='n/a',
                                                      skipped=[{'file': 'app/Svc.php', 'function': 'run', 'reason': 'tầm thường'}]))

    def test_logic_item_links_to_an_existing_sub_change(self):
        self.assertValid(lambda d: d['logic']['items'][0].update(change='c1'))
        self.assertInvalid(lambda d: d['logic']['items'][0].update(change='zzz'), 'unknown sub-change')

    def test_quiz_has_two_or_three_questions(self):
        self.assertInvalid(lambda d: d['quiz']['items'].pop(), 'quiz.items')
        self.assertInvalid(lambda d: d['quiz']['items'].extend(d['quiz']['items'][:2]), 'quiz.items')

    def test_quiz_answer_needs_a_citation(self):
        self.assertInvalid(lambda d: d['quiz']['items'][0].update(refs=[]), 'quiz.items[0].refs')

    def test_section_needs_a_conclusion(self):
        self.assertInvalid(lambda d: d['risks'].update(conclusion=' '), 'risks.conclusion')

    def test_flow_needs_a_changed_step(self):
        def m(d):
            for s in d['flows']['items'][0]['steps']:
                s['changed'] = False
        self.assertInvalid(m, 'no step has changed')

    def test_why_has_two_to_five_lines(self):
        self.assertInvalid(lambda d: d['why'].update(lines=['one']), 'why.lines')


if __name__ == '__main__':
    unittest.main()
