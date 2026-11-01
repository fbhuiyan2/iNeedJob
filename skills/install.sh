#!/usr/bin/env bash
# Install the resume-engine slash commands so they work from ANY directory,
# in whichever agent harnesses are present on this machine.
#
#   bash skills/install.sh                  detected harnesses
#   bash skills/install.sh --harness claude,opencode
#   bash skills/install.sh --all            every harness below, creating dirs
#   bash skills/install.sh --list           what is detected and installed
#   bash skills/install.sh --uninstall      remove only what this script put there
#
# Idempotent. Re-run after pulling to pick up playbook changes, and after
# moving or re-cloning the repo (the engine path is baked into each copy).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$(cd "$HERE/.." && pwd)"   # HERE is skills/, so ENGINE is the repo root

SKILLS=(ijob-tailor ijob-profile ijob-setup ijob-scrape ijob-shortlist)
MARKER=".installed-by-resume-tailor-agent"   # ownership marker, see the backup check

# Harnesses and the directory each one scans for skills, relative to $HOME.
# A harness not listed here can still use the playbooks: they are plain
# Markdown and self-contained, so pointing any agent at skills/<name>/SKILL.md
# works without installing anything. See AGENTS.md.
HARNESS_DIRS="
claude      .claude/skills
opencode    .config/opencode/skills
codex       .codex/skills
agents      .agents/skills
cursor      .cursor/skills
gemini      .gemini/skills
copilot     .copilot/skills
amp         .config/agents/skills
kiro        .kiro/skills
factory     .factory/skills
"
# OpenCode auto-loads ~/.claude/skills as "external skills" unless
# disableClaudeCodeSkills or disableExternalSkills is set (verified in
# opencode 1.18.29). Installing into both roots makes it log "duplicate skill
# name" and shadow one copy, so ~/.claude/skills wins and the opencode root is
# skipped whenever it exists.
SKIP_IF_CLAUDE="opencode"
OPENCODE_CMD="$HOME/.config/opencode/command"

mode=install
selection=
force_all=0
while [ $# -gt 0 ]; do
  case "$1" in
    --harness) selection="${2//,/ }"; shift 2 ;;
    --harness=*) selection="${1#*=}"; selection="${selection//,/ }"; shift ;;
    --all) force_all=1; shift ;;
    --list) mode=list; shift ;;
    --uninstall) mode=uninstall; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

dir_for() { awk -v k="$1" '$1==k {print $2}' <<<"$HARNESS_DIRS"; }

targets=()
if [ -n "$selection" ]; then
  for key in $selection; do
    rel="$(dir_for "$key")"
    [ -n "$rel" ] || { echo "unknown harness: $key" >&2; exit 2; }
    targets+=("$key:$HOME/$rel")
  done
else
  while read -r key rel; do
    [ -n "${key:-}" ] || continue
    if [ "$force_all" -eq 1 ]; then
      targets+=("$key:$HOME/$rel")
    elif [ -d "$HOME/$rel" ] || [ -d "$HOME/$(dirname "$rel")" ]; then
      # The parent counts: ~/.claude exists long before ~/.claude/skills does.
      targets+=("$key:$HOME/$rel")
    fi
  done <<<"$HARNESS_DIRS"
fi

if [ "$mode" = list ]; then
  printf '%-10s %-28s %s\n' HARNESS DIRECTORY STATE
  while read -r key rel; do
    [ -n "${key:-}" ] || continue
    state="-"
    [ -d "$HOME/$rel" ] && state=present
    [ -f "$HOME/$rel/ijob-tailor/$MARKER" ] && state=installed
    printf '%-10s %-28s %s\n' "$key" "~/$rel" "$state"
  done <<<"$HARNESS_DIRS"
  exit 0
fi

if [ ${#targets[@]} -eq 0 ]; then
  echo "No agent harness directory found under $HOME." >&2
  echo "Name one explicitly:  bash skills/install.sh --harness claude" >&2
  echo "Or read the playbooks straight from the clone - see AGENTS.md." >&2
  exit 1
fi

# Pre-flight: verify every source exists BEFORE touching anything installed,
# so a missing source cannot leave a skill deleted and not replaced.
for s in "${SKILLS[@]}"; do
  [ -f "$HERE/$s/SKILL.md" ] || { echo "ERROR: missing $HERE/$s/SKILL.md - aborting, nothing changed" >&2; exit 1; }
done

# Whether ~/.claude/skills is in play, which decides if the opencode root is
# skipped. On disk counts as well as in this run: `--harness claude` followed
# later by `--harness opencode` would otherwise install the second copy the
# skip exists to prevent.
claude_present=0
[ -d "$HOME/.claude/skills" ] && claude_present=1
for entry in "${targets[@]}"; do
  [ "${entry%%:*}" = claude ] && claude_present=1
done

for entry in "${targets[@]}"; do
  key="${entry%%:*}"
  dir="${entry#*:}"

  if [ "$claude_present" -eq 1 ] && [[ " $SKIP_IF_CLAUDE " == *" $key "* ]] && [ "$mode" = install ]; then
    echo "Skipping $key - it reads ~/.claude/skills, and a second copy would shadow the first"
    continue
  fi

  if [ "$mode" = uninstall ]; then
    for s in "${SKILLS[@]}"; do
      if [ -f "$dir/$s/$MARKER" ]; then rm -rf "${dir:?}/$s"; echo "  removed $key:/$s"; fi
    done
    continue
  fi

  echo "Installing skills -> $dir"
  mkdir -p "$dir"
  for s in "${SKILLS[@]}"; do
    target="$dir/$s"
    staging="$dir/.$s.new.$$"

    # These are generic names. If a skill of the same name exists and was not
    # installed by us, back it up rather than silently destroying it.
    if [ -d "$target" ] && [ ! -f "$target/$MARKER" ]; then
      backup="$target.bak.$(date +%Y%m%d%H%M%S)"
      echo "  NOTE: existing $s/ is not ours - backing up to $(basename "$backup")"
      mv "$target" "$backup"
    fi

    rm -rf "$staging"
    cp -r "$HERE/$s" "$staging"

    # Bake the engine's absolute path in so the skills need no env vars.
    # Done in Python, not sed: an engine path containing | & or \ silently
    # corrupts a sed substitution, and BSD/macOS sed -i needs a suffix arg.
    # Only the assignment is rewritten. A blanket replace also hit the prose
    # that tells a reader what to do when the token is still there, turning
    # "if it still reads __ENGINE_PATH__" into "if it still reads /home/..."
    # in every installed copy, which is the one place that advice is needed.
    python3 - "$staging/SKILL.md" "$ENGINE" <<'SUBST'
import sys, pathlib
f = pathlib.Path(sys.argv[1])
f.write_text(f.read_text().replace('ENGINE="__ENGINE_PATH__"',
                                   'ENGINE="%s"' % sys.argv[2]))
SUBST

    printf '%s\n' "$ENGINE" > "$staging/$MARKER"

    rm -rf "$target"
    mv "$staging" "$target"
    echo "  /$s"
  done
done

if [ -d "$HOME/.config/opencode" ] && [ "$mode" = install ]; then
  echo "Installing OpenCode command shims -> $OPENCODE_CMD"
  mkdir -p "$OPENCODE_CMD"
  shim() {
    cat > "$OPENCODE_CMD/$1.md" <<SHIM
---
description: $2
---
Invoke the \`$1\` skill and follow it exactly. Arguments: \$ARGUMENTS
SHIM
    echo "  /$1"
  }
  shim ijob-tailor "Tailor a resume + cover letter to a job description (resume-tailor-agent)"
  shim ijob-profile "Build or update profile.json"
  shim ijob-setup "Bootstrap the resume-tailor-agent binaries (open-ATS scorer + Tectonic)"
  shim ijob-scrape "Find job postings, rank them against your profile, hand them to /ijob-tailor"
  shim ijob-shortlist "Narrow and rank the postings already collected (no fetching, no quota)"
elif [ "$mode" = uninstall ]; then
  for s in "${SKILLS[@]}"; do rm -f "$OPENCODE_CMD/$s.md"; done
fi

[ "$mode" = uninstall ] && { echo; echo "Uninstalled."; exit 0; }

echo
echo "Engine path baked in: $ENGINE"
echo "Re-run this script if you move or re-clone the repo."
echo
echo "Next:"
echo "  /ijob-setup     fetch the binaries (gitignored, per-machine)"
echo "  /ijob-profile   build profile.json"
echo "  /ijob-tailor    tailor to a job description"
echo "  /ijob-scrape    find postings worth applying to (needs python3)"
echo "  /ijob-shortlist narrow what you already have (free)"
