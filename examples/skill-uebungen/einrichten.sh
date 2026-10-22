#!/usr/bin/env bash
# Richtet die Skill-Übungen als eigenes Git-Projekt ein.
#   ./einrichten.sh ~/lcc-uebungen
set -euo pipefail

ziel="${1:?Zielordner angeben, z. B. ~/lcc-uebungen}"
quelle="$(cd "$(dirname "$0")" && pwd)"
skills="$quelle/../skills"

if [ -e "$ziel" ]; then
  echo "$ziel existiert bereits – bitte anderen Ordner wählen oder vorher löschen." >&2
  exit 1
fi

mkdir -p "$ziel/.lcc/skills"
cp -r "$quelle"/. "$ziel"/
rm -f "$ziel/einrichten.sh"
for skill in "$skills"/*/; do
  cp -r "$skill" "$ziel/.lcc/skills/"
done

cd "$ziel"
git init -q
git add -A
git commit -q -m "Ausgangsstand der Skill-Übungen"

# Offene Änderungen für die Übung "commit-nachricht"
python3 - <<'PY'
from pathlib import Path

utils = Path("utils.py")
utils.write_text(utils.read_text(encoding="utf-8") + '''

def kuerzen(text: str, laenge: int = 40) -> str:
    """Kürzt Text für Listenansichten und hängt '…' an."""
    if len(text) <= laenge:
        return text
    return text[: laenge - 1].rstrip() + "…"
''', encoding="utf-8")

lager = Path("lager.py")
lager.write_text(
    lager.read_text(encoding="utf-8").replace("mindestbestand: int = 5", "mindestbestand: int = 10"),
    encoding="utf-8",
)
PY

echo "Fertig: $ziel"
echo "Aufgaben: $ziel/UEBUNGEN.md"
