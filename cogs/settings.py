from __future__ import annotations

from cogs.common import *  # noqa: F401,F403


@bot.tree.command(name="마피아설정", description="마피아 게임 기본 설정을 변경합니다.")
@app_commands.describe(
    mafia="마피아 수",
    doctor="의사 수",
    police="경찰 수",
    citizen_special="시민 특수룰 수",
    mafia_special="마피아 특수룰 수",
    neutral_special="중립 특수룰 수",
    slowmode="낮 채팅 슬로우모드 초. 기본 3초",
    death_role_reveal="사망 시 직업 공개 여부",
    police_status_reveal="낮에 경찰 조사 성공 여부 공개 여부",
    mafia_count_reveal="아침마다 생존 마피아 수 공개 여부",
    detective="사립탐정 활성화 여부",
    shaman="영매 활성화 여부",
    graverobber="도굴꾼 활성화 여부",
    spy="스파이 활성화 여부",
    contractor="청부업자 활성화 여부",
    witch="마녀 활성화 여부",
    scientist="과학자 활성화 여부",
    godfather="대부 활성화 여부",
    joker="조커 활성화 여부",
    politician="정치인 활성화 여부",
    judge="판사 활성화 여부",
    reporter="기자 활성화 여부",
    hacker="해커 활성화 여부",
    terrorist="테러리스트 활성화 여부",
    soldier="군인 활성화 여부",
)
async def configure_game(
    interaction: discord.Interaction,
    mafia: int | None = None,
    doctor: int | None = None,
    police: int | None = None,
    citizen_special: int | None = None,
    mafia_special: int | None = None,
    neutral_special: int | None = None,
    slowmode: int | None = None,
    death_role_reveal: bool | None = None,
    police_status_reveal: bool | None = None,
    mafia_count_reveal: bool | None = None,
    detective: bool | None = None,
    shaman: bool | None = None,
    graverobber: bool | None = None,
    spy: bool | None = None,
    contractor: bool | None = None,
    witch: bool | None = None,
    scientist: bool | None = None,
    godfather: bool | None = None,
    joker: bool | None = None,
    politician: bool | None = None,
    judge: bool | None = None,
    reporter: bool | None = None,
    hacker: bool | None = None,
    terrorist: bool | None = None,
    soldier: bool | None = None,
) -> None:
    require_manager(interaction)
    updates: dict[str, int | bool] = {}
    int_updates = {
        "default_mafia_count": mafia,
        "default_doctor_count": doctor,
        "default_police_count": police,
        "citizen_special_count": citizen_special,
        "mafia_special_count": mafia_special,
        "neutral_special_count": neutral_special,
        "chat_slowmode_seconds": slowmode,
    }
    for key, value in int_updates.items():
        if value is None:
            continue
        if value < 0:
            await send_interaction_reply(interaction, "설정 값은 0 이상이어야 합니다.", private=True)
            return
        updates[key] = value
    if mafia is not None and mafia < 1:
        await send_interaction_reply(interaction, "마피아는 최소 1명이어야 합니다.", private=True)
        return

    bool_updates = {
        "reveal_death_roles": death_role_reveal,
        "reveal_public_police_status": police_status_reveal,
        "reveal_morning_mafia_count": mafia_count_reveal,
        "enable_detective": detective,
        "enable_shaman": shaman,
        "enable_graverobber": graverobber,
        "enable_spy": spy,
        "enable_contractor": contractor,
        "enable_witch": witch,
        "enable_scientist": scientist,
        "enable_godfather": godfather,
        "enable_joker": joker,
        "enable_politician": politician,
        "enable_judge": judge,
        "enable_reporter": reporter,
        "enable_hacker": hacker,
        "enable_terrorist": terrorist,
        "enable_soldier": soldier,
    }
    for key, value in bool_updates.items():
        if value is not None:
            updates[key] = value

    previous = {key: getattr(config, key) for key in updates}
    for key, value in updates.items():
        setattr(config, key, value)

    try:
        role_counts = selected_role_counts(choose_special_roles())
        validate_max_player_count(role_counts, config.max_player_count)
    except ValueError as error:
        for key, value in previous.items():
            setattr(config, key, value)
        await send_interaction_reply(interaction, str(error), private=True)
        return

    save_config()
    await send_interaction_reply(interaction, current_settings_text(), private=False)


@bot.tree.command(
    name="마피아웹설정",
    description="브라우저에서 게임 설정을 편집할 수 있는 1회용 링크를 발급합니다. (관리자 전용)",
)
async def web_configure_game(interaction: discord.Interaction) -> None:
    member = require_manager(interaction)

    token = web_settings_sessions.issue(
        guild_id=interaction.guild_id or 0,
        user_id=member.id,
        user_label=display_name(member),
    )
    url = f"{web_settings_base_url()}{WEB_SETTINGS_PATH}/{token}"
    minutes = max(1, WEB_SETTINGS_SESSION_TTL_SECONDS // 60)

    await interaction.response.send_message(
        embed=make_embed(
            "아래 링크에서 마피아 게임 설정을 편집할 수 있습니다.\n"
            f"{url}\n\n"
            f"⚠️ 이 링크는 **{display_name(member)}** 님만 사용할 수 있고, "
            f"**{minutes}분 동안 1회**만 유효합니다. 다른 사람과 공유하지 마세요.",
            title="웹 설정 링크 발급",
            color=SUCCESS_EMBED_COLOR,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="마피아인원설정", description="마피아 게임 모집 최대 인원을 설정합니다.")
@app_commands.describe(max_players=f"최대 참가 인원. 0은 제한 없음(봇 최대 {MAX_GAME_PLAYERS}명)")
async def configure_player_limit(
    interaction: discord.Interaction,
    max_players: int,
) -> None:
    require_manager(interaction)
    try:
        role_counts = selected_role_counts(choose_special_roles())
        validate_max_player_count(role_counts, max_players)
    except ValueError as error:
        await send_interaction_reply(interaction, str(error), private=True)
        return

    config.max_player_count = max_players
    save_config()
    await send_interaction_reply(
        interaction,
        current_settings_text("마피아 인원 설정을 저장했습니다."),
        private=False,
    )


@bot.tree.command(name="마피아익명설정", description="마피아 게임 익명 채팅 사용 여부를 설정합니다.")
@app_commands.describe(enabled="익명 채팅 사용 여부", 이름방식="익명 이름을 동물로 할지 숫자로 할지 선택합니다.")
@app_commands.choices(
    이름방식=[
        app_commands.Choice(name="동물", value="animal"),
        app_commands.Choice(name="숫자", value="number"),
    ]
)
async def configure_anonymous_mode(
    interaction: discord.Interaction,
    enabled: bool,
    이름방식: str | None = None,
) -> None:
    require_manager(interaction)
    config.anonymous_mode = enabled
    if 이름방식 is not None:
        config.anonymous_name_mode = 이름방식
    save_config()
    await send_interaction_reply(
        interaction,
        current_settings_text("마피아 익명 설정을 저장했습니다."),
        private=False,
    )


@bot.tree.command(name="마피아추가설정", description="추가 역할 묶음을 설정합니다.")
@app_commands.describe(
    nurse="간호사 역할 활성화 여부",
    lover="연인 역할 활성화 여부. 선택되면 연인 2명이 함께 배정됩니다.",
    priest="성직자 역할 활성화 여부",
    madam="마담 역할 활성화 여부",
    cult_team="교주팀 활성화 여부. 켜면 교주와 광신도가 함께 배정됩니다.",
)
async def configure_extra_roles(
    interaction: discord.Interaction,
    nurse: bool | None = None,
    lover: bool | None = None,
    priest: bool | None = None,
    madam: bool | None = None,
    cult_team: bool | None = None,
) -> None:
    require_manager(interaction)
    updates: dict[str, bool] = {}
    if nurse is not None:
        updates["enable_nurse"] = nurse
    if lover is not None:
        updates["enable_lover"] = lover
    if priest is not None:
        updates["enable_priest"] = priest
    if madam is not None:
        updates["enable_madam"] = madam
    if cult_team is not None:
        updates["enable_cult_team"] = cult_team

    previous = {key: getattr(config, key) for key in updates}
    for key, value in updates.items():
        setattr(config, key, value)

    try:
        role_counts = selected_role_counts(choose_special_roles())
        validate_max_player_count(role_counts, config.max_player_count)
    except ValueError as error:
        for key, value in previous.items():
            setattr(config, key, value)
        await send_interaction_reply(interaction, str(error), private=True)
        return

    save_config()
    await send_interaction_reply(
        interaction,
        current_settings_text("마피아 추가 설정을 저장했습니다."),
        private=False,
    )


@bot.tree.command(name="마피아수사설정", description="수사직 후보를 설정합니다.")
@app_commands.describe(
    agent="요원을 수사직 랜덤 후보에 포함할지 설정합니다.",
    vigilante="자경단원을 수사직 랜덤 후보에 포함할지 설정합니다.",
)
async def configure_investigation_role(
    interaction: discord.Interaction,
    agent: bool | None = None,
    vigilante: bool | None = None,
) -> None:
    require_manager(interaction)
    updates: dict[str, bool] = {}
    if agent is not None:
        updates["use_agent"] = agent
    if vigilante is not None:
        updates["use_vigilante"] = vigilante

    previous = {key: getattr(config, key) for key in updates}
    for key, value in updates.items():
        setattr(config, key, value)

    try:
        role_counts = selected_role_counts(choose_special_roles())
        validate_max_player_count(role_counts, config.max_player_count)
    except ValueError as error:
        for key, value in previous.items():
            setattr(config, key, value)
        await send_interaction_reply(interaction, str(error), private=True)
        return

    save_config()
    await send_interaction_reply(
        interaction,
        current_settings_text("마피아 수사 설정을 저장했습니다."),
        private=False,
    )

@configure_game.error
@configure_player_limit.error
@configure_extra_roles.error
@configure_investigation_role.error
async def command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    await send_command_error(interaction, error)

