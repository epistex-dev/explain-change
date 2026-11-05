"""D1: edges run through the gaps between boxes. The router (assets/ui/route.js, pure) is run under node on box layouts and
every route is checked here, independently: no segment enters a box or a zone title, every route leaves the source and
enters the target, no label overlaps a box. Layouts: modelled from page2.layout() (random shapes) and recorded from the
real pages (tests/fixtures/geometry-*.json, boxes measured once in a browser; the test itself runs no browser)."""
import glob
import json
import os
import random
import shutil
import subprocess
import unittest

from helpers import SKILL
from lib import page2

DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'route_driver.js')
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
EPS = .5
SEP, BORDER_AUDIT = 8, 5  # runs of two edges on shared ground are SEP apart; no run lies within BORDER_AUDIT of a zone side
GAP, PAD, LABEL_H = 24, 16, 30


def route_all(jobs):
    node = shutil.which('node')
    if not node:
        raise AssertionError('node is required to run the router tests (the skill page checker needs it too)')
    p = subprocess.run([node, DRIVER], input=json.dumps(jobs), capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout)


def inside(x, y, r):
    return r['l'] + EPS < x < r['r'] - EPS and r['t'] + EPS < y < r['b'] - EPS


def seg_hits(a, b, r):
    (x1, y1), (x2, y2) = a, b
    return max(x1, x2) > r['l'] + EPS and min(x1, x2) < r['r'] - EPS and max(y1, y2) > r['t'] + EPS and min(y1, y2) < r['b'] - EPS


def on_side(p, r):
    x, y = p
    return (abs(x - r['l']) < EPS or abs(x - r['r']) < EPS) and r['t'] - EPS <= y <= r['b'] + EPS or \
        (abs(y - r['t']) < EPS or abs(y - r['b']) < EPS) and r['l'] - EPS <= x <= r['r'] + EPS


def overlap(a1, a2, b1, b2):
    return min(max(a1, a2), max(b1, b2)) - max(min(a1, a2), min(b1, b2))


def runs(pts):
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


def along_zone_border(a, b, z):
    (x1, y1), (x2, y2) = a, b
    if x1 == x2:
        return (abs(x1 - z['l']) < BORDER_AUDIT or abs(x1 - z['r']) < BORDER_AUDIT) and overlap(y1, y2, z['t'], z['b']) > EPS
    return y1 == y2 and (abs(y1 - z['t']) < BORDER_AUDIT or abs(y1 - z['b']) < BORDER_AUDIT) and overlap(x1, x2, z['l'], z['r']) > EPS


def parallel_too_close(a, b, ends_a=(), ends_b=()):
    """Two runs of different edges, same direction, over the same stretch, closer than SEP. Not counted: two runs that leave or enter the
    same port (a point that is an end of both paths): that is one trunk."""
    (ax1, ay1), (ax2, ay2), (bx1, by1), (bx2, by2) = a[0], a[1], b[0], b[1]
    shared = {tuple(a[0]), tuple(a[1])} & {tuple(b[0]), tuple(b[1])}
    if any(p in {tuple(x) for x in ends_a} and p in {tuple(x) for x in ends_b} for p in shared):
        return False
    if ay1 == ay2 and by1 == by2:
        return abs(ay1 - by1) < SEP - EPS and overlap(ax1, ax2, bx1, bx2) > 1
    if ax1 == ax2 and bx1 == bx2:
        return abs(ax1 - bx1) < SEP - EPS and overlap(ay1, ay2, by1, by2) > 1
    return False


def audit(job, result, strict=True):
    """Problems of one routed layout, as strings. strict=False tolerates parallel runs closer than SEP when both touch a port: a port sits
    on the middle of a box side and cannot move, so two such runs on facing ports may share ground."""
    boxes = {b['id']: b for b in job['boxes']}
    solids = list(job['boxes']) + list(job.get('obstacles') or [])
    bad = []
    placed = []
    for k, (e, pts, lab) in enumerate(zip(job['edges'], result['paths'], result['labels'])):
        tag = 'edge %s->%s' % (e['a'], e['b'])
        if pts is None:
            bad.append(tag + ': not routed')
            continue
        src, dst = boxes[e['a']], boxes[e['b']]
        if not (on_side(pts[0], src) and on_side(pts[-1], dst)):
            bad.append(tag + ': does not start on the source and end on the target')
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if a[0] != b[0] and a[1] != b[1]:
                bad.append('%s: segment %d is not horizontal or vertical' % (tag, i))
            for r in solids:
                if seg_hits(a, b, r):
                    bad.append('%s: segment %d crosses %s' % (tag, i, r.get('id', 'a zone title')))
            for z in (job.get('zones') or []) + (job.get('obstacles') or []):
                if along_zone_border(a, b, z):
                    bad.append('%s: segment %d runs along a zone border or title' % (tag, i))
        if len(pts) >= 2:  # the first step leaves the source, the last step comes from outside the target
            if inside(*pts[1], src) or any(inside(*pts[1], r) for r in solids):
                bad.append(tag + ': first step runs inside a box')
            if inside(*pts[-2], dst):
                bad.append(tag + ': arrives from inside the target')
        if lab:
            for r in solids:
                if lab['r'] > r['l'] and lab['l'] < r['r'] and lab['b'] > r['t'] and lab['t'] < r['b']:
                    bad.append('%s: label overlaps %s' % (tag, r.get('id', 'a zone title')))
            for o in placed:
                if lab['r'] > o['l'] and lab['l'] < o['r'] and lab['b'] > o['t'] and lab['t'] < o['b']:
                    bad.append(tag + ': label overlaps another label')
            placed.append(lab)
            near = {'l': lab['l'] - 6, 'r': lab['r'] + 6, 't': lab['t'] - 6, 'b': lab['b'] + 6}
            if not any(seg_hits(a, b, near) for a, b in runs(pts)):
                bad.append(tag + ': label is not on or beside a run of its edge')
    allruns = [(k, i in (0, len(pts) - 2), r) for k, pts in enumerate(result['paths']) if pts for i, r in enumerate(runs(pts))]
    ends = {k: (pts[0], pts[-1]) for k, pts in enumerate(result['paths']) if pts}
    for n, (k1, port1, r1) in enumerate(allruns):
        for k2, port2, r2 in allruns[n + 1:]:
            if port1 and port2 and (r1[0][0] == r1[1][0] == r2[0][0] == r2[1][0] or r1[0][1] == r1[1][1] == r2[0][1] == r2[1][1]):
                continue  # two port stubs on one line (facing ports): one trunk, not two lines side by side
            if k1 != k2 and parallel_too_close(r1, r2, ends[k1], ends[k2]) and (strict or not (port1 and port2)):
                bad.append('edges %d and %d run parallel closer than %d px' % (k1, k2, SEP))
    return bad


# ---- a model of the page's CSS grid built from page2.layout() ------------------------------------
def model(rng, n_zones, W=1000):
    mods, edges, n = [], [], 0
    for z in range(n_zones):
        key = 'z%d' % z
        for _ in range(rng.randint(1, 4)):
            mods.append({'i': n, 'id': 'm%d' % n, 'tok': 'n%d' % n, 'zone': '__out' if z == 0 and rng.random() < .5 else key, 'zlabel': 'Zone %d' % z,
                         'changed': rng.random() < .4, 'outside': False, 'is_test': False, 'icon': 'file-code', 'files': [0] * rng.randint(0, 3)})
            n += 1
    for m in mods:
        m['outside'] = m['zone'] == '__out'
    for _ in range(rng.randint(2, 7)):
        a, b = rng.sample(mods, 2)
        edges.append({'from': a['id'], 'to': b['id'], 'kind': rng.choice(['flow', 'flow', 'arch', 'tests'])})
    cols = page2.layout(mods, edges)
    widths = []
    for col in cols:
        widths.append(2.4 if any(len(z['mods']) >= 3 for z in col) and len(cols) > 1 or (len(cols) == 1) else 1.3)
    avail = W - GAP * (len(cols) - 1)
    px = [max(200, avail * w / sum(widths)) for w in widths]
    boxes, titles, zones, x, H = [], [], [], 0, 0
    for col, cw in zip(cols, px):
        y = 0
        for z in col:
            zc = 1 if len(z['mods']) < 3 else 2
            inner = cw - 2 * PAD
            nw = (inner - GAP * (zc - 1)) / zc
            z0 = y
            titles.append({'l': x + PAD, 'r': x + PAD + 140, 't': y + PAD, 'b': y + PAD + 18})
            rows = [z['mods'][i:i + zc] for i in range(0, len(z['mods']), zc)]
            ry = y + PAD + LABEL_H
            for row in rows:
                h = 0
                for c, m in enumerate(row):
                    nh = 84 + 17 * (m['i'] % 4) + 26 * len(m['files'])
                    h = max(h, nh)
                    boxes.append({'id': m['tok'], 'l': round(x + PAD + c * (nw + GAP)), 'r': round(x + PAD + c * (nw + GAP) + nw), 't': round(ry), 'b': round(ry + nh)})
                ry += h + GAP
            zones.append({'l': x, 'r': x + cw, 't': z0, 'b': ry - GAP + PAD})
            y = ry - GAP + PAD + GAP
        H = max(H, y)
        x += cw + GAP
    tok = {m['id']: m['tok'] for m in mods}
    routed = [{'a': tok[e['from']], 'b': tok[e['to']], 'lw': 58 if e['kind'] == 'arch' else 0, 'lh': 13} for e in edges]
    return {'boxes': boxes, 'obstacles': titles, 'zones': zones, 'edges': routed, 'W': W, 'H': H}


class RouteGeometry(unittest.TestCase):
    def test_random_layouts_route_without_crossing_a_box(self):
        rng = random.Random(7)
        jobs = [model(rng, rng.randint(2, 6), rng.choice([760, 1000, 1200])) for _ in range(120)]
        results = route_all(jobs)
        problems, edges, labels = [], 0, 0
        for j, r in zip(jobs, results):
            problems += audit(j, r, strict=False)
            edges += len(j['edges'])
            labels += sum(1 for x in r['labels'] if x)
        close = [p for p in problems if 'parallel closer' in p]
        self.assertEqual([p for p in problems if p not in close][:10], [], '%d problems in %d edges' % (len(problems), edges))
        # three lines do not fit a 24 px gutter at 8 px apart with 8 px left at each end, and a run that ends 3 px from its box cannot move:
        # these rare pairs are tolerated, up to 2% of the edges (the first router left 54 of 532, 10%)
        self.assertLessEqual(len(close), edges * 2 // 100, close)
        self.assertGreater(edges, 300)
        wanted = sum(1 for j in jobs for e in j['edges'] if e.get('lw'))
        self.assertGreater(wanted, 100)
        self.assertGreaterEqual(labels / wanted, .65, 'a label has many spots to try before it is dropped (the first router placed 40%%): %d of %d' % (labels, wanted))

    def test_a_straight_neighbour_edge_stays_short_and_a_blocked_one_goes_round(self):
        job = {'boxes': [{'id': 'a', 'l': 0, 'r': 100, 't': 0, 'b': 60}, {'id': 'x', 'l': 200, 'r': 300, 't': 0, 'b': 60},
                         {'id': 'b', 'l': 400, 'r': 500, 't': 0, 'b': 60}], 'obstacles': [], 'edges': [{'a': 'a', 'b': 'x'}, {'a': 'a', 'b': 'b'}], 'W': 500, 'H': 60}
        res = route_all([job])[0]
        self.assertEqual(audit(job, res), [])
        self.assertEqual(res['paths'][0], [[100, 30], [200, 30]])
        self.assertGreater(len(res['paths'][1]), 2, 'the edge to b cannot run straight through x')

    def test_the_arrow_points_from_source_to_target(self):
        job = {'boxes': [{'id': 'a', 'l': 0, 'r': 100, 't': 0, 'b': 60}, {'id': 'b', 'l': 300, 'r': 400, 't': 100, 'b': 160}],
               'obstacles': [], 'edges': [{'a': 'a', 'b': 'b'}, {'a': 'b', 'b': 'a'}], 'W': 400, 'H': 160}
        res = route_all([job])[0]
        self.assertEqual(audit(job, res), [])
        ab, ba = res['paths']
        self.assertTrue(on_side(ab[0], job['boxes'][0]) and on_side(ab[-1], job['boxes'][1]))
        self.assertTrue(on_side(ba[0], job['boxes'][1]) and on_side(ba[-1], job['boxes'][0]))

    def test_an_unroutable_edge_is_dropped_not_drawn_through_a_box(self):
        job = {'boxes': [{'id': 'a', 'l': 0, 'r': 100, 't': 0, 'b': 60}, {'id': 'b', 'l': 0, 'r': 100, 't': 60, 'b': 120}],
               'obstacles': [], 'edges': [{'a': 'a', 'b': 'a'}, {'a': 'a', 'b': 'zzz'}], 'W': 100, 'H': 120}
        res = route_all([job])[0]
        self.assertEqual(res['paths'], [None, None])

    def test_an_edge_walled_in_by_other_things_is_dropped(self):
        job = {'boxes': [{'id': 'a', 'l': 100, 'r': 200, 't': 100, 'b': 160}, {'id': 'b', 'l': 400, 'r': 500, 't': 100, 'b': 160}],
               'obstacles': [{'l': 50, 'r': 250, 't': 60, 'b': 90}, {'l': 50, 'r': 250, 't': 170, 'b': 200}, {'l': 50, 'r': 90, 't': 60, 'b': 200},
                             {'l': 210, 'r': 250, 't': 60, 'b': 200}], 'edges': [{'a': 'a', 'b': 'b', 'lw': 40}], 'W': 500, 'H': 260}
        res = route_all([job])[0]
        self.assertEqual((res['paths'], res['labels']), ([None], [None]))

    def test_two_labels_on_one_run_do_not_overlap(self):
        job = {'boxes': [{'id': 'a', 'l': 0, 'r': 100, 't': 0, 'b': 60}, {'id': 'b', 'l': 400, 'r': 500, 't': 0, 'b': 60}], 'obstacles': [],
               'edges': [{'a': 'a', 'b': 'b', 'lw': 50, 'lh': 13}, {'a': 'a', 'b': 'b', 'lw': 50, 'lh': 13}], 'W': 500, 'H': 60}
        res = route_all([job])[0]
        self.assertTrue(all(res['labels']), res['labels'])
        self.assertEqual(audit(job, res), [])
        a, b = res['labels']
        self.assertFalse(a['r'] > b['l'] and b['r'] > a['l'] and a['b'] > b['t'] and b['b'] > a['t'])

    def test_the_audit_catches_a_path_through_a_box(self):  # the verifier itself must be able to fail
        job = {'boxes': [{'id': 'a', 'l': 0, 'r': 100, 't': 0, 'b': 60}, {'id': 'x', 'l': 150, 'r': 250, 't': 0, 'b': 60},
                         {'id': 'b', 'l': 300, 'r': 400, 't': 0, 'b': 60}], 'obstacles': [], 'edges': [{'a': 'a', 'b': 'b', 'lw': 40}], 'W': 400, 'H': 60}
        bad = audit(job, {'paths': [[[100, 30], [300, 30]]], 'labels': [{'l': 130, 'r': 170, 't': 22, 'b': 38}]})
        self.assertTrue(any('crosses x' in b for b in bad), bad)
        self.assertTrue(any('label overlaps x' in b for b in bad), bad)


class Separation(unittest.TestCase):
    def test_two_edges_through_one_gutter_are_8px_apart(self):
        # the rows are walled off, so both edges must cross the one gutter between the columns (a single grid line, x=200)
        job = {'boxes': [{'id': 'a1', 'l': 0, 'r': 100, 't': 0, 'b': 60}, {'id': 'a2', 'l': 0, 'r': 100, 't': 100, 'b': 160},
                         {'id': 'b1', 'l': 300, 'r': 400, 't': 0, 'b': 60}, {'id': 'b2', 'l': 300, 'r': 400, 't': 100, 'b': 160}],
               'obstacles': [{'l': -20, 'r': 100, 't': 60, 'b': 100}, {'l': 300, 'r': 420, 't': 60, 'b': 100},
                             {'l': -20, 'r': 420, 't': -20, 'b': -2}, {'l': -20, 'r': 420, 't': 162, 'b': 180}],
               'edges': [{'a': 'a1', 'b': 'b2'}, {'a': 'a2', 'b': 'b1'}], 'W': 400, 'H': 160}
        res = route_all([job])[0]
        self.assertEqual(audit(job, res), [])
        self.assertTrue(all(res['paths']), res['paths'])
        xs = sorted(p[0] for pts in res['paths'] for p, q in runs(pts) if p[0] == q[0] and 100 < p[0] < 300 and abs(p[1] - q[1]) > 40)
        self.assertEqual(len(xs), 2, res['paths'])
        self.assertGreaterEqual(xs[1] - xs[0], SEP)

    def test_two_edges_in_a_narrow_gutter_between_zones_share_it_evenly(self):
        # the gutter between the zones is 24 px, and a run keeps 6 px off each zone side: two runs fit only if both leave the middle
        job = {'boxes': [{'id': 'a1', 'l': 16, 'r': 272, 't': 0, 'b': 60}, {'id': 'a2', 'l': 16, 'r': 272, 't': 100, 'b': 160},
                         {'id': 'b1', 'l': 328, 'r': 584, 't': 0, 'b': 60}, {'id': 'b2', 'l': 328, 'r': 584, 't': 100, 'b': 160}],
               'obstacles': [{'l': -20, 'r': 290, 't': 60, 'b': 100}, {'l': 310, 'r': 620, 't': 60, 'b': 100},
                             {'l': -20, 'r': 620, 't': -20, 'b': -2}, {'l': -20, 'r': 620, 't': 162, 'b': 180}],
               'zones': [{'l': 0, 'r': 288, 't': -10, 'b': 170}, {'l': 312, 'r': 600, 't': -10, 'b': 170}],
               'edges': [{'a': 'a1', 'b': 'b2'}, {'a': 'a2', 'b': 'b1'}], 'W': 600, 'H': 160}
        res = route_all([job])[0]
        self.assertTrue(all(res['paths']), res['paths'])
        self.assertEqual(audit(job, res), [])
        xs = sorted(p[0] for pts in res['paths'] for p, q in runs(pts) if p[0] == q[0] and 288 < p[0] < 312 and abs(p[1] - q[1]) > 40)
        self.assertEqual(len(xs), 2, res['paths'])
        self.assertGreaterEqual(xs[1] - xs[0], SEP)

    def test_two_grid_lines_two_pixels_apart_are_not_two_lines_in_one_gutter(self):  # the page showed two dashed edges 2 px apart
        job = {'boxes': [{'id': 'a', 'l': 0, 'r': 100, 't': 0, 'b': 60}, {'id': 'b', 'l': 0, 'r': 100, 't': 120, 'b': 180},
                         {'id': 'c', 'l': 300, 'r': 400, 't': 0, 'b': 60}, {'id': 'd', 'l': 302, 'r': 402, 't': 120, 'b': 180}],
               'obstacles': [], 'edges': [{'a': 'a', 'b': 'd'}, {'a': 'b', 'b': 'c'}], 'W': 402, 'H': 180}
        res = route_all([job])[0]
        self.assertEqual(audit(job, res), [])

    def test_no_run_lies_along_a_zone_border(self):
        # two zones 8 px apart: the line between box rows (y=104) is 4 px from both borders, a line along them
        job = {'boxes': [{'id': 'a', 'l': 20, 'r': 120, 't': 40, 'b': 84}, {'id': 'b', 'l': 380, 'r': 480, 't': 124, 'b': 168},
                         {'id': 'm', 'l': 200, 'r': 300, 't': 124, 'b': 168}],
               'obstacles': [], 'zones': [{'l': 0, 'r': 500, 't': 0, 'b': 100}, {'l': 0, 'r': 500, 't': 108, 'b': 190}],
               'edges': [{'a': 'a', 'b': 'b'}], 'W': 500, 'H': 190}
        res = route_all([job])[0]
        self.assertEqual(audit(job, res), [])
        self.assertTrue(res['paths'][0])
        bad = audit(job, {'paths': [[[120, 62], [150, 62], [150, 104], [430, 104], [430, 124]]], 'labels': [None]})
        self.assertTrue(any('zone border or title' in b for b in bad), bad)  # the audit itself can fail

    def test_a_route_that_used_to_run_along_a_zone_border(self):
        # found by random search: without the border rule the edge n4 -> n0 climbs the gap between two zones at x=564, 1.8 px from a zone side
        job = {"boxes": [{"id": "n0", "l": 16, "r": 159, "t": 46, "b": 156}, {"id": "n3", "l": 183, "r": 326, "t": 46, "b": 207}, {"id": "n1", "l": 16, "r": 159, "t": 231, "b": 358},
                         {"id": "n2", "l": 382, "r": 550, "t": 46, "b": 216}, {"id": "n4", "l": 606, "r": 774, "t": 46, "b": 130}],
               "obstacles": [{"l": 16, "r": 156, "t": 16, "b": 34}, {"l": 381.76, "r": 521.76, "t": 16, "b": 34}, {"l": 605.76, "r": 745.76, "t": 16, "b": 34}],
               "zones": [{"l": 0, "r": 341.76, "t": 0, "b": 374}, {"l": 365.76, "r": 565.76, "t": 0, "b": 232}, {"l": 589.76, "r": 789.76, "t": 0, "b": 146}],
               "edges": [{"a": "n4", "b": "n0", "lw": 0, "lh": 13}], "W": 760, "H": 398}
        res = route_all([job])[0]
        self.assertTrue(res['paths'][0])
        self.assertEqual(audit(job, res), [])

    def test_the_audit_catches_two_runs_two_pixels_apart(self):
        job = {'boxes': [], 'obstacles': [], 'edges': [{'a': 'x', 'b': 'y'}, {'a': 'x', 'b': 'y'}], 'W': 400, 'H': 100}
        bad = audit({**job, 'boxes': [{'id': 'x', 'l': 0, 'r': 10, 't': 0, 'b': 10}, {'id': 'y', 'l': 390, 'r': 400, 't': 90, 'b': 100}]},
                    {'paths': [[[10, 5], [100, 5], [100, 50], [300, 50], [300, 95], [390, 95]], [[10, 5], [150, 5], [150, 52], [350, 52], [350, 95], [390, 95]]], 'labels': [None, None]})
        self.assertTrue(any('parallel closer' in b for b in bad), bad)


class NoReversal(unittest.TestCase):
    """An edge that runs rightwards must not loop back left (or an upward one dip down) when a straight gutter exists. The layout is a
    random one (seed 11) in which the first router led n1 -> n2 out of n1's left side, round the outer margin and back right."""
    JOB = json.loads('''{"boxes":[{"id":"n0","l":16,"r":184,"t":46,"b":208},{"id":"n1","l":16,"r":184,"t":294,"b":395},{"id":"n2","l":240,"r":408,"t":46,"b":216},{"id":"n6","l":240,"r":408,"t":302,"b":446},{"id":"n3","l":464,"r":607,"t":46,"b":181},{"id":"n4","l":631,"r":774,"t":46,"b":130},{"id":"n5","l":464,"r":607,"t":205,"b":358}],"obstacles":[{"l":16,"r":156,"t":16,"b":34},{"l":16,"r":156,"t":264,"b":282},{"l":240,"r":380,"t":16,"b":34},{"l":240,"r":380,"t":272,"b":290},{"l":464,"r":604,"t":16,"b":34}],"zones":[{"l":0,"r":200,"t":0,"b":224},{"l":0,"r":200,"t":248,"b":411},{"l":224,"r":424,"t":0,"b":232},{"l":224,"r":424,"t":256,"b":462},{"l":448,"r":789.76,"t":0,"b":374}],"edges":[{"a":"n0","b":"n6","lw":0,"lh":13},{"a":"n1","b":"n2","lw":0,"lh":13},{"a":"n3","b":"n5","lw":58,"lh":13},{"a":"n2","b":"n4","lw":0,"lh":13}],"W":760,"H":486}''')

    @staticmethod
    def against_net_direction(pts):
        net = (pts[-1][0] > pts[0][0]) - (pts[-1][0] < pts[0][0])
        return net != 0 and any(((b[0] > a[0]) - (b[0] < a[0])) not in (0, net) for a, b in zip(pts, pts[1:]))

    def test_a_rightward_edge_does_not_leave_by_the_left_side_and_loop_back(self):
        res = route_all([self.JOB])[0]
        self.assertEqual(audit(self.JOB, res), [])
        pts = res['paths'][1]  # n1 -> n2
        self.assertIsNotNone(pts)
        self.assertFalse(self.against_net_direction(pts), pts)
        self.assertGreaterEqual(min(x for x, _ in pts), 0, 'the route must not use the outer margin to turn back')

    def test_random_layouts_have_few_routes_against_their_own_direction(self):
        rng = random.Random(11)
        jobs = [model(rng, rng.randint(2, 6), rng.choice([760, 1000, 1200])) for _ in range(400)]
        results = route_all(jobs)
        paths = [p for r in results for p in r['paths'] if p]
        against = sum(1 for p in paths if self.against_net_direction(p))
        self.assertGreater(len(paths), 1500)
        self.assertLessEqual(against, len(paths) * 14 // 1000, '%d of %d routes turn back (the first router: 41, 2.2%%)' % (against, len(paths)))

    def test_the_checker_itself_can_fail(self):
        self.assertTrue(self.against_net_direction([[16, 344], [-10, 344], [-10, 240], [324, 240], [324, 216]]))
        self.assertFalse(self.against_net_direction([[184, 344], [212, 344], [212, 240], [324, 240]]))


class RecordedPages(unittest.TestCase):
    """Boxes of the two real pages at 1440 and 800 px wide, measured once in a browser."""

    def test_the_recorded_layouts_exist_and_route_cleanly(self):
        files = sorted(glob.glob(os.path.join(FIXTURES, 'geometry-*.json')))
        self.assertGreaterEqual(len(files), 4, 'tests/fixtures/geometry-*.json (autofill and fixture at 1440 and 800 px)')
        jobs = []
        for f in files:
            with open(f, encoding='utf-8') as fh:
                jobs.append(json.load(fh))
        results = route_all(jobs)
        for f, j, r in zip(files, jobs, results):
            self.assertEqual(audit(j, r), [], os.path.basename(f))  # strict: no parallel runs under 8 px, none along a zone border
            self.assertTrue(all(p for p in r['paths']), '%s: every edge is routed' % os.path.basename(f))
        placed = [l for r in results for l in r['labels'] if l]
        self.assertTrue(placed, 'the /api/v1/* label is on the map')


if __name__ == '__main__':
    unittest.main()
