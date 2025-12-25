"""Role and identity assignment commands."""

import discord
from discord import app_commands
from discord.ext import commands
import random

from data.identities import ANON_IDENTITIES
from helpers.game_state import get_game
from helpers.permissions import gm_only, require_game


class RolesCog(commands.Cog):
    """Commands for assigning roles and identities."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="assign_role", description="[GM/IM] Secretly assign alignment and role to a player")
    @app_commands.describe(
        player="The player to assign",
        alignment="Village or Elims",
        role="Specific role (e.g., Vanilla, Godfather, Doctor, Cop)"
    )
    @app_commands.choices(alignment=[
        app_commands.Choice(name="Village", value="village"),
        app_commands.Choice(name="Elims", value="elims")
    ])
    @gm_only()
    @require_game()
    async def assign_role(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        alignment: app_commands.Choice[str],
        role: str = "Vanilla"
    ):
        """Assign alignment and role to a player."""
        game = get_game(interaction.guild_id)
        
        if player.id not in game.players:
            await interaction.response.send_message(
                f"❌ {player.mention} is not in the game!",
                ephemeral=True
            )
            return
        
        game.players[player.id].alignment = alignment.value
        game.players[player.id].role = role
        
        await interaction.response.send_message(
            f"✅ Assigned **{alignment.name} - {role}** to {player.mention}",
            ephemeral=True
        )
        
        # Send PM if private thread exists
        if game.players[player.id].private_channel_id:
            private_thread = interaction.guild.get_thread(game.players[player.id].private_channel_id)
            if private_thread:
                await private_thread.send(
                    f"🎭 **Your Role Assignment:**\n"
                    f"**Alignment:** {alignment.name}\n"
                    f"**Role:** {role}"
                )
    
    @app_commands.command(name="randomize_alignments", description="[GM/IM] Randomly assign village/elim alignments")
    @app_commands.describe(num_elims="Number of elims (default: 1/4 of players, rounded up)")
    @gm_only()
    @require_game(status='setup')
    async def randomize_alignments(self, interaction: discord.Interaction, num_elims: int = None):
        """Randomly assign alignments to all players."""
        game = get_game(interaction.guild_id)
        total_players = len(game.players)
        
        if total_players < 3:
            await interaction.response.send_message(
                "❌ Need at least 3 players to randomize alignments!",
                ephemeral=True
            )
            return
        
        # Default: 1/4 of players, minimum 1
        if num_elims is None:
            num_elims = max(1, (total_players + 3) // 4)
        
        if num_elims >= total_players:
            await interaction.response.send_message(
                "❌ Number of elims must be less than total players!",
                ephemeral=True
            )
            return
        
        # Randomize
        player_ids = list(game.players.keys())
        random.shuffle(player_ids)
        
        assignments = []
        for i, user_id in enumerate(player_ids):
            if i < num_elims:
                game.players[user_id].alignment = 'elims'
                game.players[user_id].role = 'Vanilla'
                assignments.append(f"{game.players[user_id].display_name} → **Elims**")
            else:
                game.players[user_id].alignment = 'village'
                game.players[user_id].role = 'Vanilla'
                assignments.append(f"{game.players[user_id].display_name} → **Village**")
        
        await interaction.response.send_message(
            f"✅ **Alignments Randomized:**\n"
            f"**Elims:** {num_elims} | **Village:** {total_players - num_elims}\n\n"
            + "\n".join(assignments),
            ephemeral=True
        )
    
    @app_commands.command(name="assign_identities", description="[GM/IM] Randomly assign anonymous identities to all players")
    @gm_only()
    @require_game()
    async def assign_identities(self, interaction: discord.Interaction):
        """Randomly assign anon identities."""
        game = get_game(interaction.guild_id)
        
        if not game.anon_mode:
            await interaction.response.send_message(
                "❌ Anonymous mode is not enabled! Use `/config_game anon_mode:True`",
                ephemeral=True
            )
            return
        
        if len(game.players) > len(ANON_IDENTITIES):
            await interaction.response.send_message(
                f"❌ Too many players ({len(game.players)}) for available identities ({len(ANON_IDENTITIES)})!",
                ephemeral=True
            )
            return
        
        # Shuffle and assign
        available = game.available_identities.copy()
        random.shuffle(available)
        
        assignments = []
        for i, (user_id, player) in enumerate(game.players.items()):
            identity = available[i]
            player.anon_identity = identity
            game.available_identities.remove(identity)
            assignments.append(f"{player.display_name} → **{identity}**")
        
        await interaction.response.send_message(
            f"✅ **Identities Assigned:**\n" + "\n".join(assignments),
            ephemeral=True
        )
    
    @app_commands.command(name="assign_identity", description="[GM/IM] Manually assign a specific anonymous identity to a player")
    @app_commands.describe(
        player="The player to assign",
        identity="The anonymous identity to assign"
    )
    @gm_only()
    @require_game()
    async def assign_identity(self, interaction: discord.Interaction, player: discord.Member, identity: str):
        """Manually assign a specific anon identity."""
        game = get_game(interaction.guild_id)
        
        if not game.anon_mode:
            await interaction.response.send_message(
                "❌ Anonymous mode is not enabled!",
                ephemeral=True
            )
            return
        
        if player.id not in game.players:
            await interaction.response.send_message(
                f"❌ {player.mention} is not in the game!",
                ephemeral=True
            )
            return
        
        if identity not in ANON_IDENTITIES:
            await interaction.response.send_message(
                f"❌ Unknown identity: {identity}\n**Available:** {', '.join(ANON_IDENTITIES.keys())}",
                ephemeral=True
            )
            return
        
        if identity not in game.available_identities:
            await interaction.response.send_message(
                f"❌ {identity} is already assigned!",
                ephemeral=True
            )
            return
        
        # Free old identity
        old_identity = game.players[player.id].anon_identity
        if old_identity:
            game.available_identities.append(old_identity)
        
        # Assign new
        game.players[player.id].anon_identity = identity
        game.available_identities.remove(identity)
        
        await interaction.response.send_message(
            f"✅ Assigned **{identity}** to {player.mention}",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RolesCog(bot))