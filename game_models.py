from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    MAFIA = "마피아"
    DOCTOR = "의사"
    NURSE = "간호사"
    POLICE = "경찰"
    AGENT = "요원"
    VIGILANTE = "자경단원"
    REPORTER = "기자"
    HACKER = "해커"
    DETECTIVE = "사립탐정"
    SHAMAN = "영매"
    PRIEST = "성직자"
    SOLDIER = "군인"
    SPY = "스파이"
    CONTRACTOR = "청부업자"
    WITCH = "마녀"
    SCIENTIST = "과학자"
    MADAM = "마담"
    GRAVEROBBER = "도굴꾼"
    GODFATHER = "대부"
    JOKER = "조커"
    POLITICIAN = "정치인"
    JUDGE = "판사"
    TERRORIST = "테러리스트"
    LOVER = "연인"
    CULT_LEADER = "교주"
    FANATIC = "광신도"
    FROG = "개구리"
    VILLAIN = "악인"
    CITIZEN = "시민"


class Phase(str, Enum):
    NIGHT = "밤"
    DAY = "낮"
    VOTE = "투표"
    FINAL_DEFENSE = "최후변론"
    CONFIRM_VOTE = "찬반투표"
    ENDED = "종료"


class Winner(str, Enum):
    MAFIA = "마피아"
    CITIZEN = "시민"
    JOKER = "조커"
    CULT = "교주"


MAFIA_TEAM_ROLES = {
    Role.MAFIA,
    Role.SPY,
    Role.CONTRACTOR,
    Role.WITCH,
    Role.SCIENTIST,
    Role.MADAM,
    Role.GODFATHER,
    Role.VILLAIN,
}
INVESTIGATION_ROLES = {Role.POLICE, Role.AGENT, Role.VIGILANTE}
CONTRACTOR_GUESSABLE_ROLES = {
    Role.MAFIA,
    Role.DOCTOR,
    Role.REPORTER,
    Role.HACKER,
    Role.DETECTIVE,
    Role.SHAMAN,
    Role.PRIEST,
    Role.GRAVEROBBER,
    Role.POLITICIAN,
    Role.JUDGE,
    Role.TERRORIST,
    Role.LOVER,
    Role.SOLDIER,
    Role.NURSE,
    Role.CULT_LEADER,
    Role.FANATIC,
    Role.WITCH,
    Role.SCIENTIST,
    Role.MADAM,
    Role.JOKER,
    Role.CITIZEN,
}


@dataclass
class Player:
    user_id: int
    name: str
    role: Role
    alive: bool = True


@dataclass
class NightResult:
    killed: Player | None
    protected: Player | None
    mafia_target: Player | None
    police_target: Player | None
    police_target_is_mafia: bool | None
    killed_players: list[Player] = field(default_factory=list)
    detective_results: dict[int, str] = field(default_factory=dict)
    spy_results: dict[int, str] = field(default_factory=dict)
    spy_contacts: list[int] = field(default_factory=list)
    contractor_results: dict[int, str] = field(default_factory=dict)
    contractor_contacts: list[int] = field(default_factory=list)
    contractor_kills: list[Player] = field(default_factory=list)
    witch_results: dict[int, str] = field(default_factory=dict)
    witch_contacts: list[int] = field(default_factory=list)
    godfather_results: dict[int, str] = field(default_factory=dict)
    godfather_contacts: list[int] = field(default_factory=list)
    graverobber_results: dict[int, Role] = field(default_factory=dict)
    terrorist_retaliations: list[tuple[Player, Player]] = field(default_factory=list)
    soldier_blocks: list[Player] = field(default_factory=list)
    lover_sacrifices: list[tuple[Player, Player]] = field(default_factory=list)
    shaman_results: dict[int, str] = field(default_factory=dict)
    shaman_purifications: list[int] = field(default_factory=list)
    priest_results: dict[int, str] = field(default_factory=dict)
    priest_revives: list[Player] = field(default_factory=list)
    agent_results: dict[int, str] = field(default_factory=dict)
    reporter_results: dict[int, str] = field(default_factory=dict)
    hacker_results: dict[int, str] = field(default_factory=dict)
    vigilante_results: dict[int, str] = field(default_factory=dict)
    vigilante_kills: list[Player] = field(default_factory=list)
    nurse_results: dict[int, str] = field(default_factory=dict)
    nurse_contacts: list[int] = field(default_factory=list)
    cult_results: dict[int, str] = field(default_factory=dict)
    fanatic_results: dict[int, str] = field(default_factory=dict)
    fanatic_inherits: list[int] = field(default_factory=list)
    cult_bells: int = 0


@dataclass
class VoteResult:
    executed: Player | None
    tied: bool
    skipped: bool = False
    vote_counts: dict[int | None, int] = field(default_factory=dict)
    madam_seduced: list[Player] = field(default_factory=list)


@dataclass
class ConfirmVoteResult:
    executed: Player | None
    approved: bool
    tied: bool
    blocked_by_politician: bool = False
    extra_killed: list[Player] = field(default_factory=list)
    vote_counts: dict[bool, int] = field(default_factory=dict)
    judge: Player | None = None
    judge_choice: bool | None = None
    decided_by_judge: bool = False
