"""Player management commands - join, leave, spectate, list."""

import discord
from discord import app_commands
from discord.ext import commands

from helpers.game_state import get_game, Player
from helpers.permissions import is_gm_or_im, gm_only, require_game
from helpers.utils import add_user_to_thread_safe


class PlayersCog(commands.Cog):
    """Commands for player management."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="join_game", description="Join the current game as a player")
    @require_game(status='setup')
    async def join_game(self, interaction: discord.Interaction):
        """Players use this to join the game."""
        game = get_game(interaction.guild_id)
        user_id = interaction.user.id
        
        if user_id in game.players:
            await interaction.response.send_message("⚠️ You're already in the game!", ephemeral=True)
            return
        
        game.players[user_id] = Player(
            user_id=user_id,
            username=interaction.user.name,
            display_name=interaction.user.display_name
        )
        
        await interaction.response.send_message(f"✅ {interaction.user.mention} has joined the game!")
    
    @app_commands.command(name="leave_game", description="Leave the game before it starts")
    @require_game(status='setup')
    async def leave_game(self, interaction: discord.Interaction):
        """Players use this to leave before game starts."""
        game = get_game(interaction.guild_id)
        user_id = interaction.user.id
        
        if user_id not in game.players:
            await interaction.response.send_message("❌ You're not in the game!", ephemeral=True)
            return
        
        # Free up anon identity if assigned
        player = game.players.pop(user_id)
        if player.anon_identity:
            game.available_identities.append(player.anon_identity)
        
        await interaction.response.send_message(f"✅ {interaction.user.mention} has left the game.")
    
    @app_commands.command(name="player_list", description="Display all players in the game")
    @require_game()
    async def player_list(self, interaction: discord.Interaction):
        """Show list of all players."""
        game = get_game(interaction.guild_id)
        
        if not game.players:
            await interaction.response.send_message("📝 No players have joined yet.", ephemeral=True)
            return
        
        is_gm = is_gm_or_im(interaction)
        
        player_lines = []
        for i, (user_id, player) in enumerate(game.players.items(), 1):
            status = "💀" if not player.is_alive else "✅"
            
            # Display name based on mode
            if game.anon_mode and player.anon_identity:
                name_display = player.anon_identity
            else:
                name_display = player.display_name
                if player.character_name:
                    name_display += f" ({player.character_name})"
            
            # Show role info for dead players or GMs
            role_info = ""
            if player.alignment and (not player.is_alive or is_gm):
                role_info = f" - {player.alignment.title()}"
                if player.role:
                    role_info += f" ({player.role})"
            
            player_lines.append(f"{i}. {status} {name_display}{role_info}")
        
        player_list_text = "\n".join(player_lines)
        
        await interaction.response.send_message(
            f"**📋 Player List ({len(game.players)} players)**\n"
            f"```\n{player_list_text}\n```",
            ephemeral=is_gm
        )
    
    @app_commands.command(name="remove_player", description="[GM/IM] Remove a player from the game (before start)")
    @app_commands.describe(player="The player to remove")
    @gm_only()
    @require_game(status='setup')
    async def remove_player(self, interaction: discord.Interaction, player: discord.Member):
        """GM removes a player from the game before it starts."""
        game = get_game(interaction.guild_id)
        
        if player.id not in game.players:
            await interaction.response.send_message(
                f"❌ {player.mention} is not in the game.",
                ephemeral=True
            )
            return
        
        removed = game.players.pop(player.id)
        if removed.anon_identity:
            game.available_identities.append(removed.anon_identity)
        
        await interaction.response.send_message(f"✅ Removed {player.mention} from the game.")
    
    @app_commands.command(name="spectate_game", description="Join the game as a spectator")
    @require_game(status='active')
    async def spectate_game(self, interaction: discord.Interaction):
        """Allow users to spectate the game."""
        game = get_game(interaction.guild_id)
        user_id = interaction.user.id
        
        if user_id in game.players:
            await interaction.response.send_message(
                "❌ You're already a player in this game!",
                ephemeral=True
            )
            return
        
        if user_id in game.spectators:
            await interaction.response.send_message(
                "⚠️ You're already spectating this game!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
        member = guild.get_member(user_id)
        
        game.spectators.append(user_id)
        
        # Add to dead/spec thread
        if game.dead_spec_thread_id:
            dead_spec_thread = guild.get_thread(game.dead_spec_thread_id)
            if dead_spec_thread:
                await add_user_to_thread_safe(dead_spec_thread, member)
        
        # Add to all player threads (read-only)
        for uid, player_data in game.players.items():
            if player_data.private_channel_id:
                private_thread = guild.get_thread(player_data.private_channel_id)
                if private_thread:
                    await add_user_to_thread_safe(private_thread, member)
        
        # Add to elim thread
        if game.elim_discussion_thread_id:
            elim_thread = guild.get_thread(game.elim_discussion_thread_id)
            if elim_thread:
                await add_user_to_thread_safe(elim_thread, member)
        
        await interaction.followup.send(
            f"✅ **You are now spectating the game!**\n"
            f"You have been added to all game threads.\n"
            f"You can only post in the dead/spectator thread.",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayersCog(bot))