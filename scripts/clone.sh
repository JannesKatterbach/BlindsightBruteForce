#!/bin/sh
# Holt Project Blindsight frisch von GitHub in den nächsten Versionsordner und startet es.
#
# Liegen V1 und V2 im Basisordner, entsteht V3/BlindsightBruteForce mit dem Repository darin.
# Läuft mit jeder POSIX Shell (sh, dash, bash, ash, zsh), also auf jedem gängigen Linux, auch wenn
# fish die Standardshell ist. Braucht git und Python 3.10 oder neuer.
#
# Aufruf
#   sh clone.sh                     Basisordner wie unten beschrieben, klonen und starten
#   sh clone.sh ~/Projekte          anderer Basisordner
#   sh clone.sh --no-start          nur klonen
#   sh clone.sh --branch main       anderer Branch
#   sh clone.sh --help              diese Hilfe
#
# Basisordner ohne Angabe
#   Liegt das Skript in einem geklonten Repository (V3/BlindsightBruteForce/scripts/clone.sh), ist es der
#   Ordner, der V3 enthält. Sonst ist es der Ordner, in dem das Skript liegt.
set -eu

REPO_URL="https://github.com/JannesKatterbach/BlindsightBruteForce.git"
BRANCH="claude/great-johnson-5glkh8"   # leer heißt Standard Branch des Repositorys
REPO_DIR="BlindsightBruteForce"
START_APP=1
FIRST_PORT=8765
BASE=""

say() { printf '%s\n' "$*"; }
fail() { printf 'Fehler. %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

# -- Argumente ------------------------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage ;;
        --no-start) START_APP=0 ;;
        --branch)
            [ $# -ge 2 ] || fail "--branch braucht einen Namen"
            BRANCH="$2"; shift ;;
        --branch=*) BRANCH="${1#--branch=}" ;;
        --dir)
            [ $# -ge 2 ] || fail "--dir braucht einen Ordner"
            BASE="$2"; shift ;;
        --dir=*) BASE="${1#--dir=}" ;;
        -*) fail "unbekannte Option $1 (Hilfe mit --help)" ;;
        *) BASE="$1" ;;
    esac
    shift
done

# -- Werkzeuge prüfen -----------------------------------------------------------------------------------
install_hint() {
    if command -v apt-get >/dev/null 2>&1; then say "  sudo apt-get install $1"
    elif command -v dnf >/dev/null 2>&1; then say "  sudo dnf install $1"
    elif command -v pacman >/dev/null 2>&1; then say "  sudo pacman -S $1"
    elif command -v zypper >/dev/null 2>&1; then say "  sudo zypper install $1"
    elif command -v apk >/dev/null 2>&1; then say "  sudo apk add $1"
    else say "  über die Paketverwaltung deines Systems installieren ($1)"
    fi
}

command -v git >/dev/null 2>&1 || { say "git fehlt. Installieren mit"; install_hint git; exit 1; }

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ] && [ "$START_APP" = 1 ]; then
    say "Python 3.10 oder neuer fehlt, zum Klonen reicht es trotzdem. Installieren mit"
    install_hint python3
    say "Ich klone jetzt nur und starte nicht."
    START_APP=0
fi

# -- Basisordner ----------------------------------------------------------------------------------------
script_dir=$(cd "$(dirname "$0")" 2>/dev/null && pwd -P) || script_dir=""
if [ -z "$BASE" ]; then
    if [ -n "$script_dir" ] && [ "$(basename "$script_dir")" = scripts ] && [ -d "$script_dir/../.git" ]; then
        repo_root=$(cd "$script_dir/.." && pwd -P)
        version_dir=$(dirname "$repo_root")
        case "$(basename "$version_dir")" in
            V[0-9]*) BASE=$(dirname "$version_dir") ;;
            *) BASE=$version_dir ;;
        esac
    elif [ -n "$script_dir" ] && [ -f "$script_dir/$(basename "$0")" ]; then
        BASE=$script_dir
    else
        BASE=$(pwd -P)  # zum Beispiel über eine Pipe gestartet
    fi
fi
[ -d "$BASE" ] || fail "Basisordner $BASE gibt es nicht"
BASE=$(cd "$BASE" && pwd -P)

# -- Nächste Versionsnummer -----------------------------------------------------------------------------
last=0
for dir in "$BASE"/V*; do
    [ -d "$dir" ] || continue
    num=${dir##*/V}
    case "$num" in ''|*[!0-9]*) continue ;; esac
    num=$(printf '%s' "$num" | sed 's/^0*//')
    [ -n "$num" ] || num=0
    [ "$num" -gt "$last" ] && last=$num
done
next=$((last + 1))
target="$BASE/V$next"

# -- Klonen ---------------------------------------------------------------------------------------------
say "Lege $target an und klone das Repository"
mkdir "$target" || fail "$target lässt sich nicht anlegen"
if [ -n "$BRANCH" ]; then
    set -- clone --branch "$BRANCH" "$REPO_URL" "$target/$REPO_DIR"
else
    set -- clone "$REPO_URL" "$target/$REPO_DIR"
fi
if ! git "$@"; then
    rmdir "$target" 2>/dev/null || true
    fail "Klonen fehlgeschlagen, V$next wurde wieder entfernt"
fi
say ""
say "Neue Version in $target/$REPO_DIR"

if [ "$START_APP" != 1 ]; then
    say "Starten mit  cd \"$target/$REPO_DIR\" && python3 run.py"
    exit 0
fi

# -- Starten --------------------------------------------------------------------------------------------
# Läuft noch eine alte Version auf dem Port, nimmt die neue den nächsten freien. Sonst zeigte der Browser
# die alte Version
port=$("$PYTHON" - "$FIRST_PORT" <<'EOF'
import socket, sys
port = int(sys.argv[1])
while port < 65535:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            break
        except OSError:
            port += 1
print(port)
EOF
)
[ "$port" = "$FIRST_PORT" ] || say "Port $FIRST_PORT ist belegt (läuft noch eine alte Version?), nehme $port"

# Ohne grafische Oberfläche (Server, SSH) keinen Browser öffnen, sonst startet eventuell ein Textbrowser
set -- --port "$port"
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    set -- "$@" --no-browser
    say "Keine grafische Oberfläche gefunden. Im Browser öffnen  http://127.0.0.1:$port"
fi

cd "$target/$REPO_DIR"
say "Starte Blindsight V$next (beenden mit Strg+C)"
exec "$PYTHON" run.py "$@"
