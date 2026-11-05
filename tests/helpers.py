"""測試共用：暫存 git repo、假檢查員、執行 referee.py。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_inspector.py")


def git(root, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "core.autocrlf=false"]
                       + list(args), cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise RuntimeError("git {} 失敗：{}".format(args, r.stdout.decode("utf-8", "replace")))
    return r.stdout.decode("utf-8")


def write(root, path, content):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    data = content.encode("utf-8") if isinstance(content, str) else content
    with open(full, "wb") as f:
        f.write(data)


def lines(n, prefix="line"):
    return "".join("{} {}\n".format(prefix, i) for i in range(1, n + 1))


def init_repo(files):
    """建一個 main 分支、有一個 commit 的暫存 repo，回傳路徑。呼叫端負責 rmtree。"""
    root = os.path.realpath(tempfile.mkdtemp(prefix="referee-test-"))
    git(root, "init", "-q", "-b", "main")
    for path, content in files.items():
        write(root, path, content)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def commit_all(root, message="change"):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def functions_sheet(functions, tools=None, settings=None):
    d = {"schema": "referee.functions/1", "tools": tools or {}, "functions": functions}
    if settings is not None:
        d["settings"] = settings
    return d


def mutants_sheet(mutants, tools=None, settings=None):
    d = {"schema": "referee.mutants/1", "tools": tools or {}, "mutants": mutants}
    if settings is not None:
        d["settings"] = settings
    return d


def fn(file, name, start, end, complexity, coverage):
    return {"file": file, "name": name, "start": start, "end": end, "complexity": complexity, "coverage": coverage}


def mu(file, line, status, mutator="CONDITIONALS_BOUNDARY", **extra):
    d = {"file": file, "line": line, "mutator": mutator, "status": status}
    d.update(extra)
    return d


def run_referee(root, args, env=None):
    e = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    e.update(env or {})
    r = subprocess.run([sys.executable, os.path.join(REPO, "referee.py")] + list(args), cwd=root, env=e,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout, r.stderr


def dump(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TempDirMixin:
    def make_tmp(self):
        d = os.path.realpath(tempfile.mkdtemp(prefix="referee-tmp-"))
        self.addCleanup(shutil.rmtree, d, True)
        return d
