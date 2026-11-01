# Source

- Upstream. https://github.com/nicohodt/claude-code-ui-ux-skill (`.claude/skills/ui-ux-pro-max/`)
- Commit. 29dc4c56aa862226a6ff053ff4255bbed062af81
- License. MIT, see `LICENSE` (Copyright (c) 2026 Nicolay Hodt)
- Local changes
  - `SKILL.md`. The script path `${CLAUDE_PLUGIN_ROOT}/.claude/skills/ui-ux-pro-max/scripts/search.py` (plugin install) is
    replaced by `.claude/skills/ui-ux-pro-max/scripts/search.py`, run from the repository root (project skill)
  - Left out. `scripts/tests/` and `scripts/validate_data.py` (development of the skill only)
- The scripts use only the Python standard library, read the CSV files in `data/` and write files only with `--persist`
