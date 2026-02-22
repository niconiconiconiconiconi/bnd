#!/usr/bin/env python3
"""
BnD (Beads and Dragons) — XP, leveling, skill, and achievement system
for tasks tracked in beads (bd), a git-backed graph issue tracker.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

PREFIX = "[bnd]"

# ---
# Config
# ---

@dataclass
class Config:
    raw: Dict[str, Any]

    @property
    def vault_path(self) -> Path:
        return Path(os.path.expanduser(self.raw["obsidian"]["vault_path"]))

    @property
    def style(self) -> str:
        return self.raw["aesthetic"].get("style", "rpg")

    @property
    def messages(self) -> Dict[str, str]:
        return self.raw["aesthetic"]["messages"]

    @property
    def xp_priority(self) -> Dict[str, int]:
        return self.raw["xp"]["priority"]

    @property
    def subtask_multiplier(self) -> float:
        return float(self.raw["xp"]["subtask_multiplier"])

    @property
    def epic_bonus(self) -> int:
        return int(self.raw["xp"]["epic_bonus"])

    @property
    def bonus_blocker(self) -> float:
        return float(self.raw["xp"]["bonuses"]["blocker"])

    @property
    def bonus_same_day(self) -> float:
        return float(self.raw["xp"]["bonuses"]["same_day"])

    @property
    def shard_rate(self) -> float:
        return float(self.raw["currency"]["rate"])

    @property
    def shard_symbol(self) -> str:
        return self.raw["currency"]["symbol"]

    @property
    def levels(self) -> List[Dict]:
        return self.raw["levels"]

    @property
    def skills(self) -> Dict[str, str]:
        return self.raw["skills"]["keywords"]

    @property
    def default_skill(self) -> str:
        return self.raw["skills"].get("default", "build")

    @property
    def checkpoint_interval(self) -> int:
        return int(self.raw["checkpoints"]["interval"])

    @property
    def checkpoint_prompt(self) -> str:
        return self.raw["checkpoints"]["prompt"]

    @property
    def achievements(self) -> List[Dict]:
        return self.raw["achievements"]


def load_config(path: Optional[str] = None) -> Config:
    if path is None:
        path = Path(__file__).parent / "bnd.config.yaml"
    else:
        path = Path(path)
    if not path.exists():
        print(f"{PREFIX} Config not found at {path}. Copy bnd.config.yaml to your project.")
        sys.exit(1)
    with open(path) as f:
        raw = yaml.safe_load(f)
    return Config(raw)


def fmt(config: Config, template_key: str, **kwargs) -> str:
    template = config.messages.get(template_key, "")
    return template.format_map(kwargs)


# ---
# State
# ---

GLOBAL_STATE_DEFAULTS: Dict[str, Any] = {
    "shards": 0,
    "p0_count": 0,
    "p1_count": 0,
    "p2_count": 0,
    "p3_count": 0,
    "epic_count": 0,
    "achievements": [],
    "current_streak": 0,
    "last_active_date": "",
    "skills": {"build": 0, "debug": 0, "design": 0, "ops": 0, "learn": 0},
    "skill_tasks": {"build": 0, "debug": 0, "design": 0, "ops": 0, "learn": 0},
}

REALM_STATE_DEFAULTS: Dict[str, Any] = {
    "total_xp": 0,
    "last_checkpoint_xp": 0,
}


def atomic_write(path: Path, data: Any, is_json: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            if is_json:
                json.dump(data, f, indent=2)
            else:
                f.write(data)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def load_json(path: Path, defaults: Dict) -> Dict:
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        # Merge missing keys from defaults
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
        return data
    return dict(defaults)


def global_state_path(vault: Path) -> Path:
    return vault / ".bnd-global.json"


def realm_state_path(vault: Path, realm: str) -> Path:
    return vault / "realms" / realm / ".bnd-realm.json"


def realm_cache_path(vault: Path, realm: str) -> Path:
    return vault / "realms" / realm / ".bnd-cache.json"


def load_global_state(vault: Path) -> Dict:
    return load_json(global_state_path(vault), dict(GLOBAL_STATE_DEFAULTS))


def save_global_state(vault: Path, state: Dict) -> None:
    atomic_write(global_state_path(vault), state)


def load_realm_state(vault: Path, realm: str) -> Dict:
    d = load_json(realm_state_path(vault, realm), dict(REALM_STATE_DEFAULTS))
    d.setdefault("realm", realm)
    return d


def save_realm_state(vault: Path, realm: str, state: Dict) -> None:
    atomic_write(realm_state_path(vault, realm), state)


def load_cache(vault: Path, realm: str) -> Dict:
    p = realm_cache_path(vault, realm)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def save_cache(vault: Path, realm: str, cache: Dict) -> None:
    atomic_write(realm_cache_path(vault, realm), cache)


# ---
# Cache / Realms helpers
# ---

def list_realms(vault: Path) -> List[str]:
    realms_dir = vault / "realms"
    if not realms_dir.exists():
        return []
    return [d.name for d in realms_dir.iterdir() if d.is_dir()]


def all_cache_entries(vault: Path) -> List[Dict]:
    entries = []
    for realm in list_realms(vault):
        cache = load_cache(vault, realm)
        for tid, entry in cache.items():
            entries.append({**entry, "id": tid, "realm": realm})
    return entries


# ---
# XP
# ---

def is_subtask(task_id: str) -> bool:
    return "." in task_id


def xp_to_level(xp: int, levels_config: List[Dict]) -> Tuple[int, str, Optional[int]]:
    """Returns (level_num, title, next_xp_threshold | None)."""
    current_level = levels_config[0]
    for lvl in levels_config:
        if xp >= lvl["xp"]:
            current_level = lvl
        else:
            break
    idx = levels_config.index(current_level)
    if idx + 1 < len(levels_config):
        next_xp = levels_config[idx + 1]["xp"]
    else:
        next_xp = None
    return current_level["level"], current_level["title"], next_xp


def parse_priority(priority) -> str:
    if isinstance(priority, int):
        return f"p{priority}"
    return str(priority).lower()


def calculate_xp(task: Dict, all_tasks: List[Dict], config: Config) -> int:
    priority_str = parse_priority(task.get("priority", 3))
    base_xp = config.xp_priority.get(priority_str, config.xp_priority.get("default", 10))

    if is_subtask(task["id"]):
        base_xp = int(base_xp * config.subtask_multiplier)

    # Same-day bonus
    created = task.get("created_at", "")
    closed = task.get("closed_at") or task.get("updated_at", "")
    try:
        created_date = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
        closed_date = datetime.fromisoformat(closed.replace("Z", "+00:00")).date()
        if created_date == closed_date:
            base_xp = int(base_xp * (1 + config.bonus_same_day))
    except (ValueError, AttributeError):
        pass

    # Blocker bonus
    task_id = task["id"]
    unblocked_count = sum(1 for t in all_tasks if task_id in t.get("blockers", []))
    if unblocked_count >= 2:
        base_xp = int(base_xp * (1 + config.bonus_blocker))

    return base_xp


def is_epic(task: Dict, all_tasks: List[Dict]) -> bool:
    prefix = task["id"] + "."
    return any(t["id"].startswith(prefix) for t in all_tasks)


# ---
# Skills
# ---

SKILL_ORDER = ["debug", "design", "ops", "learn", "build"]


def llm_classify(title: str, description: str) -> Optional[str]:
    # TODO: wire up LLM API here for ambiguous classification
    return None


def classify_skill(task: Dict, config: Config) -> str:
    text = (task.get("title", "") + " " + task.get("description", "")).lower()
    for skill in SKILL_ORDER:
        pattern = config.skills.get(skill, "")
        if pattern and re.search(pattern, text, re.IGNORECASE):
            return skill
    result = llm_classify(task.get("title", ""), task.get("description", ""))
    if result:
        return result
    return config.default_skill


# ---
# Achievements
# ---

def check_achievements(
    config: Config,
    global_state: Dict,
    vault: Path,
    realm: str,
    log_lines: List[str],
    max_unblocked_in_run: int,
) -> List[str]:
    unlocked = []
    today_str = date.today().isoformat()

    for ach in config.achievements:
        aid = ach["id"]
        if aid in global_state["achievements"]:
            continue

        ctype = ach["condition_type"]
        ccount = ach.get("condition_count", 1)
        satisfied = False

        if ctype == "close_priority":
            cp = ach.get("condition_priority", "p0")
            key = f"{cp}_count"
            satisfied = global_state.get(key, 0) >= ccount

        elif ctype == "epic_closed":
            satisfied = global_state.get("epic_count", 0) >= ccount

        elif ctype == "streak":
            satisfied = global_state.get("current_streak", 0) >= ccount

        elif ctype == "skill_level":
            cskill = ach.get("condition_skill", "build")
            skill_xp = global_state["skills"].get(cskill, 0)
            lvl, _, _ = xp_to_level(skill_xp, config.levels)
            satisfied = lvl >= ccount

        elif ctype == "skill_tasks":
            cskill = ach.get("condition_skill", "learn")
            satisfied = global_state["skill_tasks"].get(cskill, 0) >= ccount

        elif ctype == "daily_closes":
            all_entries = all_cache_entries(vault)
            today_count = sum(1 for e in all_entries if e.get("date") == today_str)
            satisfied = today_count >= ccount

        elif ctype == "unblocked":
            satisfied = max_unblocked_in_run >= ccount

        if satisfied:
            global_state["achievements"].append(aid)
            msg = fmt(config, "achievement", name=ach["name"])
            print(f"{PREFIX} {msg}")
            log_lines.append(f"- 🏆 Achievement: **{ach['name']}**")
            unlocked.append(aid)

    return unlocked


# ---
# Obsidian Output
# ---

def ensure_vault_dirs(vault: Path, realm: str) -> None:
    (vault / "realms" / realm / "log").mkdir(parents=True, exist_ok=True)
    (vault / "checkpoints").mkdir(parents=True, exist_ok=True)


def write_global_md(vault: Path, config: Config, global_state: Dict) -> None:
    all_realms = list_realms(vault)
    realm_rows = []
    for r in all_realms:
        rs = load_realm_state(vault, r)
        lvl, title, _ = xp_to_level(rs["total_xp"], config.levels)
        realm_rows.append(f"| {r} | {lvl} | {rs['total_xp']} XP | {title} |")

    skill_rows = []
    for sk in ["build", "debug", "design", "ops", "learn"]:
        xp = global_state["skills"].get(sk, 0)
        lvl, title, _ = xp_to_level(xp, config.levels)
        skill_rows.append(f"| {sk.capitalize()} | {xp} XP | Lv.{lvl} {title} |")

    unlocked = set(global_state["achievements"])
    trophy_lines = []
    for ach in config.achievements:
        if ach["id"] in unlocked:
            trophy_lines.append(f'- [x] **{ach["name"]}** — {ach["description"]}')
        else:
            trophy_lines.append(f'- [ ] {ach["name"]} — {ach["description"]}')

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    shards = global_state.get("shards", 0)
    streak = global_state.get("current_streak", 0)
    ach_count = len(unlocked)
    total_ach = len(config.achievements)

    content = f"""# BnD — Global Character Sheet

**{config.shard_symbol} Shards:** {shards}
**Streak:** {streak} day(s)
**Achievements:** {ach_count} / {total_ach}

---

## Skills

| Skill  | XP      | Rank              |
|--------|---------|-------------------|
{chr(10).join(skill_rows)}

---

## Trophies

{chr(10).join(trophy_lines)}

---

## Realms

| Realm      | Level | XP       | Title      |
|------------|-------|----------|------------|
{chr(10).join(realm_rows)}

---

*Last updated: {now}*
"""
    atomic_write(vault / "global.md", content, is_json=False)


def write_realm_profile(vault: Path, config: Config, realm: str, realm_state: Dict, cache: Dict) -> None:
    total_xp = realm_state["total_xp"]
    lvl, title, next_xp = xp_to_level(total_xp, config.levels)
    if next_xp is not None:
        xp_to_next = next_xp - total_xp
        next_str = str(next_xp)
    else:
        xp_to_next = 0
        next_str = "MAX"

    last_cp = realm_state.get("last_checkpoint_xp", 0)
    cp_remaining = config.checkpoint_interval - ((total_xp - last_cp) % config.checkpoint_interval)
    if cp_remaining == config.checkpoint_interval:
        cp_remaining = 0

    # Last 10 cache entries
    entries = sorted(cache.items(), key=lambda x: x[1].get("date", ""), reverse=True)[:10]
    rows = []
    for tid, e in entries:
        rows.append(f"| {e.get('date','')} | {e.get('title', tid)[:30]} | {e.get('skill','')} | +{e.get('xp',0)} |")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"""# {realm} — Realm Sheet

**Level:** {lvl} — {title}
**Realm XP:** {total_xp} / {next_str} ({xp_to_next} to next)
**Next checkpoint:** {cp_remaining} XP away

---

## Recent Tasks

| Date       | Task                  | Skill  | XP  |
|------------|-----------------------|--------|-----|
{chr(10).join(rows) if rows else '| — | — | — | — |'}

---

*Last updated: {now}*
"""
    atomic_write(vault / "realms" / realm / "profile.md", content, is_json=False)


def append_log(vault: Path, realm: str, log_lines: List[str]) -> None:
    if not log_lines:
        return
    today_str = date.today().isoformat()
    log_path = vault / "realms" / realm / "log" / f"{today_str}.md"
    header = f"# Log — {realm} — {today_str}\n\n"
    if not log_path.exists():
        existing = header
    else:
        with open(log_path) as f:
            existing = f.read()
    existing += "\n".join(log_lines) + "\n"
    atomic_write(log_path, existing, is_json=False)


def write_checkpoint(vault: Path, config: Config, realm: str, realm_state: Dict, cache: Dict, n: int) -> None:
    today_str = date.today().isoformat()
    total_xp = realm_state["total_xp"]
    last_cp = realm_state.get("last_checkpoint_xp", 0)
    leg_xp = total_xp - last_cp
    lvl, title, _ = xp_to_level(total_xp, config.levels)

    entries = sorted(cache.items(), key=lambda x: x[1].get("date", ""), reverse=True)[:20]
    task_lines = []
    for tid, e in entries:
        task_lines.append(f"- task {tid} [{e.get('skill','')}] +{e.get('xp',0)} XP")

    cp_path = vault / "checkpoints" / f"{realm}-checkpoint-{n:02d}.md"
    content = f"""# Rest Stop {n} — {realm}

**Date:** {today_str}
**XP this leg:** {leg_xp}
**Realm XP:** {total_xp}
**Current rank:** Level {lvl} — {title}

---

## Reflection

*{config.checkpoint_prompt}*

> 

---

## Tasks closed this leg

{chr(10).join(task_lines)}
"""
    atomic_write(cp_path, content, is_json=False)
    msg = fmt(config, "checkpoint", xp=leg_xp)
    print(f"{PREFIX} {msg}")


def write_shop_md(vault: Path) -> None:
    shop_path = vault / "shop.md"
    if shop_path.exists():
        return
    content = """# Shard Shop 💎

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
"""
    atomic_write(shop_path, content, is_json=False)


# ---
# bd Integration
# ---

def get_realm_name() -> str:
    return Path.cwd().name


def fetch_closed_tasks() -> Optional[List[Dict]]:
    """Fetch closed tasks from bd. Returns None if bd not available."""
    # Check bd exists
    try:
        result = subprocess.run(["which", "bd"], capture_output=True)
        if result.returncode != 0:
            result2 = subprocess.run(["bd", "--version"], capture_output=True)
            if result2.returncode != 0:
                print(f"{PREFIX} Error: 'bd' not found. Install beads: https://github.com/steveyegge/beads")
                sys.exit(1)
    except FileNotFoundError:
        print(f"{PREFIX} Error: 'bd' not found. Install beads: https://github.com/steveyegge/beads")
        sys.exit(1)

    # Try fetching tasks
    for args in [
        ["bd", "list", "--status", "closed", "--format", "json"],
        ["bd", "list", "-s", "closed", "-f", "json"],
    ]:
        try:
            result = subprocess.run(args, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                try:
                    tasks = json.loads(result.stdout)
                    if isinstance(tasks, list):
                        return tasks
                except json.JSONDecodeError:
                    continue
        except FileNotFoundError:
            print(f"{PREFIX} Error: 'bd' not found. Install beads: https://github.com/steveyegge/beads")
            sys.exit(1)

    return None


def verify_beads_project() -> None:
    """Verify we're in a beads project directory."""
    try:
        result = subprocess.run(["bd", "list"], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"{PREFIX} Error: No beads project found in current directory. Run 'bd init' first.")
            sys.exit(1)
    except FileNotFoundError:
        print(f"{PREFIX} Error: 'bd' not found. Install beads: https://github.com/steveyegge/beads")
        sys.exit(1)


# ---
# Streak
# ---

def update_streak(global_state: Dict, processed_any: bool) -> None:
    if not processed_any:
        return
    today_str = date.today().isoformat()
    yesterday_str = (date.today().replace(day=date.today().day - 1)).isoformat() if date.today().day > 1 else None
    # More robust yesterday calculation
    from datetime import timedelta
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    last = global_state.get("last_active_date", "")
    if last == today_str:
        return
    elif last == yesterday_str:
        global_state["current_streak"] = global_state.get("current_streak", 0) + 1
    else:
        global_state["current_streak"] = 1
    global_state["last_active_date"] = today_str


# ---
# CLI
# ---

def rebuild_global_state_from_caches(vault: Path, config: Config) -> Dict:
    """Rebuild global state from all realm caches (for recalculation)."""
    state = load_json(global_state_path(vault), dict(GLOBAL_STATE_DEFAULTS))
    # Reset accumulators but keep achievements/streak/last_active
    state["shards"] = 0
    state["p0_count"] = 0
    state["p1_count"] = 0
    state["p2_count"] = 0
    state["p3_count"] = 0
    state["epic_count"] = 0
    state["skills"] = {"build": 0, "debug": 0, "design": 0, "ops": 0, "learn": 0}
    state["skill_tasks"] = {"build": 0, "debug": 0, "design": 0, "ops": 0, "learn": 0}
    for realm in list_realms(vault):
        cache = load_cache(vault, realm)
        for tid, entry in cache.items():
            xp = entry.get("xp", 0)
            skill = entry.get("skill", "build")
            priority = entry.get("priority", "p3")
            is_ep = entry.get("is_epic", False)
            state["shards"] += int(xp * config.shard_rate)
            state["skills"][skill] = state["skills"].get(skill, 0) + xp
            state["skill_tasks"][skill] = state["skill_tasks"].get(skill, 0) + 1
            p_key = f"{priority}_count"
            if p_key in state:
                state[p_key] += 1
            if is_ep:
                state["epic_count"] += 1
    return state


def cmd_process(config: Config) -> None:
    verify_beads_project()
    realm = get_realm_name()
    vault = config.vault_path
    vault.mkdir(parents=True, exist_ok=True)
    ensure_vault_dirs(vault, realm)
    write_shop_md(vault)

    tasks = fetch_closed_tasks()
    if not tasks:
        print(f"{PREFIX} No closed tasks found.")
        return

    cache = load_cache(vault, realm)
    realm_state = load_realm_state(vault, realm)
    realm_state.setdefault("realm", realm)
    global_state = load_global_state(vault)

    new_tasks = [t for t in tasks if t["id"] not in cache]
    if not new_tasks:
        print(f"{PREFIX} No new tasks to process.")
        write_global_md(vault, config, global_state)
        write_realm_profile(vault, config, realm, realm_state, cache)
        return

    log_lines: List[str] = []
    max_unblocked = 0

    for task in new_tasks:
        task_id = task["id"]
        priority_str = parse_priority(task.get("priority", 3))
        skill = classify_skill(task, config)
        xp = calculate_xp(task, tasks, config)

        # Unblocked tracking
        unblocked_count = sum(1 for t in tasks if task_id in t.get("blockers", []))
        if unblocked_count > max_unblocked:
            max_unblocked = unblocked_count

        epic = is_epic(task, tasks)
        if epic:
            xp += config.epic_bonus
            global_state["epic_count"] = global_state.get("epic_count", 0) + 1
            epic_msg = fmt(config, "epic_bonus", xp=config.epic_bonus)
            print(f"{PREFIX} {epic_msg}")

        # Realm XP
        realm_state["total_xp"] = realm_state.get("total_xp", 0) + xp

        # Global skill XP
        global_state["skills"][skill] = global_state["skills"].get(skill, 0) + xp
        global_state["skill_tasks"][skill] = global_state["skill_tasks"].get(skill, 0) + 1

        # Priority counts
        p_key = f"{priority_str}_count"
        global_state[p_key] = global_state.get(p_key, 0) + 1

        # Shards
        earned_shards = int(xp * config.shard_rate)
        global_state["shards"] = global_state.get("shards", 0) + earned_shards

        # Cache entry
        cache[task_id] = {
            "xp": xp,
            "skill": skill,
            "date": date.today().isoformat(),
            "title": task.get("title", ""),
            "priority": priority_str,
            "is_epic": epic,
        }

        msg = fmt(config, "xp_gained", xp=xp, task_title=task.get("title", task_id))
        print(f"{PREFIX} {msg}")

        if earned_shards > 0:
            shard_msg = fmt(config, "new_shards", shards=earned_shards)
            print(f"{PREFIX} {shard_msg}")

        log_lines.append(f"- +{xp} XP [{skill}] — {task.get('title', task_id)}")

    # Level up detection
    old_lvl, _, _ = xp_to_level(realm_state.get("total_xp", 0) - sum(cache[t["id"]]["xp"] for t in new_tasks if t["id"] in cache), config.levels)
    new_lvl, new_title, _ = xp_to_level(realm_state["total_xp"], config.levels)
    if new_lvl > old_lvl:
        lvl_msg = fmt(config, "level_up", level=new_lvl, title=new_title)
        print(f"{PREFIX} {lvl_msg}")

    # Streak
    update_streak(global_state, len(new_tasks) > 0)

    # Achievements
    check_achievements(config, global_state, vault, realm, log_lines, max_unblocked)

    # Checkpoint
    total_xp = realm_state["total_xp"]
    last_cp_xp = realm_state.get("last_checkpoint_xp", 0)
    if (total_xp - last_cp_xp) >= config.checkpoint_interval:
        n = total_xp // config.checkpoint_interval
        write_checkpoint(vault, config, realm, realm_state, cache, n)
        realm_state["last_checkpoint_xp"] = total_xp

    # Save state
    save_cache(vault, realm, cache)
    save_realm_state(vault, realm, realm_state)
    save_global_state(vault, global_state)

    # Write Obsidian docs
    append_log(vault, realm, log_lines)
    write_realm_profile(vault, config, realm, realm_state, cache)
    write_global_md(vault, config, global_state)

    print(f"{PREFIX} Done. Processed {len(new_tasks)} new task(s).")


def cmd_status(config: Config, realm_filter: Optional[str] = None) -> None:
    vault = config.vault_path
    global_state = load_global_state(vault)

    if realm_filter:
        rs = load_realm_state(vault, realm_filter)
        total_xp = rs["total_xp"]
        lvl, title, next_xp = xp_to_level(total_xp, config.levels)
        if next_xp is not None:
            xp_to_next = next_xp - total_xp
        else:
            xp_to_next = 0
            next_xp = total_xp
        last_cp = rs.get("last_checkpoint_xp", 0)
        cp_remaining = config.checkpoint_interval - ((total_xp - last_cp) % config.checkpoint_interval)
        if cp_remaining == config.checkpoint_interval:
            cp_remaining = 0

        width = 40
        def row(text):
            return f"║  {text:<{width - 4}}║"

        print("╔" + "═" * (width - 2) + "╗")
        print(f"║       BnD — {realm_filter:<{width - 16}}║")
        print("╠" + "═" * (width - 2) + "╣")
        print(row(f"Level {lvl}    {title}"))
        print(row(f"XP    {total_xp} / {next_xp}  ({xp_to_next} to next)"))
        print(row(f"Next checkpoint: {cp_remaining} XP away"))
        print("╚" + "═" * (width - 2) + "╝")
    else:
        shards = global_state.get("shards", 0)
        streak = global_state.get("current_streak", 0)
        ach_count = len(global_state.get("achievements", []))
        total_ach = len(config.achievements)

        width = 42
        def row(text):
            return f"║  {text:<{width - 4}}║"

        print("╔" + "═" * (width - 2) + "╗")
        print(f"║       BnD — Global Character Sheet   ║")
        print("╠" + "═" * (width - 2) + "╣")
        print(row(f"{config.shard_symbol} Shards: {shards}   Streak: {streak} day(s)"))
        print(row(f"Achievements: {ach_count} / {total_ach}"))
        print("╠" + "═" * (width - 2) + "╣")
        print(row("Skills"))
        for sk in ["build", "debug", "design", "ops", "learn"]:
            xp = global_state["skills"].get(sk, 0)
            lvl, _, _ = xp_to_level(xp, config.levels)
            print(row(f"  {sk:<10} Lv.{lvl}   {xp} XP"))
        print("╠" + "═" * (width - 2) + "╣")
        print(row("Realms"))
        for r in list_realms(vault):
            rs = load_realm_state(vault, r)
            lvl, title, _ = xp_to_level(rs["total_xp"], config.levels)
            print(row(f"  {r:<14} Lv.{lvl}  {rs['total_xp']} XP  {title}"))
        print("╚" + "═" * (width - 2) + "╝")


def cmd_reset(config: Config, global_reset: bool = False) -> None:
    vault = config.vault_path

    if global_reset:
        print(f"{PREFIX} This will wipe ALL vault state and cache files.")
        confirm = input("Type 'yes' to confirm: ").strip()
        if confirm != "yes":
            print(f"{PREFIX} Aborted.")
            return
        for realm in list_realms(vault):
            for fname in [".bnd-realm.json", ".bnd-cache.json"]:
                p = vault / "realms" / realm / fname
                if p.exists():
                    p.unlink()
        gp = global_state_path(vault)
        if gp.exists():
            gp.unlink()
        print(f"{PREFIX} Global reset complete.")
    else:
        realm = get_realm_name()
        print(f"{PREFIX} This will wipe vault state and cache for realm '{realm}'.")
        confirm = input("Type 'yes' to confirm: ").strip()
        if confirm != "yes":
            print(f"{PREFIX} Aborted.")
            return
        for fname in [".bnd-realm.json", ".bnd-cache.json"]:
            p = vault / "realms" / realm / fname
            if p.exists():
                p.unlink()
        print(f"{PREFIX} Realm '{realm}' reset complete.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="bnd", description="BnD — Beads and Dragons XP system")
    parser.add_argument("--status", action="store_true", help="Print character sheet")
    parser.add_argument("--realm", type=str, help="Filter status to a specific realm")
    parser.add_argument("--reset", action="store_true", help="Reset state/cache")
    parser.add_argument("--global", dest="global_reset", action="store_true", help="Reset all realms globally")
    parser.add_argument("--config", type=str, default=None, help="Path to config file")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.status:
        cmd_status(config, realm_filter=args.realm)
    elif args.reset:
        cmd_reset(config, global_reset=args.global_reset)
    else:
        cmd_process(config)


if __name__ == "__main__":
    main()
