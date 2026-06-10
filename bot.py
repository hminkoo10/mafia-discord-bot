from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import fields
import json
import os
from pathlib import Path
import secrets
import sys
import time

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import uvicorn

from game import MafiaGame, NightResult, Phase, Player, Role, VoteResult, Winner
from bot_constants import (
    RECRUITMENT_SECONDS,
    MAX_GAME_PLAYERS,
    DAY_EXTENSION_VOTE_SECONDS,
    DISCUSSION_EXTENSION_SECONDS,
    CONFIRM_VOTE_SECONDS,
    GAME_NOTIFICATION_ROLE,
    DEAD_PLAYER_ROLE,
    SPECTATOR_ROLE,
    OLD_DEAD_CHAT_CHANNEL_NAME,
    SHAMAN_CHAT_CHANNEL_NAME,
    FROG_CHAT_CHANNEL_NAME,
    PRIVATE_CHAT_ROLES,
    PRIVATE_CHANNEL_NAMES,
    CITIZEN_SPECIAL_ROLES,
    MAFIA_SPECIAL_ROLES,
    NEUTRAL_SPECIAL_ROLES,
    PUBLIC_MAFIA_SPECIAL_ROLES,
    PUBLIC_CITIZEN_SPECIAL_ROLES,
    PUBLIC_NEUTRAL_SPECIAL_ROLES,
    PUBLIC_CULT_SPECIAL_ROLES,
    CONTRACTOR_GUESS_ROLES,
    DEFAULT_EMBED_COLOR,
    ERROR_EMBED_COLOR,
    SUCCESS_EMBED_COLOR,
    WARNING_EMBED_COLOR,
    DayDiscussionResult,
    ANIMAL_ALIASES,
    ANIMAL_EMOJI_CODES,
    NUMBER_AVATAR_COLORS,
)
from bot_state import BotConfig, RunningGame, TimedNightEvents
from role_data import (
    ROLE_GUIDE_ORDER,
    ROLE_TEAM_TEXT,
    ROLE_GOAL_TEXT,
    ROLE_ABILITY_TEXTS,
    ROLE_RULE_TEXTS,
    ROLE_GUIDE_COMMON_TEXT,
    MAFIA_TERM_ENTRIES,
)
from stats_store import (
    default_player_stats,
    ensure_player_stats,
    initial_role_for_stats,
    is_mafia_team_role,
    leaderboard_text,
    leaderboard_value,
    load_stats,
    personal_stats_text,
    player_won_game,
    record_game_stats,
    role_stats_text,
    save_stats,
    win_rate_text,
)
from time_text import duration_text, play_duration_text
import web_settings


sys.modules.setdefault("bot", sys.modules[__name__])

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
CONFIG_EXAMPLE_FILE = BASE_DIR / "config.example.json"
STATS_FILE = BASE_DIR / "stats.json"

# /마피아웹설정 명령어가 발급하는 1회용 설정 편집 링크 관련 상수.
WEB_SETTINGS_PATH = "/web-settings"
WEB_SETTINGS_SESSION_TTL_SECONDS = 600
WEB_SETTINGS_DEFAULT_HOST = "0.0.0.0"
WEB_SETTINGS_DEFAULT_PORT = 8800


def parse_user_id_list(values: object) -> list[int]:
    if not isinstance(values, list):
        return []
    user_ids: set[int] = set()
    for value in values:
        with suppress(TypeError, ValueError):
            user_ids.add(int(value))
    return sorted(user_ids)


def load_config() -> BotConfig:
    if not CONFIG_FILE.exists():
        if CONFIG_EXAMPLE_FILE.exists():
            CONFIG_FILE.write_text(CONFIG_EXAMPLE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            raise FileNotFoundError("config.json 파일이 없습니다. config.example.json을 복사해 config.json을 만들어 주세요.")

    with CONFIG_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return BotConfig(
        participant_role=str(data["participant_role"]),
        manager_role=str(data["manager_role"]),
        default_mafia_count=int(data["default_mafia_count"]),
        default_doctor_count=int(data["default_doctor_count"]),
        default_police_count=int(data["default_police_count"]),
        default_joker_count=int(data.get("default_joker_count", 1)),
        max_player_count=int(data.get("max_player_count", 0)),
        night_seconds=int(data["night_seconds"]),
        discussion_seconds=int(data.get("discussion_seconds", 60)),
        vote_seconds=int(data["vote_seconds"]),
        chat_slowmode_seconds=int(data.get("chat_slowmode_seconds", 3)),
        reveal_death_roles=bool(data.get("reveal_death_roles", False)),
        reveal_public_police_status=bool(data.get("reveal_public_police_status", True)),
        reveal_morning_mafia_count=bool(data.get("reveal_morning_mafia_count", True)),
        citizen_special_count=int(data.get("citizen_special_count", 0)),
        mafia_special_count=int(data.get("mafia_special_count", 0)),
        neutral_special_count=int(data.get("neutral_special_count", data.get("default_joker_count", 1))),
        enable_detective=bool(data.get("enable_detective", True)),
        enable_graverobber=bool(data.get("enable_graverobber", True)),
        enable_spy=bool(data.get("enable_spy", True)),
        enable_contractor=bool(data.get("enable_contractor", True)),
        enable_witch=bool(data.get("enable_witch", True)),
        enable_scientist=bool(data.get("enable_scientist", True)),
        enable_madam=bool(data.get("enable_madam", True)),
        enable_godfather=bool(data.get("enable_godfather", True)),
        enable_joker=bool(data.get("enable_joker", True)),
        enable_politician=bool(data.get("enable_politician", True)),
        enable_judge=bool(data.get("enable_judge", True)),
        enable_reporter=bool(data.get("enable_reporter", True)),
        enable_hacker=bool(data.get("enable_hacker", True)),
        enable_terrorist=bool(data.get("enable_terrorist", True)),
        enable_lover=bool(data.get("enable_lover", True)),
        enable_shaman=bool(data.get("enable_shaman", True)),
        enable_priest=bool(data.get("enable_priest", True)),
        enable_soldier=bool(data.get("enable_soldier", True)),
        enable_nurse=bool(data.get("enable_nurse", True)),
        enable_cult_team=bool(data.get("enable_cult_team", False)),
        use_agent=bool(data.get("use_agent", False)),
        use_vigilante=bool(data.get("use_vigilante", False)),
        anonymous_mode=bool(data.get("anonymous_mode", False)),
        anonymous_name_mode=str(data.get("anonymous_name_mode", "animal")),
        game_enabled=bool(data.get("game_enabled", True)),
        blacklist_user_ids=parse_user_id_list(data.get("blacklist_user_ids", [])),
    )


config = load_config()
games: dict[int, RunningGame] = {}
recruiting_guilds: set[int] = set()
known_presence_statuses: dict[tuple[int, int], discord.Status | str] = {}

def config_to_dict(value: BotConfig) -> dict[str, object]:
    return {item.name: getattr(value, item.name) for item in fields(BotConfig)}


def save_config() -> None:
    saved_data: dict[str, object] = {}
    with suppress(OSError, json.JSONDecodeError):
        with CONFIG_FILE.open("r", encoding="utf-8") as file:
            existing_data = json.load(file)
        if isinstance(existing_data, dict):
            saved_data.update(existing_data)

    saved_data.update(config_to_dict(config))
    temp_path = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(saved_data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temp_path, CONFIG_FILE)


# --- /마피아웹설정: 브라우저에서 설정을 편집할 수 있는 1회용 링크 -------------------

web_settings_sessions = web_settings.WebSettingsSessionStore(ttl_seconds=WEB_SETTINGS_SESSION_TTL_SECONDS)


def web_config_values() -> dict[str, object]:
    return {spec.name: getattr(config, spec.name) for spec in web_settings.EDITABLE_FIELDS}


def apply_web_config_updates(updates: dict[str, object]) -> str | None:
    """웹 폼에서 제출된 설정 값을 적용합니다.

    `/마피아설정` 명령어와 동일하게, 적용 후 특수 역할 조합이 모집 인원과
    맞는지 검증하고 실패하면 이전 값으로 되돌립니다. 성공하면 ``config.json``
    까지 저장하고 ``None`` 을, 실패하면 사용자에게 보여줄 오류 메시지를
    돌려줍니다.
    """

    if int(updates.get("default_mafia_count", config.default_mafia_count)) < 1:
        return "마피아는 최소 1명이어야 합니다."

    previous = {key: getattr(config, key) for key in updates}
    for key, value in updates.items():
        setattr(config, key, value)

    try:
        role_counts = selected_role_counts(choose_special_roles())
        validate_max_player_count(role_counts, config.max_player_count)
    except ValueError as error:
        for key, value in previous.items():
            setattr(config, key, value)
        return str(error)

    save_config()
    return None


web_settings_app = web_settings.create_app(
    sessions=web_settings_sessions,
    get_config_values=web_config_values,
    apply_config_updates=apply_web_config_updates,
    base_path=WEB_SETTINGS_PATH,
)


def web_settings_base_url() -> str:
    """사용자에게 보여줄 설정 페이지의 기본 URL을 계산합니다.

    `WEB_SETTINGS_BASE_URL` 환경 변수가 있으면 그대로 사용하고(리버스 프록시나
    도메인을 쓰는 경우), 없으면 호스트/포트로부터 추정합니다.
    """

    base_url = os.getenv("WEB_SETTINGS_BASE_URL")
    if base_url:
        return base_url.rstrip("/")
    host = os.getenv("WEB_SETTINGS_HOST", WEB_SETTINGS_DEFAULT_HOST)
    port = os.getenv("WEB_SETTINGS_PORT", str(WEB_SETTINGS_DEFAULT_PORT))
    display_host = "localhost" if host in ("0.0.0.0", "::") else host
    return f"http://{display_host}:{port}"


def remember_member_presence(guild_id: int, member: discord.Member) -> None:
    raw_status = getattr(member, "raw_status", "offline")
    if raw_status != "offline":
        known_presence_statuses[(guild_id, member.id)] = member.status


def remember_presence_update(before: discord.Member, after: discord.Member) -> None:
    known_presence_statuses[(after.guild.id, after.id)] = after.status


def member_is_confirmed_offline(guild_id: int, member: discord.Member) -> bool:
    guild = bot.get_guild(guild_id)
    cached_member = guild.get_member(member.id) if guild else None
    for candidate in (cached_member, member):
        if not isinstance(candidate, discord.Member):
            continue
        raw_status = getattr(candidate, "raw_status", "offline")
        if raw_status != "offline":
            known_presence_statuses[(guild_id, candidate.id)] = candidate.status
            return False

    status = known_presence_statuses.get((guild_id, member.id))
    return status in {discord.Status.offline, "offline"}


def member_has_role(member: discord.Member, role_name: str) -> bool:
    return any(role.name == role_name for role in member.roles)


def require_manager(interaction: discord.Interaction) -> discord.Member:
    if not isinstance(interaction.user, discord.Member):
        raise app_commands.CheckFailure("서버 안에서만 사용할 수 있습니다.")
    if not member_has_role(interaction.user, config.manager_role):
        raise app_commands.CheckFailure(
            f"'{config.manager_role}' 역할을 가진 사람만 사용할 수 있습니다."
        )
    return interaction.user


def display_name(member: discord.Member) -> str:
    return member.nick or member.global_name or member.name


def blacklist_user_ids() -> set[int]:
    return set(parse_user_id_list(config.blacklist_user_ids))


def is_blacklisted(user_id: int) -> bool:
    return user_id in blacklist_user_ids()


def set_blacklist_status(user_id: int, blacklisted: bool) -> bool:
    user_ids = blacklist_user_ids()
    was_blacklisted = user_id in user_ids
    if blacklisted:
        user_ids.add(user_id)
    else:
        user_ids.discard(user_id)
    config.blacklist_user_ids = sorted(user_ids)
    return was_blacklisted != blacklisted


def special_role_rule_text(role: Role) -> str:
    if role == Role.LOVER:
        return (
            "연인은 두 명이 함께 배정됩니다.\n"
            "연인 대화방은 밤에만 열리며, 두 연인이 모두 생존 중일 때 사용할 수 있습니다."
        )
    action = {
        Role.MAFIA: "공격",
        Role.DOCTOR: "보호",
        Role.POLICE: "조사",
        Role.AGENT: "공작",
        Role.VIGILANTE: "숙청",
    }.get(role, "행동")
    return (
        f"{role.value}가 여러 명이면 같은 대상이 살아있는 {role.value} 인원의 "
        f"과반 초과를 받아야 {action}이 행사됩니다.\n"
        "동률이거나 과반에 못 미치면 그 밤 행동은 행사되지 않습니다."
    )


def selected_role_counts(
    special_roles: list[Role] | None = None,
) -> dict[Role, int]:
    selected_special_roles = special_roles or []
    mafia_special_count = sum(1 for role in selected_special_roles if role in MAFIA_SPECIAL_ROLES)
    if mafia_special_count > config.default_mafia_count:
        raise ValueError(
            "마피아 특수룰 수는 전체 마피아 수보다 많을 수 없습니다. "
            f"현재 마피아 {config.default_mafia_count}명, 마피아 특수 {mafia_special_count}명입니다."
        )
    if config.default_mafia_count - mafia_special_count < 1:
        raise ValueError(
            "접선 전 특수 마피아만으로는 게임을 진행할 수 없습니다. "
            "일반 마피아가 최소 1명 필요합니다."
        )
    investigation_role = random_investigation_role()
    role_counts = {
        Role.MAFIA: config.default_mafia_count - mafia_special_count,
        Role.DOCTOR: config.default_doctor_count,
    }
    if config.default_police_count > 0:
        role_counts[investigation_role] = config.default_police_count
    for role in selected_special_roles:
        role_counts[role] = role_counts.get(role, 0) + special_role_player_count(role)
    if config.enable_cult_team:
        role_counts[Role.CULT_LEADER] = role_counts.get(Role.CULT_LEADER, 0) + 1
        role_counts[Role.FANATIC] = role_counts.get(Role.FANATIC, 0) + 1
    return role_counts


def enabled_special_roles(pool: tuple[Role, ...]) -> list[Role]:
    enabled = {
        Role.DETECTIVE: config.enable_detective,
        Role.SHAMAN: config.enable_shaman,
        Role.GRAVEROBBER: config.enable_graverobber,
        Role.SPY: config.enable_spy,
        Role.CONTRACTOR: config.enable_contractor,
        Role.WITCH: config.enable_witch,
        Role.SCIENTIST: config.enable_scientist,
        Role.MADAM: config.enable_madam,
        Role.GODFATHER: config.enable_godfather,
        Role.JOKER: config.enable_joker,
        Role.POLITICIAN: config.enable_politician,
        Role.JUDGE: config.enable_judge,
        Role.REPORTER: config.enable_reporter,
        Role.HACKER: config.enable_hacker,
        Role.TERRORIST: config.enable_terrorist,
        Role.LOVER: config.enable_lover,
        Role.PRIEST: config.enable_priest,
        Role.SOLDIER: config.enable_soldier,
        Role.NURSE: config.enable_nurse,
    }
    return [role for role in pool if enabled[role]]


def choose_special_roles() -> list[Role]:
    selected: list[Role] = []
    for pool, count in (
        (CITIZEN_SPECIAL_ROLES, config.citizen_special_count),
        (MAFIA_SPECIAL_ROLES, config.mafia_special_count),
        (NEUTRAL_SPECIAL_ROLES, config.neutral_special_count),
    ):
        candidates = enabled_special_roles(pool)
        if count > len(candidates):
            raise ValueError(
                f"{', '.join(role.value for role in pool)} 중 활성화된 역할보다 선택할 특수룰 수가 많습니다."
            )
        selected.extend(random_sample_roles(candidates, count))
    return selected


def special_role_player_count(role: Role) -> int:
    return 2 if role == Role.LOVER else 1


def expand_special_roles_for_game(roles: list[Role]) -> list[Role]:
    expanded: list[Role] = []
    for role in roles:
        expanded.extend([role] * special_role_player_count(role))
    return expanded


def random_sample_roles(candidates: list[Role], count: int) -> list[Role]:
    return secrets.SystemRandom().sample(candidates, count) if count > 0 else []


def investigation_role_candidates() -> list[Role]:
    candidates = [Role.POLICE]
    if config.use_agent:
        candidates.append(Role.AGENT)
    if config.use_vigilante:
        candidates.append(Role.VIGILANTE)
    return candidates


def random_investigation_role() -> Role:
    return secrets.choice(investigation_role_candidates())


def minimum_player_count(role_counts: dict[Role, int]) -> int:
    special_count = sum(role_counts.values())
    mafia_count = (
        role_counts.get(Role.MAFIA, 0)
        + role_counts.get(Role.SPY, 0)
        + role_counts.get(Role.CONTRACTOR, 0)
        + role_counts.get(Role.MADAM, 0)
        + role_counts.get(Role.GODFATHER, 0)
    )
    return max(3, special_count, mafia_count * 2 + 1)


def effective_max_player_count() -> int:
    if config.max_player_count <= 0:
        return MAX_GAME_PLAYERS
    return min(config.max_player_count, MAX_GAME_PLAYERS)


def max_player_setting_text() -> str:
    if config.max_player_count <= 0:
        return f"제한 없음(봇 최대 {MAX_GAME_PLAYERS}명)"
    return f"{effective_max_player_count()}명"


def validate_max_player_count(role_counts: dict[Role, int], max_players: int) -> None:
    if max_players < 0:
        raise ValueError("최대 인원은 0 이상이어야 합니다. 0은 제한 없음입니다.")
    if max_players > MAX_GAME_PLAYERS:
        raise ValueError(f"최대 인원은 {MAX_GAME_PLAYERS}명 이하로 설정해야 합니다.")
    minimum_players = minimum_player_count(role_counts)
    if max_players and max_players < minimum_players:
        raise ValueError(
            f"현재 설정의 최소 시작 인원은 {minimum_players}명이라 "
            f"최대 인원을 {max_players}명으로 설정할 수 없습니다."
        )


def count_role_group(role_counts: dict[Role, int], roles: tuple[Role, ...]) -> int:
    return sum(role_counts.get(role, 0) for role in roles)


def investigation_candidates_text() -> str:
    return ", ".join(role.value for role in investigation_role_candidates())


def public_role_count_text_from_counts(
    role_counts: dict[Role, int],
    total_players: int | None = None,
) -> str:
    mafia_special = count_role_group(role_counts, PUBLIC_MAFIA_SPECIAL_ROLES)
    mafia_total = role_counts.get(Role.MAFIA, 0) + mafia_special
    doctor_total = role_counts.get(Role.DOCTOR, 0)
    police_total = role_counts.get(Role.POLICE, 0)
    agent_total = role_counts.get(Role.AGENT, 0)
    vigilante_total = role_counts.get(Role.VIGILANTE, 0)
    citizen_special = count_role_group(role_counts, PUBLIC_CITIZEN_SPECIAL_ROLES)
    neutral_special = count_role_group(role_counts, PUBLIC_NEUTRAL_SPECIAL_ROLES)
    cult_total = count_role_group(role_counts, PUBLIC_CULT_SPECIAL_ROLES)

    if total_players is None:
        citizen_text = f"시민 변동(중 특수 {citizen_special}명)"
    else:
        citizen_total = max(
            0,
            total_players
            - mafia_total
            - doctor_total
            - police_total
            - agent_total
            - vigilante_total
            - neutral_special
            - cult_total,
        )
        citizen_text = f"시민 {citizen_total}명(중 특수 {citizen_special}명)"

    investigation_total = police_total + agent_total + vigilante_total
    investigation_text = f"수사직 {investigation_total}명"
    parts = [
        f"마피아 {mafia_total}명(중 특수 {mafia_special}명)",
        f"의사 {doctor_total}명",
        investigation_text,
        citizen_text,
    ]
    if neutral_special > 0:
        parts.append(f"중립 특수 {neutral_special}명")
    if cult_total > 0:
        parts.append(f"교주팀 {cult_total}명")
    return ", ".join(parts)


def public_role_count_text(game: MafiaGame) -> str:
    role_counts: dict[Role, int] = {}
    for player in game.players:
        role_counts[player.role] = role_counts.get(player.role, 0) + 1
    return "역할 구성: " + public_role_count_text_from_counts(role_counts, len(game.players))


def public_game_settings_text(game: MafiaGame, prefix: str = "게임 방 설정입니다.") -> str:
    return (
        f"{prefix}\n"
        f"{public_role_count_text(game)}\n"
        f"최대 참가 인원: {max_player_setting_text()}\n"
        f"교주팀: {'켜짐 - 교주 1명, 광신도 1명 필수 배정' if config.enable_cult_team else '꺼짐'}\n"
        f"사망 시 직업 공개: {'공개' if config.reveal_death_roles else '비공개'}\n"
        f"경찰 조사 성공 여부 공개: {'공개' if config.reveal_public_police_status else '비공개'}\n"
        f"아침 생존 마피아 수 공개: {'공개' if config.reveal_morning_mafia_count else '비공개'}\n"
        f"채팅 슬로우모드: {config.chat_slowmode_seconds}초\n"
        f"익명 채팅: {'켜짐' if config.anonymous_mode else '꺼짐'}"
        f"{f' ({anonymous_name_mode_text()})' if config.anonymous_mode else ''}"
    )


def normalized_anonymous_name_mode() -> str:
    return config.anonymous_name_mode if config.anonymous_name_mode in {"animal", "number"} else "animal"


def anonymous_name_mode_text() -> str:
    return "숫자 이름" if normalized_anonymous_name_mode() == "number" else "동물 이름"


def current_settings_text(prefix: str = "마피아 설정을 저장했습니다.") -> str:
    enabled = [
        role.value
        for role in (
            Role.DETECTIVE,
            Role.SHAMAN,
            Role.GRAVEROBBER,
            Role.SPY,
            Role.CONTRACTOR,
            Role.WITCH,
            Role.SCIENTIST,
            Role.MADAM,
            Role.GODFATHER,
            Role.JOKER,
            Role.POLITICIAN,
            Role.JUDGE,
            Role.REPORTER,
            Role.HACKER,
            Role.TERRORIST,
            Role.LOVER,
            Role.PRIEST,
            Role.SOLDIER,
            Role.NURSE,
            Role.CULT_LEADER,
            Role.FANATIC,
        )
        if {
            Role.DETECTIVE: config.enable_detective,
            Role.SHAMAN: config.enable_shaman,
            Role.GRAVEROBBER: config.enable_graverobber,
            Role.SPY: config.enable_spy,
            Role.CONTRACTOR: config.enable_contractor,
            Role.WITCH: config.enable_witch,
            Role.SCIENTIST: config.enable_scientist,
            Role.MADAM: config.enable_madam,
            Role.GODFATHER: config.enable_godfather,
            Role.JOKER: config.enable_joker,
            Role.POLITICIAN: config.enable_politician,
            Role.JUDGE: config.enable_judge,
            Role.REPORTER: config.enable_reporter,
            Role.HACKER: config.enable_hacker,
            Role.TERRORIST: config.enable_terrorist,
            Role.LOVER: config.enable_lover,
            Role.PRIEST: config.enable_priest,
            Role.SOLDIER: config.enable_soldier,
            Role.NURSE: config.enable_nurse,
            Role.CULT_LEADER: config.enable_cult_team,
            Role.FANATIC: config.enable_cult_team,
        }[role]
    ]
    return (
        f"{prefix}\n"
        f"게임 상태: {'활성화' if config.game_enabled else '비활성화'}\n"
        f"기본 직업: 마피아 {config.default_mafia_count}명, "
        f"의사 {config.default_doctor_count}명, "
        f"수사직 {config.default_police_count}명\n"
        f"최대 참가 인원: {max_player_setting_text()}\n"
        f"특수룰 수: 시민 {config.citizen_special_count}개, "
        f"마피아 {config.mafia_special_count}개, 중립 {config.neutral_special_count}개\n"
        f"활성 특수룰: {', '.join(enabled) if enabled else '없음'}\n"
        f"수사직 후보: {investigation_candidates_text()}\n"
        f"교주팀: {'켜짐 - 교주 1명, 광신도 1명 필수 배정' if config.enable_cult_team else '꺼짐'}\n"
        f"채팅 슬로우모드: {config.chat_slowmode_seconds}초\n"
        f"사망 시 직업 공개: {'공개' if config.reveal_death_roles else '비공개'}\n"
        f"경찰 조사 성공 여부 공개: {'공개' if config.reveal_public_police_status else '비공개'}\n"
        f"아침 생존 마피아 수 공개: {'공개' if config.reveal_morning_mafia_count else '비공개'}\n"
        f"익명 채팅: {'켜짐' if config.anonymous_mode else '꺼짐'}\n"
        f"익명 이름 방식: {anonymous_name_mode_text()}"
    )


def disable_view_items(view: discord.ui.View | None) -> None:
    if not view:
        return
    for item in view.children:
        if hasattr(item, "disabled"):
            item.disabled = True


def target_select_label(target: Player, actor_id: int) -> str:
    label = f"{target.name}(나)" if target.user_id == actor_id else target.name
    return label[:100]


def make_embed(
    message: str,
    *,
    title: str = "마피아 게임",
    color: discord.Color = DEFAULT_EMBED_COLOR,
) -> discord.Embed:
    lines = message.splitlines()
    if lines:
        first_line = lines[0] if "**" in lines[0] else f"**{lines[0]}**"
        description = "\n".join([first_line, *lines[1:]])
    else:
        description = message

    embed = discord.Embed(
        title=f"[마피아] {title}",
        description=description,
        color=color,
    )
    embed.set_author(name="마피아 게임 알림")
    embed.set_footer(text="마피아 게임 진행 메시지")
    return embed


async def send_embed(
    channel: discord.abc.Messageable,
    message: str,
    *,
    view: discord.ui.View | None = None,
    title: str = "마피아 게임",
    color: discord.Color = DEFAULT_EMBED_COLOR,
) -> discord.Message:
    return await channel.send(embed=make_embed(message, title=title, color=color), view=view)


async def send_private(
    member: discord.Member,
    message: str,
    view: discord.ui.View | None = None,
) -> bool:
    try:
        await member.send(embed=make_embed(message, title="비밀 메시지"), view=view)
        return True
    except discord.Forbidden:
        return False


async def send_interaction_reply(
    interaction: discord.Interaction,
    message: str,
    *,
    private: bool,
) -> None:
    ephemeral = private and interaction.guild is not None
    embed = make_embed(
        message,
        color=ERROR_EMBED_COLOR if private else DEFAULT_EMBED_COLOR,
    )
    if interaction.response.is_done():
        with suppress(discord.HTTPException, discord.NotFound):
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
    else:
        try:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        except discord.NotFound:
            with suppress(discord.HTTPException, discord.NotFound):
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)


def status_display_name(running: RunningGame, player: Player) -> str:
    if running.anonymous_enabled:
        return running.anonymous_aliases.get(player.user_id, player.name)
    return player.name


def status_player_list(running: RunningGame, players: list[Player]) -> str:
    if not players:
        return "없음"
    sorted_players = sorted(
        players,
        key=lambda player: status_display_name(running, player).casefold(),
    )
    names = [status_display_name(running, player) for player in sorted_players]
    shown = names[:40]
    suffix = f" 외 {len(names) - len(shown)}명" if len(names) > len(shown) else ""
    return ", ".join(shown) + suffix


def game_status_text(running: RunningGame) -> str:
    alive = running.game.alive_players()
    dead = running.game.dead_players()
    return (
        f"{running.game.day_number}일차 / 현재 단계: {running.game.phase.value}\n"
        f"생존자 **{len(alive)}명** / 사망자 **{len(dead)}명**\n\n"
        f"생존자 목록\n{status_player_list(running, alive)}\n\n"
        f"사망자 목록\n{status_player_list(running, dead)}"
    )


def private_role_status_players(running: RunningGame, player: Player) -> tuple[str, list[Player]]:
    game = running.game
    if game.is_cult_team(player):
        return "내 교주팀", [target for target in game.players if game.is_cult_team(target)]
    if game.is_known_mafia_team(player):
        return "내 마피아팀", [target for target in game.players if game.is_known_mafia_team(target)]
    return f"내 역할({player.role.value})", [target for target in game.players if target.role == player.role]


def command_status_text(running: RunningGame, requester_id: int) -> str:
    message = game_status_text(running)
    player = running.game.get_player(requester_id)
    if not running.anonymous_enabled or not player:
        return message

    label, same_group = private_role_status_players(running, player)
    alive = [target for target in same_group if target.alive]
    dead = [target for target in same_group if not target.alive]
    return (
        f"{message}\n\n"
        f"{label} 현황\n"
        f"생존 **{len(alive)}명** / 사망 **{len(dead)}명**\n"
        f"생존: {status_player_list(running, alive)}\n"
        f"사망: {status_player_list(running, dead)}"
    )


def memo_target_name(running: RunningGame, player: Player) -> str:
    return status_display_name(running, player)


def memo_chunks(running: RunningGame, target: Player, memos: list[str]) -> list[str]:
    target_name = memo_target_name(running, target)
    header = f"{target_name} 님에 대한 메모"
    if not memos:
        return [f"{header}\n저장된 메모가 없습니다."]

    chunks: list[str] = []
    current = header
    for index, memo in enumerate(memos, start=1):
        line = f"{index}. {memo}"
        if len(current) + len(line) + 1 > 3500:
            chunks.append(current)
            current = f"{header} (계속)\n{line}"
        else:
            current += "\n" + line
    chunks.append(current)
    return chunks


async def upsert_game_status(guild: discord.Guild, running: RunningGame) -> None:
    channel = guild.get_channel(running.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    embed = make_embed(game_status_text(running), title="게임 현황", color=SUCCESS_EMBED_COLOR)
    if running.game_status_message_id:
        try:
            message = await channel.fetch_message(running.game_status_message_id)
            await message.edit(embed=embed)
            return
        except discord.DiscordException:
            pass

    with suppress(discord.DiscordException):
        message = await channel.send(embed=embed)
        running.game_status_message_id = message.id


async def wait_for_event_or_timeout(event: asyncio.Event, seconds: int) -> None:
    try:
        await asyncio.wait_for(event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return


def create_logged_background_task(coro, label: str) -> asyncio.Task:
    task = asyncio.create_task(coro)

    def log_task_error(done_task: asyncio.Task) -> None:
        error = None
        with suppress(asyncio.CancelledError):
            error = done_task.exception()
        if error:
            print(f"{label} error: {error!r}")

    task.add_done_callback(log_task_error)
    return task


async def wait_for_day_vote_or_timeout(running: RunningGame, seconds: int) -> bool:
    if running.day_vote_event.is_set():
        return True

    vote_task = asyncio.create_task(running.day_vote_event.wait())
    timeout_task = asyncio.create_task(asyncio.sleep(seconds))
    _done, pending = await asyncio.wait(
        {vote_task, timeout_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    return running.day_vote_event.is_set()


async def wait_for_day_vote_or_view(running: RunningGame, view: discord.ui.View) -> bool:
    if running.day_vote_event.is_set():
        return True

    vote_task = asyncio.create_task(running.day_vote_event.wait())
    view_task = asyncio.create_task(view.wait())
    _done, pending = await asyncio.wait(
        {vote_task, view_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    return running.day_vote_event.is_set()


async def disable_message_view(message: discord.Message, view: discord.ui.View) -> None:
    disable_view_items(view)
    try:
        await message.edit(view=view)
    except discord.DiscordException:
        pass


class JoinGameView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        host_user_id: int,
        participant_role_id: int,
        role_counts: dict[Role, int],
        reveal_death_roles: bool,
        reveal_public_police_status: bool,
        reveal_morning_mafia_count: bool,
        max_players: int,
    ) -> None:
        super().__init__(timeout=RECRUITMENT_SECONDS + 5)
        self.guild_id = guild_id
        self.host_user_id = host_user_id
        self.participant_role_id = participant_role_id
        self.role_counts = role_counts
        self.reveal_death_roles = reveal_death_roles
        self.reveal_public_police_status = reveal_public_police_status
        self.reveal_morning_mafia_count = reveal_morning_mafia_count
        self.max_players = max_players
        self.minimum_players = minimum_player_count(role_counts)
        self.joined_ids: set[int] = set()
        self.joined_names: dict[int, str] = {}
        self.spectator_ids: set[int] = set()
        self.spectator_names: dict[int, str] = {}
        self.accepting = True
        self.started = False
        self.cancelled = False
        self.done = asyncio.Event()
        self.lock = asyncio.Lock()
        self.message: discord.Message | None = None

    def participant_text(self) -> str:
        if not self.joined_names:
            return "아직 참가자가 없습니다."
        names = sorted(self.joined_names.values(), key=str.casefold)
        return "\n".join(f"{index}. {name}" for index, name in enumerate(names, start=1))

    def spectator_text(self) -> str:
        if not self.spectator_names:
            return "아직 관전자가 없습니다."
        names = sorted(self.spectator_names.values(), key=str.casefold)
        return "\n".join(f"{index}. {name}" for index, name in enumerate(names, start=1))

    def role_count_text(self) -> str:
        return public_role_count_text_from_counts(self.role_counts)

    def minimum_status_text(self) -> str:
        shortage = self.minimum_players - len(self.joined_ids)
        if shortage <= 0:
            return f"최소 시작 인원 **{self.minimum_players}명** 충족"
        return f"최소 시작 인원 **{self.minimum_players}명**까지 **{shortage}명** 더 필요"

    def capacity_status_text(self) -> str:
        remaining = self.max_players - len(self.joined_ids)
        if remaining <= 0:
            return f"최대 참가 인원 **{self.max_players}명** 도달"
        return f"최대 참가 인원 **{self.max_players}명**까지 **{remaining}명** 더 참가 가능"

    def joined_count_text(self) -> str:
        return f"현재 참가자 **{len(self.joined_ids)}/{self.max_players}명**"

    def embed(
        self,
        status: str,
        *,
        title: str = "참가자 모집",
        color: discord.Color = SUCCESS_EMBED_COLOR,
    ) -> discord.Embed:
        return make_embed(
            f"최대 {duration_text(RECRUITMENT_SECONDS)} 동안 참가자를 모집합니다.\n"
            "참가 버튼을 누르면 게임 참가자로 등록되고, "
            f"'{config.participant_role}' 역할이 부여됩니다.\n"
            f"관전 버튼을 누르면 '{SPECTATOR_ROLE}' 역할이 부여되고 게임 채널을 읽을 수 있습니다.\n"
            "주최자는 `시작` 버튼으로 즉시 시작하거나 `취소` 버튼으로 모집을 취소할 수 있습니다.\n\n"
            f"역할 구성: {self.role_count_text()}\n"
            f"사망 시 직업 공개: {'공개' if self.reveal_death_roles else '비공개'}\n"
            f"경찰 조사 성공 여부 공개: {'공개' if self.reveal_public_police_status else '비공개'}\n"
            f"아침 생존 마피아 수 공개: {'공개' if self.reveal_morning_mafia_count else '비공개'}\n"
            f"{self.minimum_status_text()}\n\n"
            f"{self.capacity_status_text()}\n\n"
            f"{self.joined_count_text()}\n"
            f"{self.participant_text()}\n\n"
            f"현재 관전자 **{len(self.spectator_ids)}명**\n"
            f"{self.spectator_text()}\n\n"
            f"{status}",
            title=title,
            color=color,
        )

    async def refresh_message(
        self,
        status: str = "모집 중입니다.",
        *,
        title: str = "참가자 모집",
        color: discord.Color = SUCCESS_EMBED_COLOR,
    ) -> None:
        if not self.message:
            return
        try:
            await self.message.edit(embed=self.embed(status, title=title, color=color), view=self)
        except discord.DiscordException:
            return

    async def finish_from_host(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
        *,
        cancelled: bool,
    ) -> None:
        if interaction.user.id != self.host_user_id:
            await send_interaction_reply(
                interaction,
                "게임을 모집한 주최자만 사용할 수 있습니다.",
                private=True,
            )
            return

        async with self.lock:
            if not self.accepting:
                await send_interaction_reply(interaction, "참가자 모집이 이미 종료되었습니다.", private=True)
                return
            if not cancelled and len(self.joined_ids) < self.minimum_players:
                await send_interaction_reply(
                    interaction,
                    f"아직 시작할 수 없습니다. 최소 {self.minimum_players}명이 필요합니다. "
                    f"현재 {len(self.joined_ids)}명입니다.",
                    private=True,
                )
                return

            self.accepting = False
            self.cancelled = cancelled
            self.started = not cancelled
            disable_view_items(self)
            button.label = "취소 완료" if cancelled else "시작 확정"
            status = "주최자가 참가자 모집을 취소했습니다." if cancelled else "주최자가 게임 시작을 눌렀습니다."
            title = "참가자 모집 취소" if cancelled else "참가자 모집 종료"
            color = ERROR_EMBED_COLOR if cancelled else SUCCESS_EMBED_COLOR
            await interaction.response.edit_message(
                content=None,
                embed=self.embed(status, title=title, color=color),
                view=self,
            )
            self.done.set()
            self.stop()

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success)
    async def join_game(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if not interaction.response.is_done():
            with suppress(discord.HTTPException, discord.NotFound):
                await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.lock:
            if not self.accepting:
                await send_interaction_reply(interaction, "참가자 모집이 종료되었습니다.", private=True)
                return
            if interaction.guild_id != self.guild_id or not interaction.guild:
                await send_interaction_reply(interaction, "이 모집에는 참가할 수 없습니다.", private=True)
                return
            if not isinstance(interaction.user, discord.Member) or interaction.user.bot:
                await send_interaction_reply(interaction, "서버 멤버만 참가할 수 있습니다.", private=True)
                return
            if is_blacklisted(interaction.user.id):
                await send_interaction_reply(
                    interaction,
                    "블랙리스트에 등록된 유저는 참가할 수 없습니다.",
                    private=True,
                )
                return
            if member_is_confirmed_offline(interaction.guild_id, interaction.user):
                await send_interaction_reply(
                    interaction,
                    "오프라인으로 표시된 유저는 참가할 수 없습니다.",
                    private=True,
                )
                return

            participant_role = interaction.guild.get_role(self.participant_role_id)
            if not participant_role:
                await send_interaction_reply(
                    interaction,
                    f"'{config.participant_role}' 역할을 찾을 수 없습니다.",
                    private=True,
                )
                return
            if interaction.user.id in self.joined_ids:
                await send_interaction_reply(interaction, "이미 참가했습니다.", private=True)
                return
            if interaction.user.id in self.spectator_ids:
                await send_interaction_reply(interaction, "이미 관전자로 등록되어 있습니다.", private=True)
                return
            if len(self.joined_ids) >= self.max_players:
                await send_interaction_reply(
                    interaction,
                    f"최대 참가 인원 {self.max_players}명에 도달해 더 이상 참가할 수 없습니다.",
                    private=True,
                )
                return

            try:
                if participant_role not in interaction.user.roles:
                    await interaction.user.add_roles(
                        participant_role,
                        reason="마피아 게임 참가 신청",
                    )
            except discord.DiscordException:
                await send_interaction_reply(
                    interaction,
                    f"'{config.participant_role}' 역할 부여에 실패했습니다. "
                    "봇에게 역할 관리 권한이 있고, 봇 역할이 참가자 역할보다 위에 있는지 확인하세요.",
                    private=True,
                )
                return

            self.joined_ids.add(interaction.user.id)
            self.joined_names[interaction.user.id] = display_name(interaction.user)
            await send_interaction_reply(
                interaction,
                f"참가 완료! '{config.participant_role}' 역할을 부여했습니다.",
                private=True,
            )
            await self.refresh_message()

    @discord.ui.button(label="관전", style=discord.ButtonStyle.secondary)
    async def spectate_game(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if not interaction.response.is_done():
            with suppress(discord.HTTPException, discord.NotFound):
                await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.lock:
            if not self.accepting:
                await send_interaction_reply(interaction, "참가자 모집이 종료되었습니다.", private=True)
                return
            if interaction.guild_id != self.guild_id or not interaction.guild:
                await send_interaction_reply(interaction, "이 모집에는 관전할 수 없습니다.", private=True)
                return
            if not isinstance(interaction.user, discord.Member) or interaction.user.bot:
                await send_interaction_reply(interaction, "서버 멤버만 관전할 수 있습니다.", private=True)
                return
            if is_blacklisted(interaction.user.id):
                await send_interaction_reply(
                    interaction,
                    "블랙리스트에 등록된 유저는 관전할 수 없습니다.",
                    private=True,
                )
                return
            if interaction.user.id in self.joined_ids:
                await send_interaction_reply(interaction, "이미 참가자로 등록되어 있습니다.", private=True)
                return
            if interaction.user.id in self.spectator_ids:
                await send_interaction_reply(interaction, "이미 관전자로 등록되어 있습니다.", private=True)
                return

            spectator_role = await ensure_spectator_role(interaction.guild)
            if not spectator_role:
                await send_interaction_reply(
                    interaction,
                    f"'{SPECTATOR_ROLE}' 역할을 만들거나 찾을 수 없습니다. "
                    "봇에게 역할 관리 권한이 있고, 봇 역할이 관전자 역할보다 위에 있는지 확인하세요.",
                    private=True,
                )
                return

            try:
                if spectator_role not in interaction.user.roles:
                    await interaction.user.add_roles(
                        spectator_role,
                        reason="마피아 게임 관전 신청",
                    )
            except discord.DiscordException:
                await send_interaction_reply(
                    interaction,
                    f"'{SPECTATOR_ROLE}' 역할 부여에 실패했습니다. "
                    "봇에게 역할 관리 권한이 있고, 봇 역할이 관전자 역할보다 위에 있는지 확인하세요.",
                    private=True,
                )
                return

            self.spectator_ids.add(interaction.user.id)
            self.spectator_names[interaction.user.id] = display_name(interaction.user)
            await send_interaction_reply(
                interaction,
                f"관전 등록 완료! '{SPECTATOR_ROLE}' 역할을 부여했습니다.",
                private=True,
            )
            await self.refresh_message()

    @discord.ui.button(label="시작", style=discord.ButtonStyle.primary)
    async def start_now(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await self.finish_from_host(interaction, button, cancelled=False)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.danger)
    async def cancel_recruitment(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await self.finish_from_host(interaction, button, cancelled=True)


class NightActionSelect(discord.ui.Select[discord.ui.View]):
    def __init__(self, guild_id: int, actor_id: int, role: Role, targets: list[Player]) -> None:
        options = [
            discord.SelectOption(label=target_select_label(target, actor_id), value=str(target.user_id))
            for target in targets[:25]
        ]
        if role == Role.REPORTER:
            options.append(discord.SelectOption(label="사용 안함", value="skip"))
        placeholder = {
            Role.MAFIA: "공격할 대상을 선택하세요",
            Role.DOCTOR: "보호할 대상을 선택하세요",
            Role.NURSE: "처방/치료 대상을 선택하세요",
            Role.POLICE: "조사할 대상을 선택하세요",
            Role.VIGILANTE: "숙청할 대상을 선택하세요",
            Role.REPORTER: "특종을 낼 대상 또는 사용 안함을 선택하세요",
            Role.DETECTIVE: "추적할 대상을 선택하세요",
            Role.SHAMAN: "성불할 사망자를 선택하세요",
            Role.PRIEST: "소생할 사망자를 선택하세요",
            Role.SPY: "첩보할 대상을 선택하세요",
            Role.WITCH: "저주할 대상을 선택하세요",
            Role.GODFATHER: "확정 처치할 대상을 선택하세요",
            Role.TERRORIST: "지목할 대상을 선택하세요",
            Role.CULT_LEADER: "포교할 대상을 선택하세요",
            Role.FANATIC: "추종할 대상을 선택하세요",
        }[role]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)
        self.guild_id = guild_id
        self.actor_id = actor_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.actor_id:
            await send_interaction_reply(
                interaction,
                "본인에게 온 선택지만 사용할 수 있습니다.",
                private=True,
            )
            return

        running = games.get(self.guild_id)
        if not running:
            await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
            return

        try:
            target_id = None if self.values[0] == "skip" else int(self.values[0])
            result = running.game.submit_night_action(self.actor_id, target_id)
            cult_bell_count = running.game.consume_cult_bells()
        except ValueError as error:
            await send_interaction_reply(interaction, str(error), private=True)
            return

        actor = running.game.get_player(self.actor_id)
        immediate_result: str | None = None
        if actor and actor.role == Role.POLICE:
            immediate_result = running.game.consume_ready_police_result()
            if immediate_result:
                guild = bot.get_guild(running.guild_id)
                if guild:
                    await send_police_result_message(
                        guild,
                        running,
                        immediate_result,
                        exclude_user_ids={actor.user_id},
                    )
            else:
                immediate_result = "다른 경찰의 선택이 남아 있어 조사 결과는 아직 확정되지 않았습니다."
        if actor and actor.role == Role.MAFIA:
            guild = bot.get_guild(running.guild_id)
            if guild:
                await sync_role_status_message(guild, running, Role.MAFIA)
            await interaction.response.edit_message(
                content=None,
                embed=make_embed(
                    f"{result}\n\n{mafia_night_target_status_text(running)}",
                    title="마피아 처치 선택",
                    color=SUCCESS_EMBED_COLOR,
                ),
                view=self.view,
            )
            return

        disable_view_items(self.view)
        if actor and actor.role == Role.SPY and running.game.spy_can_use_bonus_action(self.actor_id):
            await interaction.response.edit_message(
                content=None,
                embed=make_embed(
                    f"{result}\n\n추가 첩보를 한 번 더 사용할 수 있습니다.",
                    title="접선 성공",
                    color=SUCCESS_EMBED_COLOR,
                ),
                view=NightActionView(self.guild_id, actor, night_targets(running.game, actor)),
            )
            return

        if actor and actor.role == Role.WITCH and running.night_timed_events_due:
            guild = bot.get_guild(running.guild_id)
            channel = guild.get_channel(running.channel_id) if guild else None
            if guild and isinstance(channel, discord.abc.Messageable):
                trigger_timed_night_events(guild, channel, running)
        response_message = result if not immediate_result else f"{result}\n\n{immediate_result}"
        result = response_message
        await interaction.response.edit_message(
            content=None,
            embed=make_embed(result, title="밤 행동 완료", color=SUCCESS_EMBED_COLOR),
            view=self.view,
        )
        if cult_bell_count:
            await announce_cult_bells_now(running, cult_bell_count)
        if should_finish_night_early(running):
            running.night_complete_event.set()


class NightActionView(discord.ui.View):
    def __init__(self, guild_id: int, actor: Player, targets: list[Player]) -> None:
        super().__init__(timeout=None)
        self.add_item(NightActionSelect(guild_id, actor.user_id, actor.role, targets))


class HackerDayActionSelect(discord.ui.Select[discord.ui.View]):
    def __init__(self, guild_id: int, actor_id: int, targets: list[Player]) -> None:
        options = [
            discord.SelectOption(label=target_select_label(target, actor_id), value=str(target.user_id))
            for target in targets[:25]
        ]
        super().__init__(
            placeholder="해킹할 대상을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.guild_id = guild_id
        self.actor_id = actor_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.actor_id:
            await send_interaction_reply(interaction, "본인에게 온 선택지만 사용할 수 있습니다.", private=True)
            return

        running = games.get(self.guild_id)
        if not running:
            await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
            return

        try:
            result = running.game.submit_hacker_action(self.actor_id, int(self.values[0]))
        except ValueError as error:
            await send_interaction_reply(interaction, str(error), private=True)
            return

        disable_view_items(self.view)
        await interaction.response.edit_message(
            content=None,
            embed=make_embed(
                f"{result}\n밤이 시작될 때 대상의 직업을 확인합니다.",
                title="해킹 완료",
                color=SUCCESS_EMBED_COLOR,
            ),
            view=self.view,
        )


class HackerDayActionView(discord.ui.View):
    def __init__(self, guild_id: int, actor: Player, targets: list[Player]) -> None:
        super().__init__(timeout=None)
        self.add_item(HackerDayActionSelect(guild_id, actor.user_id, targets))


class VigilanteDayActionSelect(discord.ui.Select[discord.ui.View]):
    def __init__(self, guild_id: int, actor_id: int, targets: list[Player]) -> None:
        options = [
            discord.SelectOption(label=target_select_label(target, actor_id), value=str(target.user_id))
            for target in targets[:25]
        ]
        super().__init__(
            placeholder="숙청 조사 대상을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.guild_id = guild_id
        self.actor_id = actor_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.actor_id:
            await send_interaction_reply(interaction, "본인에게 온 선택지만 사용할 수 있습니다.", private=True)
            return

        running = games.get(self.guild_id)
        if not running:
            await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
            return

        try:
            result = running.game.submit_vigilante_investigation(self.actor_id, int(self.values[0]))
            investigation_result = running.game.consume_vigilante_results().get(self.actor_id)
        except ValueError as error:
            await send_interaction_reply(interaction, str(error), private=True)
            return

        disable_view_items(self.view)
        await interaction.response.edit_message(
            content=None,
            embed=make_embed(
                f"{result}\n\n{investigation_result or '조사 결과를 확인하지 못했습니다.'}",
                title="숙청 조사 완료",
                color=SUCCESS_EMBED_COLOR,
            ),
            view=self.view,
        )


class VigilanteDayActionView(discord.ui.View):
    def __init__(self, guild_id: int, actor: Player, targets: list[Player]) -> None:
        super().__init__(timeout=None)
        self.add_item(VigilanteDayActionSelect(guild_id, actor.user_id, targets))


class ContractorTargetSelect(discord.ui.Select[discord.ui.View]):
    def __init__(self, parent_view: "ContractorContractView", slot: int, targets: list[Player]) -> None:
        options = [
            discord.SelectOption(
                label=target_select_label(target, parent_view.actor.user_id),
                value=str(target.user_id),
            )
            for target in targets[:25]
        ]
        super().__init__(
            placeholder=f"{slot + 1}번째 청부 대상",
            min_values=1,
            max_values=1,
            options=options,
            row=slot * 2,
        )
        self.parent_view = parent_view
        self.slot = slot

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.parent_view.actor.user_id:
            await send_interaction_reply(interaction, "본인에게 온 선택지만 사용할 수 있습니다.", private=True)
            return
        self.parent_view.target_ids[self.slot] = int(self.values[0])
        await interaction.response.defer()


class ContractorRoleSelect(discord.ui.Select[discord.ui.View]):
    def __init__(self, parent_view: "ContractorContractView", slot: int) -> None:
        options = [
            discord.SelectOption(label=role.value, value=role.name)
            for role in CONTRACTOR_GUESS_ROLES
        ]
        super().__init__(
            placeholder=f"{slot + 1}번째 대상 직업 추측",
            min_values=1,
            max_values=1,
            options=options,
            row=slot * 2 + 1,
        )
        self.parent_view = parent_view
        self.slot = slot

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.parent_view.actor.user_id:
            await send_interaction_reply(interaction, "본인에게 온 선택지만 사용할 수 있습니다.", private=True)
            return
        self.parent_view.guessed_roles[self.slot] = Role[self.values[0]]
        await interaction.response.defer()


class ContractorContractView(discord.ui.View):
    def __init__(self, guild_id: int, actor: Player, targets: list[Player]) -> None:
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.actor = actor
        self.target_ids: list[int | None] = [None, None]
        self.guessed_roles: list[Role | None] = [None, None]
        self.add_item(ContractorTargetSelect(self, 0, targets))
        self.add_item(ContractorRoleSelect(self, 0))
        self.add_item(ContractorTargetSelect(self, 1, targets))
        self.add_item(ContractorRoleSelect(self, 1))

    @discord.ui.button(label="청부 확정", style=discord.ButtonStyle.danger, row=4)
    async def submit_contract(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.actor.user_id:
            await send_interaction_reply(interaction, "본인에게 온 선택지만 사용할 수 있습니다.", private=True)
            return
        if any(target_id is None for target_id in self.target_ids) or any(
            role is None for role in self.guessed_roles
        ):
            await send_interaction_reply(interaction, "청부 대상 2명과 각 대상의 직업을 모두 선택하세요.", private=True)
            return

        running = games.get(self.guild_id)
        if not running:
            await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
            return

        try:
            result = running.game.submit_contractor_contract(
                self.actor.user_id,
                int(self.target_ids[0]),
                self.guessed_roles[0],
                int(self.target_ids[1]),
                self.guessed_roles[1],
            )
        except ValueError as error:
            await send_interaction_reply(interaction, str(error), private=True)
            return

        disable_view_items(self)
        if should_finish_night_early(running):
            running.night_complete_event.set()
        await interaction.response.edit_message(
            content=None,
            embed=make_embed(result, title="밤 행동 완료", color=SUCCESS_EMBED_COLOR),
            view=self,
        )


class DayVoteSelect(discord.ui.Select[discord.ui.View]):
    def __init__(self, guild_id: int, targets: list[Player]) -> None:
        options = [
            discord.SelectOption(label=target.name[:100], value=str(target.user_id))
            for target in targets[:24]
        ]
        options.append(discord.SelectOption(label="스킵", value="skip"))
        super().__init__(
            placeholder="처형할 대상 또는 스킵을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        running = games.get(self.guild_id)
        if not running:
            await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
            return
        try:
            target_id = None if self.values[0] == "skip" else int(self.values[0])
            result = running.game.submit_day_vote(interaction.user.id, target_id)
        except ValueError as error:
            await send_interaction_reply(interaction, str(error), private=True)
            return
        if running.game.all_day_votes_submitted():
            running.vote_complete_event.set()
        await send_interaction_reply(interaction, result, private=True)


class DayVoteView(discord.ui.View):
    def __init__(self, guild_id: int, targets: list[Player]) -> None:
        super().__init__(timeout=None)
        self.add_item(DayVoteSelect(guild_id, targets))


class ConfirmVoteView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.guild_id = guild_id

    async def vote(self, interaction: discord.Interaction, approve: bool) -> None:
        running = games.get(self.guild_id)
        if not running:
            await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
            return
        try:
            result = running.game.submit_confirmation_vote(interaction.user.id, approve)
        except ValueError as error:
            await send_interaction_reply(interaction, str(error), private=True)
            return
        if running.game.all_confirm_votes_submitted():
            running.confirm_complete_event.set()
        await send_interaction_reply(interaction, result, private=True)

    @discord.ui.button(label="찬성", style=discord.ButtonStyle.success)
    async def approve(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await self.vote(interaction, True)

    @discord.ui.button(label="반대", style=discord.ButtonStyle.danger)
    async def reject(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await self.vote(interaction, False)


class DayExtensionVoteView(discord.ui.View):
    def __init__(self, guild_id: int, alive_user_ids: set[int]) -> None:
        super().__init__(timeout=DAY_EXTENSION_VOTE_SECONDS)
        self.guild_id = guild_id
        self.alive_user_ids = alive_user_ids
        self.voter_ids: set[int] = set()
        self.required_votes = (len(alive_user_ids) // 2) + 1
        self.extended = False
        self.accepting = True

    @discord.ui.button(label="1분 연장", style=discord.ButtonStyle.secondary)
    async def extend_discussion(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if not self.accepting:
            await send_interaction_reply(interaction, "연장 투표가 종료되었습니다.", private=True)
            return
        if interaction.user.id not in self.alive_user_ids:
            await send_interaction_reply(
                interaction,
                "생존 중인 참가자만 연장 투표를 할 수 있습니다.",
                private=True,
            )
            return
        running = games.get(self.guild_id)
        if not running or running.game.phase != Phase.DAY:
            await send_interaction_reply(
                interaction,
                "지금 진행 중인 낮 토론이 없습니다.",
                private=True,
            )
            return
        if interaction.user.id in self.voter_ids:
            await send_interaction_reply(
                interaction,
                f"이미 1분 연장에 투표했습니다. 현재 {len(self.voter_ids)}/{self.required_votes}명",
                private=True,
            )
            return

        self.voter_ids.add(interaction.user.id)
        if len(self.voter_ids) < self.required_votes:
            await send_interaction_reply(
                interaction,
                f"1분 연장에 투표했습니다. 현재 {len(self.voter_ids)}/{self.required_votes}명",
                private=True,
            )
            return

        self.extended = True
        self.accepting = False
        disable_view_items(self)
        button.label = "연장 확정"
        await interaction.response.edit_message(
            content=None,
            embed=make_embed(
                f"생존자 과반수가 1분 연장을 선택했습니다. "
                f"({len(self.voter_ids)}/{len(self.alive_user_ids)}명)\n"
                "낮 토론을 1분 연장합니다.",
                title="낮 토론 연장",
                color=SUCCESS_EMBED_COLOR,
            ),
            view=self,
        )
        self.stop()


class DaySkipToVoteView(discord.ui.View):
    def __init__(self, guild_id: int, alive_user_ids: set[int]) -> None:
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.alive_user_ids = alive_user_ids
        self.voter_ids: set[int] = set()
        self.required_votes = (len(alive_user_ids) // 2) + 1
        self.accepting = True

    @discord.ui.button(label="바로 투표", style=discord.ButtonStyle.primary)
    async def skip_to_vote(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if not self.accepting:
            await send_interaction_reply(interaction, "바로 투표 선택이 종료되었습니다.", private=True)
            return
        if interaction.user.id not in self.alive_user_ids:
            await send_interaction_reply(
                interaction,
                "생존 중인 참가자만 바로 투표를 선택할 수 있습니다.",
                private=True,
            )
            return

        running = games.get(self.guild_id)
        if not running or running.game.phase != Phase.DAY:
            await send_interaction_reply(
                interaction,
                "지금 진행 중인 낮 토론이 없습니다.",
                private=True,
            )
            return
        if interaction.user.id in self.voter_ids:
            await send_interaction_reply(
                interaction,
                f"이미 바로 투표에 동의했습니다. 현재 {len(self.voter_ids)}/{self.required_votes}명",
                private=True,
            )
            return

        self.voter_ids.add(interaction.user.id)
        if len(self.voter_ids) < self.required_votes:
            await send_interaction_reply(
                interaction,
                f"바로 투표에 동의했습니다. 현재 {len(self.voter_ids)}/{self.required_votes}명",
                private=True,
            )
            return

        self.accepting = False
        disable_view_items(self)
        button.label = "투표 확정"
        await interaction.response.edit_message(
            content=None,
            embed=make_embed(
                f"생존자 과반수가 바로 투표를 선택했습니다. "
                f"({len(self.voter_ids)}/{len(self.alive_user_ids)}명)\n"
                "토론을 끝내고 바로 지목 투표로 넘어갑니다.",
                title="바로 투표",
                color=SUCCESS_EMBED_COLOR,
            ),
            view=self,
        )
        running.day_vote_event.set()
        self.stop()


def has_changeable_mafia_action(running: RunningGame) -> bool:
    return any(actor.role == Role.MAFIA for actor in running.game.night_action_actors())


def should_finish_night_early(running: RunningGame) -> bool:
    return running.game.all_night_actions_submitted() and not has_changeable_mafia_action(running)


class MafiaBot(commands.Bot):
    async def setup_hook(self) -> None:
        from cogs import load_all

        load_all()
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")

    async def on_ready(self) -> None:
        for guild in self.guilds:
            for member in guild.members:
                remember_member_presence(guild.id, member)

    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        remember_presence_update(before, after)


intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True
bot = MafiaBot(command_prefix="!", intents=intents)


def anonymous_message_body(message: discord.Message) -> str:
    parts: list[str] = []
    if message.content.strip():
        parts.append(message.content.strip())
    if message.attachments:
        parts.extend(attachment.url for attachment in message.attachments)
    return "\n".join(parts) or "(내용 없음)"


def can_use_anonymous_general_chat(running: RunningGame, player: Player) -> bool:
    if not player.alive:
        return False
    if running.game.is_frog(player):
        return False
    if running.game.is_madam_seduced(player):
        return False
    if running.game.phase == Phase.DAY:
        return True
    return running.game.phase == Phase.FINAL_DEFENSE and running.final_defense_user_id == player.user_id


def can_use_anonymous_dead_chat(running: RunningGame, player: Player) -> bool:
    return not player.alive and player.user_id not in running.game.purified_dead_ids


def can_use_anonymous_shaman_chat(running: RunningGame, player: Player) -> bool:
    if not player.alive:
        return player.user_id not in running.game.purified_dead_ids
    return (
        player.role == Role.SHAMAN
        and running.game.phase == Phase.NIGHT
        and not running.game.is_frog(player)
        and not running.game.is_madam_seduced(player)
    )


def can_use_anonymous_role_chat(running: RunningGame, player: Player, role: Role) -> bool:
    if running.game.is_frog(player):
        return False
    if running.game.is_madam_seduced(player):
        return False
    if role == Role.LOVER:
        return player.alive and player.role == Role.LOVER and lover_chat_is_open(running.game)
    if player.alive and (player.user_id, role) in running.anonymous_role_input_channel_ids:
        return True
    if role == Role.MAFIA:
        return player.alive and running.game.is_known_mafia_team(player)
    return player.alive and player.role == role


def anonymous_avatar_url(author_label: str) -> str | None:
    if author_label.endswith("번") and author_label[:-1].isdigit():
        number = int(author_label[:-1])
        color = NUMBER_AVATAR_COLORS[(number - 1) % len(NUMBER_AVATAR_COLORS)]
        return f"https://dummyimage.com/128x128/{color}/ffffff.png&text={number}"
    emoji_code = ANIMAL_EMOJI_CODES.get(author_label)
    if not emoji_code:
        return None
    return f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{emoji_code}.png"


async def send_anonymous_text(
    channel: discord.abc.Messageable,
    author_label: str,
    body: str,
    *,
    running: RunningGame | None = None,
) -> None:
    if running and isinstance(channel, discord.TextChannel):
        webhook = await anonymous_webhook(channel, running)
        if webhook:
            with suppress(discord.HTTPException):
                send_kwargs = {
                    "username": author_label[:80],
                    "allowed_mentions": discord.AllowedMentions.none(),
                    "wait": False,
                }
                avatar_url = anonymous_avatar_url(author_label)
                if avatar_url:
                    send_kwargs["avatar_url"] = avatar_url
                await webhook.send(body, **send_kwargs)
                return
    with suppress(discord.HTTPException):
        await channel.send(
            f"{author_label}: {body}",
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def send_member_webhook_text(
    channel: discord.abc.Messageable,
    author: discord.Member | discord.User,
    body: str,
    *,
    running: RunningGame,
) -> None:
    if isinstance(channel, discord.TextChannel):
        webhook = await anonymous_webhook(channel, running)
        if webhook:
            with suppress(discord.HTTPException):
                avatar = getattr(author, "display_avatar", None)
                send_kwargs = {
                    "username": getattr(author, "display_name", author.name)[:80],
                    "allowed_mentions": discord.AllowedMentions.none(),
                    "wait": False,
                }
                if avatar:
                    send_kwargs["avatar_url"] = avatar.url
                await webhook.send(body, **send_kwargs)
                return
    with suppress(discord.HTTPException):
        await channel.send(
            f"{getattr(author, 'display_name', author.name)}: {body}",
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def anonymous_webhook(
    channel: discord.TextChannel,
    running: RunningGame,
) -> discord.Webhook | None:
    url = running.anonymous_webhook_urls.get(channel.id)
    if url:
        return discord.Webhook.from_url(url, client=bot)
    try:
        webhook = await channel.create_webhook(name="Mafia Anonymous")
    except discord.DiscordException:
        return None
    running.anonymous_webhook_urls[channel.id] = webhook.url
    return webhook


async def prepare_anonymous_webhook(
    channel: discord.TextChannel,
    running: RunningGame,
) -> None:
    await anonymous_webhook(channel, running)


async def relay_to_channels(
    deliveries: list[tuple[discord.abc.Messageable, str, str]],
    running: RunningGame,
) -> None:
    semaphore = asyncio.Semaphore(20)

    async def send_one(channel: discord.abc.Messageable, label: str, body: str) -> None:
        async with semaphore:
            await send_anonymous_text(channel, label, body, running=running)

    await asyncio.gather(
        *(send_one(channel, label, body) for channel, label, body in deliveries),
        return_exceptions=True,
    )


async def send_anonymous_log(
    guild: discord.Guild,
    running: RunningGame,
    *,
    player: Player,
    body: str,
    role: Role | None = None,
    context: str | None = None,
) -> None:
    channel = guild.get_channel(running.channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        return
    alias = running.anonymous_aliases.get(player.user_id, player.name)
    label = role.value if role else context
    prefix = f"[익명 로그/{label}]" if label else "[익명 로그]"
    await send_anonymous_text(channel, prefix, f"{alias} - {body}")


async def relay_anonymous_general_message(
    guild: discord.Guild,
    running: RunningGame,
    sender: Player,
    body: str,
) -> None:
    sender_alias = running.anonymous_aliases.get(sender.user_id, "익명")
    deliveries: list[tuple[discord.abc.Messageable, str, str]] = []

    for viewer in running.game.alive_players():
        if viewer.user_id == sender.user_id:
            continue
        if running.game.is_frog(viewer):
            continue
        channel_id = running.anonymous_input_channel_ids.get(viewer.user_id)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            continue
        deliveries.append((channel, sender_alias, body))

    await relay_to_channels(deliveries, running)
    await send_anonymous_log(guild, running, player=sender, body=body, context="일반")


def anonymous_dead_chat_viewers(running: RunningGame) -> list[Player]:
    return [
        player
        for player in running.game.players
        if not player.alive and player.user_id not in running.game.purified_dead_ids
    ]


def anonymous_shaman_chat_viewers(running: RunningGame) -> list[Player]:
    viewers: list[Player] = []
    for player in running.game.players:
        if not player.alive and player.user_id not in running.game.purified_dead_ids:
            viewers.append(player)
        elif player.alive and player.role == Role.SHAMAN and not running.game.is_frog(player):
            viewers.append(player)
    return viewers


def anonymous_dead_sender_label(running: RunningGame, sender: Player) -> str:
    if sender.alive and sender.role == Role.SHAMAN:
        return "익명의 목소리"
    if running.anonymous_enabled:
        return running.anonymous_aliases.get(sender.user_id, "익명")
    return sender.name


async def send_dead_chat_text(
    guild: discord.Guild,
    running: RunningGame,
    channel: discord.TextChannel,
    sender: Player,
    body: str,
) -> None:
    if running.anonymous_enabled:
        await send_anonymous_text(
            channel,
            anonymous_dead_sender_label(running, sender),
            body,
            running=running,
        )
        return
    author = await get_guild_member(guild, sender.user_id)
    if author:
        await send_member_webhook_text(channel, author, body, running=running)
        return
    await send_anonymous_text(channel, sender.name, body, running=running)


async def relay_anonymous_dead_message(
    guild: discord.Guild,
    running: RunningGame,
    sender: Player,
    body: str,
) -> None:
    deliveries: list[discord.TextChannel] = []

    for viewer in anonymous_dead_chat_viewers(running):
        if viewer.user_id == sender.user_id:
            continue
        await set_anonymous_dead_input_access(
            guild,
            running,
            viewer,
            can_view=True,
            can_chat=can_use_anonymous_dead_chat(running, viewer),
            reason="마피아 게임 사망자 개인 채팅 권한 갱신",
        )
        channel_id = running.anonymous_dead_input_channel_ids.get(viewer.user_id)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            continue
        deliveries.append(channel)

    await asyncio.gather(
        *(send_dead_chat_text(guild, running, channel, sender, body) for channel in deliveries),
        return_exceptions=True,
    )


async def send_anonymous_shaman_log(
    guild: discord.Guild,
    running: RunningGame,
    *,
    player: Player,
    body: str,
) -> None:
    channel = guild.get_channel(running.shaman_channel_id) if running.shaman_channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return
    alias = anonymous_dead_sender_label(running, player)
    await send_anonymous_text(
        channel,
        "[익명 로그/영매]",
        f"{alias} - {body}",
        running=running,
    )


async def relay_anonymous_shaman_message(
    guild: discord.Guild,
    running: RunningGame,
    sender: Player,
    body: str,
) -> None:
    sender_alias = anonymous_dead_sender_label(running, sender)
    deliveries: list[tuple[discord.abc.Messageable, str, str]] = []

    for viewer in anonymous_shaman_chat_viewers(running):
        if viewer.user_id == sender.user_id:
            continue
        channel_id = running.anonymous_shaman_input_channel_ids.get(viewer.user_id)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            continue
        deliveries.append((channel, sender_alias, body))

    await relay_to_channels(deliveries, running)
    await send_anonymous_shaman_log(guild, running, player=sender, body=body)


async def relay_anonymous_role_message(
    guild: discord.Guild,
    running: RunningGame,
    sender: Player,
    role: Role,
    body: str,
) -> None:
    sender_alias = running.anonymous_aliases.get(sender.user_id, "익명")
    deliveries: list[tuple[discord.abc.Messageable, str, str]] = []

    for viewer in anonymous_role_status_players(running, role):
        if viewer.user_id == sender.user_id:
            continue
        if not can_use_anonymous_role_chat(running, viewer, role):
            continue
        input_id = running.anonymous_role_input_channel_ids.get((viewer.user_id, role))
        input_channel = guild.get_channel(input_id) if input_id else None
        if not isinstance(input_channel, discord.TextChannel):
            continue
        deliveries.append((input_channel, sender_alias, body))

    await relay_to_channels(deliveries, running)
    await send_anonymous_log(guild, running, player=sender, body=body, role=role)


async def mirror_role_chat_to_dead(
    guild: discord.Guild,
    running: RunningGame,
    author: discord.Member | discord.User,
    role: Role,
    body: str,
) -> None:
    deliveries: list[discord.TextChannel] = []
    for viewer in anonymous_dead_chat_viewers(running):
        await set_anonymous_dead_input_access(
            guild,
            running,
            viewer,
            can_view=True,
            can_chat=can_use_anonymous_dead_chat(running, viewer),
            reason="마피아 게임 사망자 개인 채팅 권한 갱신",
        )
        channel_id = running.anonymous_dead_input_channel_ids.get(viewer.user_id)
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            deliveries.append(channel)
    await asyncio.gather(
        *(
            send_member_webhook_text(
                channel,
                author,
                f"[{role.value}채팅] {body}",
                running=running,
            )
            for channel in deliveries
        ),
        return_exceptions=True,
    )


async def set_anonymous_general_input_access(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    *,
    can_chat: bool,
    reason: str,
) -> None:
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return
    channel_id = running.anonymous_input_channel_ids.get(player.user_id)
    channel = guild.get_channel(channel_id) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return
    can_use = can_chat and player.alive and not running.game.is_frog(player) and not running.game.is_madam_seduced(player)
    with suppress(discord.DiscordException):
        await set_permissions_if_changed(
            channel,
            member,
            overwrite=anonymous_input_overwrite(True, can_use),
            reason=reason,
            running=running,
        )


async def set_anonymous_channel_slowmode(
    guild: discord.Guild,
    channel_id: int | None,
    seconds: int,
    reason: str,
) -> None:
    channel = guild.get_channel(channel_id) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return
    if channel.slowmode_delay == seconds:
        return
    with suppress(discord.DiscordException):
        await channel.edit(slowmode_delay=seconds, reason=reason)


async def ensure_anonymous_dead_input_channel(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    *,
    can_chat: bool,
    reason: str,
) -> discord.TextChannel | None:
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return None

    channel_id = running.anonymous_dead_input_channel_ids.get(player.user_id)
    channel = guild.get_channel(channel_id) if channel_id else None
    if isinstance(channel, discord.TextChannel):
        with suppress(discord.DiscordException):
            await set_permissions_if_changed(
                channel,
                member,
                overwrite=anonymous_input_overwrite(True, can_chat),
                reason=reason,
                running=running,
            )
        return channel

    source_channel = guild.get_channel(running.channel_id)
    category = source_channel_category(source_channel) if source_channel else None
    alias = running.anonymous_aliases.get(player.user_id, player.name) if running.anonymous_enabled else player.name
    overwrites = anonymous_base_overwrites(
        guild,
        participant_can_view=False,
        participant_can_chat=False,
        default_can_view=False,
        default_can_chat=False,
    )
    overwrites[member] = anonymous_input_overwrite(True, can_chat)
    channel = await create_text_channel_safe(
        guild,
        name=f"{sanitize_channel_part(alias)}-사망자-채팅",
        overwrites=overwrites,
        category=category,
        reason="마피아 게임 사망자 개인 채팅 채널 생성",
        slowmode_delay=0,
    )
    if not isinstance(channel, discord.TextChannel):
        return None

    running.anonymous_dead_input_channel_ids[player.user_id] = channel.id
    running.anonymous_dead_input_channel_owners[channel.id] = player.user_id
    await send_embed(
        channel,
        "사망자 개인 채팅 채널입니다.\n"
        "여기에 쓰면 사망자 채팅을 볼 수 있는 사람들의 사망자 개인 채널로만 전달됩니다.",
        title="사망자 개인 채팅",
        color=SUCCESS_EMBED_COLOR,
    )
    return channel


async def set_anonymous_dead_input_access(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    *,
    can_view: bool,
    can_chat: bool,
    reason: str,
) -> None:
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return
    channel_id = running.anonymous_dead_input_channel_ids.get(player.user_id)
    channel = guild.get_channel(channel_id) if channel_id else None
    if can_view and not isinstance(channel, discord.TextChannel):
        await ensure_anonymous_dead_input_channel(
            guild,
            running,
            player,
            can_chat=can_chat,
            reason=reason,
        )
        return
    if isinstance(channel, discord.TextChannel):
        with suppress(discord.DiscordException):
            await set_permissions_if_changed(
                channel,
                member,
                overwrite=anonymous_input_overwrite(can_view, can_chat if can_view else False),
                reason=reason,
                running=running,
            )


async def ensure_anonymous_shaman_input_channel(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    *,
    can_chat: bool,
    reason: str,
) -> discord.TextChannel | None:
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return None

    channel_id = running.anonymous_shaman_input_channel_ids.get(player.user_id)
    channel = guild.get_channel(channel_id) if channel_id else None
    if isinstance(channel, discord.TextChannel):
        with suppress(discord.DiscordException):
            await set_permissions_if_changed(
                channel,
                member,
                overwrite=anonymous_input_overwrite(True, can_chat),
                reason=reason,
                running=running,
            )
        return channel

    source_channel = guild.get_channel(running.channel_id)
    category = source_channel_category(source_channel) if source_channel else None
    alias = running.anonymous_aliases.get(player.user_id, str(player.user_id))
    overwrites = anonymous_base_overwrites(
        guild,
        participant_can_view=False,
        participant_can_chat=False,
        default_can_view=False,
        default_can_chat=False,
    )
    overwrites[member] = anonymous_input_overwrite(True, can_chat)
    channel = await create_text_channel_safe(
        guild,
        name=f"{sanitize_channel_part(alias)}-영매-채팅",
        overwrites=overwrites,
        category=category,
        reason="마피아 게임 익명 영매 입력 채널 생성",
        slowmode_delay=0,
    )
    if not isinstance(channel, discord.TextChannel):
        return None

    running.anonymous_shaman_input_channel_ids[player.user_id] = channel.id
    running.anonymous_shaman_input_channel_owners[channel.id] = player.user_id
    await send_embed(
        channel,
        "영매 익명 채팅 개인 채널입니다.\n"
        "여기에 쓰면 영매 채팅을 볼 수 있는 사람들의 영매 개인 채널로만 전달됩니다.",
        title="익명 영매 채팅",
        color=SUCCESS_EMBED_COLOR,
    )
    return channel


async def set_anonymous_shaman_input_access(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    *,
    can_view: bool,
    can_chat: bool,
    reason: str,
) -> None:
    if not running.anonymous_enabled:
        return
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return
    channel_id = running.anonymous_shaman_input_channel_ids.get(player.user_id)
    channel = guild.get_channel(channel_id) if channel_id else None
    if can_view and not isinstance(channel, discord.TextChannel):
        await ensure_anonymous_shaman_input_channel(
            guild,
            running,
            player,
            can_chat=can_chat,
            reason=reason,
        )
        return
    if isinstance(channel, discord.TextChannel):
        with suppress(discord.DiscordException):
            await set_permissions_if_changed(
                channel,
                member,
                overwrite=anonymous_input_overwrite(can_view, can_chat if can_view else False),
                reason=reason,
                running=running,
            )


async def set_anonymous_general_chat_permissions(
    guild: discord.Guild,
    running: RunningGame,
    *,
    can_chat: bool,
    reason: str,
) -> None:
    for player in running.game.alive_players():
        await set_anonymous_general_input_access(
            guild,
            running,
            player,
            can_chat=can_chat,
            reason=reason,
        )


async def delete_message_quietly(message: discord.Message) -> None:
    with suppress(discord.DiscordException):
        await message.delete()


async def handle_anonymous_message(
    message: discord.Message,
    running: RunningGame,
    *,
    owner_id: int,
    role: Role | None,
    dead_chat: bool = False,
    shaman_chat: bool = False,
) -> bool:
    if message.author.id != owner_id:
        await delete_message_quietly(message)
        return True
    if not message.guild:
        return True

    player = running.game.get_player(owner_id)
    if not player:
        return True

    body = anonymous_message_body(message)

    if dead_chat:
        if not can_use_anonymous_dead_chat(running, player):
            await set_anonymous_dead_input_access(
                message.guild,
                running,
                player,
                can_view=True,
                can_chat=False,
                reason="마피아 게임 사망자 채팅 불가 시간 권한 재적용",
            )
            return True
        await relay_anonymous_dead_message(message.guild, running, player, body)
        return True

    if shaman_chat:
        if not can_use_anonymous_shaman_chat(running, player):
            await set_anonymous_shaman_input_access(
                message.guild,
                running,
                player,
                can_view=True,
                can_chat=False,
                reason="마피아 게임 영매 채팅 불가 시간 권한 재적용",
            )
            return True
        await relay_anonymous_shaman_message(message.guild, running, player, body)
        return True

    if role is None:
        if not can_use_anonymous_general_chat(running, player):
            await set_anonymous_general_input_access(
                message.guild,
                running,
                player,
                can_chat=False,
                reason="마피아 게임 채팅 불가 시간 권한 재적용",
            )
            return True
        await relay_anonymous_general_message(message.guild, running, player, body)
        return True
    else:
        if not can_use_anonymous_role_chat(running, player, role):
            member = await get_guild_member(message.guild, player.user_id)
            if member and isinstance(message.channel, discord.TextChannel):
                with suppress(discord.DiscordException):
                    await set_permissions_if_changed(
                        message.channel,
                        member,
                        overwrite=anonymous_input_overwrite(True, False),
                        reason="마피아 게임 역할 채팅 불가 시간 권한 재적용",
                        running=running,
                    )
            return True
        await relay_anonymous_role_message(message.guild, running, player, role, body)
        await mirror_role_chat_to_dead(message.guild, running, message.author, role, body)
        return True


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    for running in games.values():
        dead_owner_id = running.anonymous_dead_input_channel_owners.get(message.channel.id)
        if dead_owner_id is not None:
            await handle_anonymous_message(
                message,
                running,
                owner_id=dead_owner_id,
                role=None,
                dead_chat=True,
            )
            return

        shaman_owner_id = running.anonymous_shaman_input_channel_owners.get(message.channel.id)
        if shaman_owner_id is not None:
            await handle_anonymous_message(
                message,
                running,
                owner_id=shaman_owner_id,
                role=None,
                shaman_chat=True,
            )
            return

        owner_id = running.anonymous_input_channel_owners.get(message.channel.id)
        if owner_id is not None:
            await handle_anonymous_message(message, running, owner_id=owner_id, role=None)
            return

        role_input = running.anonymous_role_input_channels.get(message.channel.id)
        if role_input is not None:
            owner_id, role = role_input
            await handle_anonymous_message(message, running, owner_id=owner_id, role=role)
            return

        if message.guild and not running.anonymous_enabled:
            role = next(
                (
                    channel_role
                    for channel_role, channel_id in running.private_channel_ids.items()
                    if channel_id == message.channel.id
                ),
                None,
            )
            if role is not None:
                player = running.game.get_player(message.author.id)
                if player:
                    await mirror_role_chat_to_dead(message.guild, running, message.author, role, anonymous_message_body(message))
                return

        if message.channel.id != running.frog_channel_id:
            continue
        player = running.game.get_player(message.author.id)
        if not player or not running.game.is_frog(player):
            await delete_message_quietly(message)
            return
        if running.game.phase != Phase.DAY:
            await delete_message_quietly(message)
            return

        croak_count = max(1, len(message.content))
        game_channel = message.guild.get_channel(running.channel_id) if message.guild else None
        await delete_message_quietly(message)
        if isinstance(game_channel, discord.abc.Messageable):
            await send_embed(
                game_channel,
                f"개구리: {'개굴' * croak_count}",
                title="개구리 채팅",
            )
        return

    await bot.process_commands(message)



async def collect_participants(
    guild: discord.Guild,
    participant_role: discord.Role,
) -> list[discord.Member]:
    return await members_with_role(guild, participant_role, fail_if_empty_fetch_failed=True)


async def members_with_role(
    guild: discord.Guild,
    role: discord.Role,
    *,
    fail_if_empty_fetch_failed: bool = False,
) -> list[discord.Member]:
    members_by_id: dict[int, discord.Member] = {}
    for member in guild.members:
        if not member.bot and role in member.roles:
            members_by_id[member.id] = member

    try:
        async for member in guild.fetch_members(limit=None):
            if not member.bot and role in member.roles:
                members_by_id[member.id] = member
    except discord.DiscordException as error:
        if fail_if_empty_fetch_failed and not members_by_id:
            raise ValueError(
                "참가자 목록을 불러오지 못했습니다. "
                "Discord Developer Portal에서 Server Members Intent를 켰는지 확인하세요."
            ) from error

    return sorted(members_by_id.values(), key=lambda member: display_name(member).casefold())


async def clear_existing_participant_roles(
    guild: discord.Guild,
    participant_role: discord.Role,
) -> list[str]:
    failed_names: list[str] = []
    for member in await members_with_role(guild, participant_role):
        try:
            await member.remove_roles(
                participant_role,
                reason="마피아 게임 참가 모집 초기화",
            )
        except discord.DiscordException:
            failed_names.append(display_name(member))
    return failed_names


async def clear_existing_spectator_roles(
    guild: discord.Guild,
    spectator_role: discord.Role,
) -> list[str]:
    failed_names: list[str] = []
    for member in await members_with_role(guild, spectator_role):
        try:
            await member.remove_roles(
                spectator_role,
                reason="마피아 게임 관전 모집 초기화",
            )
        except discord.DiscordException:
            failed_names.append(display_name(member))
    return failed_names


async def collect_joined_participants(
    guild: discord.Guild,
    user_ids: set[int],
) -> list[discord.Member]:
    participants: list[discord.Member] = []
    for user_id in user_ids:
        member = await get_guild_member(guild, user_id)
        if member and not member.bot:
            participants.append(member)
    return sorted(participants, key=lambda member: display_name(member).casefold())


async def get_guild_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member:
        return member

    try:
        return await guild.fetch_member(user_id)
    except discord.DiscordException:
        return None


def clone_overwrite(
    overwrite: discord.PermissionOverwrite | None,
) -> discord.PermissionOverwrite | None:
    if overwrite is None:
        return None
    return discord.PermissionOverwrite.from_pair(*overwrite.pair())


def overwrites_equal(
    left: discord.PermissionOverwrite | None,
    right: discord.PermissionOverwrite | None,
) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return left.pair() == right.pair()


async def set_permissions_if_changed(
    channel: discord.abc.Messageable,
    target: discord.abc.Snowflake,
    *,
    overwrite: discord.PermissionOverwrite | None,
    reason: str,
    running: RunningGame | None = None,
) -> bool:
    if not hasattr(channel, "set_permissions"):
        return False
    channel_id = getattr(channel, "id", None)
    target_id = getattr(target, "id", None)
    cache_key = (channel_id, target_id) if channel_id is not None and target_id is not None else None
    desired = clone_overwrite(overwrite)
    current_marker = object()
    current: discord.PermissionOverwrite | None | object = current_marker
    if running is not None and cache_key is not None and cache_key in running.permission_overwrite_cache:
        current = clone_overwrite(running.permission_overwrite_cache[cache_key])
    if current is current_marker:
        current = clone_overwrite(getattr(channel, "overwrites", {}).get(target))

    if overwrites_equal(current if current is not current_marker else None, desired):
        return False

    await channel.set_permissions(target, overwrite=desired, reason=reason)
    if running is not None and cache_key is not None:
        running.permission_overwrite_cache[cache_key] = clone_overwrite(desired)
    return True


def cached_channel_overwrite(
    channel: discord.abc.Messageable,
    target: discord.abc.Snowflake,
    running: RunningGame,
) -> discord.PermissionOverwrite | None:
    channel_id = getattr(channel, "id", None)
    target_id = getattr(target, "id", None)
    if channel_id is not None and target_id is not None:
        cache_key = (channel_id, target_id)
        if cache_key in running.permission_overwrite_cache:
            return clone_overwrite(running.permission_overwrite_cache[cache_key])
    return clone_overwrite(getattr(channel, "overwrites", {}).get(target))


def remember_channel_overwrites(
    running: RunningGame,
    channel: discord.abc.Messageable,
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite],
) -> None:
    channel_id = getattr(channel, "id", None)
    if channel_id is None:
        return
    for target, overwrite in overwrites.items():
        target_id = getattr(target, "id", None)
        if target_id is None:
            continue
        running.permission_overwrite_cache[(channel_id, target_id)] = clone_overwrite(overwrite)


def supports_member_overwrites(channel: discord.abc.Messageable) -> bool:
    return all(
        hasattr(channel, attribute)
        for attribute in ("overwrites", "overwrites_for", "set_permissions")
    )


def get_participant_role(guild: discord.Guild) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=config.participant_role)


def get_dead_player_role(guild: discord.Guild) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=DEAD_PLAYER_ROLE)


def get_spectator_role(guild: discord.Guild) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=SPECTATOR_ROLE)


async def ensure_spectator_role(guild: discord.Guild) -> discord.Role | None:
    spectator_role = get_spectator_role(guild)
    if spectator_role:
        return spectator_role
    try:
        return await guild.create_role(
            name=SPECTATOR_ROLE,
            reason="마피아 게임 관전자 역할 생성",
        )
    except discord.DiscordException:
        return None


def set_chat_values(overwrite: discord.PermissionOverwrite, can_send: bool) -> None:
    overwrite.send_messages = can_send
    overwrite.send_messages_in_threads = can_send
    overwrite.create_public_threads = can_send
    overwrite.create_private_threads = can_send
    overwrite.add_reactions = can_send


async def set_game_channel_chat(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
    participants_can_chat: bool,
    reason: str,
) -> bool:
    if running.anonymous_enabled:
        await set_anonymous_general_chat_permissions(
            guild,
            running,
            can_chat=participants_can_chat,
            reason=reason,
        )
        participants_can_chat = False
    if not supports_member_overwrites(channel):
        return False

    participant_role = get_participant_role(guild)
    if not participant_role:
        await send_embed(
            channel,
            f"'{config.participant_role}' 역할을 찾을 수 없습니다.",
            color=ERROR_EMBED_COLOR,
        )
        return False

    targets = [
        (guild.default_role, False),
        (participant_role, participants_can_chat),
    ]
    failed = False
    for target, can_send in targets:
        if target.id not in running.game_channel_overwrites:
            running.game_channel_overwrites[target.id] = clone_overwrite(channel.overwrites.get(target))

        overwrite = cached_channel_overwrite(channel, target, running)
        if overwrite is None:
            overwrite = channel.overwrites_for(target)
        set_chat_values(overwrite, can_send)
        try:
            await set_permissions_if_changed(
                channel,
                target,
                overwrite=overwrite,
                reason=reason,
                running=running,
            )
        except discord.DiscordException:
            failed = True

    if failed:
        await send_embed(
            channel,
            "게임 채널 권한 변경에 실패했습니다. "
            "봇에게 채널 관리 권한이 있는지 확인하세요.",
            color=ERROR_EMBED_COLOR,
        )
    return not failed


async def set_spectator_game_channel_access(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
    reason: str,
) -> None:
    if not supports_member_overwrites(channel):
        return
    spectator_role = get_spectator_role(guild)
    if not spectator_role:
        return
    if spectator_role.id not in running.game_channel_overwrites:
        running.game_channel_overwrites[spectator_role.id] = clone_overwrite(
            channel.overwrites.get(spectator_role)
        )
    try:
        await set_permissions_if_changed(
            channel,
            spectator_role,
            overwrite=spectator_channel_overwrite(),
            reason=reason,
            running=running,
        )
    except discord.DiscordException:
        await send_embed(
            channel,
            "관전자 채널 권한 변경에 실패했습니다. 봇에게 채널 관리 권한이 있는지 확인하세요.",
            color=ERROR_EMBED_COLOR,
        )


async def set_channel_slowmode(
    channel: discord.abc.Messageable,
    running: RunningGame,
    seconds: int,
    reason: str,
) -> None:
    if not isinstance(channel, discord.TextChannel):
        return
    if running.original_slowmode_delay is None:
        running.original_slowmode_delay = channel.slowmode_delay
        running.original_slowmode_channel_id = channel.id
    try:
        await channel.edit(slowmode_delay=seconds, reason=reason)
    except discord.DiscordException:
        await send_embed(
            channel,
            "채널 슬로우모드 변경에 실패했습니다. 봇에게 채널 관리 권한이 있는지 확인하세요.",
            color=ERROR_EMBED_COLOR,
        )


async def restore_channel_slowmode(guild: discord.Guild, running: RunningGame) -> None:
    if running.original_slowmode_delay is None:
        return
    channel = guild.get_channel(running.original_slowmode_channel_id or running.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.edit(
            slowmode_delay=running.original_slowmode_delay,
            reason="마피아 게임 종료로 슬로우모드 복구",
        )
    except discord.DiscordException:
        await send_embed(channel, "채널 슬로우모드 복구에 실패했습니다.", color=ERROR_EMBED_COLOR)


async def restore_game_channel_chat(guild: discord.Guild, running: RunningGame) -> None:
    if not running.game_channel_overwrites:
        return

    channel = guild.get_channel(running.channel_id)
    if not isinstance(channel, discord.abc.Messageable) or not supports_member_overwrites(channel):
        running.game_channel_overwrites.clear()
        return

    failed_targets: list[str] = []
    for target_id, original in list(running.game_channel_overwrites.items()):
        target = guild.default_role if target_id == guild.default_role.id else guild.get_role(target_id)
        if not target:
            running.game_channel_overwrites.pop(target_id, None)
            continue

        try:
            await set_permissions_if_changed(
                channel,
                target,
                overwrite=clone_overwrite(original),
                reason="마피아 게임 종료로 게임 채널 권한 복구",
                running=running,
            )
            running.game_channel_overwrites.pop(target_id, None)
        except discord.DiscordException:
            failed_targets.append(target.name)

    if failed_targets:
        await send_embed(
            channel,
            "게임 채널 권한 복구에 실패했습니다: "
            + ", ".join(failed_targets)
            + "\n봇에게 채널 관리 권한이 있는지 확인하세요.",
            color=ERROR_EMBED_COLOR,
        )


async def set_member_chat_permission(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
    player: Player,
    can_send: bool,
    reason: str,
) -> None:
    if running.anonymous_enabled:
        await set_anonymous_general_input_access(
            guild,
            running,
            player,
            can_chat=can_send,
            reason=reason,
        )
        if can_send:
            await set_anonymous_channel_slowmode(
                guild,
                running.anonymous_input_channel_ids.get(player.user_id),
                0,
                "마피아 게임 익명 최후변론 슬로우모드 해제",
            )
        return
    if not supports_member_overwrites(channel):
        return
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return
    if member.id not in running.member_channel_overwrites:
        running.member_channel_overwrites[member.id] = clone_overwrite(channel.overwrites.get(member))
    overwrite = channel.overwrites_for(member)
    set_chat_values(overwrite, can_send)
    try:
        await set_permissions_if_changed(channel, member, overwrite=overwrite, reason=reason, running=running)
    except discord.DiscordException:
        await send_embed(channel, "최후변론 채팅 권한 변경에 실패했습니다.", color=ERROR_EMBED_COLOR)


async def restore_member_channel_chat(guild: discord.Guild, running: RunningGame) -> None:
    if running.anonymous_enabled and running.final_defense_user_id is not None:
        player = running.game.get_player(running.final_defense_user_id)
        if player:
            await set_anonymous_general_input_access(
                guild,
                running,
                player,
                can_chat=False,
                reason="마피아 게임 최후변론 종료로 익명 입력 권한 제거",
            )
            await set_anonymous_channel_slowmode(
                guild,
                running.anonymous_input_channel_ids.get(player.user_id),
                config.chat_slowmode_seconds,
                "마피아 게임 익명 최후변론 종료로 슬로우모드 복구",
            )
    running.final_defense_user_id = None
    if not running.member_channel_overwrites:
        return
    channel = guild.get_channel(running.channel_id)
    if not isinstance(channel, discord.abc.Messageable) or not supports_member_overwrites(channel):
        running.member_channel_overwrites.clear()
        return
    for user_id, original in list(running.member_channel_overwrites.items()):
        member = await get_guild_member(guild, user_id)
        if not member:
            running.member_channel_overwrites.pop(user_id, None)
            continue
        try:
            await set_permissions_if_changed(
                channel,
                member,
                overwrite=clone_overwrite(original),
                reason="마피아 게임 최후변론 채팅 권한 복구",
                running=running,
            )
        except discord.DiscordException:
            pass
        running.member_channel_overwrites.pop(user_id, None)


async def sync_madam_seduction_permissions(
    guild: discord.Guild,
    running: RunningGame,
    *,
    reason: str,
) -> None:
    channel = guild.get_channel(running.channel_id)
    for player in running.game.alive_players():
        if running.game.is_madam_seduced(player):
            for role in PRIVATE_CHAT_ROLES:
                await set_player_private_channel_access(
                    guild,
                    running,
                    role,
                    player,
                    can_chat=False,
                    reason=reason,
                )
        else:
            await refresh_player_private_channel_access(guild, running, player)

    if running.anonymous_enabled:
        for player in running.game.alive_players():
            await set_anonymous_general_input_access(
                guild,
                running,
                player,
                can_chat=can_use_anonymous_general_chat(running, player),
                reason=reason,
            )
        return
    if not isinstance(channel, discord.abc.Messageable) or not supports_member_overwrites(channel):
        running.madam_seduction_channel_overwrites.clear()
        return

    current_seduced = {
        player.user_id
        for player in running.game.alive_players()
        if running.game.is_madam_seduced(player)
    }
    for player in running.game.alive_players():
        member = await get_guild_member(guild, player.user_id)
        if not member:
            continue
        if player.user_id in current_seduced:
            if member.id not in running.madam_seduction_channel_overwrites:
                running.madam_seduction_channel_overwrites[member.id] = clone_overwrite(channel.overwrites.get(member))
            overwrite = channel.overwrites_for(member)
            set_chat_values(overwrite, False)
            with suppress(discord.DiscordException):
                await set_permissions_if_changed(channel, member, overwrite=overwrite, reason=reason, running=running)
        elif member.id in running.madam_seduction_channel_overwrites:
            original = running.madam_seduction_channel_overwrites.pop(member.id, None)
            with suppress(discord.DiscordException):
                await set_permissions_if_changed(
                    channel,
                    member,
                    overwrite=clone_overwrite(original),
                    reason=reason,
                    running=running,
                )

    for user_id, original in list(running.madam_seduction_channel_overwrites.items()):
        if user_id in current_seduced:
            continue
        member = await get_guild_member(guild, user_id)
        running.madam_seduction_channel_overwrites.pop(user_id, None)
        if member:
            with suppress(discord.DiscordException):
                await set_permissions_if_changed(
                    channel,
                    member,
                    overwrite=clone_overwrite(original),
                    reason=reason,
                    running=running,
                )


async def restore_madam_seduction_permissions(guild: discord.Guild, running: RunningGame) -> None:
    if running.anonymous_enabled:
        return
    channel = guild.get_channel(running.channel_id)
    if not isinstance(channel, discord.abc.Messageable) or not supports_member_overwrites(channel):
        running.madam_seduction_channel_overwrites.clear()
        return
    for user_id, original in list(running.madam_seduction_channel_overwrites.items()):
        member = await get_guild_member(guild, user_id)
        running.madam_seduction_channel_overwrites.pop(user_id, None)
        if member:
            with suppress(discord.DiscordException):
                await set_permissions_if_changed(
                    channel,
                    member,
                    overwrite=clone_overwrite(original),
                    reason="마피아 게임 종료로 마담 유혹 채팅 권한 복구",
                    running=running,
                )


async def remove_participant_role_from_dead(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
) -> bool:
    participant_role = get_participant_role(guild)
    if not participant_role:
        return False

    member = await get_guild_member(guild, player.user_id)
    if not member:
        return False
    if participant_role not in member.roles:
        return True

    try:
        await member.remove_roles(
            participant_role,
            reason="마피아 게임 사망자 발언 제한",
        )
        return True
    except discord.DiscordException:
        return False


async def add_dead_player_role(
    guild: discord.Guild,
    player: Player,
) -> bool | None:
    dead_role = get_dead_player_role(guild)
    if not dead_role:
        return None

    member = await get_guild_member(guild, player.user_id)
    if not member:
        return False
    if dead_role in member.roles:
        return True

    try:
        await member.add_roles(
            dead_role,
            reason="마피아 게임 사망자 역할 부여",
        )
        return True
    except discord.DiscordException:
        return False


async def remove_participant_roles_from_ids(
    guild: discord.Guild,
    user_ids: set[int],
    reason: str,
) -> list[str]:
    participant_role = get_participant_role(guild)
    if not participant_role:
        return [str(user_id) for user_id in sorted(user_ids)]

    failed_names: list[str] = []
    for user_id in sorted(user_ids):
        member = await get_guild_member(guild, user_id)
        if not member:
            continue

        try:
            if participant_role in member.roles:
                await member.remove_roles(
                    participant_role,
                    reason=reason,
                )
        except discord.DiscordException:
            failed_names.append(display_name(member))
    return failed_names


async def remove_dead_player_roles_from_ids(
    guild: discord.Guild,
    user_ids: set[int],
    reason: str,
) -> list[str]:
    dead_role = get_dead_player_role(guild)
    if not dead_role:
        return []

    failed_names: list[str] = []
    for user_id in sorted(user_ids):
        member = await get_guild_member(guild, user_id)
        if not member:
            continue

        try:
            if dead_role in member.roles:
                await member.remove_roles(
                    dead_role,
                    reason=reason,
                )
        except discord.DiscordException:
            failed_names.append(display_name(member))
    return failed_names


async def remove_spectator_roles_from_ids(
    guild: discord.Guild,
    user_ids: set[int],
    reason: str,
) -> list[str]:
    spectator_role = get_spectator_role(guild)
    if not spectator_role:
        return []

    failed_names: list[str] = []
    for user_id in sorted(user_ids):
        member = await get_guild_member(guild, user_id)
        if not member:
            continue

        try:
            if spectator_role in member.roles:
                await member.remove_roles(
                    spectator_role,
                    reason=reason,
                )
        except discord.DiscordException:
            failed_names.append(display_name(member))
    return failed_names


async def remove_game_participant_roles(guild: discord.Guild, running: RunningGame) -> None:
    if not running.participant_user_ids:
        return

    failed_names = await remove_participant_roles_from_ids(
        guild,
        running.participant_user_ids,
        "마피아 게임 종료로 참가자 역할 제거",
    )
    channel = guild.get_channel(running.channel_id)
    if failed_names and isinstance(channel, discord.abc.Messageable):
        await send_embed(
            channel,
            f"'{config.participant_role}' 역할 제거에 실패한 참가자: "
            + ", ".join(failed_names)
            + "\n봇에게 역할 관리 권한이 있고, 봇 역할이 참가자 역할보다 위에 있는지 확인하세요.",
            color=ERROR_EMBED_COLOR,
        )


async def remove_game_dead_player_roles(guild: discord.Guild, running: RunningGame) -> None:
    if not running.participant_user_ids:
        return

    failed_names = await remove_dead_player_roles_from_ids(
        guild,
        running.participant_user_ids,
        "마피아 게임 종료로 사망자 역할 제거",
    )
    channel = guild.get_channel(running.channel_id)
    if failed_names and isinstance(channel, discord.abc.Messageable):
        await send_embed(
            channel,
            f"'{DEAD_PLAYER_ROLE}' 역할 제거에 실패한 참가자: "
            + ", ".join(failed_names)
            + "\n봇에게 역할 관리 권한이 있고, 봇 역할이 사망자 역할보다 위에 있는지 확인하세요.",
            color=ERROR_EMBED_COLOR,
        )


async def remove_game_spectator_roles(guild: discord.Guild, running: RunningGame) -> None:
    if not running.spectator_user_ids:
        return

    failed_names = await remove_spectator_roles_from_ids(
        guild,
        running.spectator_user_ids,
        "마피아 게임 종료로 관전자 역할 제거",
    )
    channel = guild.get_channel(running.channel_id)
    if failed_names and isinstance(channel, discord.abc.Messageable):
        await send_embed(
            channel,
            f"'{SPECTATOR_ROLE}' 역할 제거에 실패한 관전자: "
            + ", ".join(failed_names)
            + "\n봇에게 역할 관리 권한이 있고, 봇 역할이 관전자 역할보다 위에 있는지 확인하세요.",
            color=ERROR_EMBED_COLOR,
        )


def source_channel_category(
    channel: discord.abc.Messageable,
) -> discord.CategoryChannel | None:
    if isinstance(channel, discord.TextChannel):
        return channel.category
    if isinstance(channel, discord.Thread) and isinstance(channel.parent, discord.TextChannel):
        return channel.parent.category
    return None


def private_channel_overwrite(can_chat: bool) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=can_chat,
        send_messages=can_chat,
        send_messages_in_threads=can_chat,
        create_public_threads=can_chat,
        create_private_threads=can_chat,
        read_message_history=can_chat,
        add_reactions=can_chat,
    )


def dead_channel_overwrite(can_view: bool, can_chat: bool) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=can_view,
        send_messages=can_chat,
        send_messages_in_threads=can_chat,
        create_public_threads=can_chat,
        create_private_threads=can_chat,
        read_message_history=can_view,
        add_reactions=can_chat,
    )


def spectator_channel_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=False,
        send_messages_in_threads=False,
        create_public_threads=False,
        create_private_threads=False,
        read_message_history=True,
        add_reactions=False,
    )


def add_spectator_overwrite(
    guild: discord.Guild,
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite],
) -> None:
    spectator_role = get_spectator_role(guild)
    if spectator_role:
        overwrites[spectator_role] = spectator_channel_overwrite()


def anonymous_input_overwrite(can_view: bool, can_chat: bool) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=can_view,
        send_messages=can_chat,
        send_messages_in_threads=can_chat,
        create_public_threads=False,
        create_private_threads=False,
        read_message_history=can_view,
        add_reactions=can_chat,
    )


def sanitize_channel_part(value: str) -> str:
    return value.replace(" ", "-").replace("/", "-").lower()


def assign_anonymous_aliases(running: RunningGame) -> None:
    players = sorted(running.game.players, key=lambda player: player.user_id)
    if normalized_anonymous_name_mode() == "number":
        aliases = [f"{index}번" for index in range(1, len(players) + 1)]
    else:
        aliases = list(ANIMAL_ALIASES)
    secrets.SystemRandom().shuffle(aliases)
    running.anonymous_aliases = {
        player.user_id: aliases[index] if index < len(aliases) else f"{index + 1}번"
        for index, player in enumerate(players)
    }


def apply_anonymous_player_names(running: RunningGame) -> None:
    if not running.anonymous_enabled:
        return
    if not running.anonymous_original_names:
        running.anonymous_original_names = {
            player.user_id: player.name for player in running.game.players
        }
    for player in running.game.players:
        alias = running.anonymous_aliases.get(player.user_id)
        if alias:
            player.name = alias


def original_player_name(running: RunningGame, player: Player) -> str:
    return running.anonymous_original_names.get(player.user_id, player.name)


async def create_text_channel_safe(
    guild: discord.Guild,
    *,
    name: str,
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite],
    category: discord.CategoryChannel | None,
    reason: str,
    slowmode_delay: int | None = None,
    topic: str | None = None,
) -> discord.TextChannel | None:
    options: dict[str, object] = {}
    if slowmode_delay is not None:
        options["slowmode_delay"] = slowmode_delay
    if topic is not None:
        options["topic"] = topic[:1024]
    try:
        return await guild.create_text_channel(
            name=name,
            overwrites=overwrites,
            category=category,
            reason=reason,
            **options,
        )
    except discord.DiscordException:
        try:
            return await guild.create_text_channel(
                name=name,
                overwrites=overwrites,
                reason=reason,
                **options,
            )
        except discord.DiscordException:
            return None


def anonymous_base_overwrites(
    guild: discord.Guild,
    *,
    participant_can_view: bool,
    participant_can_chat: bool,
    default_can_view: bool,
    default_can_chat: bool,
) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: anonymous_input_overwrite(default_can_view, default_can_chat),
    }
    participant_role = get_participant_role(guild)
    manager_role = discord.utils.get(guild.roles, name=config.manager_role)
    bot_member = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
    if participant_role:
        overwrites[participant_role] = anonymous_input_overwrite(participant_can_view, participant_can_chat)
    add_spectator_overwrite(guild, overwrites)
    if manager_role:
        overwrites[manager_role] = anonymous_input_overwrite(False, False)
    if bot_member:
        overwrites[bot_member] = anonymous_input_overwrite(True, True)
    return overwrites


async def ensure_memo_channel(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
) -> discord.TextChannel | None:
    channel_id = running.memo_channel_ids.get(player.user_id)
    channel = guild.get_channel(channel_id) if channel_id else None
    if isinstance(channel, discord.TextChannel):
        return channel

    member = await get_guild_member(guild, player.user_id)
    if not member:
        return None

    source_channel = guild.get_channel(running.channel_id)
    category = source_channel_category(source_channel) if source_channel else None
    participant_role = get_participant_role(guild)
    manager_role = discord.utils.get(guild.roles, name=config.manager_role)
    bot_member = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: private_channel_overwrite(False),
        member: private_channel_overwrite(True),
    }
    if participant_role:
        overwrites[participant_role] = private_channel_overwrite(False)
    add_spectator_overwrite(guild, overwrites)
    if manager_role:
        overwrites[manager_role] = private_channel_overwrite(False)
    if bot_member:
        overwrites[bot_member] = private_channel_overwrite(True)

    channel = await create_text_channel_safe(
        guild,
        name=f"{sanitize_channel_part(status_display_name(running, player))}-메모",
        overwrites=overwrites,
        category=category,
        reason="마피아 게임 개인 메모 채널 생성",
        slowmode_delay=0,
    )
    if not isinstance(channel, discord.TextChannel):
        return None

    running.memo_channel_ids[player.user_id] = channel.id
    await send_embed(
        channel,
        "개인 메모 채널입니다.\n"
        "`/메모 참가자 메모내용`으로 참가자별 메모를 저장하고, "
        "`/메모 참가자`로 저장한 메모를 다시 볼 수 있습니다.",
        title="메모 채널",
        color=SUCCESS_EMBED_COLOR,
    )
    return channel


async def create_memo_channels(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    failed_names: list[str] = []
    for player in running.game.players:
        memo_channel = await ensure_memo_channel(guild, running, player)
        if not memo_channel:
            failed_names.append(status_display_name(running, player))
    if failed_names:
        await send_embed(
            channel,
            "개인 메모 채널 생성 실패: " + ", ".join(failed_names),
            color=ERROR_EMBED_COLOR,
        )


async def create_anonymous_chat_channels(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    if not running.anonymous_enabled:
        return
    category = source_channel_category(channel)
    assign_anonymous_aliases(running)
    apply_anonymous_player_names(running)
    for player in running.game.players:
        member = await get_guild_member(guild, player.user_id)
        if not member:
            continue
        alias = running.anonymous_aliases[player.user_id]
        input_overwrites = anonymous_base_overwrites(
            guild,
            participant_can_view=False,
            participant_can_chat=False,
            default_can_view=False,
            default_can_chat=False,
        )
        input_overwrites[member] = anonymous_input_overwrite(
            True,
            can_use_anonymous_general_chat(running, player),
        )
        input_channel = await create_text_channel_safe(
            guild,
            name=f"{sanitize_channel_part(alias)}-채팅",
            overwrites=input_overwrites,
            category=category,
            reason="마피아 게임 개인 익명 입력 채널 생성",
            slowmode_delay=config.chat_slowmode_seconds,
        )
        if not input_channel:
            continue
        remember_channel_overwrites(running, input_channel, input_overwrites)
        running.anonymous_input_channel_ids[player.user_id] = input_channel.id
        running.anonymous_input_channel_owners[input_channel.id] = player.user_id
        await send_embed(
            input_channel,
            f"당신의 익명 이름은 **{alias}** 입니다.\n"
            "이 개인 채널이 일반 채팅을 대체합니다.\n"
            "여기에 쓰면 모든 참가자의 개인 채팅방에 익명으로 전달됩니다.",
            title="익명 입력 채널",
            color=SUCCESS_EMBED_COLOR,
        )


async def hide_original_game_channel_for_anonymous(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    if not running.anonymous_enabled or not supports_member_overwrites(channel):
        return
    participant_role = get_participant_role(guild)
    if participant_role:
        bot_member = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
        if bot_member:
            if bot_member.id not in running.member_channel_overwrites:
                running.member_channel_overwrites[bot_member.id] = clone_overwrite(
                    channel.overwrites.get(bot_member)
                )
            bot_overwrite = channel.overwrites_for(bot_member)
            bot_overwrite.view_channel = True
            bot_overwrite.read_message_history = True
            set_chat_values(bot_overwrite, True)
            with suppress(discord.DiscordException):
                await set_permissions_if_changed(
                    channel,
                    bot_member,
                    overwrite=bot_overwrite,
                    reason="마피아 게임 익명 모드 진행을 위한 봇 권한 유지",
                    running=running,
                )
        if participant_role.id not in running.game_channel_overwrites:
            running.game_channel_overwrites[participant_role.id] = clone_overwrite(
                channel.overwrites.get(participant_role)
            )
        overwrite = channel.overwrites_for(participant_role)
        overwrite.view_channel = False
        overwrite.read_message_history = False
        set_chat_values(overwrite, False)
        with suppress(discord.DiscordException):
            await set_permissions_if_changed(
                channel,
                participant_role,
                overwrite=overwrite,
                reason="마피아 게임 익명 모드로 원본 채널 참가자 역할 열람 차단",
                running=running,
            )
        return

    for player in running.game.players:
        member = await get_guild_member(guild, player.user_id)
        if not member:
            continue
        if member.id not in running.anonymous_original_channel_overwrites:
            running.anonymous_original_channel_overwrites[member.id] = clone_overwrite(
                channel.overwrites.get(member)
            )
        overwrite = channel.overwrites_for(member)
        overwrite.view_channel = False
        overwrite.send_messages = False
        overwrite.read_message_history = False
        try:
            await set_permissions_if_changed(
                channel,
                member,
                overwrite=overwrite,
                reason="마피아 게임 익명 모드로 원본 채널 참가자 열람 차단",
                running=running,
            )
        except discord.DiscordException:
            continue


async def restore_original_game_channel_for_anonymous(
    guild: discord.Guild,
    running: RunningGame,
) -> None:
    if not running.anonymous_original_channel_overwrites:
        return
    channel = guild.get_channel(running.channel_id)
    if not isinstance(channel, discord.abc.Messageable) or not supports_member_overwrites(channel):
        running.anonymous_original_channel_overwrites.clear()
        return
    for user_id, original in list(running.anonymous_original_channel_overwrites.items()):
        member = await get_guild_member(guild, user_id)
        if not member:
            running.anonymous_original_channel_overwrites.pop(user_id, None)
            continue
        try:
            await set_permissions_if_changed(
                channel,
                member,
                overwrite=clone_overwrite(original),
                reason="마피아 게임 익명 모드 종료로 원본 채널 권한 복구",
                running=running,
            )
        except discord.DiscordException:
            pass
        running.anonymous_original_channel_overwrites.pop(user_id, None)


def anonymous_personal_channel(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
) -> discord.TextChannel | None:
    channel_id = running.anonymous_input_channel_ids.get(player.user_id)
    channel = guild.get_channel(channel_id) if channel_id else None
    return channel if isinstance(channel, discord.TextChannel) else None


async def send_anonymous_personal_embed(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    message: str,
    *,
    view: discord.ui.View | None = None,
    title: str = "마피아 게임",
    color: discord.Color = DEFAULT_EMBED_COLOR,
) -> discord.Message | None:
    channel = anonymous_personal_channel(guild, running, player)
    if not channel:
        return None
    with suppress(discord.DiscordException):
        return await send_embed(channel, message, view=view, title=title, color=color)
    return None


async def broadcast_anonymous_personal_embed(
    guild: discord.Guild,
    running: RunningGame,
    message: str,
    *,
    view: discord.ui.View | None = None,
    title: str = "마피아 게임",
    color: discord.Color = DEFAULT_EMBED_COLOR,
    include_dead: bool = False,
) -> list[discord.Message]:
    if not running.anonymous_enabled:
        return []
    targets = running.game.players if include_dead else running.game.alive_players()
    if view is None:
        semaphore = asyncio.Semaphore(8)

        async def send_one(player: Player) -> discord.Message | None:
            async with semaphore:
                return await send_anonymous_personal_embed(
                    guild,
                    running,
                    player,
                    message,
                    view=None,
                    title=title,
                    color=color,
                )

        results = await asyncio.gather(
            *(send_one(player) for player in targets),
            return_exceptions=True,
        )
        return [result for result in results if isinstance(result, discord.Message)]

    messages: list[discord.Message] = []
    for player in targets:
        sent = await send_anonymous_personal_embed(
            guild,
            running,
            player,
            message,
            view=view,
            title=title,
            color=color,
        )
        if sent:
            messages.append(sent)
    return messages


async def send_game_embed(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
    message: str,
    *,
    view: discord.ui.View | None = None,
    title: str = "마피아 게임",
    color: discord.Color = DEFAULT_EMBED_COLOR,
    include_dead: bool = False,
    broadcast: bool = True,
) -> discord.Message:
    sent = await send_embed(channel, message, view=view, title=title, color=color)
    if broadcast:
        await broadcast_anonymous_personal_embed(
            guild,
            running,
            message,
            view=view,
            title=title,
            color=color,
            include_dead=include_dead,
        )
    return sent


async def announce_cult_bells_now(running: RunningGame, count: int) -> None:
    if count <= 0:
        return
    guild = bot.get_guild(running.guild_id)
    if not guild:
        return
    channel = guild.get_channel(running.channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        return
    await send_game_embed(
        guild,
        channel,
        running,
        "\n".join("교주의 종소리가 울렸습니다." for _ in range(count)),
        title="교주 포교",
        color=WARNING_EMBED_COLOR,
        include_dead=True,
    )


async def handle_madam_seduction_result(
    guild: discord.Guild,
    running: RunningGame,
    result: VoteResult,
) -> None:
    if not result.madam_seduced:
        return

    for player in result.madam_seduced:
        await send_player_secret(
            guild,
            running,
            player,
            "마담에게 유혹당했습니다. 다음 낮이 될 때까지 능력을 사용할 수 없고 말할 수 없습니다.\n"
            "마피아팀이라면 능력 사용은 가능하지만, 유혹 중에는 마피아 비밀방에도 말할 수 없습니다.",
        )

    for player in running.game.alive_players():
        if running.game.is_known_mafia_team(player):
            await add_player_to_private_role_channel(guild, running, Role.MAFIA, player)

    for madam in running.game.alive_players():
        if madam.role == Role.MADAM and madam.user_id in running.game.madam_contacted:
            await add_player_to_private_role_channel(guild, running, Role.MAFIA, madam)
            await send_player_secret(
                guild,
                running,
                madam,
                "[접대] 마피아팀과 접선했습니다. 이제 마피아 비밀방에서 밤 대화가 가능합니다.",
            )

    await sync_madam_seduction_permissions(
        guild,
        running,
        reason="마피아 게임 마담 유혹으로 채팅 권한 갱신",
    )


async def send_player_secret(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    message: str,
    view: discord.ui.View | None = None,
) -> bool:
    if running.anonymous_enabled:
        sent = await send_anonymous_personal_embed(
            guild,
            running,
            player,
            message,
            view=view,
            title="비밀 메시지",
        )
        if sent:
            return True
    member = await get_guild_member(guild, player.user_id)
    return bool(member and await send_private(member, message, view))


def role_chat_players(game: MafiaGame, role: Role) -> list[Player]:
    if role == Role.MAFIA:
        return [player for player in game.alive_players() if game.is_known_mafia_team(player)]
    return [player for player in game.alive_players() if player.role == role]


def lover_chat_is_open(game: MafiaGame) -> bool:
    return (
        game.phase == Phase.NIGHT
        and sum(
            1
            for player in game.alive_players()
            if player.role == Role.LOVER and not game.is_frog(player)
        ) >= 2
    )


def anonymous_role_status_players(running: RunningGame, role: Role) -> list[Player]:
    granted_ids = {
        user_id
        for (user_id, granted_role) in running.anonymous_role_input_channel_ids
        if granted_role == role
    }
    players: list[Player] = []
    for player in running.game.alive_players():
        if running.game.is_frog(player):
            continue
        if player.user_id in granted_ids:
            players.append(player)
        elif role == Role.MAFIA and running.game.is_known_mafia_team(player):
            players.append(player)
        elif role == Role.CULT_LEADER and running.game.is_cult_team(player):
            players.append(player)
        elif player.role == role:
            players.append(player)
    return sorted({player.user_id: player for player in players}.values(), key=lambda item: item.name.casefold())


def role_status_players(running: RunningGame, role: Role) -> list[Player]:
    if running.anonymous_enabled:
        return anonymous_role_status_players(running, role)
    return sorted(role_chat_players(running.game, role), key=lambda item: item.name.casefold())


def mafia_night_target_status_text(running: RunningGame) -> str:
    if running.game.phase != Phase.NIGHT:
        return ""
    actors = [
        actor
        for actor in running.game.night_action_actors()
        if actor.role == Role.MAFIA
    ]
    if not actors:
        return ""

    lines = ["마피아 처치 선택 현황"]
    for actor in sorted(actors, key=lambda item: status_display_name(running, item).casefold()):
        target_id = running.game.mafia_display_targets.get(actor.user_id) or running.game.mafia_targets.get(actor.user_id)
        target = running.game.get_player(target_id) if target_id else None
        target_name = status_display_name(running, target) if target else "미선택"
        lines.append(f"- {status_display_name(running, actor)} → {target_name}")
    return "\n".join(lines)


def role_channel_status_text(running: RunningGame, role: Role) -> str:
    players = role_status_players(running, role)
    if not players:
        text = "현재 생존: 없음"
    else:
        names = ", ".join(status_display_name(running, player) for player in players)
        text = f"현재 생존: {names}"
    if role == Role.MAFIA:
        mafia_status = mafia_night_target_status_text(running)
        if mafia_status:
            text = f"{text}\n\n{mafia_status}"
    return text


def anonymous_role_status_text(running: RunningGame, role: Role) -> str:
    return role_channel_status_text(running, role)


async def upsert_anonymous_role_status_message(
    channel: discord.TextChannel,
    running: RunningGame,
    role: Role,
    key: Role | tuple[int, Role],
) -> None:
    status_id = (
        running.anonymous_role_status_message_ids.get(key)
        if isinstance(key, Role)
        else running.anonymous_role_input_status_message_ids.get(key)
    )
    embed = make_embed(
        anonymous_role_status_text(running, role),
        title=f"{role.value} 채팅 현황",
        color=SUCCESS_EMBED_COLOR,
    )
    if status_id:
        with suppress(discord.DiscordException):
            message = await channel.fetch_message(status_id)
            await message.edit(embed=embed)
            return
    with suppress(discord.DiscordException):
        message = await channel.send(embed=embed)
        if isinstance(key, Role):
            running.anonymous_role_status_message_ids[key] = message.id
        else:
            running.anonymous_role_input_status_message_ids[key] = message.id


async def sync_anonymous_role_statuses(
    guild: discord.Guild,
    running: RunningGame,
    *,
    update_messages: bool = True,
) -> None:
    if not running.anonymous_enabled:
        return
    for role in PRIVATE_CHAT_ROLES:
        if not should_create_role_chat(running.game, role):
            continue
        topic = f"{role.value} 익명 채팅 | {anonymous_role_status_text(running, role)}"
        for (user_id, input_role), input_id in list(running.anonymous_role_input_channel_ids.items()):
            if input_role != role:
                continue
            input_channel = guild.get_channel(input_id)
            if isinstance(input_channel, discord.TextChannel):
                with suppress(discord.DiscordException):
                    await input_channel.edit(topic=topic[:1024])
                if update_messages:
                    await upsert_anonymous_role_status_message(
                        input_channel,
                        running,
                        role,
                        (user_id, input_role),
                    )


async def upsert_private_role_status_message(
    guild: discord.Guild,
    running: RunningGame,
    role: Role,
) -> None:
    if running.anonymous_enabled:
        return
    channel_id = running.private_channel_ids.get(role)
    channel = guild.get_channel(channel_id) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return
    embed = make_embed(
        role_channel_status_text(running, role),
        title=f"{role.value} 채팅 현황",
        color=SUCCESS_EMBED_COLOR,
    )
    status_id = running.private_role_status_message_ids.get(role)
    if status_id:
        with suppress(discord.DiscordException):
            message = await channel.fetch_message(status_id)
            await message.edit(embed=embed)
            return
    with suppress(discord.DiscordException):
        message = await channel.send(embed=embed)
        running.private_role_status_message_ids[role] = message.id


async def sync_role_status_message(
    guild: discord.Guild,
    running: RunningGame,
    role: Role,
) -> None:
    if running.anonymous_enabled:
        await sync_anonymous_role_statuses(guild, running)
        return
    await upsert_private_role_status_message(guild, running, role)


def should_create_role_chat(game: MafiaGame, role: Role) -> bool:
    if role == Role.MAFIA:
        return any(player.role == Role.MAFIA for player in game.players) or any(
            player.role in MAFIA_SPECIAL_ROLES for player in game.players
        )
    return any(player.role == role for player in game.players)


async def set_anonymous_role_access(
    guild: discord.Guild,
    running: RunningGame,
    role: Role,
    player: Player,
    *,
    can_access: bool,
    reason: str,
) -> None:
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return

    input_id = running.anonymous_role_input_channel_ids.get((player.user_id, role))
    input_channel = guild.get_channel(input_id) if input_id else None
    if can_access and not isinstance(input_channel, discord.TextChannel):
        source_channel = guild.get_channel(running.channel_id)
        category = source_channel_category(source_channel) if source_channel else None
        alias = running.anonymous_aliases.get(player.user_id, str(player.user_id))
        input_overwrites = anonymous_base_overwrites(
            guild,
            participant_can_view=False,
            participant_can_chat=False,
            default_can_view=False,
            default_can_chat=False,
        )
        input_overwrites[member] = anonymous_input_overwrite(True, True)
        input_channel = await create_text_channel_safe(
            guild,
            name=f"{sanitize_channel_part(alias)}-{sanitize_channel_part(role.value)}-채팅",
            overwrites=input_overwrites,
            category=category,
            reason="마피아 게임 익명 역할 입력 채널 생성",
            slowmode_delay=0,
        )
        if isinstance(input_channel, discord.TextChannel):
            running.anonymous_role_input_channel_ids[(player.user_id, role)] = input_channel.id
            running.anonymous_role_input_channels[input_channel.id] = (player.user_id, role)
            await send_embed(
                input_channel,
                f"{role.value} 역할 개인 채팅 채널입니다.\n"
                "여기에 쓰면 같은 역할의 개인 채팅방에 익명으로 전달됩니다.\n"
                "이 채널 하나에서 역할 대화와 밤 행동을 처리하세요.",
                title="익명 역할 입력",
                color=SUCCESS_EMBED_COLOR,
            )
    elif isinstance(input_channel, discord.TextChannel):
        if input_channel.slowmode_delay:
            with suppress(discord.DiscordException):
                await input_channel.edit(
                    slowmode_delay=0,
                    reason="마피아 게임 역할 채팅방 슬로우모드 해제",
                )
        with suppress(discord.DiscordException):
            await set_permissions_if_changed(
                input_channel,
                member,
                overwrite=anonymous_input_overwrite(can_access, can_access),
                reason=reason,
                running=running,
            )


async def set_anonymous_role_view_only(
    guild: discord.Guild,
    running: RunningGame,
    role: Role,
    player: Player,
    *,
    can_view: bool,
    reason: str,
) -> None:
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return

    input_id = running.anonymous_role_input_channel_ids.get((player.user_id, role))
    input_channel = guild.get_channel(input_id) if input_id else None
    if can_view and not isinstance(input_channel, discord.TextChannel):
        source_channel = guild.get_channel(running.channel_id)
        category = source_channel_category(source_channel) if source_channel else None
        alias = running.anonymous_aliases.get(player.user_id, str(player.user_id))
        input_overwrites = anonymous_base_overwrites(
            guild,
            participant_can_view=False,
            participant_can_chat=False,
            default_can_view=False,
            default_can_chat=False,
        )
        input_overwrites[member] = anonymous_input_overwrite(True, False)
        input_channel = await create_text_channel_safe(
            guild,
            name=f"{sanitize_channel_part(alias)}-{sanitize_channel_part(role.value)}-채팅",
            overwrites=input_overwrites,
            category=category,
            reason="마피아 게임 익명 역할 보기 전용 채널 생성",
            slowmode_delay=0,
        )
        if isinstance(input_channel, discord.TextChannel):
            running.anonymous_role_input_channel_ids[(player.user_id, role)] = input_channel.id
            running.anonymous_role_input_channels[input_channel.id] = (player.user_id, role)
            await send_embed(
                input_channel,
                f"{role.value} 역할 보기 전용 채널입니다.\n"
                "이 채널에서 역할 대화를 확인할 수 있습니다.",
                title="익명 역할 채팅",
                color=SUCCESS_EMBED_COLOR,
            )
    elif isinstance(input_channel, discord.TextChannel):
        if input_channel.slowmode_delay:
            with suppress(discord.DiscordException):
                await input_channel.edit(
                    slowmode_delay=0,
                    reason="마피아 게임 역할 채팅방 슬로우모드 해제",
                )
        with suppress(discord.DiscordException):
            await set_permissions_if_changed(
                input_channel,
                member,
                overwrite=anonymous_input_overwrite(can_view, False),
                reason=reason,
                running=running,
            )


async def create_anonymous_role_channels(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    failed_roles: list[str] = []
    for role in PRIVATE_CHAT_ROLES:
        if not should_create_role_chat(running.game, role):
            continue
        before_count = len(running.anonymous_role_input_channel_ids)
        for player in role_chat_players(running.game, role):
            await set_anonymous_role_access(
                guild,
                running,
                role,
                player,
                can_access=True,
                reason="마피아 게임 익명 역할 채팅 권한 부여",
            )
        if len(running.anonymous_role_input_channel_ids) == before_count and role_chat_players(running.game, role):
            failed_roles.append(role.value)
    await sync_anonymous_role_statuses(guild, running, update_messages=False)
    if failed_roles:
        await send_embed(
            channel,
            "익명 역할 개인 채팅방 생성 실패: " + ", ".join(failed_roles),
            color=ERROR_EMBED_COLOR,
        )


async def create_private_role_channels(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    if running.anonymous_enabled:
        await create_anonymous_role_channels(guild, channel, running)
        return

    category = source_channel_category(channel)
    failed_roles: list[str] = []
    participant_role = get_participant_role(guild)
    manager_role = discord.utils.get(guild.roles, name=config.manager_role)
    bot_member = guild.me or (guild.get_member(bot.user.id) if bot.user else None)

    for role in PRIVATE_CHAT_ROLES:
        players = [player for player in running.game.players if player.role == role]
        should_create = bool(players)
        if role == Role.MAFIA:
            should_create = should_create or any(
                player.role in MAFIA_SPECIAL_ROLES for player in running.game.players
            )
        if not should_create:
            continue

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: private_channel_overwrite(False),
        }
        if participant_role:
            overwrites[participant_role] = private_channel_overwrite(False)
        add_spectator_overwrite(guild, overwrites)
        if manager_role:
            overwrites[manager_role] = private_channel_overwrite(False)
        if bot_member:
            overwrites[bot_member] = private_channel_overwrite(True)

        for player in players:
            member = await get_guild_member(guild, player.user_id)
            if member:
                can_open = role != Role.LOVER or lover_chat_is_open(running.game)
                overwrites[member] = private_channel_overwrite(can_open)

        try:
            private_channel = await guild.create_text_channel(
                name=PRIVATE_CHANNEL_NAMES[role],
                overwrites=overwrites,
                category=category,
                reason="마피아 게임 역할별 비공개 채팅방 생성",
                slowmode_delay=0,
            )
        except discord.DiscordException:
            try:
                private_channel = await guild.create_text_channel(
                    name=PRIVATE_CHANNEL_NAMES[role],
                    overwrites=overwrites,
                    reason="마피아 게임 역할별 비공개 채팅방 생성",
                    slowmode_delay=0,
                )
            except discord.DiscordException:
                failed_roles.append(role.value)
                continue

        running.private_channel_ids[role] = private_channel.id
        await send_embed(
            private_channel,
            f"{role.value} 전용 비공개 채팅방입니다. "
            f"살아있는 {role.value}만 볼 수 있습니다.\n\n"
            f"{special_role_rule_text(role)}",
            title="역할 비공개 채널",
            color=SUCCESS_EMBED_COLOR,
        )
        await upsert_private_role_status_message(guild, running, role)

    if failed_roles:
        await send_embed(
            channel,
            "역할별 비공개 채널 생성에 실패했습니다: "
            + ", ".join(failed_roles)
            + "\n봇에게 채널 관리 권한이 있는지 확인하세요.",
            color=ERROR_EMBED_COLOR,
        )


def shaman_chat_status_text(running: RunningGame) -> str:
    if running.anonymous_enabled:
        return (
            "사망자와 영매가 접신하는 채팅입니다.\n"
            "영매는 이 채널만 볼 수 있으며, 밤에만 말할 수 있습니다.\n"
            "익명 모드에서는 각자의 영매 개인 채널을 사용하세요."
        )
    return (
        "사망자와 영매가 접신하는 채팅입니다.\n"
        "영매는 이 채널만 볼 수 있으며, 밤에만 말할 수 있습니다."
    )


async def upsert_shaman_chat_status(guild: discord.Guild, running: RunningGame) -> None:
    if running.shaman_channel_id is None:
        return
    channel = guild.get_channel(running.shaman_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    embed = make_embed(
        shaman_chat_status_text(running),
        title="영매 채팅 상태",
        color=SUCCESS_EMBED_COLOR,
    )
    if running.shaman_status_message_id:
        with suppress(discord.DiscordException):
            message = await channel.fetch_message(running.shaman_status_message_id)
            await message.edit(embed=embed)
            return
    with suppress(discord.DiscordException):
        message = await channel.send(embed=embed)
        running.shaman_status_message_id = message.id


async def create_shaman_chat_channel(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    if not any(player.role == Role.SHAMAN for player in running.game.players):
        return
    category = source_channel_category(channel)
    participant_role = get_participant_role(guild)
    dead_role = get_dead_player_role(guild)
    manager_role = discord.utils.get(guild.roles, name=config.manager_role)
    bot_member = guild.me or (guild.get_member(bot.user.id) if bot.user else None)

    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: dead_channel_overwrite(False, False),
    }
    if participant_role:
        overwrites[participant_role] = dead_channel_overwrite(False, False)
    if dead_role:
        overwrites[dead_role] = dead_channel_overwrite(True, not running.anonymous_enabled)
    add_spectator_overwrite(guild, overwrites)
    if manager_role:
        overwrites[manager_role] = dead_channel_overwrite(False, False)
    if bot_member:
        overwrites[bot_member] = dead_channel_overwrite(True, True)

    for player in running.game.alive_players():
        if player.role != Role.SHAMAN:
            continue
        member = await get_guild_member(guild, player.user_id)
        if member:
            overwrites[member] = dead_channel_overwrite(True, False)

    shaman_channel = await create_text_channel_safe(
        guild,
        name=SHAMAN_CHAT_CHANNEL_NAME,
        overwrites=overwrites,
        category=category,
        reason="마피아 게임 영매 채팅방 생성",
    )
    if not isinstance(shaman_channel, discord.TextChannel):
        await send_embed(
            channel,
            "영매 채팅방 생성에 실패했습니다. 봇에게 채널 관리 권한이 있는지 확인하세요.",
            color=ERROR_EMBED_COLOR,
        )
        return

    running.shaman_channel_id = shaman_channel.id
    await send_embed(
        shaman_channel,
        "영매와 사망자가 접신하는 채팅방입니다.\n"
        "사망자는 이곳에서 대화할 수 있고, 영매는 밤에만 말할 수 있습니다.\n"
        "영매는 사망자 채팅방을 볼 수 없습니다.",
        title="영매 채팅방",
        color=SUCCESS_EMBED_COLOR,
    )
    if running.anonymous_enabled:
        for player in running.game.alive_players():
            if player.role != Role.SHAMAN:
                continue
            await set_anonymous_shaman_input_access(
                guild,
                running,
                player,
                can_view=True,
                can_chat=False,
                reason="마피아 게임 영매 익명 채팅 채널 생성",
            )
    await upsert_shaman_chat_status(guild, running)


async def create_frog_chat_channel(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    if not any(player.role == Role.WITCH for player in running.game.players):
        return
    category = source_channel_category(channel)
    participant_role = get_participant_role(guild)
    manager_role = discord.utils.get(guild.roles, name=config.manager_role)
    bot_member = guild.me or (guild.get_member(bot.user.id) if bot.user else None)

    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: dead_channel_overwrite(False, False),
    }
    if participant_role:
        overwrites[participant_role] = dead_channel_overwrite(False, False)
    add_spectator_overwrite(guild, overwrites)
    if manager_role:
        overwrites[manager_role] = dead_channel_overwrite(False, False)
    if bot_member:
        overwrites[bot_member] = dead_channel_overwrite(True, True)

    try:
        frog_channel = await guild.create_text_channel(
            name=FROG_CHAT_CHANNEL_NAME,
            overwrites=overwrites,
            category=category,
            reason="마피아 게임 개구리 채팅방 생성",
        )
    except discord.DiscordException:
        try:
            frog_channel = await guild.create_text_channel(
                name=FROG_CHAT_CHANNEL_NAME,
                overwrites=overwrites,
                reason="마피아 게임 개구리 채팅방 생성",
            )
        except discord.DiscordException:
            await send_embed(
                channel,
                "개구리 채팅방 생성에 실패했습니다. 봇에게 채널 관리 권한이 있는지 확인하세요.",
                color=ERROR_EMBED_COLOR,
            )
            return

    running.frog_channel_id = frog_channel.id
    await send_embed(
        frog_channel,
        "개구리 전용 채팅방입니다.\n"
        "저주에 걸린 참가자가 이곳에 쓴 말은 게임 채널에 개굴 소리로 전달됩니다.",
        title="개구리 채팅방",
        color=SUCCESS_EMBED_COLOR,
    )


async def set_dead_channel_member_access(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    *,
    can_view: bool,
    can_chat: bool,
    reason: str,
) -> None:
    await set_anonymous_dead_input_access(
        guild,
        running,
        player,
        can_view=can_view,
        can_chat=can_chat,
        reason=reason,
    )
    if running.anonymous_enabled and not player.alive:
        await set_anonymous_general_input_access(
            guild,
            running,
            player,
            can_chat=False,
            reason="마피아 게임 사망으로 일반 익명 채팅 권한 제거",
        )


async def set_shaman_channel_member_access(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    *,
    can_view: bool,
    can_chat: bool,
    reason: str,
) -> None:
    if running.shaman_channel_id is None:
        return
    channel = guild.get_channel(running.shaman_channel_id)
    if not isinstance(channel, discord.TextChannel):
        running.shaman_channel_id = None
        return
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return
    dead_role = get_dead_player_role(guild)
    should_set_member = (
        dead_role is None
        or player.role == Role.SHAMAN
        or cached_channel_overwrite(channel, member, running) is not None
        or not can_view
        or not can_chat
    )
    if should_set_member:
        with suppress(discord.DiscordException):
            await set_permissions_if_changed(
                channel,
                member,
                overwrite=dead_channel_overwrite(can_view, can_chat and not running.anonymous_enabled and not running.game.is_madam_seduced(player)),
                reason=reason,
                running=running,
            )
    if running.anonymous_enabled:
        await set_anonymous_shaman_input_access(
            guild,
            running,
            player,
            can_view=can_view,
            can_chat=can_chat and not running.game.is_madam_seduced(player),
            reason=reason,
        )
    await upsert_shaman_chat_status(guild, running)


async def set_frog_channel_member_access(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    *,
    can_view: bool,
    can_chat: bool,
    reason: str,
) -> None:
    if running.frog_channel_id is None:
        return
    channel = guild.get_channel(running.frog_channel_id)
    if not isinstance(channel, discord.TextChannel):
        running.frog_channel_id = None
        return
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return
    try:
        await set_permissions_if_changed(
            channel,
            member,
            overwrite=dead_channel_overwrite(can_view, can_chat),
            reason=reason,
            running=running,
        )
    except discord.DiscordException:
        return


async def set_frog_game_channel_permission(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    *,
    can_chat: bool,
    reason: str,
) -> None:
    channel = guild.get_channel(running.channel_id)
    if not isinstance(channel, discord.abc.Messageable) or not supports_member_overwrites(channel):
        return
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return
    if member.id not in running.frog_game_channel_overwrites:
        running.frog_game_channel_overwrites[member.id] = clone_overwrite(channel.overwrites.get(member))
    overwrite = channel.overwrites_for(member)
    set_chat_values(overwrite, can_chat)
    try:
        await set_permissions_if_changed(channel, member, overwrite=overwrite, reason=reason, running=running)
    except discord.DiscordException:
        return


async def restore_frog_game_channel_permission(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
) -> None:
    channel = guild.get_channel(running.channel_id)
    if not isinstance(channel, discord.abc.Messageable) or not supports_member_overwrites(channel):
        running.frog_game_channel_overwrites.pop(player.user_id, None)
        return
    member = await get_guild_member(guild, player.user_id)
    if not member:
        running.frog_game_channel_overwrites.pop(player.user_id, None)
        return
    original = running.frog_game_channel_overwrites.pop(member.id, None)
    try:
        await set_permissions_if_changed(
            channel,
            member,
            overwrite=clone_overwrite(original),
            reason="마피아 게임 개구리 저주 종료로 채팅 권한 복구",
            running=running,
        )
    except discord.DiscordException:
        return


async def sync_shaman_channel_permissions(
    guild: discord.Guild,
    running: RunningGame,
    *,
    can_chat: bool,
) -> None:
    for player in running.game.alive_players():
        if player.role != Role.SHAMAN:
            continue
        await set_shaman_channel_member_access(
            guild,
            running,
            player,
            can_view=True,
            can_chat=can_chat,
            reason="마피아 게임 영매 접신 권한 갱신",
        )
    await upsert_shaman_chat_status(guild, running)


async def disable_anonymous_channels_for_player(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
) -> None:
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return
    input_id = running.anonymous_input_channel_ids.get(player.user_id)
    input_channel = guild.get_channel(input_id) if input_id else None
    if isinstance(input_channel, discord.TextChannel):
        with suppress(discord.DiscordException):
            await set_permissions_if_changed(
                input_channel,
                member,
                overwrite=anonymous_input_overwrite(True, False),
                reason="마피아 게임 익명 채팅 권한 제거",
                running=running,
            )
    can_dead_chat = (not player.alive) and player.user_id not in running.game.purified_dead_ids
    await set_anonymous_dead_input_access(
        guild,
        running,
        player,
        can_view=can_dead_chat,
        can_chat=can_dead_chat,
        reason="마피아 게임 사망자 익명 채팅 권한 갱신",
    )
    can_shaman_view = (
        can_dead_chat
        or (player.alive and player.role == Role.SHAMAN and not running.game.is_frog(player))
    )
    await set_anonymous_shaman_input_access(
        guild,
        running,
        player,
        can_view=can_shaman_view,
        can_chat=can_use_anonymous_shaman_chat(running, player),
        reason="마피아 게임 영매 익명 채팅 권한 갱신",
    )
    for role in PRIVATE_CHAT_ROLES:
        await set_anonymous_role_access(
            guild,
            running,
            role,
            player,
            can_access=False,
            reason="마피아 게임 익명 역할 채팅 권한 제거",
        )
    await sync_anonymous_role_statuses(guild, running)


async def disable_private_role_channel_for_player(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
) -> None:
    if running.anonymous_enabled:
        await disable_anonymous_channels_for_player(guild, running, player)
        return

    member = await get_guild_member(guild, player.user_id)
    if not member:
        return

    for channel in private_role_channels(guild, running):
        if cached_channel_overwrite(channel, member, running) is None:
            continue
        try:
            await set_permissions_if_changed(
                channel,
                member,
                overwrite=private_channel_overwrite(False),
                reason="마피아 게임 역할 채팅방 권한 제거",
                running=running,
            )
        except discord.DiscordException:
            continue
    for role in PRIVATE_CHAT_ROLES:
        await upsert_private_role_status_message(guild, running, role)


def private_role_channels(
    guild: discord.Guild,
    running: RunningGame,
) -> list[discord.TextChannel]:
    channels_by_id: dict[int, discord.TextChannel] = {}
    private_channel_names = set(PRIVATE_CHANNEL_NAMES.values())

    for role, channel_id in list(running.private_channel_ids.items()):
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            channels_by_id[channel.id] = channel
        else:
            running.private_channel_ids.pop(role, None)

    for channel in guild.text_channels:
        if channel.name in private_channel_names:
            channels_by_id[channel.id] = channel

    return list(channels_by_id.values())


async def sync_dead_players_private_role_channels(
    guild: discord.Guild,
    running: RunningGame,
) -> None:
    for dead_player in running.game.dead_players():
        await disable_private_role_channel_for_player(guild, running, dead_player)


async def add_player_to_private_role_channel(
    guild: discord.Guild,
    running: RunningGame,
    channel_role: Role,
    player: Player,
) -> None:
    if running.anonymous_enabled:
        can_access = (
            player.alive
            and not running.game.is_frog(player)
            and not running.game.is_madam_seduced(player)
        )
        await set_anonymous_role_access(
            guild,
            running,
            channel_role,
            player,
            can_access=can_access,
            reason="마피아 게임 익명 역할 채팅 권한 부여",
        )
        await sync_anonymous_role_statuses(guild, running)
        return

    if not player.alive:
        await disable_private_role_channel_for_player(guild, running, player)
        return

    channel_id = running.private_channel_ids.get(channel_role)
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return
    can_chat = not running.game.is_madam_seduced(player)
    try:
        await set_permissions_if_changed(
            channel,
            member,
            overwrite=private_channel_overwrite(can_chat),
            reason="마피아 게임 접선으로 비공개 채널 권한 부여",
            running=running,
        )
    except discord.DiscordException:
        return
    await upsert_private_role_status_message(guild, running, channel_role)


async def set_player_private_channel_access(
    guild: discord.Guild,
    running: RunningGame,
    channel_role: Role,
    player: Player,
    *,
    can_chat: bool,
    reason: str,
) -> None:
    if running.anonymous_enabled:
        can_chat = can_chat and not running.game.is_madam_seduced(player)
        await set_anonymous_role_access(
            guild,
            running,
            channel_role,
            player,
            can_access=can_chat,
            reason=reason,
        )
        await sync_anonymous_role_statuses(guild, running)
        return

    channel_id = running.private_channel_ids.get(channel_role)
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    member = await get_guild_member(guild, player.user_id)
    if not member:
        return
    can_chat = can_chat and not running.game.is_madam_seduced(player)
    try:
        await set_permissions_if_changed(
            channel,
            member,
            overwrite=private_channel_overwrite(can_chat),
            reason=reason,
            running=running,
        )
    except discord.DiscordException:
        return


async def sync_lover_chat_access(
    guild: discord.Guild,
    running: RunningGame,
    *,
    reason: str,
) -> None:
    if not any(player.role == Role.LOVER for player in running.game.players):
        return
    can_open = lover_chat_is_open(running.game)
    for player in running.game.players:
        if player.role != Role.LOVER:
            continue
        await set_player_private_channel_access(
            guild,
            running,
            Role.LOVER,
            player,
            can_chat=can_open and player.alive and not running.game.is_frog(player),
            reason=reason,
        )


async def sync_cult_team_channel_access(
    guild: discord.Guild,
    running: RunningGame,
) -> None:
    if not any(player.role in {Role.CULT_LEADER, Role.FANATIC} for player in running.game.players):
        return

    role = Role.CULT_LEADER
    reason = "마피아 게임 교주팀 채팅 권한 갱신"
    if running.anonymous_enabled:
        for player in running.game.players:
            can_view = (
                player.alive
                and not running.game.is_frog(player)
                and running.game.is_cult_team(player)
            )
            if player.alive and can_view and player.role == Role.CULT_LEADER and not running.game.is_madam_seduced(player):
                await set_anonymous_role_access(
                    guild,
                    running,
                    role,
                    player,
                    can_access=True,
                    reason=reason,
                )
            else:
                await set_anonymous_role_view_only(
                    guild,
                    running,
                    role,
                    player,
                    can_view=can_view,
                    reason=reason,
                )
        await sync_anonymous_role_statuses(guild, running)
        return

    channel_id = running.private_channel_ids.get(role)
    channel = guild.get_channel(channel_id) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return

    for player in running.game.players:
        member = await get_guild_member(guild, player.user_id)
        if not member:
            continue
        can_view = (
            player.alive
            and not running.game.is_frog(player)
            and running.game.is_cult_team(player)
        )
        can_chat = player.alive and can_view and player.role == Role.CULT_LEADER and not running.game.is_madam_seduced(player)
        with suppress(discord.DiscordException):
            await set_permissions_if_changed(
                channel,
                member,
                overwrite=dead_channel_overwrite(can_view, can_chat),
                reason=reason,
                running=running,
            )


async def refresh_player_private_channel_access(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
) -> None:
    if not player.alive or running.game.is_frog(player):
        await disable_private_role_channel_for_player(guild, running, player)
        return
    if running.anonymous_enabled:
        member = await get_guild_member(guild, player.user_id)
        input_id = running.anonymous_input_channel_ids.get(player.user_id)
        input_channel = guild.get_channel(input_id) if input_id else None
        if member and isinstance(input_channel, discord.TextChannel):
            with suppress(discord.DiscordException):
                await set_permissions_if_changed(
                    input_channel,
                    member,
                    overwrite=anonymous_input_overwrite(
                        True,
                        running.game.phase == Phase.DAY
                        and not running.game.is_frog(player)
                        and not running.game.is_madam_seduced(player),
                    ),
                    reason="마피아 게임 익명 채팅 권한 복구",
                    running=running,
                )
    if player.role in PRIVATE_CHAT_ROLES:
        await add_player_to_private_role_channel(guild, running, player.role, player)
    if running.game.is_known_mafia_team(player):
        await add_player_to_private_role_channel(guild, running, Role.MAFIA, player)


async def delete_private_role_channels(guild: discord.Guild, running: RunningGame) -> None:
    for role, channel_id in list(running.private_channel_ids.items()):
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                await channel.delete(reason="마피아 게임 종료로 역할별 비공개 채널 삭제")
            except discord.DiscordException:
                continue
        running.private_channel_ids.pop(role, None)


async def delete_memo_channels(guild: discord.Guild, running: RunningGame) -> None:
    for user_id, channel_id in list(running.memo_channel_ids.items()):
        channel = guild.get_channel(channel_id)
        if channel:
            with suppress(discord.DiscordException):
                await channel.delete(reason="마피아 게임 종료로 개인 메모 채널 삭제")
        running.memo_channel_ids.pop(user_id, None)
    running.memos.clear()


async def delete_anonymous_chat_channels(guild: discord.Guild, running: RunningGame) -> None:
    channel_ids: set[int] = set()
    channel_ids.update(running.anonymous_input_channel_ids.values())
    channel_ids.update(running.anonymous_dead_input_channel_ids.values())
    channel_ids.update(running.anonymous_shaman_input_channel_ids.values())
    channel_ids.update(running.anonymous_role_input_channel_ids.values())

    for channel_id in channel_ids:
        channel = guild.get_channel(channel_id)
        if channel:
            with suppress(discord.DiscordException):
                await channel.delete(reason="마피아 게임 종료로 익명 채팅방 삭제")

    running.anonymous_input_channel_ids.clear()
    running.anonymous_input_channel_owners.clear()
    running.anonymous_dead_input_channel_ids.clear()
    running.anonymous_dead_input_channel_owners.clear()
    running.anonymous_shaman_input_channel_ids.clear()
    running.anonymous_shaman_input_channel_owners.clear()
    running.anonymous_role_input_channel_ids.clear()
    running.anonymous_role_input_channels.clear()
    running.anonymous_role_status_message_ids.clear()
    running.anonymous_role_input_status_message_ids.clear()
    running.anonymous_aliases.clear()
    running.anonymous_original_names.clear()
    running.anonymous_webhook_urls.clear()


async def cleanup_old_dead_chat_channels(guild: discord.Guild) -> None:
    for channel in guild.text_channels:
        if channel.name != OLD_DEAD_CHAT_CHANNEL_NAME:
            continue
        with suppress(discord.DiscordException):
            await channel.delete(reason="마피아 게임 공용 사망자 채팅방 미사용으로 삭제")


async def delete_shaman_chat_channel(guild: discord.Guild, running: RunningGame) -> None:
    if running.shaman_channel_id is None:
        return
    channel = guild.get_channel(running.shaman_channel_id)
    if channel:
        try:
            await channel.delete(reason="마피아 게임 종료로 영매 채팅방 삭제")
        except discord.DiscordException:
            return
    running.shaman_channel_id = None
    running.shaman_status_message_id = None


async def delete_frog_chat_channel(guild: discord.Guild, running: RunningGame) -> None:
    if running.frog_channel_id is None:
        return
    channel = guild.get_channel(running.frog_channel_id)
    if channel:
        try:
            await channel.delete(reason="마피아 게임 종료로 개구리 채팅방 삭제")
        except discord.DiscordException:
            return
    running.frog_channel_id = None


async def warm_anonymous_startup_resources(guild_id: int, running: RunningGame) -> None:
    await asyncio.sleep(5)
    guild = bot.get_guild(guild_id)
    if not guild or games.get(running.guild_id) is not running or not running.anonymous_enabled:
        return

    await sync_anonymous_role_statuses(guild, running)

    channel_ids: list[int] = []
    channel_ids.extend(running.anonymous_input_channel_ids.values())
    channel_ids.extend(running.anonymous_dead_input_channel_ids.values())
    channel_ids.extend(running.anonymous_shaman_input_channel_ids.values())
    channel_ids.extend(running.anonymous_role_input_channel_ids.values())
    seen: set[int] = set()
    for channel_id in channel_ids:
        if channel_id in seen:
            continue
        seen.add(channel_id)
        if games.get(running.guild_id) is not running or not running.anonymous_enabled:
            return
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            await prepare_anonymous_webhook(channel, running)
            await asyncio.sleep(0.05)


async def restore_all_frog_game_channel_permissions(
    guild: discord.Guild,
    running: RunningGame,
) -> None:
    for user_id in list(running.frog_game_channel_overwrites):
        player = running.game.get_player(user_id)
        if player:
            await restore_frog_game_channel_permission(guild, running, player)
        else:
            running.frog_game_channel_overwrites.pop(user_id, None)


async def cleanup_game(guild: discord.Guild, running: RunningGame) -> None:
    await restore_all_frog_game_channel_permissions(guild, running)
    await restore_member_channel_chat(guild, running)
    await restore_madam_seduction_permissions(guild, running)
    await restore_original_game_channel_for_anonymous(guild, running)
    await restore_game_channel_chat(guild, running)
    await restore_channel_slowmode(guild, running)
    await remove_game_participant_roles(guild, running)
    await remove_game_dead_player_roles(guild, running)
    await remove_game_spectator_roles(guild, running)
    await delete_private_role_channels(guild, running)
    await delete_memo_channels(guild, running)
    await delete_anonymous_chat_channels(guild, running)
    await delete_shaman_chat_channel(guild, running)
    await delete_frog_chat_channel(guild, running)


async def game_loop(guild: discord.Guild, running: RunningGame) -> None:
    channel = guild.get_channel(running.channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        games.pop(running.guild_id, None)
        return

    try:
        original_channel = channel
        await create_anonymous_chat_channels(guild, original_channel, running)
        channel = original_channel
        await set_spectator_game_channel_access(
            guild,
            original_channel,
            running,
            "마피아 게임 관전자 게임 채널 열람 권한 설정",
        )
        await cleanup_old_dead_chat_channels(guild)
        await hide_original_game_channel_for_anonymous(guild, original_channel, running)
        await create_private_role_channels(guild, channel, running)
        await create_memo_channels(guild, channel, running)
        await sync_cult_team_channel_access(guild, running)
        await create_shaman_chat_channel(guild, channel, running)
        await create_frog_chat_channel(guild, channel, running)
        await send_game_embed(
            guild,
            channel,
            running,
            public_game_settings_text(running.game, "게임 방 설정입니다."),
            title="방 설정",
            broadcast=not running.anonymous_enabled,
        )
        await send_game_embed(
            guild,
            channel,
            running,
            game_rule_text(running.game, running.reveal_death_roles),
            title="게임 설명",
            broadcast=not running.anonymous_enabled,
        )
        await send_roles(guild, running)
        await send_game_embed(
            guild,
            channel,
            running,
            "역할 배정이 끝났습니다. 각자 비밀 메시지와 역할별 비공개 채널을 확인하세요.",
            title="역할 배정 완료",
            color=SUCCESS_EMBED_COLOR,
            broadcast=not running.anonymous_enabled,
        )
        if running.anonymous_enabled:
            asyncio.create_task(warm_anonymous_startup_resources(guild.id, running))
        await upsert_game_status(guild, running)

        while running.game.phase != Phase.ENDED:
            await run_night(guild, channel, running)
            if await announce_winner(channel, running):
                break

            await set_game_channel_chat(
                guild,
                channel,
                running,
                participants_can_chat=True,
                reason="마피아 게임 낮 토론 시작",
            )
            await sync_madam_seduction_permissions(
                guild,
                running,
                reason="마피아 게임 낮 시작으로 마담 유혹 권한 갱신",
            )
            await set_channel_slowmode(
                channel,
                running,
                config.chat_slowmode_seconds,
                "마피아 게임 낮 토론 슬로우모드 적용",
            )
            await upsert_game_status(guild, running)
            day_result = await run_day_discussion(channel, running)
            if day_result == "stop":
                break

            await run_vote_phase(guild, channel, running)

            if await announce_winner(channel, running):
                break
    except asyncio.CancelledError:
        return
    except Exception as error:
        print(f"Game loop error: {error!r}")
        with suppress(discord.DiscordException):
            await send_embed(
                original_channel,
                "게임 시작 중 오류가 발생해 자동 정리했습니다.\n"
                f"오류: `{type(error).__name__}: {error}`",
                title="게임 시작 오류",
                color=ERROR_EMBED_COLOR,
            )
    finally:
        await cleanup_game(guild, running)
        if games.get(running.guild_id) is running:
            games.pop(running.guild_id, None)


async def run_vote_phase(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    running.game.start_vote()
    await upsert_game_status(guild, running)
    running.vote_complete_event.clear()
    alive = running.game.alive_players()
    await set_game_channel_chat(
        guild,
        channel,
        running,
        participants_can_chat=False,
        reason="마피아 게임 투표 시작",
    )
    await send_game_embed(
        guild,
        channel,
        running,
        f"지목 투표를 시작합니다. {config.vote_seconds}초 안에 최후변론에 세울 사람을 선택하세요.\n"
        "투표 중에는 게임 채널 채팅이 비활성화됩니다.\n"
        "생존자가 모두 투표하면 남은 시간을 기다리지 않고 바로 정산합니다.",
        view=DayVoteView(running.guild_id, alive),
        title="지목 투표 시작",
    )
    await wait_for_event_or_timeout(running.vote_complete_event, config.vote_seconds)

    vote_result = running.game.resolve_nomination_vote()
    await handle_madam_seduction_result(guild, running, vote_result)
    vote_summary = anonymous_vote_summary(running.game, vote_result)
    nominee = vote_result.executed
    if not nominee:
        if vote_result.tied:
            message = "투표가 동률이라 최후변론 대상이 없습니다."
        elif vote_result.skipped:
            message = "스킵이 최다 득표하여 최후변론 대상이 없습니다."
        else:
            message = "투표가 없어 최후변론 대상이 없습니다."
        await send_game_embed(
            guild,
            channel,
            running,
            f"{message}\n\n익명 투표 집계\n{vote_summary}",
            title="지목 투표 결과",
        )
        return

    await send_game_embed(
        guild,
        channel,
        running,
        f"지목 투표 결과, {nominee.name} 님이 최후변론 대상이 되었습니다.\n\n익명 투표 집계\n{vote_summary}",
        title="지목 투표 결과",
    )
    await set_final_defense_mode(guild, channel, running, nominee)
    await send_game_embed(
        guild,
        channel,
        running,
        f"{nominee.name} 님의 최후변론 시간입니다. 20초 동안 지목된 사람만 말할 수 있습니다.\n"
        "이 시간 동안 슬로우모드는 해제됩니다.",
        title="최후변론",
    )
    await asyncio.sleep(20)
    await restore_member_channel_chat(guild, running)

    running.game.start_confirmation_vote()
    await upsert_game_status(guild, running)
    running.confirm_complete_event.clear()
    await send_game_embed(
        guild,
        channel,
        running,
        f"{nominee.name} 님 처형 여부를 찬반투표합니다. {CONFIRM_VOTE_SECONDS}초 안에 선택하세요.\n"
        "찬성이 반대보다 많으면 처형됩니다.",
        view=ConfirmVoteView(running.guild_id),
        title="찬반투표",
    )
    await wait_for_event_or_timeout(running.confirm_complete_event, CONFIRM_VOTE_SECONDS)
    confirm_result = running.game.resolve_confirmation_vote(nominee.user_id)
    await set_channel_slowmode(
        channel,
        running,
        config.chat_slowmode_seconds,
        "마피아 게임 찬반투표 종료 후 슬로우모드 복구",
    )

    counts = confirm_result.vote_counts
    summary = f"찬성 {counts.get(True, 0)}표 / 반대 {counts.get(False, 0)}표"
    judge_notice = ""
    if confirm_result.decided_by_judge and confirm_result.judge:
        if confirm_result.judge_choice is None:
            judge_choice = "미투표(처형 없음)"
        else:
            judge_choice = "찬성" if confirm_result.judge_choice else "반대"
        judge_notice = (
            f"\n\n[판사 {confirm_result.judge.name}님이 투표 결과를 정했습니다]\n"
            f"판사의 선택: {judge_choice}"
        )
    if confirm_result.blocked_by_politician:
        await send_game_embed(
            guild,
            channel,
            running,
            f"찬반투표 결과, {nominee.name} 님은 **정치인** 입니다.\n"
            "[정치인은 투표로 죽지 않습니다]\n\n"
            f"{nominee.name} 님은 처형되지 않고 밤으로 넘어갑니다."
            f"{judge_notice}\n\n"
            f"찬반투표 집계\n{summary}",
            title="찬반투표 결과",
            color=WARNING_EMBED_COLOR,
        )
    elif confirm_result.executed:
        killed_players = [confirm_result.executed, *confirm_result.extra_killed]
        killed_lines: list[str] = []
        for killed in killed_players:
            removed_role = await remove_participant_role_from_dead(guild, running, killed)
            added_dead_role = await add_dead_player_role(guild, killed)
            await set_dead_channel_member_access(
                guild,
                running,
                killed,
                can_view=True,
                can_chat=killed.user_id not in running.game.purified_dead_ids,
                reason="마피아 게임 사망자 채팅방 권한 부여",
            )
            await set_shaman_channel_member_access(
                guild,
                running,
                killed,
                can_view=True,
                can_chat=killed.user_id not in running.game.purified_dead_ids,
                reason="마피아 게임 영매 채팅방 권한 부여",
            )
            await remove_frog_permissions(guild, running, killed)
            await disable_private_role_channel_for_player(guild, running, killed)
            if killed.role == Role.SCIENTIST and killed.user_id in running.game.scientist_contacted:
                await set_player_private_channel_access(
                    guild,
                    running,
                    Role.MAFIA,
                    killed,
                    can_chat=True,
                    reason="마피아 게임 과학자 유착으로 마피아 채널 권한 부여",
                )
            line = f"- {killed.name}: {death_role_text(running, killed)}"
            if removed_role:
                line += f" '{config.participant_role}' 역할을 제거했습니다."
            else:
                line += (
                    f" '{config.participant_role}' 역할 제거에 실패했습니다. "
                    "봇의 역할 관리 권한과 역할 순서를 확인하세요."
                )
            if added_dead_role is True:
                line += f" '{DEAD_PLAYER_ROLE}' 역할을 부여했습니다."
            elif added_dead_role is None:
                line += f" '{DEAD_PLAYER_ROLE}' 역할을 찾지 못했습니다."
            else:
                line += f" '{DEAD_PLAYER_ROLE}' 역할 부여에 실패했습니다."
            killed_lines.append(line)
        await sync_dead_players_private_role_channels(guild, running)
        await sync_cult_team_channel_access(guild, running)
        await sync_lover_chat_access(guild, running, reason="마피아 게임 투표 사망으로 연인 채팅 권한 갱신")
        await upsert_game_status(guild, running)

        message = f"찬반투표 결과, {confirm_result.executed.name} 님이 처형되었습니다."
        if confirm_result.extra_killed:
            if confirm_result.executed.role == Role.TERRORIST:
                message += "\n테러리스트의 [산화]가 발동해 지목 중이던 적 팀도 함께 사망했습니다."
            else:
                message += "\n처형 대상이 지목하고 있던 시민팀이 아닌 대상도 함께 사망했습니다."
        await send_game_embed(
            guild,
            channel,
            running,
            f"{message}\n\n사망자\n"
            + "\n".join(killed_lines)
            + f"{judge_notice}\n\n찬반투표 집계\n{summary}",
            title="찬반투표 결과",
            include_dead=True,
        )
    elif confirm_result.tied:
        await send_game_embed(
            guild,
            channel,
            running,
            f"찬반투표가 동률이라 처형하지 않습니다.{judge_notice}\n\n찬반투표 집계\n{summary}",
            title="찬반투표 결과",
        )
    else:
        reject_message = (
            "판사의 선택으로 처형하지 않습니다."
            if confirm_result.decided_by_judge
            else "반대가 많아 처형하지 않습니다."
        )
        await send_game_embed(
            guild,
            channel,
            running,
            f"{reject_message}{judge_notice}\n\n찬반투표 집계\n{summary}",
            title="찬반투표 결과",
        )


async def set_final_defense_mode(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
    nominee: Player,
) -> None:
    running.final_defense_user_id = nominee.user_id
    await set_game_channel_chat(
        guild,
        channel,
        running,
        participants_can_chat=False,
        reason="마피아 게임 최후변론 시작",
    )
    if not running.game.is_frog(nominee) and not running.game.is_madam_seduced(nominee):
        await set_member_chat_permission(
            guild,
            channel,
            running,
            nominee,
            True,
            "마피아 게임 최후변론 대상 발언 허용",
        )
    await set_channel_slowmode(channel, running, 0, "마피아 게임 최후변론 슬로우모드 해제")


async def send_hacker_day_actions(
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    guild = bot.get_guild(running.guild_id)
    if not guild:
        return
    failed_names: list[str] = []
    for actor in running.game.hacker_day_actors():
        targets = [
            player
            for player in sorted(running.game.alive_players(), key=lambda item: item.name.casefold())
            if player.user_id != actor.user_id
        ]
        sent = await send_player_secret(
            guild,
            running,
            actor,
            "해커 낮 행동을 선택하세요.\n"
            "해킹은 1회용입니다. 선택한 대상의 직업은 밤이 시작될 때 비밀 메시지로 전달됩니다.\n"
            "해킹 사용 후 자신에게 쓰이는 능력은 해킹 대상에게 우회됩니다.",
            HackerDayActionView(running.guild_id, actor, targets),
        )
        if not sent:
            failed_names.append(actor.name)
    if failed_names:
        await send_embed(
            channel,
            "해커 낮 행동 DM을 보낼 수 없는 참가자: " + ", ".join(failed_names),
            color=ERROR_EMBED_COLOR,
        )


async def send_vigilante_day_actions(
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    guild = bot.get_guild(running.guild_id)
    if not guild:
        return
    failed_names: list[str] = []
    for actor in running.game.vigilante_day_actors():
        targets = [
            player
            for player in sorted(running.game.alive_players(), key=lambda item: item.name.casefold())
            if player.user_id != actor.user_id
        ]
        sent = await send_player_secret(
            guild,
            running,
            actor,
            "자경단원 낮 행동을 선택하세요.\n"
            "숙청 조사는 1회용입니다. 밤이 시작될 때 대상이 마피아팀인지 비밀 메시지로 전달됩니다.\n"
            "숙청 처형은 밤에 확실하게 알고 있는 마피아팀에게 한 번만 시도할 수 있습니다.",
            VigilanteDayActionView(running.guild_id, actor, targets),
        )
        if not sent:
            failed_names.append(actor.name)
    if failed_names:
        await send_embed(
            channel,
            "자경단원 낮 행동 DM을 보낼 수 없는 참가자: " + ", ".join(failed_names),
            color=ERROR_EMBED_COLOR,
        )


async def run_day_discussion(
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> DayDiscussionResult:
    guild = bot.get_guild(running.guild_id)
    running.day_vote_event.clear()
    discussion_seconds = config.discussion_seconds
    extension_used = False
    discussion_time = duration_text(discussion_seconds)
    alive_user_ids = {player.user_id for player in running.game.alive_players()}
    vote_view = DaySkipToVoteView(running.guild_id, alive_user_ids)
    await send_hacker_day_actions(channel, running)
    await send_vigilante_day_actions(channel, running)
    day_message_text = (
        f"{running.game.day_number}일차 낮입니다. {discussion_time} 동안 자유롭게 토론하세요.\n"
        "생존자 과반이 `바로 투표`를 누르면 토론과 연장을 끝내고 바로 지목 투표로 넘어갑니다.\n"
        f"시간이 지나면 {DAY_EXTENSION_VOTE_SECONDS}초 동안 1분 연장 투표가 열립니다. "
        "생존자 과반수가 연장을 누르면 1분 연장되고, 연장은 낮마다 1번만 가능합니다. "
        "과반수가 모이지 않으면 바로 투표로 넘어갑니다.\n"
        f"{running.game.public_status()}"
    )
    if guild:
        day_message = await send_game_embed(
            guild,
            channel,
            running,
            day_message_text,
            view=vote_view,
            title="낮 토론",
        )
    else:
        day_message = await send_embed(channel, day_message_text, view=vote_view, title="낮 토론")

    while running.game.phase == Phase.DAY and games.get(running.guild_id) is running:
        if await wait_for_day_vote_or_timeout(running, discussion_seconds):
            await disable_message_view(day_message, vote_view)
            return "vote"
        if running.game.phase == Phase.ENDED or games.get(running.guild_id) is not running:
            await disable_message_view(day_message, vote_view)
            return "stop"

        if extension_used:
            if guild:
                await send_game_embed(
                    guild,
                    channel,
                    running,
                    "연장된 토론 시간이 종료되었습니다.\n"
                    "토론 연장은 낮마다 1번만 가능하므로 바로 지목 투표로 넘어갑니다.",
                    title="낮 토론 종료",
                )
            else:
                await send_embed(
                    channel,
                    "연장된 토론 시간이 종료되었습니다.\n"
                    "토론 연장은 낮마다 1번만 가능하므로 바로 지목 투표로 넘어갑니다.",
                    title="낮 토론 종료",
                )
            await disable_message_view(day_message, vote_view)
            return "vote"

        alive_user_ids = {player.user_id for player in running.game.alive_players()}
        extension_view = DayExtensionVoteView(running.guild_id, alive_user_ids)
        extension_message_text = (
            f"{duration_text(discussion_seconds)} 토론 시간이 지났습니다.\n"
            f"{DAY_EXTENSION_VOTE_SECONDS}초 안에 생존자 과반수"
            f"({extension_view.required_votes}/{len(alive_user_ids)}명)가 `1분 연장`을 누르면 "
            "낮 토론을 1분 연장합니다.\n"
            "과반수가 모이지 않으면 바로 투표로 넘어갑니다."
        )
        if guild:
            vote_message = await send_game_embed(
                guild,
                channel,
                running,
                extension_message_text,
                view=extension_view,
                title="낮 토론 연장 투표",
            )
        else:
            vote_message = await send_embed(
                channel,
                extension_message_text,
                view=extension_view,
                title="낮 토론 연장 투표",
            )
        skipped_to_vote = await wait_for_day_vote_or_view(running, extension_view)
        extension_view.accepting = False
        disable_view_items(extension_view)

        if skipped_to_vote:
            try:
                await vote_message.edit(
                    embed=make_embed(
                        "생존자 과반수가 바로 투표를 선택해 연장 투표를 종료합니다.\n"
                        "바로 지목 투표로 넘어갑니다.",
                        title="바로 투표",
                        color=SUCCESS_EMBED_COLOR,
                    ),
                    view=extension_view,
                )
            except discord.DiscordException:
                pass
            await disable_message_view(day_message, vote_view)
            return "vote"

        if running.game.phase == Phase.ENDED or games.get(running.guild_id) is not running:
            await disable_message_view(day_message, vote_view)
            return "stop"
        if extension_view.extended:
            extension_used = True
            discussion_seconds = DISCUSSION_EXTENSION_SECONDS
            continue

        try:
            await vote_message.edit(
                embed=make_embed(
                    f"{DAY_EXTENSION_VOTE_SECONDS}초 동안 1분 연장 투표가 과반수에 도달하지 못했습니다. "
                    f"({len(extension_view.voter_ids)}/{extension_view.required_votes}명)\n"
                    "바로 투표로 넘어갑니다.",
                    title="낮 토론 종료",
                ),
                view=extension_view,
            )
        except discord.DiscordException:
            pass
        await disable_message_view(day_message, vote_view)
        return "vote"

    await disable_message_view(day_message, vote_view)
    return "stop"


async def send_roles(guild: discord.Guild, running: RunningGame) -> None:
    channel = guild.get_channel(running.channel_id)
    semaphore = asyncio.Semaphore(8)

    async def send_one(player: Player) -> str | None:
        async with semaphore:
            anonymous_notice = ""
            if running.anonymous_enabled:
                alias = running.anonymous_aliases.get(player.user_id, "익명")
                anonymous_notice = (
                    f"\n\n익명 이름: **{alias}**\n"
                    "채팅은 서버에 생성된 본인 익명 입력 채널에서만 진행하세요."
                )
            sent = await send_player_secret(
                guild,
                running,
                player,
                f"{role_message(running.game, player)}\n\n"
                f"방 설정\n{public_game_settings_text(running.game, '현재 게임 설정입니다.')}\n\n"
                f"게임 설명\n{game_rule_text(running.game, running.reveal_death_roles)}\n\n"
                "본인 역할 설명은 `/마피아능력`, 전체 역할 설명은 `/역할설명`으로 다시 확인할 수 있습니다."
                f"{anonymous_notice}",
            )
            return None if sent else player.name

    results = await asyncio.gather(
        *(send_one(player) for player in running.game.players),
        return_exceptions=True,
    )
    failed_names = [
        result
        for result in results
        if isinstance(result, str)
    ]

    if failed_names and isinstance(channel, discord.abc.Messageable):
        await send_embed(
            channel,
            "비밀 메시지를 보낼 수 없는 참가자: " + ", ".join(failed_names),
            color=ERROR_EMBED_COLOR,
        )


async def restore_frogs_for_new_night(guild: discord.Guild, running: RunningGame) -> None:
    restored = False
    for player in running.game.restore_frogs():
        restored = True
        await set_frog_channel_member_access(
            guild,
            running,
            player,
            can_view=False,
            can_chat=False,
            reason="마피아 게임 개구리 저주 종료",
        )
        await restore_frog_game_channel_permission(guild, running, player)
        await refresh_player_private_channel_access(guild, running, player)
    if restored:
        await sync_cult_team_channel_access(guild, running)
        await sync_shaman_channel_permissions(guild, running, can_chat=running.game.phase == Phase.NIGHT)


async def apply_frog_permissions(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
) -> None:
    await set_frog_channel_member_access(
        guild,
        running,
        player,
        can_view=True,
        can_chat=True,
        reason="마피아 게임 마녀 저주로 개구리 채팅방 권한 부여",
    )
    await set_frog_game_channel_permission(
        guild,
        running,
        player,
        can_chat=False,
        reason="마피아 게임 마녀 저주로 게임 채널 발언 제한",
    )
    if player.role == Role.SHAMAN:
        await set_shaman_channel_member_access(
            guild,
            running,
            player,
            can_view=True,
            can_chat=False,
            reason="마피아 게임 마녀 저주로 영매 채팅 권한 제거",
        )
    await disable_private_role_channel_for_player(guild, running, player)


async def remove_frog_permissions(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
) -> None:
    await set_frog_channel_member_access(
        guild,
        running,
        player,
        can_view=False,
        can_chat=False,
        reason="마피아 게임 개구리 상태 종료",
    )
    await restore_frog_game_channel_permission(guild, running, player)


async def restore_revived_player_roles(
    guild: discord.Guild,
    running: RunningGame,
    player: Player,
    *,
    reason_prefix: str = "마피아 게임 부활",
) -> None:
    participant_role = get_participant_role(guild)
    member = await get_guild_member(guild, player.user_id)
    if member and participant_role and participant_role not in member.roles:
        try:
            await member.add_roles(participant_role, reason=f"{reason_prefix}로 참가자 역할 복구")
        except discord.DiscordException:
            pass
    await remove_dead_player_roles_from_ids(
        guild,
        {player.user_id},
        f"{reason_prefix}로 사망자 역할 제거",
    )
    await set_dead_channel_member_access(
        guild,
        running,
        player,
        can_view=False,
        can_chat=False,
        reason=f"{reason_prefix}로 사망자 채팅방 권한 제거",
    )
    await set_shaman_channel_member_access(
        guild,
        running,
        player,
        can_view=False,
        can_chat=False,
        reason=f"{reason_prefix}로 영매 채팅방 권한 제거",
    )
    await refresh_player_private_channel_access(guild, running, player)
    await upsert_game_status(guild, running)


async def sync_scientist_mafia_permissions(
    guild: discord.Guild,
    running: RunningGame,
) -> None:
    for player in running.game.players:
        if player.role != Role.SCIENTIST or player.user_id not in running.game.scientist_contacted:
            continue
        if player.alive:
            await refresh_player_private_channel_access(guild, running, player)
        elif player.user_id in running.game.scientist_pending_revive_ids:
            await set_player_private_channel_access(
                guild,
                running,
                Role.MAFIA,
                player,
                can_chat=True,
                reason="마피아 게임 과학자 유착으로 마피아 채널 권한 부여",
            )


def apply_timed_night_state(running: RunningGame) -> TimedNightEvents:
    cursed_players, witch_contacts = running.game.apply_witch_curses()
    cult_bell_count = running.game.consume_cult_bells()
    revived_players = running.game.revive_pending_scientists()
    return TimedNightEvents(
        cursed_players=cursed_players,
        witch_contacts=witch_contacts,
        cult_bell_count=cult_bell_count,
        revived_players=revived_players,
    )


def timed_night_events_have_work(events: TimedNightEvents) -> bool:
    return bool(
        events.cursed_players
        or events.witch_contacts
        or events.cult_bell_count
        or events.revived_players
    )


async def announce_timed_night_events(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
    events: TimedNightEvents,
) -> None:
    for player in events.cursed_players:
        await apply_frog_permissions(guild, running, player)
    for user_id in events.witch_contacts:
        player = running.game.get_player(user_id)
        if player:
            await add_player_to_private_role_channel(guild, running, Role.MAFIA, player)
            await send_player_secret(guild, running, player, "저주 대상이 마피아라 마피아와 접선했습니다.")
    if events.cursed_players:
        await send_game_embed(
            guild,
            channel,
            running,
            "마녀의 저주가 발동했습니다.\n누군가 다음 밤까지 개구리가 되었습니다.",
            title="마녀 저주",
            color=WARNING_EMBED_COLOR,
        )
    if events.cult_bell_count:
        await announce_cult_bells_now(running, events.cult_bell_count)
    for player in events.revived_players:
        await restore_revived_player_roles(guild, running, player)
    if events.revived_players:
        await sync_cult_team_channel_access(guild, running)
        await send_game_embed(
            guild,
            channel,
            running,
            "\n".join(f"[과학자 {player.name}님이 부활했습니다.]" for player in events.revived_players),
            title="과학자 부활",
            color=SUCCESS_EMBED_COLOR,
        )


def trigger_timed_night_events(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    events = apply_timed_night_state(running)
    if not timed_night_events_have_work(events):
        return
    create_logged_background_task(
        announce_timed_night_events(guild, channel, running, events),
        "timed night events",
    )


async def wait_for_night_actions(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    running.night_timed_events_due = config.night_seconds <= 10
    if config.night_seconds <= 10:
        await wait_for_event_or_timeout(running.night_complete_event, config.night_seconds)
        trigger_timed_night_events(guild, channel, running)
        return

    await wait_for_event_or_timeout(running.night_complete_event, config.night_seconds - 10)
    if running.night_complete_event.is_set():
        return
    if running.game.phase == Phase.NIGHT and games.get(running.guild_id) is running:
        await send_game_embed(
            guild,
            channel,
            running,
            "밤 시간이 10초 남았습니다. 아직 행동하지 않았다면 지금 선택하세요.",
            title="밤 10초 전",
        )
        running.night_timed_events_due = True
        trigger_timed_night_events(guild, channel, running)
    await wait_for_event_or_timeout(running.night_complete_event, 10)


async def run_night(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    running.game.phase = Phase.NIGHT
    running.game.police_result_announced = False
    await upsert_game_status(guild, running)
    running.night_complete_event.clear()
    running.night_timed_events_due = config.night_seconds <= 10
    await restore_frogs_for_new_night(guild, running)
    await sync_lover_chat_access(guild, running, reason="마피아 게임 밤 시작으로 연인 채팅 권한 갱신")
    await announce_hacker_results(guild, running)
    await announce_vigilante_investigation_results(guild, running)
    await sync_scientist_mafia_permissions(guild, running)
    for user_id in running.game.ensure_godfather_auto_contact():
        player = running.game.get_player(user_id)
        if player:
            await add_player_to_private_role_channel(guild, running, Role.MAFIA, player)
            await send_player_secret(
                guild,
                running,
                player,
                "세 번째 밤이 되어 마피아 팀과 자동 접선했습니다. 이제 마피아 비밀방을 볼 수 있고 밤마다 확정 처치 대상을 지목합니다.",
            )
    police_can_act = any(actor.role == Role.POLICE for actor in running.game.night_action_actors())
    await set_game_channel_chat(
        guild,
        channel,
        running,
        participants_can_chat=False,
        reason="마피아 게임 밤 시작",
    )
    await sync_shaman_channel_permissions(guild, running, can_chat=True)
    await send_game_embed(
        guild,
        channel,
        running,
        f"밤이 되었습니다. {config.night_seconds}초 동안 게임 채널 채팅이 비활성화됩니다.\n"
        "밤 행동이 있는 역할은 본인 익명 채널 또는 DM에서 선택합니다.\n"
        "행동 가능한 역할이 모두 선택하면 남은 시간을 기다리지 않고 바로 아침으로 넘어갑니다.",
        title="밤",
    )
    if running.night_timed_events_due:
        trigger_timed_night_events(guild, channel, running)
    if has_changeable_mafia_action(running):
        await sync_role_status_message(guild, running, Role.MAFIA)

    failed_names: list[str] = []
    for actor in running.game.night_action_actors():
        if actor.role == Role.CONTRACTOR:
            contract_targets = sorted(
                running.game.contractor_contract_targets(actor),
                key=lambda player: player.name.casefold(),
            )
            sent = await send_player_secret(
                guild,
                running,
                actor,
                "청부업자 밤 행동을 선택하세요.\n"
                "두 명과 각 직업을 추측합니다. 둘 중 한 명이라도 마피아를 정확히 맞히면 접선합니다.\n"
                "첫날 밤에는 사용할 수 없고, 수사직과 직업이 공개된 사람은 대상에서 제외됩니다.",
                ContractorContractView(running.guild_id, actor, contract_targets),
            )
            if not sent:
                failed_names.append(actor.name)
            continue
        targets = night_targets(running.game, actor)
        if targets:
            sent = await send_player_secret(
                guild,
                running,
                actor,
                f"{actor.role.value} 밤 행동을 선택하세요.",
                NightActionView(running.guild_id, actor, targets),
            )
            if not sent:
                failed_names.append(actor.name)

    if failed_names:
        await send_game_embed(
            guild,
            channel,
            running,
            "밤 행동 선택지를 보낼 수 없는 참가자: " + ", ".join(failed_names),
            color=ERROR_EMBED_COLOR,
        )

    if should_finish_night_early(running):
        running.night_complete_event.set()
    await wait_for_night_actions(guild, channel, running)
    running.night_timed_events_due = True
    trigger_timed_night_events(guild, channel, running)
    result = running.game.resolve_night()
    await sync_lover_chat_access(guild, running, reason="마피아 게임 낮 시작으로 연인 채팅 권한 갱신")
    await sync_shaman_channel_permissions(guild, running, can_chat=False)
    await announce_night_private_results(guild, running, result)
    for user_id in result.spy_contacts:
        player = running.game.get_player(user_id)
        if player:
            await add_player_to_private_role_channel(guild, running, Role.MAFIA, player)
    for user_id in result.contractor_contacts:
        player = running.game.get_player(user_id)
        if player:
            await add_player_to_private_role_channel(guild, running, Role.MAFIA, player)
    for user_id in result.witch_contacts:
        player = running.game.get_player(user_id)
        if player:
            await add_player_to_private_role_channel(guild, running, Role.MAFIA, player)
    for user_id in result.nurse_contacts:
        player = running.game.get_player(user_id)
        if player:
            await add_player_to_private_role_channel(guild, running, Role.DOCTOR, player)
    await sync_cult_team_channel_access(guild, running)
    await sync_dead_players_private_role_channels(guild, running)
    for revived in result.priest_revives:
        await restore_revived_player_roles(
            guild,
            running,
            revived,
            reason_prefix="마피아 게임 성직자 소생",
        )
    if result.priest_revives:
        await sync_cult_team_channel_access(guild, running)
        await sync_lover_chat_access(guild, running, reason="마피아 게임 성직자 소생으로 연인 채팅 권한 갱신")

    doctor_saved = (
        result.mafia_target is not None
        and result.protected is not None
        and result.mafia_target.user_id == result.protected.user_id
        and result.mafia_target not in result.killed_players
        and not result.lover_sacrifices
    )
    if result.killed_players:
        killed_lines: list[str] = []
        for killed in result.killed_players:
            removed_role = await remove_participant_role_from_dead(guild, running, killed)
            added_dead_role = await add_dead_player_role(guild, killed)
            await set_dead_channel_member_access(
                guild,
                running,
                killed,
                can_view=True,
                can_chat=killed.user_id not in running.game.purified_dead_ids,
                reason="마피아 게임 사망자 채팅방 권한 부여",
            )
            await set_shaman_channel_member_access(
                guild,
                running,
                killed,
                can_view=True,
                can_chat=killed.user_id not in running.game.purified_dead_ids,
                reason="마피아 게임 영매 채팅방 권한 부여",
            )
            await remove_frog_permissions(guild, running, killed)
            await disable_private_role_channel_for_player(guild, running, killed)
            if killed.role == Role.SCIENTIST and killed.user_id in running.game.scientist_contacted:
                await set_player_private_channel_access(
                    guild,
                    running,
                    Role.MAFIA,
                    killed,
                    can_chat=True,
                    reason="마피아 게임 과학자 유착으로 마피아 채널 권한 부여",
                )
            if killed in result.contractor_kills:
                line = (
                    f"- {killed.name} 님이 청부업자에게 정체를 들켜 암살 당했습니다. "
                    f"{death_role_text(running, killed)}"
                )
            elif killed in result.vigilante_kills:
                line = (
                    f"- {killed.name} 님이 자경단원에게 숙청당했습니다. "
                    f"{death_role_text(running, killed)}"
                )
            else:
                line = f"- {killed.name}: {death_role_text(running, killed)}"
            if removed_role:
                line += f" '{config.participant_role}' 역할을 제거했습니다."
            else:
                line += f" '{config.participant_role}' 역할 제거에 실패했습니다."
            if added_dead_role is True:
                line += f" '{DEAD_PLAYER_ROLE}' 역할을 부여했습니다."
            elif added_dead_role is None:
                line += f" '{DEAD_PLAYER_ROLE}' 역할을 찾지 못했습니다."
            else:
                line += f" '{DEAD_PLAYER_ROLE}' 역할 부여에 실패했습니다."
            killed_lines.append(line)
        await sync_dead_players_private_role_channels(guild, running)
        await sync_cult_team_channel_access(guild, running)
        message = (
            "아침이 밝았습니다. 밤 사이 사망자가 발생했습니다.\n"
            + "\n".join(killed_lines)
        )
        if result.lover_sacrifices:
            lover_lines = [
                f"- {savior.name}님이 연인 {saved.name}님을 살리고 대신 마피아에게 살해 당했습니다!"
                for savior, saved in result.lover_sacrifices
            ]
            message += "\n\n연인 희생\n" + "\n".join(lover_lines)
        if result.terrorist_retaliations:
            retaliation_lines = [
                f"- {terrorist.name} 님이 지목 중이던 {target.name} 님도 함께 사망했습니다."
                for terrorist, target in result.terrorist_retaliations
            ]
            message += "\n\n지목 반격\n" + "\n".join(retaliation_lines)
        await send_game_embed(guild, channel, running, message, title="밤 결과", include_dead=True)
    elif doctor_saved:
        saved_player = result.protected
        await send_game_embed(
            guild,
            channel,
            running,
            f"아침이 밝았습니다. **{saved_player.name}**님이 의사의 치료로 살아났습니다.",
            title="밤 결과",
            color=SUCCESS_EMBED_COLOR,
            include_dead=True,
        )
    else:
        await send_game_embed(
            guild,
            channel,
            running,
            "아침이 밝았습니다. 아무도 사망하지 않았습니다.",
            title="밤 결과",
            include_dead=True,
        )
    if result.killed_players and doctor_saved and result.protected:
        await send_game_embed(
            guild,
            channel,
            running,
            f"**{result.protected.name}**님이 의사의 치료로 살아났습니다.",
            title="의사 치료",
            color=SUCCESS_EMBED_COLOR,
            include_dead=True,
        )
    if result.soldier_blocks:
        await send_game_embed(
            guild,
            channel,
            running,
            "\n".join(
                f"군인 **{soldier.name}**님이 마피아의 공격을 버텨냈습니다!"
                for soldier in result.soldier_blocks
            ),
            title="군인 방탄",
            color=WARNING_EMBED_COLOR,
            include_dead=True,
        )
    if result.priest_revives:
        await send_game_embed(
            guild,
            channel,
            running,
            "\n".join(f"[{player.name}님이 부활하셨습니다]" for player in result.priest_revives),
            title="성직자 소생",
            color=SUCCESS_EMBED_COLOR,
            include_dead=True,
        )
    if result.reporter_results:
        await send_game_embed(
            guild,
            channel,
            running,
            "\n".join(result.reporter_results.values()),
            title="기자 특종",
            color=SUCCESS_EMBED_COLOR,
            include_dead=True,
        )
    if result.cult_bells:
        await send_game_embed(
            guild,
            channel,
            running,
            "\n".join("교주의 종소리가 울렸습니다." for _ in range(result.cult_bells)),
            title="교주 포교",
            color=WARNING_EMBED_COLOR,
            include_dead=True,
        )
    await announce_police_result(guild, running, result)
    await announce_public_police_status(guild, channel, running, police_can_act, result)
    await announce_morning_mafia_count(guild, channel, running)
    await upsert_game_status(guild, running)


async def announce_police_result(
    guild: discord.Guild,
    running: RunningGame,
    result: NightResult,
) -> None:
    if running.game.police_result_announced:
        return
    alive_police = [
        player for player in running.game.alive_players() if player.role == Role.POLICE
    ]
    if not alive_police:
        return

    if result.police_target is None:
        message = "경찰 조사 대상이 과반을 넘지 못해 이번 밤 조사 결과가 없습니다."
    else:
        result_text = "마피아입니다" if result.police_target_is_mafia else "마피아가 아닙니다"
        message = f"조사 결과: {result.police_target.name} 님은 **{result_text}**."

    running.game.mark_police_result_announced()
    await send_police_result_message(guild, running, message)


async def announce_hacker_results(
    guild: discord.Guild,
    running: RunningGame,
) -> None:
    for user_id, message in running.game.consume_hacker_results().items():
        player = running.game.get_player(user_id)
        if player:
            await send_player_secret(guild, running, player, message)


async def announce_vigilante_investigation_results(
    guild: discord.Guild,
    running: RunningGame,
) -> None:
    for user_id, message in running.game.consume_vigilante_results().items():
        player = running.game.get_player(user_id)
        if player:
            await send_player_secret(guild, running, player, message)


async def send_police_result_message(
    guild: discord.Guild,
    running: RunningGame,
    message: str,
    *,
    exclude_user_ids: set[int] | None = None,
) -> None:
    excluded = exclude_user_ids or set()
    alive_police = [
        player
        for player in running.game.alive_players()
        if player.role == Role.POLICE and player.user_id not in excluded
    ]
    for player in alive_police:
        await send_player_secret(guild, running, player, message)


async def announce_night_private_results(
    guild: discord.Guild,
    running: RunningGame,
    result: NightResult,
) -> None:
    for user_id, message in {
        **result.detective_results,
        **result.shaman_results,
        **result.priest_results,
        **result.agent_results,
        **result.spy_results,
        **result.contractor_results,
        **result.godfather_results,
        **result.vigilante_results,
        **result.nurse_results,
        **result.cult_results,
        **result.fanatic_results,
    }.items():
        player = running.game.get_player(user_id)
        if player:
            await send_player_secret(guild, running, player, message)

    for user_id in result.shaman_purifications:
        player = running.game.get_player(user_id)
        if player:
            await set_dead_channel_member_access(
                guild,
                running,
                player,
                can_view=True,
                can_chat=False,
                reason="마피아 게임 영매 성불로 사망자 채팅 금지",
            )
            await set_shaman_channel_member_access(
                guild,
                running,
                player,
                can_view=True,
                can_chat=False,
                reason="마피아 게임 영매 성불로 영매 채팅 금지",
            )
            if running.anonymous_enabled:
                await set_anonymous_general_input_access(
                    guild,
                    running,
                    player,
                    can_chat=False,
                    reason="마피아 게임 영매 성불로 익명 사망자 채팅 금지",
                )

    for user_id, inherited_role in result.graverobber_results.items():
        player = running.game.get_player(user_id)
        if player and inherited_role in PRIVATE_CHAT_ROLES:
            await add_player_to_private_role_channel(guild, running, inherited_role, player)
        if player and inherited_role == Role.SHAMAN:
            await set_shaman_channel_member_access(
                guild,
                running,
                player,
                can_view=True,
                can_chat=running.game.phase == Phase.NIGHT,
                reason="마피아 게임 도굴꾼 영매 계승으로 영매 채팅방 권한 부여",
            )
        if player:
            await send_player_secret(
                guild,
                running,
                player,
                f"도굴꾼 능력으로 **{inherited_role.value}** 직업을 이어받았습니다.",
            )

    for soldier in result.soldier_blocks:
        await send_player_secret(
            guild,
            running,
            soldier,
            "방탄으로 마피아 공격을 한 차례 막았습니다. 누가 공격했는지는 알 수 없습니다.",
        )

    for user_id in result.fanatic_inherits:
        player = running.game.get_player(user_id)
        if player:
            await send_player_secret(guild, running, player, "교주가 사망해 광신도가 교주의 능력을 물려받았습니다.")


async def announce_public_police_status(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
    police_can_act: bool,
    result: NightResult,
) -> None:
    if not running.reveal_public_police_status:
        return
    if not police_can_act:
        return

    if result.police_target is None:
        message = "경찰 조사는 성공하지 못했습니다. 대상이 과반을 넘지 못했거나 선택이 완료되지 않았습니다."
        color = WARNING_EMBED_COLOR
    elif result.police_target_is_mafia:
        message = "경찰이 마피아를 발견했습니다. 자세한 조사 결과는 경찰 비공개 채널로 전달됩니다."
        color = SUCCESS_EMBED_COLOR
    else:
        message = "경찰이 마피아를 발견하지 못했습니다. 자세한 조사 결과는 경찰 비공개 채널로 전달됩니다."
        color = WARNING_EMBED_COLOR
    await send_game_embed(
        guild,
        channel,
        running,
        message,
        title="경찰 조사 결과 공개",
        color=color,
        include_dead=True,
    )


async def announce_morning_mafia_count(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    running: RunningGame,
) -> None:
    if not running.reveal_morning_mafia_count:
        return

    await send_game_embed(
        guild,
        channel,
        running,
        f"현재 생존 마피아: **{len(running.game.alive_known_mafia_team())}명**",
        title="아침 마피아 현황",
        include_dead=True,
    )


def night_targets(game: MafiaGame, actor: Player) -> list[Player]:
    alive = sorted(game.alive_players(), key=lambda player: player.name.casefold())
    if actor.role == Role.MAFIA:
        return [player for player in alive if game.can_mafia_attack(player, actor.user_id)]
    if actor.role == Role.DOCTOR:
        return alive
    if actor.role == Role.NURSE:
        if actor.user_id in game.nurse_contacted:
            return alive if not game.alive_role_count(Role.DOCTOR) else []
        return [player for player in alive if player.user_id != actor.user_id]
    if actor.role == Role.SHAMAN:
        return sorted(game.unpurified_dead_players(), key=lambda player: player.name.casefold())
    if actor.role == Role.PRIEST:
        return sorted(game.unpurified_dead_players(), key=lambda player: player.name.casefold())
    if actor.role == Role.CULT_LEADER:
        return [
            player
            for player in alive
            if player.user_id != actor.user_id and not game.is_cult_team(player)
        ]
    if actor.role in {
        Role.POLICE,
        Role.REPORTER,
        Role.DETECTIVE,
        Role.SPY,
        Role.WITCH,
        Role.GODFATHER,
        Role.TERRORIST,
        Role.FANATIC,
    }:
        return [player for player in alive if player.user_id != actor.user_id]
    if actor.role == Role.VIGILANTE:
        return sorted(game.vigilante_execution_targets(actor), key=lambda player: player.name.casefold())
    if actor.role == Role.CONTRACTOR:
        return sorted(game.contractor_contract_targets(actor), key=lambda player: player.name.casefold())
    return []


async def announce_winner(channel: discord.abc.Messageable, running: RunningGame) -> bool:
    winner = running.game.winner()
    if not winner:
        return False

    running.game.phase = Phase.ENDED
    guild = bot.get_guild(running.guild_id)
    if guild:
        await upsert_game_status(guild, running)
    if winner == Winner.MAFIA:
        winner_text = "마피아 승리!"
    elif winner == Winner.JOKER:
        winner_text = "조커 승리!"
    elif winner == Winner.CULT:
        winner_text = "교주팀 승리!"
    else:
        winner_text = "시민 승리!"
    await announce_final_roles(channel, running, winner_text)
    record_game_stats(running, winner)
    return True


async def announce_final_roles(
    channel: discord.abc.Messageable,
    running: RunningGame,
    result_text: str,
) -> None:
    elapsed_seconds = max(0, int(time.monotonic() - running.started_at))
    message = (
        f"{result_text}\n"
        f"플레이 시간: **{play_duration_text(elapsed_seconds)}**\n\n"
        f"최종 역할 공개\n{final_role_reveal_text(running)}"
    )
    guild = bot.get_guild(running.guild_id)
    if guild:
        await send_game_embed(
            guild,
            channel,
            running,
            message,
            title="게임 종료",
            color=SUCCESS_EMBED_COLOR,
            include_dead=True,
        )
        original_channel = guild.get_channel(running.channel_id)
        current_channel_id = getattr(channel, "id", None)
        if (
            isinstance(original_channel, discord.abc.Messageable)
            and getattr(original_channel, "id", None) != current_channel_id
        ):
            await send_embed(
                original_channel,
                message,
                title="게임 종료",
                color=SUCCESS_EMBED_COLOR,
            )
        return

    await send_embed(
        channel,
        message,
        title="게임 종료",
        color=SUCCESS_EMBED_COLOR,
    )


def final_role_reveal_text(running: RunningGame) -> str:
    def final_team(player: Player) -> str:
        if running.game.is_cult_team(player):
            return "교주팀"
        if running.game.is_mafia_team(player):
            return "마피아팀"
        if player.role == Role.JOKER:
            return "중립"
        return "시민팀"

    def role_detail(player: Player) -> str:
        state = "" if player.alive else " (사망)"
        return f"{player.role.value}{state} / 최종 진영: {final_team(player)}"

    if not running.anonymous_enabled:
        return "\n".join(
            f"- {player.name}: {role_detail(player)}"
            for player in sorted(running.game.players, key=lambda item: item.name.casefold())
        )

    lines: list[str] = []
    for player in sorted(
        running.game.players,
        key=lambda item: running.anonymous_aliases.get(item.user_id, item.name).casefold(),
    ):
        alias = running.anonymous_aliases.get(player.user_id, "익명")
        real_name = original_player_name(running, player)
        lines.append(f"- {alias} = {real_name}: {role_detail(player)}")
    return "\n".join(lines)


def role_team_text(role: Role) -> str:
    return ROLE_TEAM_TEXT.get(role, "시민팀")


def role_goal_text(role: Role) -> str:
    return ROLE_GOAL_TEXT.get(role, "시민팀을 도와 모든 마피아를 제거하세요.")


def ability_lines(role: Role) -> list[str]:
    abilities = ROLE_ABILITY_TEXTS.get(role, ROLE_ABILITY_TEXTS[Role.CITIZEN])
    return [f"`[{name}]` {description}" for name, description in abilities]


def role_rule_lines(role: Role) -> list[str]:
    return [f"- {line}" for line in ROLE_RULE_TEXTS.get(role, ())]


def role_guide_value(role: Role) -> str:
    lines = [
        f"**진영** {role_team_text(role)}",
        f"**목표** {role_goal_text(role)}",
        "**능력**",
        *ability_lines(role),
    ]
    rules = role_rule_lines(role)
    if rules:
        lines.extend(["**판정/주의**", *rules])
    return "\n".join(lines)


def personal_role_status(game: MafiaGame, player: Player) -> list[str]:
    if player.role == Role.MAFIA:
        teammates = ", ".join(
            teammate.name
            for teammate in sorted(game.players, key=lambda item: item.name.casefold())
            if game.is_known_mafia_team(teammate)
        )
        return [f"현재 알고 있는 마피아팀: {teammates or '없음'}"]
    if player.role == Role.SPY:
        contacted = player.user_id in game.spy_contacted
        return [
            "접선 상태: 완료" if contacted else "접선 상태: 미접선",
            "미접선 중에는 마피아 비밀방, 경찰 마피아 판정, 생존 마피아 수에 포함되지 않습니다.",
        ]
    if player.role == Role.CONTRACTOR:
        contacted = player.user_id in game.contractor_contacted
        return [
            "접선 상태: 완료" if contacted else "접선 상태: 미접선",
            "청부는 두 번째 밤부터 두 명의 직업을 추측하는 방식으로만 사용할 수 있습니다.",
            "추측 중 일반 마피아를 마피아로 정확히 맞히면 접선합니다.",
        ]
    if player.role == Role.WITCH:
        contacted = player.user_id in game.witch_contacted
        return [
            "접선 상태: 완료" if contacted else "접선 상태: 미접선",
            "저주는 밤 10초 전부터 적용됩니다. 10초 미만에 선택하면 바로 적용됩니다.",
        ]
    if player.role == Role.SCIENTIST:
        contacted = player.user_id in game.scientist_contacted
        revived = player.user_id in game.scientist_revive_used_ids
        return [
            "접선 상태: 완료" if contacted else "접선 상태: 사망 전까지 미접선",
            "재생 사용: 사용함" if revived else "재생 사용: 미사용",
        ]
    if player.role == Role.MADAM:
        contacted = player.user_id in game.madam_contacted
        seduced = [
            target.name
            for target in sorted(game.players, key=lambda item: item.name.casefold())
            if target.user_id in game.madam_seduced_ids
        ]
        return [
            "접선 상태: 완료" if contacted else "접선 상태: 미접선",
            f"유혹 대상: {', '.join(seduced) if seduced else '없음'}",
        ]
    if player.role == Role.GODFATHER:
        contacted = player.user_id in game.godfather_contacted
        return [
            "접선 상태: 완료" if contacted else "접선 상태: 세 번째 밤 전까지 미접선",
            "접선 후부터 마피아 비밀방에 입장하고 말살을 사용할 수 있습니다.",
        ]
    if player.role == Role.NURSE:
        contacted = player.user_id in game.nurse_contacted
        doctor_alive = game.alive_role_count(Role.DOCTOR) > 0
        return [
            "의사 접선: 완료" if contacted else "의사 접선: 미접선",
            "치료 승계: 가능" if contacted and not doctor_alive else "치료 승계: 불가",
        ]
    if player.role == Role.PRIEST:
        revivable = ", ".join(
            target.name for target in sorted(game.unpurified_dead_players(), key=lambda item: item.name.casefold())
        )
        return [
            f"소생 사용: {'사용함' if player.user_id in game.priest_used_ids else '미사용'}",
            f"소생 가능 사망자: {revivable or '없음'}",
        ]
    if player.role == Role.CULT_LEADER:
        culted = [
            target.name
            for target in sorted(game.players, key=lambda item: item.name.casefold())
            if target.user_id in game.culted_ids and target.user_id != player.user_id
        ]
        return [f"포교 대상: {', '.join(culted) if culted else '없음'}"]
    if player.role == Role.FANATIC:
        return ["포교 상태: 완료" if player.user_id in game.culted_ids else "포교 상태: 미포교"]
    if player.role == Role.VIGILANTE:
        known = [
            target.name
            for target in sorted(game.players, key=lambda item: item.name.casefold())
            if target.user_id in game.vigilante_known_enemy_ids.get(player.user_id, set())
        ]
        return [
            f"조사 사용: {'사용함' if player.user_id in game.vigilante_investigation_used_ids else '미사용'}",
            f"처형 사용: {'사용함' if player.user_id in game.vigilante_execution_used_ids else '미사용'}",
            f"숙청 가능 확정 대상: {', '.join(known) if known else '없음'}",
        ]
    return []


def role_message(game: MafiaGame, player: Player) -> str:
    lines = [
        f"당신의 역할은 **{player.role.value}** 입니다.",
        f"진영: **{role_team_text(player.role)}**",
        f"목표: {role_goal_text(player.role)}",
        "",
        "능력",
        *ability_lines(player.role),
    ]
    personal = personal_role_status(game, player)
    if personal:
        lines.extend(["", "개인 상태", *personal])
    rules = role_rule_lines(player.role)
    if rules:
        lines.extend(["", "판정/주의", *rules])
    return "\n".join(lines)


def game_rule_text(game: MafiaGame, reveal_death_roles: bool) -> str:
    death_rule = (
        "사망자의 직업은 즉시 공개됩니다."
        if reveal_death_roles
        else "사망자의 직업은 즉시 공개되지 않습니다."
    )
    return (
        f"{public_role_count_text(game)}\n\n"
        "게임은 밤과 낮을 반복합니다.\n"
        "- 역할 설명: 전체 역할 설명은 `/역할설명`, 본인 역할 설명은 `/마피아능력`으로 확인할 수 있습니다.\n"
        "- 밤: 게임 채널 채팅과 반응이 비활성화되고, 밤 행동이 있는 역할은 DM으로 행동합니다.\n"
        "- 낮: 생존자는 자유롭게 토론합니다. 생존자 과반이 `바로 투표`를 누르면 토론을 끝내고 지목 투표로 넘어갑니다. 시간이 끝나면 생존자 과반으로 1분 연장을 정할 수 있고, 연장은 낮마다 1번만 가능합니다.\n"
        f"- 마피아 수 공개: 아침 생존 마피아 수는 {'공개됩니다' if config.reveal_morning_mafia_count else '공개되지 않습니다'}.\n"
        "- 투표: 생존자는 최후변론에 세울 사람 또는 스킵을 선택합니다. 지목자는 20초 동안 혼자 최후변론을 하고, 이후 찬반투표 과반 결과를 따릅니다.\n"
        f"- 경찰 공개: 조사 성공 여부는 {'공개됩니다' if config.reveal_public_police_status else '공개되지 않습니다'}. 실제 조사 결과는 경찰에게만 전달됩니다.\n"
        f"- 채팅: 낮 토론 슬로우모드는 {config.chat_slowmode_seconds}초이며 최후변론 중에는 해제됩니다.\n"
        f"- 사망자: {death_rule} 게임 채널 채팅/반응 권한은 제거되고 '{DEAD_PLAYER_ROLE}' 역할이 부여됩니다.\n\n"
        "승리 조건\n"
        "- 시민 진영: 모든 마피아를 제거하면 승리합니다.\n"
        "- 마피아 진영: 생존 마피아 수가 나머지 생존자 수 이상이면 승리합니다.\n"
        "- 교주팀: 교주팀 생존자가 비교주팀 생존자 이상이면 승리합니다.\n"
        "- 조커: 낮 투표로 처형되면 즉시 단독 승리합니다."
    )


def death_role_text(running: RunningGame, player: Player) -> str:
    if running.reveal_death_roles:
        return f"직업은 **{player.role.value}** 입니다."
    return "직업은 공개되지 않습니다."


ROLE_GUIDE_ENTRIES: tuple[tuple[Role, str, str], ...] = tuple(
    (role, role.value, role_guide_value(role)) for role in ROLE_GUIDE_ORDER
)
ROLE_GUIDE_SECTIONS: tuple[tuple[str, str], ...] = tuple(
    (role_name, guide) for _role, role_name, guide in ROLE_GUIDE_ENTRIES
)


def make_role_guide_embed(
    game: MafiaGame | None = None,
    *,
    player: Player | None = None,
    title: str = "역할 안내",
) -> discord.Embed:
    if player:
        personal_text = role_message(game, player) if game else f"당신의 역할은 **{player.role.value}** 입니다."
        description = (
            f"{personal_text}\n\n"
            "전체 역할 설명은 `/역할설명`으로 확인할 수 있습니다."
        )
        return make_embed(description, title=title)
    else:
        description = "역할별 능력과 이 봇의 실제 판정 안내입니다. 게임 중 본인 역할은 `/마피아능력`으로 다시 확인할 수 있습니다."

    embed = make_embed(description, title=title)
    embed.add_field(name="공통 판정", value=ROLE_GUIDE_COMMON_TEXT, inline=False)
    for role_name, guide in ROLE_GUIDE_SECTIONS:
        embed.add_field(name=role_name, value=guide, inline=False)
    return embed


def make_role_guide_embeds(
    game: MafiaGame | None = None,
    *,
    player: Player | None = None,
    title: str = "역할 안내",
) -> list[discord.Embed]:
    if player:
        return [make_role_guide_embed(game, player=player, title=title)]

    embeds: list[discord.Embed] = []
    groups: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
        (
            "시민 역할",
            tuple(
                (role_name, guide)
                for role, role_name, guide in ROLE_GUIDE_ENTRIES
                if role_team_text(role).startswith("시민팀")
            ),
        ),
        (
            "마피아 역할",
            tuple(
                (role_name, guide)
                for role, role_name, guide in ROLE_GUIDE_ENTRIES
                if role_team_text(role).startswith("마피아팀")
            ),
        ),
        (
            "중립 역할",
            tuple(
                (role_name, guide)
                for role, role_name, guide in ROLE_GUIDE_ENTRIES
                if role_team_text(role) == "중립"
            ),
        ),
        (
            "교주팀 역할",
            tuple(
                (role_name, guide)
                for role, role_name, guide in ROLE_GUIDE_ENTRIES
                if role_team_text(role).startswith("교주팀")
            ),
        ),
    )

    for group_name, sections in groups:
        group_chunks: list[list[tuple[str, str]]] = []
        current: list[tuple[str, str]] = []
        current_size = len(title) + len(group_name) + 200
        for role_name, guide in sections:
            entry_size = len(role_name) + len(guide) + 8
            if current and (current_size + entry_size > 5200 or len(current) >= 6):
                group_chunks.append(current)
                current = []
                current_size = len(title) + len(group_name) + 200
            current.append((role_name, guide))
            current_size += entry_size
        if current:
            group_chunks.append(current)

        for index, chunk in enumerate(group_chunks, start=1):
            suffix = f" {index}/{len(group_chunks)}" if len(group_chunks) > 1 else ""
            embed = make_embed(
                f"{group_name} 설명입니다.",
                title=f"{title} - {group_name}{suffix}",
            )
            if not embeds:
                embed.add_field(name="공통 판정", value=ROLE_GUIDE_COMMON_TEXT, inline=False)
            for role_name, guide in chunk:
                embed.add_field(name=role_name, value=guide, inline=False)
            embeds.append(embed)
    return embeds


def anonymous_vote_summary(game: MafiaGame, result: VoteResult) -> str:
    if not result.vote_counts:
        return "투표 없음"

    rows: list[tuple[str, int]] = []
    for target_id, count in result.vote_counts.items():
        if target_id is None:
            name = "스킵"
        else:
            player = game.get_player(target_id)
            name = player.name if player else str(target_id)
        rows.append((name, count))

    rows.sort(key=lambda item: (-item[1], item[0].casefold()))
    return "\n".join(f"- {name}: {count}표" for name, count in rows)


async def run_bot_and_web_server(token: str) -> None:
    """디스코드 봇과 설정용 웹 서버(uvicorn)를 같은 이벤트 루프에서 함께 실행합니다."""

    host = os.getenv("WEB_SETTINGS_HOST", WEB_SETTINGS_DEFAULT_HOST)
    port = int(os.getenv("WEB_SETTINGS_PORT", str(WEB_SETTINGS_DEFAULT_PORT)))
    web_server = uvicorn.Server(
        uvicorn.Config(web_settings_app, host=host, port=port, log_level="warning")
    )

    async with bot:
        await asyncio.gather(
            bot.start(token),
            web_server.serve(),
        )


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(".env 파일에 DISCORD_TOKEN을 설정하세요.")
    asyncio.run(run_bot_and_web_server(token))


if __name__ == "__main__":
    main()
