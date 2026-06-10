from __future__ import annotations

from cogs.common import *  # noqa: F401,F403


@bot.tree.command(name="마피아상태", description="진행 중인 마피아 게임 상태를 확인합니다.")
async def show_status(interaction: discord.Interaction) -> None:
    require_manager(interaction)
    if not interaction.guild_id:
        await send_interaction_reply(interaction, "서버에서만 사용할 수 있습니다.", private=True)
        return

    running = games.get(interaction.guild_id)
    if not running:
        await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
        return
    await interaction.response.send_message(
        embed=make_embed(running.game.public_status(), title="게임 상태"),
        ephemeral=True,
    )


@bot.tree.command(name="상태", description="현재 마피아 게임 생존자와 사망자를 확인합니다.")
async def show_public_status(interaction: discord.Interaction) -> None:
    if not interaction.guild_id:
        await send_interaction_reply(interaction, "서버에서만 사용할 수 있습니다.", private=True)
        return

    running = games.get(interaction.guild_id)
    if not running:
        await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
        return

    player = running.game.get_player(interaction.user.id)
    await interaction.response.send_message(
        embed=make_embed(command_status_text(running, interaction.user.id), title="게임 현황"),
        ephemeral=running.anonymous_enabled and player is not None,
    )


@bot.tree.command(name="메모", description="개인 메모 채널에 참가자별 메모를 저장하거나 조회합니다.")
@app_commands.describe(참가자="메모 대상 참가자", 메모내용="저장할 메모 내용. 비워두면 조회합니다.")
async def write_memo(
    interaction: discord.Interaction,
    참가자: discord.Member,
    메모내용: str | None = None,
) -> None:
    if not interaction.guild or not interaction.guild_id:
        await send_interaction_reply(interaction, "서버에서만 사용할 수 있습니다.", private=True)
        return

    running = games.get(interaction.guild_id)
    if not running:
        await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
        return

    author = running.game.get_player(interaction.user.id)
    if not author:
        await send_interaction_reply(interaction, "현재 게임 참가자만 메모를 사용할 수 있습니다.", private=True)
        return

    target = running.game.get_player(참가자.id)
    if not target:
        await send_interaction_reply(interaction, "메모 대상은 현재 게임 참가자여야 합니다.", private=True)
        return

    memo_channel = await ensure_memo_channel(interaction.guild, running, author)
    if not memo_channel:
        await send_interaction_reply(interaction, "개인 메모 채널을 만들 수 없습니다.", private=True)
        return

    target_memos = running.memos.setdefault(author.user_id, {}).setdefault(target.user_id, [])
    content = (메모내용 or "").strip()
    if not content:
        chunks = memo_chunks(running, target, target_memos)
        await interaction.response.send_message(
            embed=make_embed(chunks[0], title="메모 조회"),
            ephemeral=True,
        )
        for chunk in chunks[1:]:
            await interaction.followup.send(
                embed=make_embed(chunk, title="메모 조회"),
                ephemeral=True,
            )
        return

    target_memos.append(content)
    memo_number = len(target_memos)
    target_name = memo_target_name(running, target)
    await send_embed(
        memo_channel,
        f"대상: {target_name}\n{memo_number}. {content}",
        title="메모 등록",
        color=SUCCESS_EMBED_COLOR,
    )
    await interaction.response.send_message(
        embed=make_embed(
            f"{target_name} 님에 대한 메모를 저장했습니다.",
            title="메모 등록",
            color=SUCCESS_EMBED_COLOR,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="내정보", description="내 마피아 게임 전적을 확인합니다.")
async def show_my_info(interaction: discord.Interaction) -> None:
    fallback_name = (
        display_name(interaction.user)
        if isinstance(interaction.user, discord.Member)
        else interaction.user.name
    )
    await interaction.response.send_message(
        embed=make_embed(personal_stats_text(interaction.user.id, fallback_name), title="내정보"),
        ephemeral=True,
    )


@bot.tree.command(name="리더보드", description="마피아 게임 전적 순위를 확인합니다.")
@app_commands.describe(기준="순위를 세울 기준")
@app_commands.choices(
    기준=[
        app_commands.Choice(name="승리수", value="wins"),
        app_commands.Choice(name="승률", value="winrate"),
        app_commands.Choice(name="판수", value="games"),
        app_commands.Choice(name="마피아팀 횟수", value="mafia"),
        app_commands.Choice(name="게임시간", value="playtime"),
    ]
)
async def show_leaderboard(
    interaction: discord.Interaction,
    기준: str = "wins",
) -> None:
    await interaction.response.send_message(
        embed=make_embed(leaderboard_text(기준), title="리더보드"),
    )


@bot.tree.command(name="리더보드초기화", description="마피아 게임 전적과 리더보드를 초기화합니다.")
async def reset_leaderboard(interaction: discord.Interaction) -> None:
    require_manager(interaction)
    save_stats({"users": {}})
    await send_interaction_reply(
        interaction,
        "리더보드와 개인 전적을 초기화했습니다.",
        private=False,
    )

@show_status.error
@show_public_status.error
@write_memo.error
@show_my_info.error
@show_leaderboard.error
@reset_leaderboard.error
async def command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    await send_command_error(interaction, error)

