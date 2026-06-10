from __future__ import annotations

import json
import os
from pathlib import Path
import time

from bot_state import RunningGame
from game import MafiaGame, Player, Role, Winner
from role_data import ROLE_GUIDE_ORDER
from time_text import play_duration_text


BASE_DIR = Path(__file__).resolve().parent
STATS_FILE = BASE_DIR / "stats.json"


def original_stats_name(running: RunningGame, player: Player) -> str:
    return running.anonymous_original_names.get(player.user_id, player.name)


def load_stats() -> dict:
    if not STATS_FILE.exists():
        return {"users": {}}
    try:
        with STATS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {"users": {}}
    if not isinstance(data, dict):
        return {"users": {}}
    if not isinstance(data.get("users"), dict):
        data["users"] = {}
    changed = False
    for entry in data["users"].values():
        if not isinstance(entry, dict):
            continue
        if "play_seconds" not in entry:
            entry["play_seconds"] = 0
            changed = True
    if changed:
        save_stats(data)
    return data


def save_stats(stats: dict) -> None:
    temp_path = STATS_FILE.with_name(f"{STATS_FILE.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(stats, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temp_path, STATS_FILE)


def default_player_stats(name: str) -> dict:
    return {
        "name": name,
        "games": 0,
        "wins": 0,
        "losses": 0,
        "mafia_team_games": 0,
        "play_seconds": 0,
        "roles": {},
    }


def ensure_player_stats(stats: dict, user_id: int, name: str) -> dict:
    users = stats.setdefault("users", {})
    key = str(user_id)
    entry = users.get(key)
    if not isinstance(entry, dict):
        entry = default_player_stats(name)
        users[key] = entry
    entry["name"] = name
    entry.setdefault("games", 0)
    entry.setdefault("wins", 0)
    entry.setdefault("losses", 0)
    entry.setdefault("mafia_team_games", 0)
    entry.setdefault("play_seconds", 0)
    entry.setdefault("roles", {})
    return entry


def initial_role_for_stats(running: RunningGame, player: Player) -> Role:
    return running.initial_roles.get(player.user_id, player.role)


def is_mafia_team_role(role: Role) -> bool:
    return role in {Role.MAFIA, Role.SPY, Role.CONTRACTOR, Role.WITCH, Role.SCIENTIST, Role.GODFATHER, Role.VILLAIN}


def player_won_game(game: MafiaGame, player: Player, winner: Winner) -> bool:
    if winner == Winner.MAFIA:
        return game.is_mafia_team(player)
    if winner == Winner.CULT:
        return game.is_cult_team(player)
    if winner == Winner.JOKER:
        joker_winner_id = getattr(game, "joker_winner_id", None)
        return player.user_id == joker_winner_id or (joker_winner_id is None and player.role == Role.JOKER)
    return game.is_citizen_team(player)


def record_game_stats(running: RunningGame, winner: Winner) -> None:
    if running.stats_recorded:
        return
    stats = load_stats()
    elapsed_seconds = max(0, int(time.monotonic() - running.started_at))
    for player in running.game.players:
        name = original_stats_name(running, player) if running.anonymous_enabled else player.name
        entry = ensure_player_stats(stats, player.user_id, name)
        entry["games"] = int(entry.get("games", 0)) + 1
        entry["play_seconds"] = int(entry.get("play_seconds", 0)) + elapsed_seconds
        role = initial_role_for_stats(running, player)
        roles = entry.setdefault("roles", {})
        roles[role.value] = int(roles.get(role.value, 0)) + 1
        if is_mafia_team_role(role):
            entry["mafia_team_games"] = int(entry.get("mafia_team_games", 0)) + 1
        if player_won_game(running.game, player, winner):
            entry["wins"] = int(entry.get("wins", 0)) + 1
        else:
            entry["losses"] = int(entry.get("losses", 0)) + 1
    save_stats(stats)
    running.stats_recorded = True


def win_rate_text(wins: int, games: int) -> str:
    if games <= 0:
        return "0.0%"
    return f"{wins / games * 100:.1f}%"


def role_stats_text(entry: dict) -> str:
    roles = entry.get("roles", {})
    if not isinstance(roles, dict) or not roles:
        return "없음"
    ordered_roles = {role.value: index for index, role in enumerate(ROLE_GUIDE_ORDER)}
    items = sorted(
        roles.items(),
        key=lambda item: (-int(item[1]), ordered_roles.get(item[0], 999), item[0]),
    )
    return ", ".join(f"{role} {count}회" for role, count in items)


def personal_stats_text(user_id: int, fallback_name: str) -> str:
    stats = load_stats()
    entry = stats.get("users", {}).get(str(user_id))
    if not isinstance(entry, dict):
        return "아직 기록된 게임 전적이 없습니다."
    games = int(entry.get("games", 0))
    wins = int(entry.get("wins", 0))
    losses = int(entry.get("losses", 0))
    mafia_games = int(entry.get("mafia_team_games", 0))
    play_seconds = int(entry.get("play_seconds", 0))
    name = str(entry.get("name") or fallback_name)
    return (
        f"{name}님의 전적\n"
        f"전체 게임: **{games}판**\n"
        f"승리/패배: **{wins}승 {losses}패**\n"
        f"승률: **{win_rate_text(wins, games)}**\n"
        f"마피아팀 플레이: **{mafia_games}회**\n"
        f"게임시간: **{play_duration_text(play_seconds)}**\n\n"
        f"역할별 플레이\n{role_stats_text(entry)}"
    )


def leaderboard_value(entry: dict, metric: str) -> float:
    games = int(entry.get("games", 0))
    wins = int(entry.get("wins", 0))
    if metric == "winrate":
        return wins / games if games else 0.0
    if metric == "games":
        return float(games)
    if metric == "mafia":
        return float(entry.get("mafia_team_games", 0))
    if metric == "playtime":
        return float(entry.get("play_seconds", 0))
    return float(wins)


def leaderboard_text(metric: str) -> str:
    stats = load_stats()
    users = stats.get("users", {})
    if not isinstance(users, dict) or not users:
        return "아직 기록된 게임 전적이 없습니다."
    entries = [
        (user_id, entry)
        for user_id, entry in users.items()
        if isinstance(entry, dict) and int(entry.get("games", 0)) > 0
    ]
    if not entries:
        return "아직 기록된 게임 전적이 없습니다."
    metric_names = {
        "wins": "승리수",
        "winrate": "승률",
        "games": "판수",
        "mafia": "마피아팀 플레이",
        "playtime": "게임시간",
    }
    entries.sort(
        key=lambda item: (
            -leaderboard_value(item[1], metric),
            -int(item[1].get("wins", 0)),
            -int(item[1].get("games", 0)),
            str(item[1].get("name", "")),
        )
    )
    lines = [f"기준: **{metric_names.get(metric, '승리수')}**"]
    for rank, (_user_id, entry) in enumerate(entries[:10], start=1):
        games = int(entry.get("games", 0))
        wins = int(entry.get("wins", 0))
        losses = int(entry.get("losses", 0))
        mafia_games = int(entry.get("mafia_team_games", 0))
        play_seconds = int(entry.get("play_seconds", 0))
        lines.append(
            f"{rank}. **{entry.get('name', '알 수 없음')}** - "
            f"{wins}승 {losses}패 / {games}판 / 승률 {win_rate_text(wins, games)} / "
            f"마피아팀 {mafia_games}회 / 게임시간 {play_duration_text(play_seconds)}"
        )
    return "\n".join(lines)
