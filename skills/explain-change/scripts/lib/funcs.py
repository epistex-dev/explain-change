"""Heuristic list of changed functions with a branch count, so the agent explains the ones that matter.
Not a parser: braces and indentation only, string/comment contents ignored. Over-approximates on purpose."""
import os
import re

from . import gitio

DEF = {
    'php': re.compile(r'\bfunction\s+&?\s*(\w+)\s*\('),
    'js': re.compile(r'\bfunction\s*\*?\s*(\w+)\s*\(|^\s*(?:(?:public|private|protected|static|async)\s+)*(\w+)\s*\([^;{)]*\)\s*(?::\s*[\w<>\[\]|?]+\s*)?\{|\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>'),
    'py': re.compile(r'^\s*(?:async\s+)?def\s+(\w+)\s*\('),
}
EXT = {'php': 'php', 'js': 'js', 'jsx': 'js', 'ts': 'js', 'tsx': 'js', 'mjs': 'js', 'vue': 'js', 'py': 'py'}
KEYWORDS_NOT_FUNCS = {'if', 'for', 'foreach', 'while', 'switch', 'catch', 'match', 'function', 'return', 'elseif', 'else'}
BRANCH = re.compile(r'\b(?:if|elseif|else|foreach|for|while|switch|case|match|catch|elif|except|when)\b|\?\?|&&|\|\||\s\?\s')
HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')
MAX_FILES = 300
MAX_BYTES = 1_000_000


def _is_comment(s):
    s = s.strip()
    return s.startswith(('//', '*', '/*', '#'))


def _span_brace(lines, start):
    depth, opened = 0, False
    for i in range(start, len(lines)):
        code = lines[i]
        if _is_comment(code):
            continue
        for ch in code:
            if ch == '{':
                depth += 1
                opened = True
            elif ch == '}':
                depth -= 1
        if opened and depth <= 0:
            return i
        if not opened and i > start + 8:
            return start  # abstract / interface method
        if not opened and code.rstrip().endswith(';'):
            return start
    return len(lines) - 1


def _span_py(lines, start):
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start
    for i in range(start + 1, len(lines)):
        if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= indent:
            break
        if lines[i].strip():
            end = i
    return end


def find_functions(text_lines, kind):
    out = []
    rx = DEF[kind]
    for i, line in enumerate(text_lines):
        if _is_comment(line):
            continue
        m = rx.search(line)
        if not m:
            continue
        name = next((g for g in m.groups() if g), None)
        if not name or name in KEYWORDS_NOT_FUNCS:
            continue
        end = _span_py(text_lines, i) if kind == 'py' else _span_brace(text_lines, i)
        out.append({'name': name, 'start': i + 1, 'end': end + 1})
    return out


def branches_in(text_lines, start, end):
    n = 0
    for line in text_lines[start - 1:end]:
        if not _is_comment(line):
            n += len(BRANCH.findall(line))
    return n


TEST_PATH = re.compile(r'(^|/)(tests?|spec|__tests__)/|(^|/)test_[^/]*$|Test\.php$|[._]tests?\.\w+$|[._]spec\.\w+$')


def is_test_path(path):
    return bool(TEST_PATH.search(path))


def changed_ranges(repo, base, head, path):
    base, head = gitio.resolve_rev(repo, base), gitio.resolve_rev(repo, head)
    out = gitio.git(repo, 'diff', '-U0', '--no-color', base, head, '--', path).decode('utf-8', 'replace')
    ranges = []
    for line in out.split('\n'):
        m = HUNK.match(line)
        if m:
            a, n = int(m.group(1)), int(m.group(2)) if m.group(2) is not None else 1
            ranges.append((a, a + max(n, 1) - 1))
    return ranges


def changed_functions(repo, base, head, files):
    result = []
    for f in files[:MAX_FILES]:
        kind = EXT.get(os.path.splitext(f['path'])[1].lstrip('.').lower())
        if not kind or f['binary'] or f['status'] == 'D':
            continue
        raw = gitio.read_version(repo, head, f['path'])
        if raw is None or len(raw) > MAX_BYTES or gitio.is_binary(raw):
            continue
        text = gitio.decode(raw).split('\n')
        ranges = changed_ranges(repo, base, head, f['path'])
        for fn in find_functions(text, kind):
            if any(a <= fn['end'] and b >= fn['start'] for a, b in ranges):
                result.append({'file': f['path'], 'name': fn['name'], 'line': fn['start'],
                               'branches': branches_in(text, fn['start'], fn['end']),
                               'test': is_test_path(f['path'])})
    return result
