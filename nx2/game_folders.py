"""Where each game's own folders go, so that one builder and one launcher entry can hold several games
(docs/one-engine.md, step 4) without moving the default game's.

One rule, kept the same in every place that picks a game's folder:

    the default game (game_profile.DEFAULT, Ocarina) keeps the folder it has always had: <base>
    any other game gets <base>-<key>

<base> is whatever the caller would have used for the default game: ~/Games/Hookshot for the game folder (the
launcher's start.args name it, nx2/make_game.py --prepare defaults to it), ~/.cache/hookshot-builder for the builder's
work folder. So Ocarina's game folder, its settings (hookshot_options.ini, in the game folder), its pipeline caches (in
the game folder) and its work folder stay exactly where they are, and a second game's sit beside them under its own
name. The saves follow the same idea on Linux through the profile's GAME_SAVES_DIR (nx2/game_profile.py saves_dir:
"hookshot", else "hookshot-<key>"); on Windows they are beside each game's executable, so in its own game folder.

The places that apply it:
  - nx2/make_game.py --prepare (RecompLauncher's step), when no --out is given: the dump decides the game
    (game_profile.for_build), and the folder is that game's;
  - Play with a game: `--play <folder> --game <key>` starts <folder> for the default game and <folder>-<key> for
    another (builder/linux/hookshot-launch, builder/setup/setup.c play_folder, builder/linux/hookshot_builder.py). The
    launcher entry's games[] adds `--game <key>` after start.args' `--play {home}/Games/Hookshot`, so a tile starts its
    own game's folder. (`--game` here is a profile key; nx2/make_game.py's own --game is still the copy's path, which
    RecompLauncher's prepare step passes: the two never meet, since Play is handled before make_game.py runs.)
  - recomplauncher.json games[] (launcher_games below), once more than one game is in the release.

    python -I nx2/game_folders.py --folder ~/Games/Hookshot --key mkw   # ~/Games/Hookshot-mkw
    python -I nx2/game_folders.py --launcher-games                     # the games[] the released profiles give
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_profile  # noqa: E402

KEY = re.compile(r"^[a-z0-9]{1,16}$")   # (RecompLauncher's games[].id pattern; a profile key is one too)


def suffix(key):
    """"" for the default game, "-<key>" for any other"""
    if not KEY.match(key or ""):
        raise ValueError("not a game key: %r" % (key,))
    return "" if key == game_profile.DEFAULT else "-" + key


def folder(base, key):
    """The game's own folder beside the default game's: base for the default game, base-<key> otherwise. A trailing
    separator on base is dropped first, so ~/Games/Hookshot/ and ~/Games/Hookshot give the same folder."""
    base = base.rstrip("/\\") or base
    return base + suffix(key)


def released():
    """The profiles a release builds: every profile that names a build (the empty one, NONE, builds nothing)"""
    return [p for p in game_profile.GAMES.values() if p.build_id]


def launcher_games(profiles=None, home="{home}/Games/Hookshot", local="{local}"):
    """recomplauncher.json's games[] for these profiles (default: released()), or None when there is only one game.

    RecompLauncher's schema wants two games or more in games[]; with one, the recomp shows as one game, which is
    Hookshot today. Each game's args add `--game <key>` after start.args (Play only: games[].args are not passed to
    prepare). Each game's saves are its own: on Linux the profile's GAME_SAVES_DIR under {local}, on Windows its game
    folder's user/. The default game's are the paths the entry's top-level saves have always named, so nothing moves.

    Not here, because the schema has no place for it yet: a per-game copy check. inputs[] items take no
    nup_build_id (only the top-level game.check does), and prepare is one step for the release. Until the launcher
    can check each game's input, the builder checks the copy itself (make_game.py check_supported_build), and a
    second game joining the release needs that settled first (docs/one-engine.md)."""
    profiles = released() if profiles is None else list(profiles)
    if len(profiles) < 2:
        return None
    games = []
    for p in profiles:
        games.append({
            "id": p.key,
            "name": p.game,
            "args": ["--game", p.key],
            "saves": ["%s/%s" % (local, game_profile.saves_dir(p)), "%s/user" % folder(home, p.key)],
        })
    return games


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folder", help="a base folder: the game's own folder for --key is printed")
    ap.add_argument("--key", help="a game profile key")
    ap.add_argument("--launcher-games", action="store_true", help="print the games[] the released profiles give")
    a = ap.parse_args(argv)
    if a.launcher_games:
        print(json.dumps(launcher_games(), indent=2))
        return 0
    if a.folder is None or not a.key:
        ap.error("--folder and --key, or --launcher-games")
    print(folder(os.path.expanduser(a.folder), a.key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
