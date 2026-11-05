"""How the architecture's groups reach the change map: a group that holds drawn modules is their frame (never an "unrelated part"), and a frame never
repeats the title of its only card. Rendered from the change sample's own modules with architectures built here."""
import copy
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sample_env as env  # noqa: E402
from helpers import SKILL  # noqa: E402,F401  (puts scripts/ on sys.path)
from lib import arch as archmod, page2  # noqa: E402


def render(nodes):
    with open(env.CHANGE, encoding='utf-8') as fh:
        doc = json.load(fh)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'architecture.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'project': {'name': 'Acme'}, 'nodes': nodes, 'edges': []}, fh)
        return page2.render(doc, arch=archmod.Architecture(path), validated=False)


def nodes(root=True, extra=()):
    out = copy.deepcopy(env.architecture()['nodes'])
    if not root:
        for n in out:
            n.pop('parent', None)
        out = [n for n in out if n['id'] != 'acme']
    return out + list(extra)


def frames(html):
    return re.findall(r'<p class="zone-label">(?:<svg.*?</svg>)?([^<]*)</p>', html)


def footnote(html):
    return re.search(r'<p class="hidden-note">([^<]*)</p>', html)


class Groups(unittest.TestCase):
    def test_the_sample_architecture_has_a_root_that_holds_every_module(self):
        self.assertEqual(nodes()[0]['id'], 'acme')
        self.assertTrue(all(n.get('parent') == 'acme' for n in nodes()[1:]))

    def test_a_root_that_holds_drawn_modules_is_their_frame_and_not_an_unrelated_part(self):
        html = render(nodes())
        self.assertIsNone(footnote(html))
        self.assertIn('System', frames(html))

    def test_one_system_frame_holds_all_the_cards(self):
        html = render(nodes())
        self.assertEqual([f for f in frames(html) if f != 'Outside the system'], ['System'])

    def test_a_node_that_is_not_drawn_is_still_counted(self):
        html = render(nodes(extra=[{'id': 'billing', 'parent': 'acme', 'label': 'Billing', 'kind': 'service', 'summary': 'x'}]))
        self.assertEqual(footnote(html).group(1), '+1 unrelated part of the system, not drawn here')

    def test_a_nested_group_of_drawn_modules_is_not_counted_either(self):
        ns = nodes()
        for n in ns:
            if n['id'] in ('web.admin', 'web.auth'):
                n['parent'] = 'web'
        ns.insert(1, {'id': 'web', 'parent': 'acme', 'label': 'Web', 'kind': 'feature', 'summary': 'x'})
        self.assertIsNone(footnote(render(ns)))

    def test_no_frame_repeats_the_title_of_its_only_card(self):
        html = render(nodes(root=False))
        cards = re.findall(r'<span class="n-name">([^<]*)</span>', html)
        self.assertTrue(cards)
        for f in frames(html):
            self.assertNotIn(f, cards)
        self.assertIsNone(footnote(html))


if __name__ == '__main__':
    unittest.main()
