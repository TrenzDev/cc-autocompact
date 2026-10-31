#!/usr/bin/env bash
# Installs cc-autocompact from this folder into your Claude Code folder (~/.claude). macOS and Linux.
#
# The one-line install is the plugin marketplace (see the README). This script is the other way:
# from a clone, without a marketplace. It copies the plugin to ~/.claude/mods/cc-autocompact and
# PRINTS the one line you need in ~/.claude/settings.json. It does not touch settings.json unless
# you pass --apply-settings, and then it saves a backup first (merging needs python3).
#
# It never deletes anything: a previous copy of the plugin is moved to
# ~/.claude/backups/cc-autocompact-<date>/ first. It writes no config.json: the plugin runs on its
# defaults, and your own config.json (in ~/.claude/cc-autocompact/) is never touched.
#
#   ./install.sh                     copy the plugin, print the settings line
#   ./install.sh --apply-settings    also add it to settings.json (after a backup)
#   ./install.sh --claude-dir DIR    another Claude Code folder (default: $CLAUDE_CONFIG_DIR or ~/.claude)
set -euo pipefail

apply=0
claude_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
while [ $# -gt 0 ]; do
  case "$1" in
    --apply-settings) apply=1 ;;
    --claude-dir) shift; claude_dir="${1:?--claude-dir needs a folder}" ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$repo/plugin"
dest="$claude_dir/mods/cc-autocompact"
settings="$claude_dir/settings.json"
stamp="$(date +%Y%m%d-%H%M%S)"
# CLAUDE_CODE_PLUGIN_DIRS uses the platform's path-list separator
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) sep=';' ;; *) sep=':' ;; esac

step() { printf '\n> %s\n' "$1"; }

for p in .claude-plugin/plugin.json hooks/hooks.json hooks/register.ts skills/wrap-up/SKILL.md; do
  [ -f "$src/$p" ] || { echo "Missing plugin/$p: run install.sh from the repository folder." >&2; exit 1; }
done
mkdir -p "$claude_dir"

step 'Plugin cc-autocompact'
if [ -e "$dest" ]; then
  mkdir -p "$claude_dir/backups"
  mv "$dest" "$claude_dir/backups/cc-autocompact-$stamp"
  echo "  Previous copy moved to $claude_dir/backups/cc-autocompact-$stamp"
fi
mkdir -p "$dest"
( cd "$src" && find . -type f ! -name '*.test.ts' ! -path './.claude-plugin/types/*' -print ) | while IFS= read -r f; do
  mkdir -p "$dest/$(dirname "$f")"
  cp "$src/$f" "$dest/$f"
done
echo "  Copied to $dest"
echo "  No config.json needed: it runs on its defaults. To change one, see config.example.json and the README."

if [ "$apply" -eq 0 ]; then
  step "Add this to $settings"
  echo "Merge it with what you have. If CLAUDE_CODE_PLUGIN_DIRS already exists, add this folder at the end, after a \"$sep\"."
  echo
  printf '{\n  "env": {\n    "CLAUDE_CODE_PLUGIN_DIRS": "%s"\n  }\n}\n' "$dest"
  echo
  echo 'Or run this script again with --apply-settings and it will add it for you (after a backup).'
else
  step "Updating $settings"
  command -v python3 >/dev/null 2>&1 || { echo '  python3 not found: add the line above by hand.' >&2; exit 1; }
  if [ -f "$settings" ]; then
    cp "$settings" "$settings.bak-$stamp"
    echo "  Backup: $settings.bak-$stamp"
  fi
  python3 - "$settings" "$dest" "$sep" <<'PY'
import json, os, sys
path, dest, sep = sys.argv[1], sys.argv[2], sys.argv[3]
data = {}
if os.path.exists(path):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    data = json.loads(text) if text.strip() else {}
env = data.setdefault("env", {})
current = (env.get("CLAUDE_CODE_PLUGIN_DIRS") or "").strip()
parts = [p.strip().rstrip("/\\") for p in current.split(sep) if p.strip()]
if not current:
    env["CLAUDE_CODE_PLUGIN_DIRS"] = dest
    print("  Added CLAUDE_CODE_PLUGIN_DIRS")
elif dest.rstrip("/\\") in parts:
    print("  CLAUDE_CODE_PLUGIN_DIRS already has the plugin: nothing to add")
else:
    env["CLAUDE_CODE_PLUGIN_DIRS"] = current + sep + dest
    print("  Added the plugin folder to CLAUDE_CODE_PLUGIN_DIRS (the folders already there stay)")
with open(path, "w", encoding="utf-8", newline="\n") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("  settings.json updated.")
PY
fi

step 'Next steps'
echo '  1. Add the "Closing tasks" rule to your CLAUDE.md (README, step 2).'
echo '  2. Start a new Claude Code session (or restart the desktop app).'
echo '  3. Type "/" and check that /compact-now is there.'
