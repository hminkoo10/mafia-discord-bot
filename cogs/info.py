from __future__ import annotations

from cogs.common import *  # noqa: F401,F403


def find_role_by_name(name: str) -> Role | None:
    normalized = name.strip()
    if not normalized:
        return None
    for role in ROLE_GUIDE_ORDER:
        if role.value == normalized:
            return role
    lowered = normalized.casefold()
    for role in ROLE_GUIDE_ORDER:
        if role.value.casefold() == lowered:
            return role
    matches = [role for role in ROLE_GUIDE_ORDER if lowered in role.value.casefold()]
    return matches[0] if len(matches) == 1 else None


async def role_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    query = current.strip().casefold()
    roles = [
        role
        for role in ROLE_GUIDE_ORDER
        if not query or query in role.value.casefold()
    ]
    return [
        app_commands.Choice(name=role.value, value=role.value)
        for role in roles[:25]
    ]


def term_primary_name(term: tuple[str, tuple[str, ...], str, str]) -> str:
    return term[1][0]


def term_field_value(term: tuple[str, tuple[str, ...], str, str]) -> str:
    _category, names, meaning, example = term
    aliases = ", ".join(names[1:])
    lines = [meaning]
    if aliases:
        lines.append(f"같은 말: {aliases}")
    if example:
        lines.append(f"예시: {example}")
    return "\n".join(lines)


def find_term_by_name(name: str) -> tuple[str, tuple[str, ...], str, str] | None:
    query = name.strip().casefold()
    if not query:
        return None
    for term in MAFIA_TERM_ENTRIES:
        if any(alias.casefold() == query for alias in term[1]):
            return term
    matches = [
        term
        for term in MAFIA_TERM_ENTRIES
        if any(query in alias.casefold() for alias in term[1])
    ]
    return matches[0] if len(matches) == 1 else None


async def term_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    query = current.strip().casefold()
    terms = [
        term
        for term in MAFIA_TERM_ENTRIES
        if not query or any(query in alias.casefold() for alias in term[1])
    ]
    return [
        app_commands.Choice(name=term_primary_name(term), value=term_primary_name(term))
        for term in terms[:25]
    ]


def make_term_guide_embeds(title: str = "용어 설명") -> list[discord.Embed]:
    embeds: list[discord.Embed] = []
    grouped_terms: dict[str, list[tuple[str, tuple[str, ...], str, str]]] = {}
    for term in MAFIA_TERM_ENTRIES:
        grouped_terms.setdefault(term[0], []).append(term)

    for category, terms in grouped_terms.items():
        current_embed: discord.Embed | None = None
        current_size = 0
        for term in terms:
            field_name = term_primary_name(term)
            field_value = term_field_value(term)
            entry_size = len(field_name) + len(field_value) + 16
            if current_embed is None or len(current_embed.fields) >= 25 or current_size + entry_size > 5200:
                suffix = f" - {category}"
                current_embed = make_embed(
                    "마피아42 용어 문서를 참고해 이 봇 진행에 맞게 짧게 정리한 용어집입니다.",
                    title=f"{title}{suffix}",
                )
                embeds.append(current_embed)
                current_size = len(current_embed.title or "") + len(current_embed.description or "")
            current_embed.add_field(name=field_name, value=field_value, inline=False)
            current_size += entry_size

    return embeds


@bot.tree.command(name="용어정보", description="마피아 게임 용어 하나를 확인합니다.")
@app_commands.describe(용어="설명을 볼 용어")
@app_commands.autocomplete(용어=term_name_autocomplete)
async def show_term_info(interaction: discord.Interaction, 용어: str) -> None:
    term = find_term_by_name(용어)
    if not term:
        await send_interaction_reply(
            interaction,
            "용어를 찾을 수 없습니다. 자동완성 목록에서 선택하거나 정확한 용어를 입력하세요.",
            private=True,
        )
        return

    category, names, _meaning, _example = term
    await interaction.response.send_message(
        embed=make_embed(
            f"분류: {category}\n\n{term_field_value(term)}",
            title=f"용어정보 - {names[0]}",
            color=SUCCESS_EMBED_COLOR,
        )
    )


@bot.tree.command(name="용어설명", description="마피아 게임 용어 설명을 공지용 임베드로 보냅니다.")
async def show_term_descriptions(interaction: discord.Interaction) -> None:
    embeds = make_term_guide_embeds()
    await interaction.response.send_message(embed=embeds[0])
    for embed in embeds[1:]:
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="직업정보", description="특정 직업의 설명을 확인합니다.")
@app_commands.describe(직업명="설명을 볼 직업 이름")
@app_commands.autocomplete(직업명=role_name_autocomplete)
async def show_role_info(interaction: discord.Interaction, 직업명: str) -> None:
    role = find_role_by_name(직업명)
    if not role:
        await send_interaction_reply(
            interaction,
            "직업을 찾을 수 없습니다. 자동완성 목록에서 선택하거나 정확한 직업명을 입력하세요.",
            private=True,
        )
        return

    await interaction.response.send_message(
        embed=make_embed(
            f"{role.value}\n{role_guide_value(role)}",
            title="직업정보",
            color=SUCCESS_EMBED_COLOR,
        )
    )


@bot.tree.command(name="마피아능력", description="배정받은 역할과 능력 설명을 다시 확인합니다.")
async def show_abilities(interaction: discord.Interaction) -> None:
    if not interaction.guild_id:
        await send_interaction_reply(interaction, "서버에서만 사용할 수 있습니다.", private=True)
        return

    running = games.get(interaction.guild_id)
    if not running:
        await send_interaction_reply(interaction, "진행 중인 게임이 없습니다.", private=True)
        return

    player = running.game.get_player(interaction.user.id)
    if not player:
        await send_interaction_reply(interaction, "현재 게임 참가자만 능력 설명을 확인할 수 있습니다.", private=True)
        return

    await interaction.response.send_message(
        embed=make_role_guide_embed(running.game, player=player, title="능력 설명"),
        ephemeral=True,
    )


@bot.tree.command(name="역할설명", description="마피아 게임 전체 역할 설명을 공지용 임베드로 보냅니다.")
async def show_role_descriptions(interaction: discord.Interaction) -> None:
    embeds = make_role_guide_embeds(title="역할 설명")
    await interaction.response.send_message(embed=embeds[0])
    for embed in embeds[1:]:
        await interaction.followup.send(embed=embed)

@show_term_info.error
@show_term_descriptions.error
@show_role_info.error
@show_abilities.error
@show_role_descriptions.error
async def command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    await send_command_error(interaction, error)

