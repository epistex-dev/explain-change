import copy
import json
import os
import shutil
import tempfile
import time
import unicodedata
import unittest

from helpers2 import (DECISION, LINT, PHPUNIT, PHPUNIT_OUT, URL, USER_1, USER_2, V2Case, WORKER_CMD, main_records, rec, run, tool_result, tool_use, write_jsonl)
from lib import check


class Requests(V2Case):
    def test_baseline_is_valid_and_counts(self):
        stats = self.assertValid()
        self.assertEqual(stats['verdict'], {'requests': {'done': 2, 'total': 3}, 'tests_passed': True, 'caveats': 1})
        self.assertEqual(stats['files'], (5, 5))
        self.assertEqual(stats['unverified'], 0)

    def test_quote_not_in_transcript_fails(self):
        self.assertInvalid(lambda d: d['requests'][0].update(quote='một câu người dùng chưa từng nói'), 'requests[0].quote: quote not found')

    def test_quote_from_assistant_message_fails(self):
        self.assertInvalid(lambda d: d['requests'][0].update(quote=DECISION), 'requests[0].quote: quote not found')

    def test_quote_only_in_thinking_or_injected_context_fails(self):
        self.assertInvalid(lambda d: d['requests'][0].update(quote='private thought only in thinking'), 'quote not found')
        self.assertInvalid(lambda d: d['requests'][0].update(quote='secret quote inside context'), 'quote not found')

    def test_quote_from_tool_result_is_not_a_user_message(self):
        self.assertInvalid(lambda d: d['requests'][0].update(quote='OK (1 test, 1 assertion)'), 'quote not found')

    def test_system_injected_user_role_messages_are_not_the_user(self):
        self.assertInvalid(lambda d: d['requests'][0].update(quote='fake request: nội dung do hệ thống chèn'), 'quote not found')
        self.assertInvalid(lambda d: d['requests'][0].update(quote='notify fake request'), 'quote not found')
        self.assertInvalid(lambda d: d['requests'][0].update(quote='meta only text'), 'quote not found')
        self.assertInvalid(lambda d: d['requests'][0].update(quote='command fake request'), 'quote not found')
        self.assertInvalid(lambda d: d['requests'][0].update(quote='local commands fake request'), 'quote not found')

    def test_worker_brief_is_not_the_user(self):
        self.assertInvalid(lambda d: d['requests'][0].update(quote='worker user text only here'), 'quote not found')

    def test_quote_is_whitespace_normalised_and_unicode_normalised(self):
        self.assertValid(lambda d: d['requests'][0].update(quote='  giới   hạn\ntheo\tmodule  '))
        nfd = unicodedata.normalize('NFD', USER_1)
        self.assertNotEqual(nfd, USER_1)
        self.assertValid(lambda d: d['requests'][0].update(quote=nfd))

    def test_quote_may_be_a_piece_of_a_message(self):
        self.assertValid(lambda d: d['requests'][0].update(quote='theo module'))

    def test_too_short_quote_fails(self):
        self.assertInvalid(lambda d: d['requests'][0].update(quote='đi'), 'too short')

    def test_status_must_be_known_and_fixes_need_a_note(self):
        self.assertInvalid(lambda d: d['requests'][0].update(status='finished'), 'requests[0].status')
        self.assertInvalid(lambda d: d['requests'][1].pop('note'), 'requests[1].note')

    def test_requests_list_is_required(self):
        self.assertInvalid(lambda d: d.update(requests=[]), 'requests: required list')

    def test_transcript_is_required_unless_declared_unavailable(self):
        self.assertInvalid(None, 'transcript: required', transcript=None)
        errs, stats = self.validate(lambda d: d.update(transcript_unavailable='chạy bằng API, không có log'), transcript=None)
        self.assertEqual(errs, [])
        self.assertTrue(any('NOT checked' in w for w in stats['warnings']))
        self.assertEqual(stats['unverified'], 9)

    def test_doc_transcript_field_is_used_when_no_flag(self):
        self.assertValid(lambda d: d.update(transcript=self.transcript), transcript=None)

    def test_transcript_outside_projects_is_refused(self):
        outside = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False)
        outside.write(json.dumps(rec('user', USER_1)).encode() + b'\n')
        outside.close()
        self.addCleanup(os.remove, outside.name)
        self.assertInvalid(None, 'must be under', transcript=outside.name)

    def test_symlink_out_of_projects_is_refused(self):
        link = os.path.join(self.root, 'link.jsonl')
        os.symlink(self.transcript, link)  # a link that stays inside is fine
        self.assertValid(transcript=link)
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside)
        shutil.copy(self.transcript, os.path.join(outside, 't.jsonl'))
        os.symlink(os.path.join(outside, 't.jsonl'), os.path.join(self.root, 'esc.jsonl'))
        self.assertInvalid(None, 'must be under', transcript=os.path.join(self.root, 'esc.jsonl'))

    def test_verdict_is_derived_and_a_wrong_typed_one_fails(self):
        self.assertValid(lambda d: d.update(verdict={'requests': {'done': 2, 'total': 3}, 'tests_passed': True}))
        self.assertInvalid(lambda d: d.update(verdict={'requests': {'done': 3, 'total': 3}, 'tests_passed': True}), 'verdict: is derived')
        self.assertInvalid(lambda d: d.update(verdict={'requests': {'done': 2, 'total': 3}, 'tests_passed': False}), 'verdict: is derived')

    def test_changed_request_leaves_the_total(self):
        def mut(d):
            d['requests'][2].update(status='changed', note='Người dùng đổi ý.')
        stats = self.assertValid(mut)
        self.assertEqual(stats['verdict']['requests'], {'done': 2, 'total': 2})

    def test_a_failed_run_makes_tests_not_passed(self):
        stats = self.assertValid(lambda d: d['evidence']['ran'][0].update(result='failed'))
        self.assertFalse(stats['verdict']['tests_passed'])


def drop_module_refs(node):
    if isinstance(node, dict):
        node.pop('modules', None) if 'quote' in node or 'what' in node or 'label' in node or 'option' in node or 'text' in node else None
        for v in node.values():
            drop_module_refs(v)
    elif isinstance(node, list):
        for v in node:
            drop_module_refs(v)


class MapRules(V2Case):
    def test_changed_file_unassigned_fails(self):
        self.assertInvalid(lambda d: d['map']['modules'][5].update(changed=False, files=[], what_changed=''), 'changed file not assigned to any changed module: logo.png')

    def test_changed_file_removed_from_its_module_fails(self):
        def mut(d):
            d['map']['modules'][4]['files'] = [self.counts('tài-liệu/ghi-chú.md')]
            d['map']['modules'][2]['files'] = [self.counts('app/Old.php')]
            d['map']['modules'][1]['files'] = []
        self.assertInvalid(mut, 'a changed module lists its changed files')

    def test_file_assigned_twice_fails(self):
        self.assertInvalid(lambda d: d['map']['modules'][2]['files'].append(self.counts('app/Svc.php')), 'also in module')

    def test_module_id_not_in_architecture_fails(self):
        self.assertInvalid(lambda d: d['map']['modules'][6].update(id='nope'), "not a node of")

    def test_file_in_the_wrong_module_fails(self):
        def mut(d):
            d['map']['modules'][1]['files'] = [self.counts('tests/SvcTest.php')]
            d['map']['modules'][3]['files'] = [self.counts('app/Svc.php')]
        self.assertInvalid(mut, "belongs to module 'tests'")

    def test_plus_minus_counts_must_match_git(self):
        def mut(d):
            d['map']['modules'][1]['files'][0]['add'] += 1
        self.assertInvalid(mut, '+/- counts differ from git')

    def test_name_and_summary_come_from_the_architecture(self):
        self.assertValid(lambda d: d['map']['modules'][1].update(name='Dịch vụ', summary='Đếm theo giới hạn.'))
        self.assertInvalid(lambda d: d['map']['modules'][1].update(name='Tên bịa'), 'differs from the architecture')

    def test_unchanged_module_lists_no_files(self):
        self.assertInvalid(lambda d: d['map']['modules'][6].update(files=[self.counts('logo.png')]), 'unchanged module lists no files')

    def test_outside_actor_cannot_shadow_an_architecture_module(self):
        self.assertInvalid(lambda d: d['map']['modules'][0].update(id='db'), 'list it as a module')

    def test_outside_actor_cannot_be_changed(self):
        self.assertInvalid(lambda d: d['map']['modules'][0].update(changed=True), 'outside actor cannot be changed')

    def test_arch_edge_must_exist_in_the_architecture(self):
        self.assertInvalid(lambda d: d['map']['edges'].append({'from': 'tests', 'to': 'db', 'kind': 'arch'}), 'needs an edge tests -> db')
        self.assertInvalid(lambda d: d['map']['edges'].append({'from': 'tests', 'to': 'nowhere', 'kind': 'flow'}), 'from/to must be ids')

    def test_module_reference_must_exist(self):
        self.assertInvalid(lambda d: d['requests'][0].update(modules=['ghost']), "unknown module id 'ghost'")
        self.assertInvalid(lambda d: d['evidence']['not_checked'][0].update(modules=['ghost']), "unknown module id 'ghost'")

    def test_duplicate_module_id_fails(self):
        self.assertInvalid(lambda d: d['map']['modules'][6].update(id='tests'), 'duplicate module id')

    def test_ignored_file_goes_to_other(self):
        self.write('deps.lock', 'x\n')
        run(self.repo, 'git', 'add', 'deps.lock')
        run(self.repo, 'git', 'commit', '-q', '-m', 'lock')
        head = self.rev('HEAD')

        def mut(d):
            d['range']['head'] = head
            d['range']['base'] = self.base
            d['map']['modules'][5]['files'].append(self.counts_at('deps.lock', head))
        self.assertValid(mut)

    def counts_at(self, path, head):
        from lib import gitio
        f = {x['path']: x for x in gitio.changed_files(self.repo, self.base, head)}[path]
        return {'path': path, 'add': f['add'], 'del': f['del']}

    def test_empty_range_fails_validation(self):
        self.assertInvalid(lambda d: d['range'].update(base=self.head), 'no changes')

    def test_fallback_without_architecture_groups_by_directory(self):
        os.remove(os.path.join(self.repo, 'floorplan', 'architecture.json'))

        def mut(d):
            drop_module_refs(d)
            d['map']['modules'] = [
                {'id': 'app', 'name': 'App', 'summary': 'Code.', 'changed': True, 'what_changed': 'Đổi.', 'files': [self.counts('app/Svc.php'), self.counts('app/Old.php')]},
                {'id': 'tests', 'name': 'Tests', 'summary': 'Test.', 'changed': True, 'what_changed': 'Thêm.', 'files': [self.counts('tests/SvcTest.php')]},
                {'id': 'tài-liệu', 'name': 'Tài liệu', 'summary': 'Ghi chú.', 'changed': True, 'what_changed': 'Mới.', 'files': [self.counts('tài-liệu/ghi-chú.md')]},
                {'id': '.', 'name': 'Gốc', 'summary': 'File gốc.', 'changed': True, 'what_changed': 'Logo.', 'files': [self.counts('logo.png')]}]
            d['map']['edges'] = []
        stats = self.assertValid(mut)
        self.assertEqual(stats['map_source'], 'dirs')
        self.assertInvalid(lambda d: (mut(d), d['map']['modules'][0].update(id='nodir')), 'is not a module of the directory map')
        self.assertInvalid(lambda d: (mut(d), d['map']['modules'][0]['files'].remove(self.counts('app/Svc.php')), d['map']['modules'][0]['files'].append(self.counts('tests/SvcTest.php')), d['map']['modules'][1]['files'].remove(self.counts('tests/SvcTest.php')), d['map']['modules'][1]['files'].append(self.counts('app/Svc.php'))), 'belongs to module')
        self.assertInvalid(lambda d: (mut(d), d['map']['modules'][0].pop('name')), 'map.modules[0].name')

    def test_architecture_is_found_in_a_parent_folder(self):
        parent = tempfile.mkdtemp(prefix='explain-parent-')
        self.addCleanup(shutil.rmtree, parent)
        sub = os.path.join(parent, 'sub')
        run(parent, 'git', 'clone', '-q', '--no-hardlinks', self.repo, sub)
        os.remove(os.path.join(sub, 'floorplan', 'architecture.json')) if os.path.exists(os.path.join(sub, 'floorplan')) else None
        shutil.rmtree(os.path.join(sub, 'floorplan'), ignore_errors=True)
        arch = json.loads(json.dumps(__import__('helpers2').ARCH, ensure_ascii=False).replace('"app/', '"sub/app/').replace('"tests/', '"sub/tests/').replace('"tài-liệu"', '"sub/tài-liệu"'))
        self.write_arch(arch, where=parent)
        from lib import arch as archmod, check as chk
        self.assertEqual(archmod.find_architecture(sub), os.path.join(os.path.realpath(parent), 'floorplan', 'architecture.json'))
        errs, stats = chk.validate(self.doc(), os.path.realpath(sub), self.transcript)
        self.assertEqual(errs, [], errs)
        self.assertEqual(stats['map_source'], 'floorplan')

    def test_overlapping_globs_first_declared_wins_and_is_reported(self):
        arch = copy.deepcopy(__import__('helpers2').ARCH)
        arch['nodes'].append({'id': 'dup', 'label': 'Trùng', 'kind': 'library', 'summary': 'Trùng tests.', 'paths': ['tests/**']})
        self.write_arch(arch)
        stats = self.assertValid()  # tests (declared first) still owns tests/SvcTest.php
        self.assertTrue(any('overlap' in w and 'tests/SvcTest.php -> tests' in w for w in stats['warnings']), stats['warnings'])
        arch['nodes'] = [n for n in arch['nodes'] if n['id'] != 'tests'] + [arch['nodes'][2]]  # declare tests after dup
        self.write_arch(arch)
        self.assertInvalid(None, "belongs to module 'dup'")


class LogicRationaleEvidence(V2Case):
    def test_step_needs_exactly_one_grounding(self):
        self.assertInvalid(lambda d: d['logic']['after'][0].pop('refs'), 'needs exactly one of refs, source')
        self.assertInvalid(lambda d: d['logic']['after'][0].update(inferred=True), 'needs exactly one of refs, source')

    def test_before_step_ref_is_checked_against_base(self):
        # the head-only text `$item->skip() ||` cannot ground a "before" step
        self.assertInvalid(lambda d: d['logic']['before'][0].update(refs=[self.ref('app/Svc.php', 8, '$item->skip() ||')]), 'snippet not found')
        self.assertValid(lambda d: d['logic']['after'][0].update(refs=[self.ref('app/Svc.php', 8, '$item->skip() ||')]))

    def test_after_step_ref_snippet_must_exist(self):
        self.assertInvalid(lambda d: d['logic']['after'][0]['refs'][0].update(snippet='nowhere in the code'), 'snippet not found')

    def test_inferred_is_allowed_and_flagged(self):
        stats = self.assertValid()
        self.assertEqual(stats['inferred'], ['logic.before[1]', 'rationale.rejected[0]', 'rationale.notes[0]'])
        self.assertEqual(stats['refs']['inferred'], 3)

    def test_inferred_not_allowed_in_evidence(self):
        self.assertInvalid(lambda d: d['evidence']['ran'][0].update(source={'inferred': True}), 'one of')

    def test_step_label_stays_short(self):
        self.assertInvalid(lambda d: d['logic']['after'][0].update(label='x' * 61), 'longer than')

    def test_visual_shape(self):
        self.assertValid(lambda d: d['logic']['after'][0].update(visual={'kind': 'form', 'rows': [{'label': 'a', 'value': 'b'}]}))
        self.assertInvalid(lambda d: d['logic']['after'][0].update(visual='picture'), '.visual')

    def test_example_cites_an_evidence_item(self):
        self.assertInvalid(lambda d: d['logic']['examples'][0].update(evidence_id='e9'), "no evidence.ran item with id 'e9'")
        self.assertInvalid(lambda d: d['logic']['examples'][0].pop('evidence_id'), 'needs exactly one')

    def test_rationale_quote_may_come_from_any_role_but_must_exist(self):
        self.assertValid(lambda d: d['rationale']['chosen'].update(source={'kind': 'transcript', 'quote': 'add a hidden username field'}))  # tool result
        self.assertInvalid(lambda d: d['rationale']['chosen']['source'].update(quote='một lý do bịa ra hoàn toàn'), 'rationale.chosen.source.quote: quote not found')
        self.assertInvalid(lambda d: d['rationale']['chosen']['source'].update(quote='private thought only in thinking'), 'quote not found')

    def test_rationale_url_must_be_seen_in_the_transcript(self):
        self.assertValid(lambda d: d['rationale']['chosen'].update(source={'kind': 'url', 'url': URL}))
        self.assertInvalid(lambda d: d['rationale']['chosen'].update(source={'kind': 'url', 'url': 'https://example.com/invented'}), 'URL not found')
        self.assertInvalid(lambda d: d['rationale']['chosen'].update(source={'kind': 'url', 'url': 'ftp://x'}), 'http(s) URL')

    def test_rationale_cannot_use_a_tool_call(self):
        self.assertInvalid(lambda d: d['rationale']['chosen'].update(source={'kind': 'tool_call', 'command': PHPUNIT, 'excerpt': 'OK (1 test'}), 'one of')

    def test_rationale_code_ref_is_verified(self):
        self.assertInvalid(lambda d: d['rationale']['rejected'][1]['source']['ref'].update(snippet='absent text'), 'snippet not found')

    def test_evidence_command_not_in_transcript_fails(self):
        self.assertInvalid(lambda d: d['evidence']['ran'][0]['source'].update(command='vendor/bin/phpunit tests/Other.php'), 'command not found in any tool call')

    def test_evidence_excerpt_from_a_different_tool_call_fails(self):
        # '0 errors found' is the lint result; it is not in the phpunit call's result
        self.assertInvalid(lambda d: d['evidence']['ran'][0]['source'].update(excerpt='0 errors found'), 'not in the result of the call that ran this command')

    def test_evidence_excerpt_not_anywhere_fails(self):
        self.assertInvalid(lambda d: d['evidence']['ran'][0]['source'].update(excerpt='OK (9 tests, 9 assertions)'), 'not in the result')

    def test_evidence_in_worker_transcript(self):
        self.assertValid()  # ran[2] cites agent-abc123
        self.assertInvalid(lambda d: d['evidence']['ran'][2]['source'].pop('transcript'), 'command not found in any tool call of transcript main')
        self.assertInvalid(lambda d: d['evidence']['ran'][2]['source'].update(transcript='agent-zzz'), 'unknown transcript')
        self.assertInvalid(lambda d: d['evidence']['ran'][2]['source'].update(transcript='../../etc/passwd'), '.transcript')

    def test_user_reported_quote_must_be_the_users(self):
        self.assertInvalid(lambda d: d['evidence']['ran'][3]['source'].update(quote=DECISION), 'quote not found')

    def test_report_kind_quotes_a_worker_report_and_is_counted(self):
        def mut(d):
            d['evidence']['ran'].append({'what': 'Trình duyệt', 'result': 'passed', 'detail': 'Báo cáo của worker.',
                                         'source': {'kind': 'report', 'quote': 'fake request: nội dung do hệ thống chèn'}})
        stats = self.assertValid(mut)
        self.assertEqual(stats['reported'], 1)
        self.assertInvalid(lambda d: mut(d) or d['evidence']['ran'][-1]['source'].update(quote='một báo cáo chưa từng có'), 'quote not found')
        # a report is not the user: it cannot ground a request
        self.assertInvalid(lambda d: d['requests'][0].update(quote='fake request: nội dung do hệ thống chèn'), 'quote not found')

    def test_request_source_is_optional_and_checked(self):
        self.assertValid(lambda d: d['requests'][0].update(source={'kind': 'transcript', 'quote': DECISION}))
        self.assertInvalid(lambda d: d['requests'][0].update(source={'kind': 'transcript', 'quote': 'chưa từng nói ở đâu'}), 'requests[0].source.quote: quote not found')
        self.assertInvalid(lambda d: d['requests'][0].update(source={'inferred': True}), 'requests[0].source')

    def test_evidence_needs_a_source(self):
        self.assertInvalid(lambda d: d['evidence']['ran'][0].pop('source'), 'evidence.ran[0].source: required')

    def test_evidence_result_is_one_of_three(self):
        self.assertInvalid(lambda d: d['evidence']['ran'][0].update(result='ok'), 'evidence.ran[0].result')

    def test_several_sources_for_one_item(self):
        def mut(d):
            d['evidence']['ran'][0]['source'] = [d['evidence']['ran'][0]['source'], {'kind': 'tool_call', 'command': LINT, 'excerpt': 'Checked 12 files'}]
        self.assertValid(mut)

    def test_numbers_in_detail_not_in_the_excerpt_warn(self):
        stats = self.assertValid(lambda d: d['evidence']['ran'][0].update(detail='3915 test đạt'))
        self.assertTrue(any('3915' in w for w in stats['warnings']))

    def test_tool_call_excerpt_may_be_any_part_of_the_result(self):
        self.assertValid(lambda d: d['evidence']['ran'][0]['source'].update(excerpt='PHPUnit 11.2 OK (1 test'))

    def test_command_matches_whitespace_normalised(self):
        self.assertValid(lambda d: d['evidence']['ran'][0]['source'].update(command='vendor/bin/phpunit   tests/SvcTest.php'))


class HostileTranscripts(V2Case):
    def test_invalid_utf8_and_malformed_json_lines_are_skipped_and_counted(self):
        write_jsonl(self.transcript, main_records(), extra_raw=[b'\xff\xfe not utf8 {"type":"user"}', b'{"type": "user", broken', b'[1,2,3]', b'   '])
        stats = self.assertValid()
        self.assertTrue(any('skipped 2 of' in w and '1 invalid UTF-8' in w and '1 malformed JSON' in w for w in stats['warnings']), stats['warnings'])

    def test_a_quote_on_a_broken_line_is_not_found(self):
        write_jsonl(self.transcript, [r for r in main_records()[:2]], extra_raw=['{"type":"user","message":{"content":"dòng hỏng '.encode() + b'\xff"}}'])
        self.assertInvalid(lambda d: d['requests'][0].update(quote='dòng hỏng'), 'quote not found')

    def test_large_transcript_is_streamed(self):
        recs = [rec('assistant', [{'type': 'text', 'text': 'dòng thứ %d ' % i + 'x' * 40}]) for i in range(50000)]
        write_jsonl(self.transcript, main_records()[:6] + recs)
        t0 = time.time()
        errs, stats = self.validate()
        self.assertTrue(all('quote not found' in e or 'command not found' in e for e in errs), errs)  # only things cut from the fixture
        self.assertLess(time.time() - t0, 20)

    def test_vietnamese_quotes_in_many_forms(self):
        for q in ('Giới Hạn Theo Module'.lower(), unicodedata.normalize('NFD', 'theo module')):
            self.assertValid(lambda d: d['requests'][0].update(quote=q))

    def test_message_content_of_unexpected_shapes_is_ignored(self):
        odd = [{'type': 'user', 'message': None}, {'type': 'user', 'message': {'content': 5}}, {'type': 'assistant', 'message': {'content': [None, 3, {'type': 'tool_use'}]}},
               {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'zz', 'content': [None, {'text': 7}]}]}}]
        write_jsonl(self.transcript, odd + main_records())
        self.assertValid()


class VersionDispatch(V2Case):
    def test_v2_needs_both_markers(self):
        self.assertInvalid(lambda d: d.update(version=1), 'version: must be 2')
        self.assertInvalid(lambda d: d.update(schema='explain-change/1'), "schema: must be 'explain-change/2'")

    def test_render_dispatches_on_version(self):
        path = os.path.join(self.repo, 'x.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(self.doc(), fh, ensure_ascii=False)
        r = self.script('render.py', path, '--transcript', self.transcript)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.repo, 'index.html'), encoding='utf-8') as fh:
            self.assertIn('id="stage"', fh.read())  # the layout-2 page, not the v1 report

    def test_validate_cli_prints_a_v2_summary(self):
        path = os.path.join(self.repo, 'x.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(self.doc(), fh, ensure_ascii=False)
        r = self.script('validate.py', path, '--transcript', self.transcript)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('requests 2/3 done | tests passed', r.stdout)
        self.assertIn('3 inferred items render "suy luận"', r.stdout)
        bad = self.doc()
        bad['requests'][0]['quote'] = 'câu bịa đặt không có thật'
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(bad, fh, ensure_ascii=False)
        r = self.script('validate.py', path, '--transcript', self.transcript)
        self.assertEqual(r.returncode, 1)
        self.assertIn('requests[0].quote: quote not found', r.stdout)


if __name__ == '__main__':
    unittest.main()
