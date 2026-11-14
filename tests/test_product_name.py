"""The release files are named by the project, and everything that makes, checks or finds them agrees on that name.

scripts/linux/appimage.sh names the AppImage <name>-<version>-x86_64.AppImage after nx2/game_profile.py PROJECT. In a
fork whose name is not Hookshot (Lakitu), scripts/linux/check_player_build.sh still looked for
build-linux/Hookshot-*-x86_64.AppImage, found nothing and failed CI's AppImage job ("no AppImage to check"); the release
scripts and .github/workflows/release.yml looked for Hookshot-<tag>-x86_64.AppImage the same way. They all read the
name from scripts/product_name.sh now. This checks that helper prints the profile's name (and HOOKSHOT_PRODUCT over
it), that check_player_build.sh finds an image named so and turns away one named otherwise, and that no script or
workflow names the AppImage with a literal Hookshot- again. Game-free.

    python -I -B tests/test_product_name.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import game_profile  # noqa: E402

RUN_ALL_SKIP = {"windows": "runs bash scripts: checked on Linux"}


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def product(**env):
    run = subprocess.run(["bash", str(ROOT / "scripts" / "product_name.sh")], capture_output=True, text=True,
                         cwd=tempfile.gettempdir(), env=dict(os.environ, **env), timeout=60)
    check(run.returncode == 0, "scripts/product_name.sh failed: " + run.stderr)
    return run.stdout.strip()


def main():
    name = game_profile.PROJECT
    check(name, "nx2/game_profile.py has no PROJECT")
    env = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_PRODUCT"}
    os.environ.clear()
    os.environ.update(env)
    check(product() == name, "scripts/product_name.sh does not print the profile's PROJECT (%r)" % name)
    check(product(HOOKSHOT_PRODUCT="Other") == "Other", "HOOKSHOT_PRODUCT does not override the name")

    # check_player_build.sh finds the image appimage.sh made, by that name, in a checkout of its own
    with tempfile.TemporaryDirectory(prefix="product-name-") as tmp:
        tree = Path(tmp)
        for rel in ("scripts/product_name.sh", "scripts/linux/check_player_build.sh", "nx2/game_profile.py"):
            (tree / rel).parent.mkdir(parents=True, exist_ok=True)
            (tree / rel).write_bytes((ROOT / rel).read_bytes())
            (tree / rel).chmod(0o755)
        (tree / "build-linux").mkdir()
        other = tree / "build-linux" / ("NotThis-v0-x86_64.AppImage" if name != "NotThis" else "Else-v0-x86_64.AppImage")
        other.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        run = subprocess.run(["bash", str(tree / "scripts/linux/check_player_build.sh")], capture_output=True,
                             text=True, timeout=60)
        check(run.returncode != 0 and "no AppImage to check" in run.stdout,
              "check_player_build.sh took an image of another name: " + run.stdout + run.stderr)
        mine = tree / "build-linux" / ("%s-v0-x86_64.AppImage" % name)
        # (a stand-in that fails its extraction: what matters is that the script got as far as running it)
        mine.write_text("#!/bin/sh\necho extracted-by-name >&2\nexit 3\n", encoding="utf-8")
        mine.chmod(0o755)
        run = subprocess.run(["bash", str(tree / "scripts/linux/check_player_build.sh")], capture_output=True,
                             text=True, timeout=60)
        check("no AppImage to check" not in run.stdout and "extracted-by-name" in run.stderr,
              "check_player_build.sh did not find build-linux/%s-*-x86_64.AppImage: %s" % (name, run.stdout + run.stderr))

    # no script or workflow names the AppImage with a literal project name of its own
    literal = re.compile(r"Hookshot-[^\s\"'`]*x86_64\.AppImage")
    places = [ROOT / ".github" / "workflows" / f for f in os.listdir(ROOT / ".github" / "workflows")]
    places += [p for p in (ROOT / "scripts").rglob("*.sh")]
    found = []
    for p in places:
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if literal.search(line) and not line.lstrip().startswith("#"):
                found.append("%s:%d" % (p.relative_to(ROOT), n))
    check(not found, "the AppImage is named with a literal Hookshot- instead of scripts/product_name.sh: %s" % found)
    check("product_name.sh" in (ROOT / "scripts/linux/appimage.sh").read_text(encoding="utf-8"),
          "scripts/linux/appimage.sh does not take the AppImage's name from scripts/product_name.sh")
    print("product name: %s; the AppImage's makers, checks and release scripts agree on it" % name)


if __name__ == "__main__":
    main()
