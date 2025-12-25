"""Admin commands - GM/IM management, force actions, game control."""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta

from helpers.game_state import get_game, delete_game
from helpers.permissions import (
    gm_only, require_game, manage_discord_role,
    get_gm_role, get_im_role, GM_ROLE, IM_ROLE
)
from helpers.utils import (
    update_game_channel_permissions, archive_game, 
    add_user_to_thread_safe, format_time_remaining
)


class AdminCog(commands.Cog):
    """Admin commands for GMs and IMs."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # ===== ROLE MANAGEMENT =====
    
    @app_commands.command(name="assign_gm", description="[GM/IM] Give a user the GM role")
    @app_commands.describe(user="The user to make a GM")
    @gm_only()
    async def assign_gm(self, interaction: discord.Interaction, user: discord.Member):
        """Assign GM role to a user."""
        await manage_discord_role(interaction, user, GM_ROLE, 'add')
    
    @app_commands.command(name="assign_im", description="[GM/IM] Give a user the IM role")
    @app_commands.describe(user="The user to make an IM")
    @gm_only()
    async def assign_im(self, interaction: discord.Interaction, user: discord.Member):
        """Assign IM role to a user."""
        await manage_discord_role(interaction, user, IM_ROLE, 'add')
    
    @app_commands.command(name="remove_gm", description="[GM/IM] Remove the GM role from a user")
    @app_commands.describe(user="The user to remove GM role from")
    @gm_only()
    async def remove_gm(self, interaction: discord.Interaction, user: discord.Member):
        """Remove GM role from a user."""
        await manage_discord_role(interaction, user, GM_ROLE, 'remove')
    
    @app_commands.command(name="remove_im", description="[GM/IM] Remove the IM role from a user")
    @app_commands.describe(user="The user to remove IM role from")
    @gm_only()
    async def remove_im(self, interaction: discord.Interaction, user: discord.Member):
        """Remove IM role from a user."""
        await manage_discord_role(interaction, user, IM_ROLE, 'remove')
    
    # ===== FORCE ACTIONS =====
    
    @app_commands.command(name="force_kill", description="[GM/IM] Force eliminate a player during the game")
    @app_commands.describe(player="The player to eliminate")
    @gm_only()
    @require_game(status='active')
    async def force_kill(self, interaction: discord.Interaction, player: discord.Member):
        """Forcibly eliminate a player."""
        game = get_game(interaction.guild_id)
        
        if player.id not in game.players:
            await interaction.response.send_message(
                f"❌ {player.mention} is not in the game.",
                ephemeral=True
            )
            return
        
        if not game.players[player.id].is_alive:
            await interaction.response.send_message(
                f"❌ {player.mention} is already dead!",
                ephemeral=True
            )
            return
        
        # Kill the player
        game.players[player.id].is_alive = False
        game.eliminated.append(player.id)
        
        # Add to dead/spec thread
        if game.dead_spec_thread_id:
            dead_spec_thread = interaction.guild.get_thread(game.dead_spec_thread_id)
            if dead_spec_thread:
                await add_user_to_thread_safe(dead_spec_thread, player)
        
        await update_game_channel_permissions(interaction.guild, game)
        
        player_name = game.get_player_display_name(player.id)
        
        await interaction.response.send_message(
            f"⚰️ **{player_name}** has been force eliminated by the GM."
        )
        
        # Check win
        winner = game.check_win_condition()
        if winner:
            game_channel = interaction.guild.get_channel(game.game_channel_id)
            if game_channel:
                await game_channel.send(
                    f"🎊 **GAME OVER!**\n"
                    f"**{winner.title()} has won!**\n\n"
                    f"Archiving game channels..."
                )
            
            game.status = 'ended'
            await archive_game(interaction.guild, game)
            delete_game(interaction.guild_id)
    
    @app_commands.command(name="revive", description="[GM/IM] Revive an eliminated player")
    @app_commands.describe(player="The player to revive")
    @gm_only()
    @require_game(status='active')
    async def revive(self, interaction: discord.Interaction, player: discord.Member):
        """Revive a dead player."""
        game = get_game(interaction.guild_id)
        
        if player.id not in game.players:
            await interaction.response.send_message(
                f"❌ {player.mention} is not in the game.",
                ephemeral=True
            )
            return
        
        if game.players[player.id].is_alive:
            await interaction.response.send_message(
                f"❌ {player.mention} is already alive!",
                ephemeral=True
            )
            return
        
        # Revive
        game.players[player.id].is_alive = True
        if player.id in game.eliminated:
            game.eliminated.remove(player.id)
        
        await update_game_channel_permissions(interaction.guild, game)
        
        player_name = game.get_player_display_name(player.id)
        
        await interaction.response.send_message(
            f"✨ **{player_name}** has been revived by the GM!"
        )
    
    # ===== GAME CONTROL =====
    
    @app_commands.command(name="start_game", description="[GM/IM] Start the game and create private threads")
    @gm_only()
    @require_game(status='setup')
    async def start_game(self, interaction: discord.Interaction):
        """Start the game - creates threads and locks settings."""
        game = get_game(interaction.guild_id)
        
        if len(game.players) < 3:
            await interaction.response.send_message(
                "❌ Need at least 3 players to start the game!",
                ephemeral=True
            )
            return
        
        if not game.game_channel_id:
            await interaction.response.send_message(
                "⚠️ No game channel set! Use `/create_game_channel` or `/set_game_channel` first.",
                ephemeral=True
            )
            return
        
        # Check alignments
        unassigned = [p.display_name for p in game.players.values() if not p.alignment]
        if unassigned:
            await interaction.response.send_message(
                f"⚠️ **Players without alignments:** {', '.join(unassigned)}\n"
                f"Use `/assign_role` or `/randomize_alignments` first!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        guild = interaction.guild
        game_channel = guild.get_channel(game.game_channel_id)
        
        if not game_channel:
            await interaction.followup.send("❌ Game channel not found!")
            return
        
        gm_role = get_gm_role(guild)
        im_role = get_im_role(guild)
        
        # Create dead/spec thread
        thread_prefix = game.game_tag.lower() if game.game_tag else ""
        dead_spec_name = f"💀-{thread_prefix}-dead-spec" if thread_prefix else "💀-dead-spec"
        dead_spec_thread = await game_channel.create_thread(
            name=dead_spec_name,
            type=discord.ChannelType.private_thread,
            invitable=False
        )
        game.dead_spec_thread_id = dead_spec_thread.id
        
        # Add GM/IM to dead/spec
        for role in [gm_role, im_role]:
            if role:
                for member in role.members:
                    await add_user_to_thread_safe(dead_spec_thread, member)
        
        # Add spectators
        for spectator_id in game.spectators:
            spectator = guild.get_member(spectator_id)
            if spectator:
                await add_user_to_thread_safe(dead_spec_thread, spectator)
        
        await dead_spec_thread.send(
            f"💀 **Dead/Spectator Thread**\n"
            f"This thread is for dead players and spectators.\n"
            f"Players will gain access here when eliminated."
        )
        
        # Create elim discussion thread
        elim_members = [
            guild.get_member(uid) 
            for uid, p in game.players.items() 
            if p.alignment == 'elims'
        ]
        
        if elim_members:
            elim_thread_name = f"🔴-{thread_prefix}-elims" if thread_prefix else "🔴-elim-discussion"
            elim_thread = await game_channel.create_thread(
                name=elim_thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False
            )
            game.elim_discussion_thread_id = elim_thread.id
            
            for member in elim_members:
                if member:
                    await add_user_to_thread_safe(elim_thread, member)
            
            for role in [gm_role, im_role]:
                if role:
                    for member in role.members:
                        await add_user_to_thread_safe(elim_thread, member)
            
            await elim_thread.send(
                f"🔴 **Elim Discussion Thread**\n"
                f"This is your private space to coordinate kills and strategy.\n"
                f"**Elims:** {', '.join(m.mention for m in elim_members if m)}\n\n"
                f"Use `!kill [player]` or `!kill none` during night phases to submit your kill."
            )
        
        # Create private threads for each player
        created_threads = []
        for user_id, player in game.players.items():
            member = guild.get_member(user_id)
            if not member:
                continue
            
            thread_name = f"{thread_prefix}-{member.name}-gm-pm" if thread_prefix else f"{member.name}-gm-pm"
            private_thread = await game_channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False
            )
            
            player.private_channel_id = private_thread.id
            created_threads.append(private_thread.mention)
            
            await add_user_to_thread_safe(private_thread, member)
            
            for role in [gm_role, im_role]:
                if role:
                    for gm_member in role.members:
                        await add_user_to_thread_safe(private_thread, gm_member)
            
            # Build welcome message
            welcome_parts = [f"Welcome {member.mention}! This is your private thread with the GM/IM."]
            
            if player.alignment:
                welcome_parts.append(
                    f"\n\n🎭 **Your Role:**\n"
                    f"**Alignment:** {player.alignment.title()}\n"
                    f"**Role:** {player.role or 'Vanilla'}"
                )
            
            if game.anon_mode and player.anon_identity:
                welcome_parts.append(f"\n\n🎭 **Your Anonymous Identity:** {player.anon_identity}")
            
            if player.alignment == 'elims' and game.elim_discussion_thread_id:
                elim_thread = guild.get_thread(game.elim_discussion_thread_id)
                if elim_thread:
                    welcome_parts.append(f"\n\n🔴 **Elim Discussion:** {elim_thread.mention}")
            
            # Commands
            vote_cmd = "`!vote [player]`"
            if game.allow_no_elimination:
                vote_cmd += " or `!vote none`"
            
            if game.anon_mode:
                welcome_parts.append(
                    f"\n\n**Commands (use in this thread):**\n"
                    f"• `!say [message]` - Post anonymously\n"
                    f"• {vote_cmd} - Vote during day\n"
                    f"• `!unvote` - Remove your current vote\n"
                    f"• `/player_list` - See living players\n"
                    f"• `/vote_count` - See current votes\n"
                    f"• `/time_remaining` - Check phase timer\n"
                    f"• `/command_list` - See all commands"
                )
            else:
                welcome_parts.append(
                    f"\n\n**Commands:**\n"
                    f"• {vote_cmd} - Vote during day\n"
                    f"• `!unvote` - Remove your current vote\n"
                    f"• `/player_list` - See living players\n"
                    f"• `/vote_count` - See current votes\n"
                    f"• `/time_remaining` - Check phase timer\n"
                    f"• `/command_list` - See all commands"
                )
            
            await private_thread.send("".join(welcome_parts))
        
        # Update permissions
        await update_game_channel_permissions(guild, game)
        
        # Start the game
        game.status = 'active'
        game.phase = 'Day'
        game.day_number = 1
        game.phase_end_time = datetime.now() + timedelta(minutes=game.day_length_minutes)
        
        # Announce
        if game_channel:
            game_name = f"{game.game_tag} - {game.flavor_name}" if game.game_tag and game.flavor_name else "Elimination Game"
            village_count, elim_count = game.get_alive_count()
            
            await game_channel.send(
                f"🎮 **{game_name} has begun!**\n"
                f"**Phase:** Day 1\n"
                f"**Players:** {len(game.players)} ({village_count} Village, {elim_count} Elim{'s' if elim_count != 1 else ''})\n"
                f"**Mode:** {'Anonymous' if game.anon_mode else 'Standard'}\n"
                f"**Phase ends:** {format_time_remaining(game.phase_end_time)}\n\n"
                f"Good luck!"
            )
        
        await interaction.followup.send(
            f"✅ **Game Started!**\n"
            f"Created {len(created_threads)} private threads.\n"
            + (f"Created elim discussion thread.\n" if game.elim_discussion_thread_id else "")
            + f"Created dead/spec thread.\n"
            + f"All threads are under {game_channel.mention}!"
        )
    
    @app_commands.command(name="end_game", description="[GM/IM] End the current game and archive channels")
    @gm_only()
    @require_game()
    async def end_game(self, interaction: discord.Interaction):
        """End and cleanup the current game."""
        game = get_game(interaction.guild_id)
        
        await interaction.response.defer()
        
        archived_count, archive_name = await archive_game(interaction.guild, game)
        delete_game(interaction.guild_id)
        
        await interaction.followup.send(
            f"✅ **Game Ended!**\n"
            f"Archived {archived_count} channel(s) to **{archive_name}**\n"
            f"All threads are now public and read-only for posterity."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))