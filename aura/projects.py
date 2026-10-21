"""Code projects: find a project folder by a spoken name ("moodline", "the jarvis one") and open it in VS Code."""
import difflib
import re
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
# Where people keep projects. Each root's sub-folders are candidates (two levels deep, for "Documents/GIT CLONES/x").
ROOTS = ["Documents", "Desktop", "Projects", "projects", "dev", "Dev", "code", "Code", "src", "repos", "git",
         "workspace", "Developer", "."]
MARKERS = [".git", "pyproject.toml", "package.json", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml",
           "Makefile", ".vscode", "main.py", "index.html", "CMakeLists.txt"]
_SKIP = {"node_modules", "venv", ".venv", "__pycache__", "site-packages", "build", "dist", "Data"}
EDITORS = ["code", "code-oss", "codium", "cursor"]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _is_project(path: Path) -> bool:
    return any((path / m).exists() for m in MARKERS)


def candidates() -> list[Path]:
    seen, out = set(), []

    def visit(folder: Path, depth: int):
        try:
            children = sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")
                              and p.name not in _SKIP)
        except OSError:
            return
        for child in children:
            if child.resolve() in seen:
                continue
            seen.add(child.resolve())
            if _is_project(child):
                out.append(child)
            elif depth > 1:  # a plain folder of projects ("GIT CLONES"): look one level in
                visit(child, depth - 1)

    for root in ROOTS:
        folder = HOME / root
        if folder.is_dir():
            visit(folder, 1 if root == "." else 2)
    return out


def find(name: str, limit: int = 5) -> list[Path]:
    """Best matches for a spoken project name, best first."""
    want = _norm(name)
    if not want:
        return []
    scored = []
    for path in candidates():
        have = _norm(path.name)
        score = difflib.SequenceMatcher(None, want, have).ratio()
        if want in have or have in want:
            score = max(score, 0.75 + 0.25 * min(len(want), len(have)) / max(len(want), len(have)))
        if score >= 0.6:
            scored.append((score, path))
    return [p for _, p in sorted(scored, key=lambda s: -s[0])[:limit]]


def editor() -> str | None:
    return next((e for e in EDITORS if shutil.which(e)), None)


def open_in_editor(path: Path) -> str:
    exe = editor()
    if not exe:
        raise ValueError("VS Code isn't installed (no `code` command found).")
    subprocess.Popen([exe, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return exe
