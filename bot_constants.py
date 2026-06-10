from __future__ import annotations

from typing import Literal

import discord

from game import Role


RECRUITMENT_SECONDS = 60
MAX_GAME_PLAYERS = 24
DAY_EXTENSION_VOTE_SECONDS = 10
DISCUSSION_EXTENSION_SECONDS = 60
CONFIRM_VOTE_SECONDS = 15
GAME_NOTIFICATION_ROLE = "게임알림"
DEAD_PLAYER_ROLE = "사망자"
SPECTATOR_ROLE = "관전자"
OLD_DEAD_CHAT_CHANNEL_NAME = "사망자-채팅방"
SHAMAN_CHAT_CHANNEL_NAME = "영매-채팅방"
FROG_CHAT_CHANNEL_NAME = "개구리-채팅방"
PRIVATE_CHAT_ROLES = (
    Role.MAFIA,
    Role.POLICE,
    Role.AGENT,
    Role.VIGILANTE,
    Role.DOCTOR,
    Role.CULT_LEADER,
    Role.LOVER,
)
PRIVATE_CHANNEL_NAMES = {
    Role.MAFIA: "마피아-비밀방",
    Role.POLICE: "경찰-비밀방",
    Role.AGENT: "요원-비밀방",
    Role.VIGILANTE: "자경단원-비밀방",
    Role.DOCTOR: "의사-비밀방",
    Role.CULT_LEADER: "교주-비밀방",
    Role.LOVER: "연인-비밀방",
}
CITIZEN_SPECIAL_ROLES = (
    Role.DETECTIVE,
    Role.SHAMAN,
    Role.PRIEST,
    Role.GRAVEROBBER,
    Role.POLITICIAN,
    Role.JUDGE,
    Role.REPORTER,
    Role.HACKER,
    Role.TERRORIST,
    Role.LOVER,
    Role.SOLDIER,
    Role.NURSE,
)
MAFIA_SPECIAL_ROLES = (Role.SPY, Role.CONTRACTOR, Role.WITCH, Role.SCIENTIST, Role.MADAM, Role.GODFATHER)
NEUTRAL_SPECIAL_ROLES = (Role.JOKER,)
PUBLIC_MAFIA_SPECIAL_ROLES = (Role.SPY, Role.CONTRACTOR, Role.WITCH, Role.SCIENTIST, Role.MADAM, Role.GODFATHER)
PUBLIC_CITIZEN_SPECIAL_ROLES = (
    Role.DETECTIVE,
    Role.SHAMAN,
    Role.PRIEST,
    Role.GRAVEROBBER,
    Role.POLITICIAN,
    Role.JUDGE,
    Role.REPORTER,
    Role.HACKER,
    Role.TERRORIST,
    Role.LOVER,
    Role.SOLDIER,
    Role.NURSE,
    Role.FANATIC,
)
PUBLIC_NEUTRAL_SPECIAL_ROLES = (Role.JOKER,)
PUBLIC_CULT_SPECIAL_ROLES = (Role.CULT_LEADER,)
CONTRACTOR_GUESS_ROLES = (
    Role.MAFIA,
    Role.DOCTOR,
    Role.WITCH,
    Role.SCIENTIST,
    Role.MADAM,
    Role.DETECTIVE,
    Role.SHAMAN,
    Role.PRIEST,
    Role.GRAVEROBBER,
    Role.POLITICIAN,
    Role.JUDGE,
    Role.REPORTER,
    Role.HACKER,
    Role.TERRORIST,
    Role.LOVER,
    Role.SOLDIER,
    Role.NURSE,
    Role.CULT_LEADER,
    Role.FANATIC,
    Role.JOKER,
    Role.CITIZEN,
)
DEFAULT_EMBED_COLOR = discord.Color.gold()
ERROR_EMBED_COLOR = discord.Color.red()
SUCCESS_EMBED_COLOR = discord.Color.green()
WARNING_EMBED_COLOR = discord.Color.orange()
DayDiscussionResult = Literal["vote", "stop"]

ANIMAL_ALIASES = (
    "사자", "호랑이", "고양이", "강아지", "토끼", "판다", "곰", "여우", "늑대", "돼지",
    "원숭이", "코끼리", "기린", "펭귄", "오리", "병아리", "부엉이", "독수리", "거북이", "돌고래",
    "상어", "고래", "악어", "뱀", "나비", "벌", "개미", "달팽이", "문어", "물고기",
    "게", "새우", "오징어", "말", "얼룩말", "소", "양", "염소", "닭", "쥐",
    "햄스터", "사슴", "라마", "캥거루", "하마", "코뿔소", "박쥐", "고슴도치", "수달", "비버",
    "너구리", "스컹크", "공작", "앵무새", "백조", "플라밍고", "칠면조", "고릴라", "오랑우탄", "물개",
)

ANIMAL_EMOJI_CODES = {
    "사자": "1f981", "호랑이": "1f42f", "고양이": "1f431", "강아지": "1f436", "토끼": "1f430",
    "판다": "1f43c", "곰": "1f43b", "여우": "1f98a", "늑대": "1f43a", "돼지": "1f437",
    "원숭이": "1f435", "코끼리": "1f418", "기린": "1f992", "펭귄": "1f427", "오리": "1f986",
    "병아리": "1f424", "부엉이": "1f989", "독수리": "1f985", "거북이": "1f422", "돌고래": "1f42c",
    "상어": "1f988", "고래": "1f433", "악어": "1f40a", "뱀": "1f40d", "나비": "1f98b",
    "벌": "1f41d", "개미": "1f41c", "달팽이": "1f40c", "문어": "1f419", "물고기": "1f41f",
    "게": "1f980", "새우": "1f990", "오징어": "1f991", "말": "1f434", "얼룩말": "1f993",
    "소": "1f42e", "양": "1f411", "염소": "1f410", "닭": "1f414", "쥐": "1f42d",
    "햄스터": "1f439", "사슴": "1f98c", "라마": "1f999", "캥거루": "1f998", "하마": "1f99b",
    "코뿔소": "1f98f", "박쥐": "1f987", "고슴도치": "1f994", "수달": "1f9a6", "비버": "1f9ab",
    "너구리": "1f99d", "스컹크": "1f9a8", "공작": "1f99a", "앵무새": "1f99c", "백조": "1f9a2",
    "플라밍고": "1f9a9", "칠면조": "1f983", "고릴라": "1f98d", "오랑우탄": "1f9a7", "물개": "1f9ad",
}

NUMBER_AVATAR_COLORS = (
    "e11d48", "2563eb", "16a34a", "f59e0b", "7c3aed", "0891b2", "db2777", "65a30d",
    "dc2626", "4f46e5", "0f766e", "ea580c", "9333ea", "0284c7", "ca8a04", "be123c",
    "1d4ed8", "15803d", "b45309", "6d28d9", "0369a1", "a21caf", "047857", "c2410c",
)
