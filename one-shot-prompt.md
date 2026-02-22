# BnD (Beads and Dragons) — One-Shot Build Prompt v2

Build a Python CLI tool called **BnD (Beads and Dragons)** — an XP, leveling, skill, and achievement system that gamifies work tracked in [beads (`bd`)](https://github.com/steveyegge/beads), a git-backed graph issue tracker. Progress is written to an Obsidian vault.

---

## Deliverables

Produce exactly these files:

```
bnd/
  bnd.py                  # main CLI entry point
  bnd.config.yaml         # default config (copied to project on init)
  shop.md                 # Obsidian reward shop template
  README.md               # setup and usage reference
```

No external Python dependencies beyond the standard library **except `pyyaml`** (`pip install pyyaml`). Only `bd` (the beads CLI) must also be installed on the system.

---

## Realm Model

A **realm** maps 1-to-1 with a beads project directory. The realm name is the directory's basename (e.g. `/home/user/projects/my-app` → realm `my-app`).

**Separate per realm:** XP, character level
**Shared globally:** skills, achievements, shards

This means a task's XP simultaneously advances:
1. The **realm's** total XP and level
2. The **global skill** matching the task's auto-tagged skill category

Running `bnd.py` from a directory that contains no beads project (i.e. `bd list` fails or returns a non-zero exit code) prints a helpful error and exits with code 1.

---

## CLI Interface

```
python bnd.py                          # process new closed tasks in cwd realm, update Obsidian
python bnd.py --status                 # print global character sheet + realm list to terminal
python bnd.py --status --realm <name>  # print single realm detail view
python bnd.py --reset                  # wipe vault state + cache for cwd realm (with confirmation)
python bnd.py --reset --global         # wipe ALL vault state + cache files (with confirmation)
python bnd.py --config <path>          # use alternate config file
```

All output lines are prefixed with `[bnd]`.

---

## File Locations

All persistent state lives **inside the vault** (path from config → `obsidian.vault_path`):

```
{vault_path}/
  .bnd-global.json              ← global state (skills, achievements, shards)
  global.md                     ← global character sheet, regenerated each run
  shop.md                       ← reward shop, never overwritten if exists
  realms/
    <realm-name>/
      .bnd-realm.json           ← realm state (realm XP, level)
      .bnd-cache.json           ← processed task IDs for this realm
      profile.md                ← realm character sheet, regenerated each run
      log/
        YYYY-MM-DD.md           ← appended each run
  checkpoints/
    checkpoint-01.md
    checkpoint-02.md
    ...
```

- **Config:** `bnd.config.yaml` next to `bnd.py`, or overridden with `--config`
- Vault path supports `~` expansion

---

## Config File: `bnd.config.yaml`

Parse with `pyyaml` (`import yaml`). The full schema:

```yaml
aesthetic:
  style: rpg          # rpg | minimal — controls message tone
  messages:
    xp_gained: "+{xp} XP — {task_title}"
    level_up: "Level {level} reached. You are now a {title}."
    achievement: "Achievement unlocked: {name}"
    checkpoint: "Rest stop. {xp} XP this leg."
    epic_bonus: "Epic closed. +{xp} bonus XP."
    new_shards: "+{shards} Shards earned."

xp:
  priority:
    p0: 100
    p1: 50
    p2: 25
    p3: 10
    default: 10
  subtask_multiplier: 0.25
  epic_bonus: 200
  bonuses:
    blocker: 0.50      # multiplier added if task unblocked 2+ others
    same_day: 0.25     # multiplier added if closed same day as created

currency:
  name: Shards
  symbol: "💎"
  rate: 0.1            # shards per XP, floored to int

skills:
  auto_tag: true
  default: build       # fallback skill if no keyword matches
  keywords:
    build:  "feat|add|implement|ship|create|build|complete|finish|integrate"
    debug:  "fix|bug|error|crash|broken|patch|resolve|revert|hotfix"
    design: "refactor|architect|redesign|restructure|spec|plan|model|abstract"
    ops:    "deploy|infra|ci|pipeline|migrate|monitor|release|provision|automate"
    learn:  "research|spike|doc|read|explore|investigate|review|study|prototype"

levels:
  - level: 1
    xp: 0
    title: "Apprentice"
  - level: 2
    xp: 100
    title: "Journeyman"
  - level: 3
    xp: 300
    title: "Craftsman"
  - level: 4
    xp: 700
    title: "Engineer"
  - level: 5
    xp: 1500
    title: "Architect"
  - level: 6
    xp: 3000
    title: "Veteran"
  - level: 7
    xp: 6000
    title: "Principal"
  - level: 8
    xp: 12000
    title: "Legend"

checkpoints:
  interval: 500
  prompt: "What did you learn this leg? What do you want to focus on next?"

achievements:
  - id: firefighter
    name: "Firefighter"
    description: "Close your first P0 task."
    condition_type: close_priority
    condition_priority: p0
    condition_count: 1
  - id: bomb_defuser
    name: "Bomb Defuser"
    description: "Close 5 P0 tasks."
    condition_type: close_priority
    condition_priority: p0
    condition_count: 5
  - id: speed_run
    name: "Speed Run"
    description: "Close 3 tasks in a single day."
    condition_type: daily_closes
    condition_count: 3
  - id: unlocker
    name: "Unlocker"
    description: "Close a task that was blocking 3 or more others."
    condition_type: unblocked
    condition_count: 3
  - id: quest_complete
    name: "Quest Complete"
    description: "Close your first epic."
    condition_type: epic_closed
    condition_count: 1
  - id: epic_slayer
    name: "Epic Slayer"
    description: "Close 5 epics."
    condition_type: epic_closed
    condition_count: 5
  - id: consistent
    name: "Consistent"
    description: "Close at least one task per day for 5 days straight."
    condition_type: streak
    condition_count: 5
  - id: on_fire
    name: "On Fire"
    description: "Close at least one task per day for 14 days straight."
    condition_type: streak
    condition_count: 14
  - id: master_builder
    name: "Master Builder"
    description: "Reach level 5 in the Build skill."
    condition_type: skill_level
    condition_skill: build
    condition_count: 5
  - id: scholar
    name: "Scholar"
    description: "Close 10 Learn-tagged tasks."
    condition_type: skill_tasks
    condition_skill: learn
    condition_count: 10

obsidian:
  vault_path: "~/Documents/Obsidian/BnD"
```

---

## State Schemas

### `.bnd-global.json` (vault root)

```json
{
  "shards": 0,
  "p0_count": 0,
  "epic_count": 0,
  "achievements": [],
  "current_streak": 0,
  "last_active_date": "",
  "skills": {
    "build": 0, "debug": 0, "design": 0, "ops": 0, "learn": 0
  },
  "skill_tasks": {
    "build": 0, "debug": 0, "design": 0, "ops": 0, "learn": 0
  }
}
```

### `realms/<name>/.bnd-realm.json`

```json
{
  "realm": "my-app",
  "total_xp": 0,
  "last_checkpoint_xp": 0
}
```

### `realms/<name>/.bnd-cache.json`

A dict keyed by beads task ID. Each entry stores:

```json
{
  "bd-a3f8": { "xp": 62, "skill": "debug", "date": "2026-02-22" }
}
```

---

## Core Logic

### Idempotency

On every run, fetch all closed tasks from `bd` for the current realm, skip any whose ID is already in that realm's cache, process only new ones. Totals are always recalculated from the cache — never accumulated incrementally — so `--reset` just wipes cache and state and a fresh run rebuilds from scratch.

### Fetching Tasks from `bd`

Run: `bd list --status closed --format json`

If that fails, try: `bd list -s closed -f json`

Parse the JSON output as a list of task objects. Each task object has at minimum:
- `id` — string, e.g. `"bd-a3f8"` or `"bd-a3f8.1"` (subtask)
- `title` — string
- `priority` — int (0–3) or string (`"p0"`–`"p3"`)
- `created_at` — ISO datetime string
- `closed_at` or `updated_at` — ISO datetime string
- `description` — string (may be absent)
- `blockers` — list of task IDs this task was blocking (may be absent)

If `bd` is not available or returns no tasks, print a helpful message and exit cleanly (code 0).

### Subtask Detection

A task ID containing a dot is a subtask: `"bd-a3f8.1"`, `"bd-a3f8.1.1"`. Subtasks receive `base_xp * subtask_multiplier`.

### Epic Detection

A task is an epic if any other task in the closed list has an ID prefixed with `{id}.`. When an epic is closed, add a flat `epic_bonus` XP on top of its normal XP. Increment `epic_count` in global state.

### XP Calculation

```
base_xp = priority_xp[priority]
if subtask: base_xp = int(base_xp * subtask_multiplier)

# Same-day bonus
if created_at.date() == closed_at.date():
    base_xp = int(base_xp * (1 + bonuses.same_day))

# Blocker bonus: count how many other tasks list this task's ID in their blockers field
unblocked_count = sum(1 for t in all_tasks if id in t.get("blockers", []))
if unblocked_count >= 2:
    base_xp = int(base_xp * (1 + bonuses.blocker))

# Epic bonus added after
if is_epic:
    base_xp += epic_bonus

final_xp = base_xp
```

This `final_xp` is added to **both** `realm_state["total_xp"]` and `global_state["skills"][skill]`.

### Skill Auto-Tagging

Match task `title + " " + description` (lowercased) against keyword regex patterns in config. Evaluation order: `debug`, `design`, `ops`, `learn`, `build`. First match wins. If nothing matches, use `skills.default`.

Patterns are pipe-separated regex alternations used directly with `re.search(pattern, text, re.IGNORECASE)`.

**LLM fallback hook (stub only):** After keyword matching fails, before falling back to default, call `llm_classify(title, description) -> str` that currently returns `None`.
```python
# TODO: wire up LLM API here for ambiguous classification
```

### Shards

`earned_shards = int(xp * shard_rate)` per task. Accumulated in `global_state["shards"]`.

### Leveling

One reusable function used for both realm levels and skill levels:

```python
def xp_to_level(xp: int, levels_config: list) -> tuple[int, str, int | None]:
    # Returns (level_num, title, next_xp_threshold | None)
```

Iterate levels list, return the highest level whose `xp` threshold the current XP meets. Return `None` for `next_xp_threshold` at max level.

### Streak Tracking

Stored in `global_state`: `current_streak` (int) and `last_active_date` (ISO date string). Updated once per run that processes at least one new task:

- If `last_active_date` == today → already counted, skip
- If `last_active_date` == yesterday → `current_streak += 1`
- Otherwise → `current_streak = 1`
- Update `last_active_date` to today

---

## Achievement Conditions

Achievements are global. Check after every run against `global_state`. For each achievement in config not yet in `global_state["achievements"]`:

| `condition_type`  | Logic |
|-------------------|-------|
| `close_priority`  | `global_state["{priority}_count"] >= condition_count` |
| `epic_closed`     | `global_state["epic_count"] >= condition_count` |
| `streak`          | `global_state["current_streak"] >= condition_count` |
| `skill_level`     | `xp_to_level(global_state["skills"][condition_skill])[0] >= condition_count` |
| `skill_tasks`     | `global_state["skill_tasks"][condition_skill] >= condition_count` |
| `daily_closes`    | Count cache entries across **all realms** with today's date >= condition_count |
| `unblocked`       | Track per-task unblocked count during processing; grant if any single task had >= condition_count |

When an achievement is unlocked: append its ID to `global_state["achievements"]`, print the `achievement` message, and append a line to today's realm log.

---

## Checkpoints

Checkpoints are **per realm**, tracked in `realm_state["last_checkpoint_xp"]`.

After processing, if `(realm_total_xp - last_checkpoint_xp) >= checkpoint_interval`:
- Print the checkpoint message
- Write `vault/checkpoints/{realm-name}-checkpoint-{N:02d}.md` where N = `realm_total_xp // checkpoint_interval`
- Update `realm_state["last_checkpoint_xp"] = realm_total_xp`

Checkpoint file format:
```markdown
# Rest Stop {N} — {realm-name}

**Date:** YYYY-MM-DD
**XP this leg:** {leg_xp}
**Realm XP:** {total_xp}
**Current rank:** Level {level} — {title}

---

## Reflection

*{checkpoint_prompt}*

> 

---

## Tasks closed this leg

{list of "- task {id} [{skill}] +{xp} XP" from cache, last 20}
```

---

## Obsidian Output

### `global.md` — regenerated every run:

```markdown
# BnD — Global Character Sheet

**💎 Shards:** {shards}
**Streak:** {current_streak} day(s)
**Achievements:** {unlocked_count} / {total_count}

---

## Skills

| Skill  | XP      | Rank              |
|--------|---------|-------------------|
| Build  | {xp} XP | Lv.{n} {title}    |
| Debug  | {xp} XP | Lv.{n} {title}    |
| Design | {xp} XP | Lv.{n} {title}    |
| Ops    | {xp} XP | Lv.{n} {title}    |
| Learn  | {xp} XP | Lv.{n} {title}    |

---

## Trophies

- [x] **{name}** — {description}    ← unlocked
- [ ] {name} — {description}        ← locked

---

## Realms

| Realm      | Level | XP       | Title      |
|------------|-------|----------|------------|
| my-app     | 4     | 823 XP   | Engineer   |
| side-proj  | 2     | 120 XP   | Journeyman |

---

*Last updated: YYYY-MM-DD HH:MM*
```

### `realms/<name>/profile.md` — regenerated every run:

```markdown
# {realm-name} — Realm Sheet

**Level:** {level} — {title}
**Realm XP:** {total_xp} / {next_xp} ({xp_to_next} to next)
**Next checkpoint:** {cp_remaining} XP away

---

## Recent Tasks

| Date       | Task                  | Skill  | XP  |
|------------|-----------------------|--------|-----|
| YYYY-MM-DD | {task_title}          | build  | +62 |

*(last 10 processed tasks from cache)*

---

*Last updated: YYYY-MM-DD HH:MM*
```

### `realms/<name>/log/YYYY-MM-DD.md` — appended each run:

Create with a `# Log — {realm} — YYYY-MM-DD` header if it doesn't exist.
Append one line per new task: `- +{xp} XP [{skill}] — {task_title}`
Append achievement unlock lines: `- 🏆 Achievement: **{name}**`

### `shop.md` — written only if it does not exist:

```markdown
# Shard Shop 💎

Spend your hard-earned Shards on rewards you define. Log spends manually below.

---

## Reward Menu

| Cost | Reward |
|------|--------|
| 5 💎 | 30-minute guilt-free break |
| 10 💎 | Coffee or treat of choice |
| 15 💎 | Order food instead of cooking |
| 25 💎 | Buy that tool, book, or game you've been eyeing |
| 40 💎 | Full afternoon of side project or free exploration |
| 60 💎 | Full free day — no obligations |

*Edit this table. These are your rules.*

---

## Spend Log

| Date | Shards Spent | Reward |
|------|-------------|--------|
|      |             |        |

---

## Balance

*Check your current Shard balance in [[global]].*
```

---

## Terminal `--status` Output (default: global view)

```
╔══════════════════════════════════════╗
║       BnD — Global Character Sheet   ║
╠══════════════════════════════════════╣
║  💎 Shards: 32   Streak: 3 day(s)    ║
║  Achievements: 3 / 10                ║
╠══════════════════════════════════════╣
║  Skills                               ║
║    build     Lv.4   420 XP            ║
║    debug     Lv.3   210 XP            ║
║    design    Lv.2   110 XP            ║
║    ops       Lv.1    60 XP            ║
║    learn     Lv.1    23 XP            ║
╠══════════════════════════════════════╣
║  Realms                               ║
║    my-app      Lv.4  823 XP  Engineer ║
║    side-proj   Lv.2  120 XP  Journeyman║
╚══════════════════════════════════════╝
```

### `--status --realm <name>` (realm detail view):

```
╔══════════════════════════════════════╗
║       BnD — my-app                   ║
╠══════════════════════════════════════╣
║  Level 4    Engineer                  ║
║  XP    823 / 1500  (677 to next)      ║
║  Next checkpoint: 177 XP away         ║
╚══════════════════════════════════════╝
```

---

## Message Formatting

```python
def fmt(template_key: str, **kwargs) -> str:
    template = config["aesthetic"]["messages"][template_key]
    return template.format_map(kwargs)
```

---

## Error Handling

- **`bd` not found:** `[bnd] Error: 'bd' not found. Install beads: https://github.com/steveyegge/beads` → exit 1
- **Not in a beads project:** `[bnd] Error: No beads project found in current directory. Run 'bd init' first.` → exit 1
- **`bd list` returns non-JSON or empty:** `[bnd] No closed tasks found.` → exit 0
- **Config missing:** `[bnd] Config not found at {path}. Copy bnd.config.yaml to your project.` → exit 1
- **Vault path missing:** Create it with `os.makedirs(..., exist_ok=True)` including all subdirs
- **All file writes:** Use atomic temp-file-then-rename pattern to avoid corruption

---

## Code Style

- Python 3.8+ compatible
- Dependencies: stdlib + `pyyaml` only
- Single file: `bnd.py`
- Use dataclasses for `Task`, `Level`, `Achievement`, `Config` where it aids clarity
- Group into clear sections with `# ---` separator comments:
  `Config`, `State`, `Cache`, `XP`, `Skills`, `Achievements`, `Obsidian`, `CLI`
- Type hints on all function signatures

---

## README.md

Include:
- What BnD is (one paragraph)
- Realm concept explanation (one paragraph)
- Dependencies (`pyyaml`, `bd`)
- Setup (config, chmod, vault path)
- CLI usage table (all flags)
- XP table (priority → XP, subtask multiplier, bonuses)
- Skill keyword table
- What is shared globally vs. per realm (clear table)
- Vault structure diagram
- File descriptions table
- Optional cron setup example
