"""Utility commands - ping, test, command list."""

import discord
from discord import app_commands
from discord.ext import commands

from helpers.game_state import get_game
from helpers.permissions import is_gm_or_im


class UtilityCog(commands.Cog):
    """Utility and help commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="ping", description="Test if the bot is responding")
    async def ping(self, interaction: discord.Interaction):
        """Simple test command."""
        await interaction.response.send_message("Pong! Bot is online and ready.")
    
    @app_commands.command(name="test", description="Test command with GM role check")
    async def test(self, interaction: discord.Interaction):
        """Test if user has GM/IM role."""
        if is_gm_or_im(interaction):
            await interaction.response.send_message("✅ You have GM/IM permissions!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You don't have GM/IM permissions.", ephemeral=True)
    
    @app_commands.command(name="command_list", description="Show all available commands based on your role")
    async def command_list(self, interaction: discord.Interaction):
        """Display available commands for the user."""
        is_gm = is_gm_or_im(interaction)
        game = get_game(interaction.guild_id)
        
        # GM/IM Commands
        gm_commands = """
**🎮 GM/IM Setup Commands:**
• `/create_game` - Create a new game
• `/set_game_name` - Set game tag and flavor name
• `/create_game_channel` - Create game discussion channel
• `/set_game_channel` - Use existing channel as game channel
• `/assign_gm` / `/assign_im` - Give roles
• `/remove_gm` / `/remove_im` - Remove roles
• `/config_game` - Configure game settings
• `/assign_role` - Assign alignment and role
• `/randomize_alignments` - Randomly assign alignments
• `/assign_identities` - Randomly assign anon identities
• `/assign_identity` - Manually assign anon identity
• `/remove_player` - Remove player (before start)
• `/start_game` - Start the game

**🎮 GM/IM Game Commands:**
• `/end_phase` - Manually end current phase
• `/clear_votes` - Clear all votes
• `/force_kill` - Force eliminate a player
• `/revive` - Revive an eliminated player
• `/end_game` - End and archive the game
• `/player_list` - View all players with alignments/roles
"""
        
        # Player Commands
        player_commands = """
**👤 Player Commands:**
• `/join_game` - Join the current game
• `/leave_game` - Leave before game starts
• `/spectate_game` - Spectate the active game
• `/player_list` - View all players
• `/vote_count` - See current vote tallies
• `/time_remaining` - Check phase time
• `/command_list` - Show this list

**💬 Text Commands (in private thread):**
"""
        
        # Build text command list based on game state
        if game and game.anon_mode:
            player_commands += "• `!say [message]` - Post anonymously\n"
        
        vote_cmd = "• `!vote [player]`"
        if game and game.allow_no_elimination:
            vote_cmd += " or `!vote none`"
        vote_cmd += " - Vote during day\n"
        player_commands += vote_cmd
        player_commands += "• `!unvote` - Remove your current vote\n"
        
        # Elim commands
        if game and interaction.user.id in game.players:
            if game.players[interaction.user.id].alignment == 'elims':
                player_commands += "• `!kill [player]` or `!kill none` - Night kill (night phase)\n"
        
        # Utility
        utility_commands = """
**🔧 Utility Commands:**
• `/ping` - Test if bot is responding
• `/test` - Test your permissions
"""
        
        if is_gm:
            response = gm_commands + player_commands + utility_commands
        else:
            response = player_commands + utility_commands
        
        await interaction.response.send_message(response, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(UtilityCog(bot))