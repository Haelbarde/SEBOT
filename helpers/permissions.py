"""Permission checks and decorators for command authorization."""

import discord
from discord import app_commands
from functools import wraps
from typing import Callable, Optional

from helpers.game_state import get_game

# Role name constants
GM_ROLE = "GM"
IM_ROLE = "IM"


def is_gm_or_im(interaction: discord.Interaction) -> bool:
    """Check if user has GM or IM role."""
    user_roles = [role.name for role in interaction.user.roles]
    return GM_ROLE in user_roles or IM_ROLE in user_roles


def get_gm_role(guild: discord.Guild) -> Optional[discord.Role]:
    """Get the GM role for a guild."""
    return discord.utils.get(guild.roles, name=GM_ROLE)


def get_im_role(guild: discord.Guild) -> Optional[discord.Role]:
    """Get the IM role for a guild."""
    return discord.utils.get(guild.roles, name=IM_ROLE)


async def check_role_manageable(
    interaction: discord.Interaction,
    role: discord.Role,
    role_name: str
) -> Optional[str]:
    """
    Check if the bot can manage a role.
    Returns error message if not manageable, None if OK.
    """
    guild = interaction.guild
    
    if not guild.me.guild_permissions.manage_roles:
        return (
            "❌ I don't have permission to manage roles!\n"
            "Please give me the 'Manage Roles' permission."
        )
    
    if role.position >= guild.me.top_role.position:
        return (
            f"❌ The {role_name} role is higher than my highest role!\n"
            f"Please move my role above the {role_name} role in Server Settings → Roles."
        )
    
    return None


async def manage_discord_role(
    interaction: discord.Interaction,
    user: discord.Member,
    role_name: str,
    action: str  # 'add' or 'remove'
) -> None:
    """
    Add or remove a Discord role from a user.
    Handles all permission checks and error responses.
    """
    guild = interaction.guild
    role = discord.utils.get(guild.roles, name=role_name)
    
    # Check if role exists
    if not role:
        await interaction.response.send_message(
            f"❌ {role_name} role does not exist in this server!\n"
            f"Please create a '{role_name}' role first.",
            ephemeral=True
        )
        return
    
    has_role = role in user.roles
    
    if action == 'add':
        if has_role:
            await interaction.response.send_message(
                f"⚠️ {user.mention} already has the {role_name} role!",
                ephemeral=True
            )
            return
    else:  # remove
        if not has_role:
            await interaction.response.send_message(
                f"⚠️ {user.mention} doesn't have the {role_name} role!",
                ephemeral=True
            )
            return
        
        # Prevent removing last GM
        if role_name == GM_ROLE and user.id == interaction.user.id:
            gm_count = sum(1 for member in guild.members if role in member.roles)
            if gm_count <= 1:
                await interaction.response.send_message(
                    "❌ You cannot remove the GM role from yourself when you're the only GM!\n"
                    "Assign another GM first.",
                    ephemeral=True
                )
                return
    
    # Check bot permissions
    error = await check_role_manageable(interaction, role, role_name)
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return
    
    # Perform the action
    try:
        if action == 'add':
            await user.add_roles(role, reason=f"Assigned by {interaction.user.name}")
            await interaction.response.send_message(
                f"✅ Assigned {role_name} role to {user.mention}!"
            )
        else:
            await user.remove_roles(role, reason=f"Removed by {interaction.user.name}")
            await interaction.response.send_message(
                f"✅ Removed {role_name} role from {user.mention}!"
            )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ I don't have permission to {'assign' if action == 'add' else 'remove'} this role!",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Error {'assigning' if action == 'add' else 'removing'} role: {e}",
            ephemeral=True
        )


def gm_only(error_message: str = "❌ Only users with GM or IM role can use this command."):
    """Decorator that restricts a command to GM/IM only."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not is_gm_or_im(interaction):
            await interaction.response.send_message(error_message, ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


def require_game(status: Optional[str] = None):
    """
    Decorator that requires an active game.
    Optionally checks for specific game status ('setup', 'active', 'ended').
    Must be used after gm_only if both are needed.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        game = get_game(interaction.guild_id)
        
        if not game:
            await interaction.response.send_message(
                "❌ No game exists in this server yet!",
                ephemeral=True
            )
            return False
        
        if status and game.status != status:
            status_messages = {
                'setup': "❌ Game has already started!",
                'active': "❌ Game hasn't started yet!" if game.status == 'setup' else "❌ Game has ended!",
            }
            await interaction.response.send_message(
                status_messages.get(status, f"❌ Game is not in '{status}' status!"),
                ephemeral=True
            )
            return False
        
        return True
    return app_commands.check(predicate)