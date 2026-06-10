from __future__ import annotations

from bot import *  # noqa: F401,F403


async def send_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    root_error = getattr(error, "original", error)
    if isinstance(root_error, app_commands.CheckFailure | ValueError):
        message = str(root_error)
    else:
        print(f"Command error: {root_error!r}")
        message = "명령을 실행하는 중 오류가 발생했습니다."

    error_embed = make_embed(message, color=ERROR_EMBED_COLOR)
    if interaction.response.is_done():
        with suppress(discord.HTTPException):
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        return

    try:
        await interaction.response.send_message(embed=error_embed, ephemeral=True)
    except discord.HTTPException:
        with suppress(discord.HTTPException):
            await interaction.followup.send(embed=error_embed, ephemeral=True)
