from __future__ import annotations

from cogs.common import *  # noqa: F401,F403


@bot.tree.command(name="마피아시작", description="저장된 설정대로 마피아 게임 참가자를 모집하고 시작합니다.")
async def start_game(
    interaction: discord.Interaction,
) -> None:
    if not interaction.guild or interaction.guild_id is None or interaction.channel_id is None:
        await send_interaction_reply(interaction, "서버 채널에서만 사용할 수 있습니다.", private=True)
        return
    if not config.game_enabled:
        await send_interaction_reply(interaction, "마피아 게임이 비활성화되어 있습니다.", private=True)
        return
    if interaction.guild_id in games:
        await send_interaction_reply(interaction, "이미 진행 중인 게임이 있습니다.", private=True)
        return
    if interaction.guild_id in recruiting_guilds:
        await send_interaction_reply(interaction, "이미 참가자를 모집 중입니다.", private=True)
        return

    participant_role = discord.utils.get(interaction.guild.roles, name=config.participant_role)
    if not participant_role:
        await send_interaction_reply(
            interaction,
            f"'{config.participant_role}' 역할을 찾을 수 없습니다.",
            private=True,
        )
        return

    await interaction.response.defer(thinking=True)
    recruiting_guilds.add(interaction.guild.id)
    try:
        try:
            special_roles = choose_special_roles()
            role_counts = selected_role_counts(special_roles)
            validate_max_player_count(role_counts, config.max_player_count)
            fixed_special_roles: list[Role] = []
            if config.enable_cult_team:
                fixed_special_roles.extend([Role.CULT_LEADER, Role.FANATIC])
            game_special_roles = [*expand_special_roles_for_game(special_roles), *fixed_special_roles]
        except ValueError as error:
            await interaction.followup.send(
                embed=make_embed(str(error), color=ERROR_EMBED_COLOR),
                ephemeral=True,
            )
            return
        clear_failed = await clear_existing_participant_roles(interaction.guild, participant_role)
        spectator_clear_failed: list[str] = []
        spectator_role = get_spectator_role(interaction.guild)
        if spectator_role:
            spectator_clear_failed = await clear_existing_spectator_roles(interaction.guild, spectator_role)
        join_view = JoinGameView(
            interaction.guild.id,
            interaction.user.id,
            participant_role.id,
            role_counts,
            config.reveal_death_roles,
            config.reveal_public_police_status,
            config.reveal_morning_mafia_count,
            effective_max_player_count(),
        )
        notification_role = discord.utils.get(interaction.guild.roles, name=GAME_NOTIFICATION_ROLE)
        recruit_message = await interaction.followup.send(
            content=notification_role.mention if notification_role else None,
            embed=join_view.embed("모집 중입니다."),
            view=join_view,
            allowed_mentions=discord.AllowedMentions(roles=True),
            wait=True,
        )
        join_view.message = recruit_message

        try:
            await asyncio.wait_for(join_view.done.wait(), timeout=RECRUITMENT_SECONDS)
        except asyncio.TimeoutError:
            pass

        if join_view.accepting:
            async with join_view.lock:
                if join_view.accepting:
                    join_view.accepting = False
                    disable_view_items(join_view)
                    if len(join_view.joined_ids) < join_view.minimum_players:
                        join_view.cancelled = True
                        await join_view.refresh_message(
                            "최소 시작 인원에 도달하지 못해 모집이 자동 취소되었습니다.",
                            title="참가자 모집 취소",
                            color=ERROR_EMBED_COLOR,
                        )
                    else:
                        await join_view.refresh_message(
                            "최대 모집 시간이 지나 자동으로 마감되었습니다. 게임을 시작합니다.",
                            title="참가자 모집 종료",
                        )
                    join_view.stop()

        if join_view.cancelled:
            await remove_participant_roles_from_ids(
                interaction.guild,
                join_view.joined_ids,
                "마피아 게임 참가 모집 취소로 참가자 역할 제거",
            )
            await remove_spectator_roles_from_ids(
                interaction.guild,
                join_view.spectator_ids,
                "마피아 게임 참가 모집 취소로 관전자 역할 제거",
            )
            await interaction.followup.send(
                embed=make_embed(
                    "참가자 모집이 취소되었습니다. 참가자/관전자 역할을 회수했습니다.",
                    title="참가자 모집 취소",
                    color=ERROR_EMBED_COLOR,
                )
            )
            return

        participants = await collect_joined_participants(interaction.guild, join_view.joined_ids)
        player_data = [(member.id, display_name(member)) for member in participants]

        try:
            game = MafiaGame(
                players=player_data,
                mafia_count=role_counts[Role.MAFIA],
                doctor_count=role_counts[Role.DOCTOR],
                police_count=role_counts.get(Role.POLICE, 0),
                joker_count=0,
                special_roles=game_special_roles,
                agent_count=role_counts.get(Role.AGENT, 0),
                vigilante_count=role_counts.get(Role.VIGILANTE, 0),
            )
        except ValueError as error:
            await remove_participant_roles_from_ids(
                interaction.guild,
                join_view.joined_ids,
                "마피아 게임 시작 실패로 참가자 역할 제거",
            )
            await remove_spectator_roles_from_ids(
                interaction.guild,
                join_view.spectator_ids,
                "마피아 게임 시작 실패로 관전자 역할 제거",
            )
            await interaction.followup.send(
                embed=make_embed(str(error), color=ERROR_EMBED_COLOR),
                ephemeral=True,
            )
            return

        running = RunningGame(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel_id,
            game=game,
            reveal_death_roles=config.reveal_death_roles,
            reveal_public_police_status=config.reveal_public_police_status,
            reveal_morning_mafia_count=config.reveal_morning_mafia_count,
            anonymous_enabled=config.anonymous_mode,
            participant_user_ids=set(join_view.joined_ids),
            spectator_user_ids=set(join_view.spectator_ids),
            initial_roles={player.user_id: player.role for player in game.players},
        )
        games[interaction.guild.id] = running
        running.task = asyncio.create_task(game_loop(interaction.guild, running))

        warning = ""
        if clear_failed:
            warning = (
                "\n\n기존 참가자 역할을 제거하지 못한 유저: "
                + ", ".join(clear_failed)
                + "\n봇 역할 관리 권한과 역할 순서를 확인하세요."
            )
        if spectator_clear_failed:
            warning += (
                "\n\n기존 관전자 역할을 제거하지 못한 유저: "
                + ", ".join(spectator_clear_failed)
                + "\n봇 역할 관리 권한과 역할 순서를 확인하세요."
            )
        await interaction.followup.send(
            embed=make_embed(
                "게임을 시작합니다. "
                f"참가자 {len(game.players)}명에게 역할을 DM으로 보냅니다.\n"
                f"관전자: {len(join_view.spectator_ids)}명\n"
                f"{public_role_count_text(game)}"
                f"\n사망 시 직업 공개: {'공개' if config.reveal_death_roles else '비공개'}"
                f"\n경찰 조사 성공 여부 공개: {'공개' if config.reveal_public_police_status else '비공개'}"
                f"\n아침 생존 마피아 수 공개: {'공개' if config.reveal_morning_mafia_count else '비공개'}"
                f"\n교주팀: {'켜짐 - 교주 1명, 광신도 1명 필수 배정' if config.enable_cult_team else '꺼짐'}"
                f"\n채팅 슬로우모드: {config.chat_slowmode_seconds}초"
                f"\n최대 참가 인원: {max_player_setting_text()}"
                f"\n익명 채팅: {'켜짐' if config.anonymous_mode else '꺼짐'}"
                f"{f' ({anonymous_name_mode_text()})' if config.anonymous_mode else ''}"
                f"{warning}",
                title="게임 시작",
                color=SUCCESS_EMBED_COLOR,
            )
        )
    finally:
        recruiting_guilds.discard(interaction.guild.id)


@bot.tree.command(name="마피아중지", description="진행 중인 마피아 게임을 중지합니다.")
async def stop_game(interaction: discord.Interaction) -> None:
    require_manager(interaction)
    if not interaction.guild or not interaction.guild_id:
        await send_interaction_reply(interaction, "서버에서만 사용할 수 있습니다.", private=True)
        return

    running = games.pop(interaction.guild_id, None)
    if not running:
        await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
        return

    await interaction.response.defer(thinking=True)
    running.game.phase = Phase.ENDED
    channel = interaction.guild.get_channel(running.channel_id)
    if isinstance(channel, discord.abc.Messageable):
        await announce_final_roles(channel, running, "관리자가 게임을 중지했습니다.")

    if running.task:
        running.task.cancel()
        try:
            await running.task
        except asyncio.CancelledError:
            pass
        except Exception as error:
            print(f"Game task error during stop: {error!r}")
            await cleanup_game(interaction.guild, running)
    else:
        await cleanup_game(interaction.guild, running)

    await interaction.followup.send(
        embed=make_embed("게임을 중지했습니다.", title="게임 중지", color=SUCCESS_EMBED_COLOR)
    )


@bot.tree.command(name="마피아비활성화", description="마피아 게임 시작을 비활성화합니다.")
async def disable_mafia_game(interaction: discord.Interaction) -> None:
    require_manager(interaction)
    config.game_enabled = False
    save_config()
    await send_interaction_reply(
        interaction,
        "마피아 게임을 비활성화했습니다. 새 게임을 시작할 수 없습니다.",
        private=False,
    )


@bot.tree.command(name="마피아활성화", description="마피아 게임 시작을 활성화합니다.")
async def enable_mafia_game(interaction: discord.Interaction) -> None:
    require_manager(interaction)
    config.game_enabled = True
    save_config()
    await send_interaction_reply(
        interaction,
        "마피아 게임을 활성화했습니다. 이제 새 게임을 시작할 수 있습니다.",
        private=False,
    )


@bot.tree.command(name="블랙리스트추가", description="마피아 게임 참가 블랙리스트에 유저를 추가합니다.")
@app_commands.describe(유저="블랙리스트에 추가할 유저")
async def add_to_blacklist(interaction: discord.Interaction, 유저: discord.Member) -> None:
    require_manager(interaction)
    if 유저.bot:
        await send_interaction_reply(interaction, "봇은 블랙리스트에 추가할 수 없습니다.", private=True)
        return

    changed = set_blacklist_status(유저.id, True)
    save_config()
    if changed:
        message = f"{display_name(유저)} 님을 블랙리스트에 추가했습니다. 이제 게임에 참가할 수 없습니다."
    else:
        message = f"{display_name(유저)} 님은 이미 블랙리스트에 있습니다."
    await send_interaction_reply(interaction, message, private=False)


@bot.tree.command(name="블랙리스트해제", description="마피아 게임 참가 블랙리스트에서 유저를 제거합니다.")
@app_commands.describe(유저="블랙리스트에서 해제할 유저")
async def remove_from_blacklist(interaction: discord.Interaction, 유저: discord.Member) -> None:
    require_manager(interaction)
    changed = set_blacklist_status(유저.id, False)
    save_config()
    if changed:
        message = f"{display_name(유저)} 님을 블랙리스트에서 해제했습니다. 이제 게임에 참가할 수 있습니다."
    else:
        message = f"{display_name(유저)} 님은 블랙리스트에 없습니다."
    await send_interaction_reply(interaction, message, private=False)


@bot.tree.command(name="블랙리스트목록", description="마피아 게임 참가 블랙리스트 목록을 확인합니다.")
async def show_blacklist(interaction: discord.Interaction) -> None:
    require_manager(interaction)
    user_ids = sorted(blacklist_user_ids())
    if not user_ids:
        await send_interaction_reply(interaction, "블랙리스트가 비어 있습니다.", private=True)
        return

    lines = []
    guild = interaction.guild
    for index, user_id in enumerate(user_ids[:50], start=1):
        member = guild.get_member(user_id) if guild else None
        name = display_name(member) if member else f"알 수 없음 ({user_id})"
        lines.append(f"{index}. {name} - `{user_id}`")
    if len(user_ids) > 50:
        lines.append(f"... 외 {len(user_ids) - 50}명")
    await interaction.response.send_message(
        embed=make_embed("\n".join(lines), title="블랙리스트"),
        ephemeral=True,
    )

@start_game.error
@stop_game.error
@disable_mafia_game.error
@enable_mafia_game.error
@add_to_blacklist.error
@remove_from_blacklist.error
@show_blacklist.error
async def command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    await send_command_error(interaction, error)

