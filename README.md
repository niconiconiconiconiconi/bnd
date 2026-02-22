# BnD — Beads and Dragons

BnD is a Python CLI tool that gamifies your software development work by layering an XP, leveling, skill, and achievement system on top of [beads (`bd`)](https://github.com/steveyegge/beads), a git-backed graph issue tracker. Every time you close tasks in a beads project, BnD awards XP, levels up your skills, tracks streaks, unlocks achievements, and writes a rich progress journal to your Obsidian vault — turning your task backlog into an RPG character sheet.

## Realms

A **realm** maps one-to-one with a beads project directory. The realm name is the directory's basename (e.g., `/home/user/projects/my-app` → realm `my-app`). Realm XP and character level are tracked independently per project, so your frontend app and your CLI tool each have their own progression. Skills, achievements, and the Shard currency are **shared globally** across all realms — closing a "fix" task in any project advances your global `debug` skill.

| What             | Scope      |
|-----------------|------------|
| XP & Level      | Per realm  |
| Skills          | Global     |
| Achievements    | Global     |
| Shards          | Global     |
| Streak          | Global     |

---

## Dependencies

- **Python 3.8+**
- **`pyyaml`** — `pip install pyyaml`
- **`bd`** (beads CLI) — must be installed and on your `$PATH`. See https://github.com/steveyegge/beads

---

## Setup

1. **Clone or copy** `bnd.py` and `bnd.config.yaml` somewhere on your system (e.g., `~/tools/bnd/`).

2. **Edit `bnd.config.yaml`** and set your vault path:
   ```yaml
   obsidian:
     vault_path: "~/Documents/Obsidian/BnD"
   ```

3. **Make executable** (optional):
   ```bash
   chmod +x bnd.py
   ```

4. **Run from a beads project directory:**
   ```bash
   cd ~/projects/my-app
   python ~/tools/bnd/bnd.py
   ```

5. **Optional: alias** in your shell config:
   ```bash
   alias bnd="python ~/tools/bnd/bnd.py"
   ```

The vault directory and all subdirectories are created automatically on first run. The `shop.md` reward file is written once and never overwritten so you can customize it freely.

---

## CLI Usage

| Command | Description |
|---------|-------------|
| `python bnd.py` | Process new closed tasks in current directory's realm, update Obsidian |
| `python bnd.py --status` | Print global character sheet to terminal |
| `python bnd.py --status --realm <name>` | Print single realm detail view |
| `python bnd.py --reset` | Wipe vault state + cache for current realm (with confirmation) |
| `python bnd.py --reset --global` | Wipe ALL vault state + cache files (with confirmation) |
| `python bnd.py --config <path>` | Use alternate config file |

All output lines are prefixed with `[bnd]`.

---

## XP Table

| Priority | Base XP |
|----------|---------|
| P0       | 100     |
| P1       | 50      |
| P2       | 25      |
| P3       | 10      |
| Default  | 10      |

| Modifier | Effect |
|----------|--------|
| Subtask (ID contains `.`) | `base_xp × 0.25` |
| Same-day close | `base_xp × 1.25` |
| Unblocked 2+ tasks | `base_xp × 1.50` |
| Epic close bonus | `+200 XP flat` |

XP is added to both the **current realm's** total and the **global skill** matched to the task.

---

## Skill Keywords

Skills are auto-tagged by matching the task title + description against these regex patterns (first match wins, in this order):

| Skill  | Keywords |
|--------|----------|
| debug  | fix, bug, error, crash, broken, patch, resolve, revert, hotfix |
| design | refactor, architect, redesign, restructure, spec, plan, model, abstract |
| ops    | deploy, infra, ci, pipeline, migrate, monitor, release, provision, automate |
| learn  | research, spike, doc, read, explore, investigate, review, study, prototype |
| build  | feat, add, implement, ship, create, build, complete, finish, integrate |

If no pattern matches, the task falls back to the `default` skill (configurable, defaults to `build`).

---

## Vault Structure

```
{vault_path}/
  .bnd-global.json              ← global state (skills, achievements, shards)
  global.md                     ← global character sheet, regenerated each run
  shop.md                       ← reward shop, never overwritten after creation
  realms/
    <realm-name>/
      .bnd-realm.json           ← realm state (realm XP, level)
      .bnd-cache.json           ← processed task IDs for this realm
      profile.md                ← realm character sheet, regenerated each run
      log/
        YYYY-MM-DD.md           ← daily log, appended each run
  checkpoints/
    <realm>-checkpoint-01.md
    <realm>-checkpoint-02.md
    ...
```

### File Descriptions

| File | Description |
|------|-------------|
| `.bnd-global.json` | Master state: shards, streak, skill XP, achievement IDs |
| `.bnd-realm.json` | Per-realm XP total and last checkpoint marker |
| `.bnd-cache.json` | Dict of processed task IDs → `{xp, skill, date, title}` |
| `global.md` | Obsidian character sheet with skills, trophies, and realm table |
| `profile.md` | Per-realm sheet with level, XP progress, recent task table |
| `log/YYYY-MM-DD.md` | Daily append-only log of XP gains and achievement unlocks |
| `checkpoints/*.md` | Milestone reflection notes written every 500 XP per realm |
| `shop.md` | Customizable reward shop for spending Shards |

---

## Optional: Cron Setup

To automatically process tasks daily, add to your crontab (`crontab -e`):

```cron
# Run BnD every day at 6 PM from your main project directory
0 18 * * * cd /home/user/projects/my-app && python /home/user/tools/bnd/bnd.py >> /tmp/bnd.log 2>&1
```

Or use a shell script to loop over multiple projects:

```bash
#!/bin/bash
for proj in ~/projects/my-app ~/projects/side-proj; do
  cd "$proj" && python ~/tools/bnd/bnd.py
done
```
