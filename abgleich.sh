#!/usr/bin/env bash
# Abgleich für den GitHub-Ablauf: holt die App-Einstellungen (Branch bot-einstellungen)
# und legt Log, status.json und hoechststand.json als einen einzigen Commit in den Branch bot-daten.
cd "$(dirname "$0")"
D="${BOT_ORDNER:-daten}"
mkdir -p "$D"
if git fetch -q origin bot-einstellungen 2>/dev/null; then
  git show origin/bot-einstellungen:einstellungen.json > "$D/einstellungen.json.neu" 2>/dev/null \
    && mv "$D/einstellungen.json.neu" "$D/einstellungen.json"
  rm -f "$D/einstellungen.json.neu"
fi
[ "$1" = "nur-holen" ] && exit 0
export GIT_INDEX_FILE="${RUNNER_TEMP:-/tmp}/bot-daten-index"
rm -f "$GIT_INDEX_FILE"
for f in status.json handelslog.md hoechststand.json; do
  [ -f "$D/$f" ] && git update-index --add --cacheinfo "100644,$(git hash-object -w "$D/$f"),$f"
done
baum=$(git write-tree)
commit=$(GIT_AUTHOR_NAME=Demo-Bot GIT_AUTHOR_EMAIL=bot@users.noreply.github.com \
  GIT_COMMITTER_NAME=Demo-Bot GIT_COMMITTER_EMAIL=bot@users.noreply.github.com \
  git commit-tree "$baum" -m "Bot-Daten $(date -u +%FT%TZ)")
# Immer nur ein Commit, damit der Verlauf nicht wächst
git push -q -f origin "$commit:refs/heads/bot-daten" || echo "Push von bot-daten fehlgeschlagen"
