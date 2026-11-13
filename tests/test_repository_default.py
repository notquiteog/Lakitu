"""Every place that names the repository releases come from names the same one, and none names NotRexed/Hookshot.

The release, update and setup code fall back to a built-in owner/name when no repository.txt was packaged (a source
build, an old package): nx2/version.py DEFAULT_REPOSITORY, the Windows Builder's Repository.cs, the setup's
HOOKSHOT_REPOSITORY, the Python builder's REPO, the Linux updater's fallback, the AppImage's defaults and the
launcher entry (recomplauncher.json). NotRexed/Hookshot, the upstream they all named, was deleted (2026-11), so every
update check, setup download and launcher install from that fallback failed. This holds them to one name, the one in
nx2/version.py, and holds the code (not the history in the docs, which cites upstream's own pull requests) to no
NotRexed/Hookshot link except an issue link (issues are a separate question: they are off on the new repository).
Game-free.

    python -I -B tests/test_repository_default.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import version  # noqa: E402


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def main():
    name = version.DEFAULT_REPOSITORY
    check(re.fullmatch(r"[\w.-]+/[\w.-]+", name or ""), "nx2/version.py DEFAULT_REPOSITORY is not owner/name: %r" % name)
    check(name != "NotRexed/Hookshot", "nx2/version.py still falls back to the deleted NotRexed/Hookshot")
    places = {
        "builder/HookshotBuilder/Repository.cs": r'const string Default = "([^"]+)";',
        "builder/setup/setup.c": r'#define HOOKSHOT_REPOSITORY "([^"]+)"',
        "builder/py/hookshot_builder/__init__.py": r'^REPO = "([^"]+)"',
        "builder/linux/linux_update.py": r'    return "([\w.-]+/[\w.-]+)"\n',
        "scripts/hardware_report.py": r'^REPO = "([^"]+)"',
        "scripts/test_requests.py": r'^REPO = "https://github\.com/([^"]+)"',
        "scripts/make_setup_parts.py": r'"https://github\.com/([\w.-]+/[\w.-]+)/releases/download/builder-parts"',
        "scripts/linux/make_parts.py": r'"https://github\.com/([\w.-]+/[\w.-]+)/releases/download/linux-parts"',
    }
    for rel, pattern in places.items():
        found = re.findall(pattern, read(rel), re.M)
        check(found, "%s: the repository it falls back to was not found (%s)" % (rel, pattern))
        check(set(found) == {name}, "%s falls back to %s, not %s" % (rel, sorted(set(found)), name))
    appimage = re.findall(r"\$\{GITHUB_REPOSITORY:-([^}]+)\}", read("scripts/linux/appimage.sh"))
    check(appimage and set(appimage) == {name}, "scripts/linux/appimage.sh's defaults are %s, not %s" % (appimage, name))
    launcher = json.loads(read("recomplauncher.json"))
    check(launcher.get("repo") == name, "recomplauncher.json's repo is %r, not %s" % (launcher.get("repo"), name))

    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    stale = []
    for rel in files:
        if rel == "tests/test_repository_default.py":   # (this file names it, to look for it)
            continue
        if rel.startswith("third_party/") or rel.endswith((".md", ".txt", ".png", ".bin", ".xz", ".ico", ".ttf", ".otf")):
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if re.search(r"NotRexed/Hookshot(?!/issues)", line):
                stale.append("%s:%d" % (rel, n))
    check(not stale, "code still names the deleted NotRexed/Hookshot: %s" % stale[:10])
    print("repository: %s everywhere a release, an update or the launcher falls back to it" % name)


if __name__ == "__main__":
    main()
