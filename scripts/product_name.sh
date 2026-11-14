#!/bin/bash
# The project's name, which names the release files (<name>-<version>-x86_64.AppImage and its .zsync): printed from the one
# place that holds it, PROJECT in nx2/game_profile.py, so a fork's rename is one line there and every script that makes,
# checks or finds those files agrees (scripts/linux/appimage.sh, scripts/linux/check_player_build.sh, the release scripts,
# .github/workflows/release.yml). HOOKSHOT_PRODUCT=<name> overrides it. No game data is involved.
set -euo pipefail
if [[ -n ${HOOKSHOT_PRODUCT:-} ]]; then
    printf '%s\n' "$HOOKSHOT_PRODUCT"
    exit 0
fi
PY=${PYTHON:-python3}
command -v "$PY" >/dev/null || PY=python
"$PY" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import game_profile; print(game_profile.PROJECT)' \
    "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/nx2"
