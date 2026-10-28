#!/usr/bin/env bash
# Läuft in der stündlichen Claude-Aufgabe, handelt selbst nie.
#   ./app_abgleich.sh einstellungen DATEI  legt die App-Einstellungen in den Branch bot-einstellungen
#   ./app_abgleich.sh daten [MINUTEN]      kopiert alle 2 Minuten Log und Status aus bot-daten in den Projektordner
cd "$(dirname "$0")"
ZIEL=/mnt/project-files/market-bot

if [ "$1" = "einstellungen" ]; then
  git fetch -q origin bot-einstellungen 2>/dev/null
  if git show origin/bot-einstellungen:einstellungen.json 2>/dev/null | cmp -s - "$2"; then
    echo "Einstellungen unverändert"; exit 0
  fi
  export GIT_INDEX_FILE="$(mktemp -u)"
  git update-index --add --cacheinfo "100644,$(git hash-object -w "$2"),einstellungen.json"
  commit=$(git -c user.name=Bot-Cockpit -c user.email=bot@users.noreply.github.com \
    commit-tree "$(git write-tree)" -m "Einstellungen aus der Handy-App")
  rm -f "$GIT_INDEX_FILE"
  git push -q -f origin "$commit:refs/heads/bot-einstellungen" && echo "Einstellungen gesendet"
  exit
fi

ende=$(( $(date +%s) + ${2:-57} * 60 ))
while :; do
  if git fetch -q origin bot-daten 2>/dev/null; then
    for f in status.json handelslog.md hoechststand.json; do
      git show "origin/bot-daten:$f" > "$ZIEL/.$f.neu" 2>/dev/null && mv "$ZIEL/.$f.neu" "$ZIEL/$f"
      rm -f "$ZIEL/.$f.neu"
    done
  fi
  [ $(( $(date +%s) + 120 )) -gt "$ende" ] && break
  sleep 120
done
echo "Abgleich fertig"
