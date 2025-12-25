"""Utility helper functions."""

import discord
from datetime import datetime
from typing import Optional

from helpers.game_state import Game
from helpers.permissions import get_gm_role, get_im_role


def format_time_remaining(end_time: Optional[datetime]) -> str:
    """Format remaining time in a readable way."""
    if not end_time:
        return "No timer set"
    
    now = datetime.now()
    remaining = end_time - now
    
    if remaining.total_seconds() <= 0:
        return "Phase has ended!"
    
    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m remaining"
    else:
        return f"{minutes}m remaining"


async def update_game_channel_permissions(guild: discord.Guild, game: Game) -> None:
    """Update game channel permissions based on living players and game mode."""
    game_channel = guild.get_channel(game.game_channel_id)
    if not game_channel:
        return
    
    gm_role = get_gm_role(guild)
    im_role = get_im_role(guild)
    
    # Base permissions
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            read_messages=True,
            send_messages=False,
            create_public_threads=False,
            create_private_threads=False
        ),
        guild.me: discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
            create_public_threads=True,
            create_private_threads=True
        )
    }
    
    # GM/IM permissions
    for role in [gm_role, im_role]:
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                create_public_threads=True,
                create_private_threads=True
            )
    
    # In non-anon mode, living players can post
    if not game.anon_mode:
        for user_id, player in game.players.items():
            member = guild.get_member(user_id)
            if member and player.is_alive:
                overwrites[member] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    create_public_threads=False,
                    create_private_threads=False
                )
    
    await game_channel.edit(overwrites=overwrites)


async def add_user_to_thread_safe(thread: discord.Thread, member: discord.Member) -> bool:
    """Safely add a user to a thread, returning success status."""
    try:
        await thread.add_user(member)
        return True
    except Exception as e:
        print(f"Error adding {member.name} to thread {thread.name}: {e}")
        return False


async def archive_game(guild: discord.Guild, game: Game) -> tuple[int, str]:
    """
    Archive all game threads and make them public.
    
    Returns:
        Tuple of (channels archived count, archive category name)
    """
    if not game.game_channel_id:
        return 0, "No channels to archive"
    
    game_channel = guild.get_channel(game.game_channel_id)
    if not game_channel:
        return 0, "Game channel not found"
    
    # Create archive category name
    if game.game_tag and game.flavor_name:
        game_name = f"{game.game_tag} - {game.flavor_name}"
    else:
        game_name = "Archived Game"
    
    archive_category = await guild.create_category(name=f"📁 {game_name}")
    
    try:
        # Move game channel to archive and make public/read-only
        await game_channel.edit(
            category=archive_category,
            sync_permissions=False,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False,
                    create_public_threads=True,
                    create_private_threads=False
                ),
                guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    create_public_threads=True,
                    create_private_threads=True
                )
            }
        )
        
        # Archive and lock all active threads
        for thread in game_channel.threads:
            try:
                if thread.archived:
                    await thread.edit(archived=False)
                await thread.edit(locked=True, archived=True)
            except Exception as e:
                print(f"Error archiving thread {thread.name}: {e}")
        
        # Also handle archived threads
        async for thread in game_channel.archived_threads(limit=100):
            try:
                await thread.edit(archived=False, locked=True)
                await thread.edit(archived=True)
            except Exception as e:
                print(f"Error archiving old thread {thread.name}: {e}")
        
        return 1, archive_category.name
        
    except Exception as e:
        print(f"Error archiving game: {e}")
        return 0, "Error during archiving"