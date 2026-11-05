"""The outward-action classifier: a pure function over one shell command string (lib/outward.py).
Two lists drive it: BENIGN (nothing leaves the working copy) and CAUGHT (command -> kinds), plus hostile inputs."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
from lib import outward  # noqa: E402

BENIGN = [
    'git push --dry-run', 'git push -n origin main', 'git push --dry-run --force', 'git push -nf origin main',
    "echo 'git push'", 'echo "git push origin main"', "grep 'git push' notes.md", 'grep -rn "git push" .',
    "cat <<'EOF'\ngit push origin main\nEOF", 'cat <<EOF > notes.txt\ngit push --force\nEOF',
    'git commit -F - <<EOF\nmention git push here\nEOF', '# git push origin main', 'ls  # git push later', 'ls # note; git push', "true # it's x && git push -f", 'echo a # b\ngit status',
    'git log --oneline', 'git status', 'git diff HEAD~1', 'git fetch origin', 'git branch -d merged', 'git branch -a',
    'gh repo view epistex-dev/x', 'gh pr view 3', 'gh pr list', 'gh release list',
    'rm notes.txt', 'rm -f /tmp/x.log', 'rm src/a.py src/b.py', 'git rm old.py',
    'printf "%s\\n" "git push" > /tmp/out', 'git commit -m "git push is next"', 'git commit -m "rm -rf /"',
    'npm publish --dry-run', 'kubectl apply -f x.yaml --dry-run=client', 'kubectl get pods', 'vercel whoami', 'vercel env ls',
    'docker build -t x .', 'fly status', 'python3 -m unittest', 'git rebase --abort', 'git commit -m fix',
    'git commit --amend --no-edit', 'git rebase -i HEAD~3', 'git reset --hard HEAD~1', 'git worktree list', 'git worktree add /tmp/w -b b', 'ls -r', 'find . -name "*.py"', 'cd /tmp && ls', 'true',
]
CAUGHT = [
    ('git push', ['push']), ('git push origin main', ['push']), ('git -C /tmp/r push origin main', ['push']),
    ('git -c core.x=1 -C r push', ['push']), ('git push --force', ['force_push']), ('git push -f origin main', ['force_push']),
    ('git push --force-with-lease origin main', ['force_push']), ('git push --force-with-lease=main:abc origin main', ['force_push']),
    ('git push origin +main', ['force_push']), ('git push origin +HEAD:refs/heads/x', ['force_push']), ('git push -u origin main', ['push']),
    ('git push origin --delete old', ['delete']), ('git push origin :old', ['delete']),
    ('cd /tmp/r && git push', ['push']), ('git add -A && git commit -m x && git push', ['push']), ('git commit -m x; git push -f', ['force_push']),
    ('git pull || git push', ['push']), ("bash -c 'git push origin main'", ['push']), ('sh -c "cd r && git push --force"', ['force_push']),
    ('bash -lc "git push"', ['push']), ('(cd r && git push)', ['push']), ('echo $(git push)', ['push']), ('echo "$(git push -f)"', ['force_push']),
    ('git push 2>&1 | tail -3', ['push']), ('git push > /tmp/out.log 2>&1', ['push']), ('git push &', ['push']),
    ('FOO=1 git push', ['push']), ('sudo git push', ['push']), ('env GIT_SSH=x git push', ['push']), ('timeout 60 git push', ['push']),
    ('/usr/bin/git push', ['push']), ('for r in a b; do git -C $r push; done', ['push']), ('if true; then git push; fi', ['push']),
    ('eval "git push"', ['push']), ('bash <<EOF\ngit push\nEOF', ['push']), ('git push \\\n  origin main', ['push']),
    ('gh repo create x --private', ['repo_created']), ('gh repo create x --private --source . --push', ['repo_created', 'push']),
    ('gh pr create --fill', ['pr']), ('gh pr merge 4 --squash', ['pr']), ('gh release create v1 -n x', ['deploy']),
    ('gh repo delete x --yes', ['delete']), ('gh pr comment 3 -b hi', ['message']), ('gh issue create -t x', ['message']),
    ('gh api -X POST repos/o/r/forks', ['other']), ('gh -R o/r pr merge 2', ['pr']),
    ('git filter-repo --path x --invert-paths', ['history_rewrite']), ('git filter-branch --tree-filter x', ['history_rewrite']),
    ('rm -rf /tmp/x', ['delete']), ('rm -r build', ['delete']), ('rm -fr /tmp/a /tmp/b', ['delete']), ('rm -f -R x', ['delete']),
    ('rm --recursive --force x', ['delete']), ('rm -rf /tmp/x && git push', ['delete', 'push']), ('rm /tmp/dir/', ['delete']), ('rmdir /tmp/d', ['delete']),
    ('git worktree remove /tmp/w', ['delete']), ('git worktree remove --force /tmp/w', ['delete']), ('git -C r branch -D feat', ['delete']),
    ('git branch -d -f x', ['delete']), ('git clean -fd', ['delete']), ('find /tmp/x -delete', ['delete']), ('find /tmp -name "x*" -exec rm -rf {} +', ['delete']),
    ('vercel', ['deploy']), ('vercel --prod', ['deploy']), ('vercel deploy', ['deploy']), ('fly deploy', ['deploy']), ('flyctl deploy -a x', ['deploy']),
    ('kubectl apply -f x.yaml', ['deploy']), ('kubectl -n prod apply -f x.yaml', ['deploy']), ('kubectl apply -f x --dry-run=none', ['deploy']),
    ('docker push ghcr.io/o/i:1', ['deploy']), ('docker image push x', ['deploy']), ('npm publish', ['deploy']), ('pnpm publish --access public', ['deploy']),
    ('terraform apply -auto-approve', ['deploy']), ('cargo publish', ['deploy']),
]
HOSTILE = [
    '', '   ', '\n\n', ';;;', '&&', '||', '|', '( ( (', ')))', "'", '"', '`', '$(', '$(git push', "git push 'origin", 'git push "origin main',
    "echo 'unterminated git push", "bash -c 'git push", 'cat <<EOF\ngit push', '\\', 'git', 'git -C', 'git -c', 'git push --', 'rm', 'rm -', 'gh', 'sudo', 'env',
    'bash -c', 'eval', 'find -exec', 'x' * 5000, '\x00', 'git\x00push', '\ud800', 'git push \udcff', '$(' * 2000 + ')' * 2000, "bash -c '" * 200 + "git push" + "'" * 200,
]


class Benign(unittest.TestCase):
    def test_nothing_is_flagged(self):
        for cmd in BENIGN:
            with self.subTest(cmd=cmd):
                self.assertEqual(outward.classify(cmd), [], cmd)


class Caught(unittest.TestCase):
    def test_each_form_gives_exactly_its_kinds(self):
        for cmd, kinds in CAUGHT:
            with self.subTest(cmd=cmd):
                self.assertEqual(sorted(k for k, _ in outward.classify(cmd)), sorted(kinds), cmd)

    def test_force_is_its_own_kind_not_also_a_push(self):
        self.assertEqual([k for k, _ in outward.classify('git push --force')], ['force_push'])

    def test_two_pushes_in_one_command_count_twice(self):
        self.assertEqual([k for k, _ in outward.classify('git -C a push && git -C b push -f')], ['push', 'force_push'])

    def test_label_names_the_action_without_the_arguments(self):
        (kind, label), = outward.classify('git push --force origin secret-branch')
        self.assertEqual(label, 'git push --force')


class Failed(unittest.TestCase):
    def test_a_failed_call_is_never_counted(self):
        self.assertEqual(outward.classify_call('git push', is_error=True, result='x'), [])
        self.assertEqual(outward.classify_call('git push', is_error=False, result='Exit code 1\nrejected'), [])
        self.assertEqual(outward.classify_call('git push', is_error=False, result='Exit code 128\nfatal'), [])

    def test_a_successful_call_is_counted(self):
        self.assertEqual([k for k, _ in outward.classify_call('git push', is_error=False, result='To github.com:o/r.git\n   a..b  main -> main')], ['push'])
        self.assertEqual([k for k, _ in outward.classify_call('git push', is_error=False, result=None)], ['push'])
        self.assertEqual([k for k, _ in outward.classify_call('git push', is_error=False, result='Exit code 0')], ['push'])


class Hostile(unittest.TestCase):
    def test_every_input_returns_a_list_of_pairs(self):
        for cmd in HOSTILE:
            with self.subTest(cmd=cmd[:40]):
                out = outward.classify(cmd)
                self.assertIsInstance(out, list)
                for item in out:
                    self.assertIn(item[0], outward.KINDS)

    def test_bytes_with_invalid_utf8_are_decoded_not_fatal(self):
        self.assertEqual([k for k, _ in outward.classify(b'git push \xff\xfe origin')], ['push'])
        self.assertEqual(outward.classify(b'\xff\xfe'), [])

    def test_non_string_input_is_empty(self):
        for x in (None, 5, [], {}):
            self.assertEqual(outward.classify(x), [])

    def test_unbalanced_quote_still_finds_the_command_before_it(self):
        self.assertEqual([k for k, _ in outward.classify("git push && echo 'oops")], ['push'])
        self.assertEqual(outward.classify("echo 'git push"), [])

    def test_one_megabyte_command_is_fast(self):
        big = 'echo ' + 'a' * (1 << 20) + ' && git push'
        t = time.time()
        out = outward.classify(big)
        self.assertLess(time.time() - t, 3)
        self.assertEqual([k for k, _ in out], ['push'])
        t = time.time()
        outward.classify("echo '" + 'git push; ' * 100000)
        outward.classify('git push ' + '"' * 100000)
        self.assertLess(time.time() - t, 5)

    def test_deep_nesting_is_bounded(self):
        cmd = 'git push'
        for _ in range(7):  # each level re-quotes the one below: the text grows about 4x per level, so stay shallow
            cmd = "bash -c '%s'" % cmd.replace("'", "'\\''")
        self.assertIsInstance(outward.classify(cmd), list)
        self.assertIsInstance(outward.classify('$(' * 60 + 'git push' + ')' * 60), list)

if __name__ == '__main__':
    unittest.main()
