"""The manifests and SKILL.md agree with each other and with the Agent Skills format (agentskills.io/specification)."""
import json
import os
import re
import unittest

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'skills', 'explain-change')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(*parts):
    with open(os.path.join(REPO, *parts), encoding='utf-8') as fh:
        return json.load(fh)


def frontmatter():
    with open(os.path.join(SKILL, 'SKILL.md'), encoding='utf-8') as fh:
        head = fh.read().split('---')[1]
    return dict(re.match(r'(\w[\w-]*):\s*(.*)', ln).groups() for ln in head.strip().splitlines())


class Manifests(unittest.TestCase):
    def test_every_manifest_names_the_skill_folder_and_carries_one_version(self):
        docs = [load('gemini-extension.json'), load('plugin.json'), load('.claude-plugin', 'plugin.json')]
        self.assertEqual({d['name'] for d in docs}, {'explain-change'})
        self.assertEqual(len({d['version'] for d in docs}), 1)
        self.assertEqual(load('.claude-plugin', 'marketplace.json')['plugins'][0]['version'], docs[0]['version'])
        self.assertEqual(docs[0]['version'], re.search(r'^## \[(\d[^\]]*)\]', open(os.path.join(REPO, 'CHANGELOG.md'), encoding='utf-8').read(), re.M).group(1))

    def test_the_portable_manifest_declares_the_agent_plugins_schema(self):
        self.assertEqual(load('plugin.json')['$schema'], 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json')

    def test_the_skills_directory_that_gemini_and_codex_scan_holds_the_skill(self):
        self.assertTrue(os.path.isfile(os.path.join(REPO, 'skills', 'explain-change', 'SKILL.md')))


class SkillFormat(unittest.TestCase):
    def test_frontmatter_follows_the_agent_skills_spec(self):
        fm = frontmatter()
        self.assertEqual(set(fm), {'name', 'description'})
        self.assertEqual(fm['name'], os.path.basename(SKILL))
        self.assertRegex(fm['name'], r'^[a-z0-9]+(-[a-z0-9]+)*$')
        self.assertLessEqual(len(fm['name']), 64)
        self.assertTrue(0 < len(fm['description']) <= 1024)

    def test_the_description_triggers_in_each_mode_and_each_language(self):
        d = frontmatter()['description']
        for want in ('explain this change', 'giải thích thay đổi', 'mình không hiểu code vừa sửa', 'summarize this session', 'how does X work', 'luồng này chạy thế nào', 'diff, commit or PR'):
            self.assertIn(want, d)

    def test_every_reference_is_one_link_from_the_skill(self):
        with open(os.path.join(SKILL, 'SKILL.md'), encoding='utf-8') as fh:
            body = fh.read()
        for name in sorted(os.listdir(os.path.join(SKILL, 'references'))):
            if name.endswith('.md'):
                self.assertIn('references/' + name, body, name)

    def test_the_steps_do_not_assume_one_harness(self):
        with open(os.path.join(SKILL, 'SKILL.md'), encoding='utf-8') as fh:
            body = fh.read()
        self.assertNotIn('claude -p', body)
        self.assertNotIn('html_preview', body)
        self.assertIn('The command in env `EXPLAIN_COLDREAD_CMD`', body)


if __name__ == '__main__':
    unittest.main()
