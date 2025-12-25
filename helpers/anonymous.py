"""Anonymous posting utilities using Discord webhooks."""

import discord
from typing import Optional

from data.identities import ANON_IDENTITIES
from helpers.game_state import Game


WEBHOOK_NAME = "SEBOT Anon Webhook"


async def get_or_create_webhook(channel: discord.TextChannel) -> discord.Webhook:
    """Get existing webhook or create new one for anonymous posting."""
    webhooks = await channel.webhooks()
    webhook = discord.utils.get(webhooks, name=WEBHOOK_NAME)
    
    if not webhook:
        webhook = await channel.create_webhook(name=WEBHOOK_NAME)
    
    return webhook


async def post_anon_message(
    guild: discord.Guild,
    game: Game,
    user_id: int,
    message: str,
    use_embed: bool = True
) -> bool:
    """
    Post an anonymous message to the game channel.
    
    Args:
        guild: The Discord guild
        game: The game instance
        user_id: The user posting the message
        message: The message content
        use_embed: If True, use an embed with colored sidebar
        
    Returns:
        True if successful, False otherwise
    """
    player = game.players.get(user_id)
    if not player or not player.anon_identity:
        return False
    
    game_channel = guild.get_channel(game.game_channel_id)
    if not game_channel:
        return False
    
    try:
        webhook = await get_or_create_webhook(game_channel)
        identity_info = ANON_IDENTITIES[player.anon_identity]
        
        if use_embed:
            embed = discord.Embed(
                description=message,
                color=identity_info['color']
            )
            await webhook.send(
                embed=embed,
                username=player.anon_identity,
                avatar_url=identity_info['avatar_url']
            )
        else:
            await webhook.send(
                content=message,
                username=player.anon_identity,
                avatar_url=identity_info['avatar_url']
            )
        
        return True
    except Exception as e:
        print(f"Error posting anon message: {e}")
        return False


async def announce_vote(
    guild: discord.Guild,
    game: Game,
    voter_id: int,
    target_display: str,
    is_unvote: bool = False
) -> None:
    """
    Announce a vote or unvote in the game channel.
    Uses webhook for anon mode, regular message otherwise.
    """
    voter_display = game.get_player_display_name(voter_id)
    
    if is_unvote:
        message = f"↩️ **Has unvoted**"
        public_message = f"↩️ **{voter_display}** has unvoted"
    else:
        message = f"🗳️ **Votes for {target_display}**"
        public_message = f"🗳️ **{voter_display}** has voted for **{target_display}**"
    
    if game.anon_mode:
        await post_anon_message(guild, game, voter_id, message)
    else:
        game_channel = guild.get_channel(game.game_channel_id)
        if game_channel:
            await game_channel.send(public_message)