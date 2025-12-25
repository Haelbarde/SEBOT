"""Gameplay commands - voting, kills, phase management."""

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import random

from helpers.game_state import games, get_game, delete_game
from helpers.permissions import is_gm_or_im, gm_only, require_game, get_gm_role, get_im_role
from helpers.matching import parse_vote_target, parse_kill_target
from helpers.anonymous import get_or_create_webhook, announce_vote
from helpers.utils import (
    format_time_remaining, update_game_channel_permissions, 
    archive_game, add_user_to_thread_safe
)
from data.identities import ANON_IDENTITIES


class GameplayCog(commands.Cog):
    """Commands for active gameplay."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.phase_timer_checker.start()
    
    def cog_unload(self):
        self.phase_timer_checker.cancel()
    
    # ===== PHASE TIMER =====
    
    @tasks.loop(seconds=10)
    async def phase_timer_checker(self):
        """Check all active games for phase transitions and warnings."""
        for guild_id, game in list(games.items()):
            if game.status != 'active' or not game.phase_end_time:
                continue
            
            if not game.auto_phase_transition:
                continue
            
            now = datetime.now()
            time_remaining = (game.phase_end_time - now).total_seconds()
            
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            
            game_channel = guild.get_channel(game.game_channel_id)
            if not game_channel:
                continue
            
            # Send warnings
            warnings = game.warnings_sent
            
            warning_thresholds = [
                (295, 305, '5min', "⏰ **5 minutes remaining** in this phase!"),
                (115, 125, '2min', "⏰ **2 minutes remaining** in this phase!"),
                (55, 65, '1min', "⏰ **1 minute remaining** in this phase!"),
                (5, 15, '10sec', "⏰ **10 seconds remaining** in this phase!")
            ]
            
            for min_time, max_time, key, message in warning_thresholds:
                if min_time <= time_remaining < max_time and key not in warnings:
                    await self._send_phase_warnings(guild, game, game_channel, message, key)
            
            # Time's up
            if time_remaining <= 0:
                await self._auto_end_phase(guild, game)
    
    async def _send_phase_warnings(self, guild, game, game_channel, message, key):
        """Send warning messages to relevant channels."""
        await game_channel.send(message)
        
        if game.phase == 'Night':
            # Warn elims about pending kill
            night_actions = game.night_actions.get(game.day_number, {})
            if not night_actions.get('elim_kill') and game.elim_discussion_thread_id:
                elim_thread = guild.get_thread(game.elim_discussion_thread_id)
                if elim_thread:
                    await elim_thread.send(
                        f"{message}\n⚠️ **Reminder:** You haven't submitted a kill yet! "
                        f"Use `!kill [player]` or `!kill none`"
                    )
        
        elif game.phase == 'Day' and game.anon_mode:
            # Warn players who haven't voted
            day_votes = game.get_day_votes()
            for user_id, player in game.players.items():
                if player.is_alive and user_id not in day_votes:
                    if player.private_channel_id:
                        private_thread = guild.get_thread(player.private_channel_id)
                        if private_thread:
                            await private_thread.send(
                                f"{message}\n⚠️ **Reminder:** You haven't voted yet! "
                                f"Use `!vote [player]`{' or `!vote none`' if game.allow_no_elimination else ''}"
                            )
        
        game.warnings_sent.add(key)
    
    async def _auto_end_phase(self, guild, game):
        """Automatically end the current phase."""
        game_channel = guild.get_channel(game.game_channel_id)
        dead_spec_thread = None
        if game.dead_spec_thread_id:
            dead_spec_thread = guild.get_thread(game.dead_spec_thread_id)
        
        try:
            if game.phase == 'Day':
                await self._process_day_end(guild, game, game_channel, dead_spec_thread)
            else:
                await self._process_night_end(guild, game, game_channel, dead_spec_thread)
        except Exception as e:
            print(f"Error in auto_end_phase: {e}")
            import traceback
            traceback.print_exc()
            if game_channel:
                await game_channel.send("❌ Error processing automatic phase end. Please contact a GM.")
    
    def _format_final_vote_count(self, game) -> str:
        """Format a complete vote record for end of day."""
        day_votes = game.get_day_votes()
        
        # Group votes by target
        vote_groups = {}
        for voter_id, target_id in day_votes.items():
            if target_id not in vote_groups:
                vote_groups[target_id] = []
            vote_groups[target_id].append(voter_id)
        
        # Find players who didn't vote (abstained)
        alive_players = [uid for uid, p in game.players.items() if p.is_alive]
        abstainers = [uid for uid in alive_players if uid not in day_votes]
        
        # Build the output
        lines = ["📊 **Final Vote Count**"]
        
        # Sort by vote count (descending)
        sorted_targets = sorted(vote_groups.items(), key=lambda x: len(x[1]), reverse=True)
        
        for target_id, voter_ids in sorted_targets:
            # Get target name
            if target_id == 'vote_none':
                target_name = "No Elimination"
            else:
                target_name = game.get_player_display_name(target_id)
            
            # Get voter names
            voter_names = [game.get_player_display_name(vid) for vid in voter_ids]
            lines.append(f"**{target_name}** ({len(voter_ids)}): {', '.join(voter_names)}")
        
        # Add abstainers
        if abstainers:
            abstainer_names = [game.get_player_display_name(uid) for uid in abstainers]
            lines.append(f"**No Vote** ({len(abstainers)}): {', '.join(abstainer_names)}")
        
        return "\n".join(lines)
    
    async def _process_day_end(self, guild, game, game_channel, dead_spec_thread):
        """Process end of day phase - handle elimination."""
        day_votes = game.get_day_votes()
        
        # Generate vote count before elimination (while all players still "alive" for display purposes)
        vote_count_msg = self._format_final_vote_count(game)
        
        elimination_msg = await self._resolve_elimination(guild, game, day_votes, dead_spec_thread)
        
        if game_channel:
            await game_channel.send(
                f"☀️ **Day {game.day_number} has ended.**\n\n"
                f"{vote_count_msg}\n\n"
                f"{elimination_msg}\n\n"
                f"🌙 **Night {game.day_number} begins...**"
            )
        
        await update_game_channel_permissions(guild, game)
        
        # Check win
        winner = game.check_win_condition()
        if winner:
            await self._handle_game_over(guild, game, game_channel, winner)
            return
        
        # Transition to night
        game.phase = 'Night'
        game.phase_end_time = datetime.now() + timedelta(minutes=game.night_length_minutes)
        game.warnings_sent = set()
    
    async def _resolve_elimination(self, guild, game, day_votes, dead_spec_thread):
        """Resolve day phase elimination. Returns announcement message."""
        min_votes = game.min_votes_to_eliminate
        
        if not day_votes:
            if min_votes == -1:
                return await self._random_elimination(guild, game, dead_spec_thread)
            return "**No votes were cast. No one was eliminated.**"
        
        # Tally votes
        vote_tally = {}
        for voter_id, target_id in day_votes.items():
            vote_tally[target_id] = vote_tally.get(target_id, 0) + 1
        
        max_votes = max(vote_tally.values())
        top_voted = [tid for tid, count in vote_tally.items() if count == max_votes]
        
        # Check minimum threshold
        if min_votes > 0 and max_votes < min_votes:
            return (
                f"**No one was eliminated today.** "
                f"(Minimum {min_votes} vote{'s' if min_votes != 1 else ''} required, only {max_votes} received)"
            )
        
        # Vote none in top?
        if 'vote_none' in top_voted:
            return "**No one was eliminated today.** (Vote for no elimination won)"
        
        # Get player votes only
        player_votes = [tid for tid in top_voted if tid != 'vote_none']
        
        if not player_votes:
            return "**No one was eliminated today.**"
        
        # Random tiebreaker
        eliminated_id = random.choice(player_votes)
        return await self._eliminate_player(guild, game, eliminated_id, dead_spec_thread)
    
    async def _random_elimination(self, guild, game, dead_spec_thread):
        """Perform random elimination when no votes cast and min_votes=-1."""
        alive_players = [uid for uid, p in game.players.items() if p.is_alive]
        if not alive_players:
            return "**No votes were cast. No one was eliminated.**"
        
        eliminated_id = random.choice(alive_players)
        msg = await self._eliminate_player(guild, game, eliminated_id, dead_spec_thread)
        return msg.replace("has been eliminated!", "has been randomly eliminated!** (No votes were cast)")
    
    async def _eliminate_player(self, guild, game, user_id, dead_spec_thread):
        """Eliminate a player and return announcement message."""
        player = game.players[user_id]
        player.is_alive = False
        game.eliminated.append(user_id)
        
        player_name = game.get_player_display_name(user_id)
        
        # Add to dead/spec thread
        if dead_spec_thread:
            member = guild.get_member(user_id)
            if member:
                await add_user_to_thread_safe(dead_spec_thread, member)
        
        return (
            f"💀 **{player_name} has been eliminated!**\n"
            f"They were: **{player.alignment.title()} - {player.role or 'Vanilla'}**"
        )
    
    async def _process_night_end(self, guild, game, game_channel, dead_spec_thread):
        """Process end of night phase - handle kills."""
        night_actions = game.night_actions.get(game.day_number, {})
        killed_id = night_actions.get('elim_kill')
        
        # Advance to next day
        game.day_number += 1
        game.phase = 'Day'
        game.phase_end_time = datetime.now() + timedelta(minutes=game.day_length_minutes)
        game.warnings_sent = set()
        
        # Process kill
        if killed_id and killed_id != 'kill_none' and killed_id in game.players:
            player = game.players[killed_id]
            player.is_alive = False
            game.eliminated.append(killed_id)
            
            player_name = game.get_player_display_name(killed_id)
            kill_msg = (
                f"💀 **{player_name} was killed during the night!**\n"
                f"They were: **{player.alignment.title()} - {player.role or 'Vanilla'}**"
            )
            
            if dead_spec_thread:
                member = guild.get_member(killed_id)
                if member:
                    await add_user_to_thread_safe(dead_spec_thread, member)
        else:
            kill_msg = "🛡️ **No one died during the night.**"
        
        if game_channel:
            await game_channel.send(
                f"☀️ **Day {game.day_number} begins!**\n\n"
                f"{kill_msg}\n\n"
                f"Discussion and voting are now open."
            )
        
        await update_game_channel_permissions(guild, game)
        
        # Check win
        winner = game.check_win_condition()
        if winner:
            await self._handle_game_over(guild, game, game_channel, winner)
    
    async def _handle_game_over(self, guild, game, game_channel, winner):
        """Handle game ending."""
        if game_channel:
            if winner == 'last_standing':
                # Find the sole survivor
                survivors = [p for p in game.players.values() if p.is_alive]
                if survivors:
                    survivor = survivors[0]
                    winner_name = game.get_player_display_name(survivor.user_id)
                    await game_channel.send(
                        f"🎊 **GAME OVER!**\n"
                        f"**{winner_name}** is the last one standing and wins!\n\n"
                        f"Archiving game channels..."
                    )
                else:
                    await game_channel.send(
                        f"🎊 **GAME OVER!**\n"
                        f"No one survived!\n\n"
                        f"Archiving game channels..."
                    )
            else:
                await game_channel.send(
                    f"🎊 **GAME OVER!**\n"
                    f"**{winner.title()} has won!**\n\n"
                    f"Archiving game channels..."
                )
        
        game.status = 'ended'
        await archive_game(guild, game)
        delete_game(guild.id)
    
    # ===== SLASH COMMANDS =====
    
    @app_commands.command(name="time_remaining", description="Check how much time is left in the current phase")
    @require_game(status='active')
    async def time_remaining(self, interaction: discord.Interaction):
        """Show time remaining in current phase."""
        game = get_game(interaction.guild_id)
        
        time_left = format_time_remaining(game.phase_end_time)
        auto_status = "🤖 Automatic" if game.auto_phase_transition else "👤 Manual"
        
        await interaction.response.send_message(
            f"⏰ **Current Phase:** {game.phase} {game.day_number}\n"
            f"**Time Remaining:** {time_left}\n"
            f"**Phase Transitions:** {auto_status}"
        )
    
    @app_commands.command(name="vote_count", description="Show current vote tallies")
    @require_game(status='active')
    async def vote_count(self, interaction: discord.Interaction):
        """Display current vote count."""
        game = get_game(interaction.guild_id)
        
        if game.phase != 'Day':
            await interaction.response.send_message("❌ No voting during night phase!", ephemeral=True)
            return
        
        day_votes = game.get_day_votes()
        
        if not day_votes:
            await interaction.response.send_message("📊 No votes cast yet today.")
            return
        
        # Tally
        tally = game.tally_votes()
        
        vote_lines = []
        for target_id, voter_ids in sorted(tally.items(), key=lambda x: len(x[1]), reverse=True):
            if target_id == 'vote_none':
                target_name = "No One"
            else:
                target_name = game.get_player_display_name(target_id)
            
            voter_names = [game.get_player_display_name(vid) for vid in voter_ids]
            vote_lines.append(f"**{target_name}** ({len(voter_ids)}): {', '.join(voter_names)}")
        
        alive_count = len([p for p in game.players.values() if p.is_alive])
        
        await interaction.response.send_message(
            f"📊 **Vote Count - Day {game.day_number}**\n"
            f"Time remaining: {format_time_remaining(game.phase_end_time)}\n\n"
            f"{chr(10).join(vote_lines)}\n\n"
            f"Total votes: {len(day_votes)}/{alive_count}"
        )
    
    @app_commands.command(name="clear_votes", description="[GM/IM] Clear all votes for current day")
    @gm_only()
    @require_game(status='active')
    async def clear_votes(self, interaction: discord.Interaction):
        """Clear all votes."""
        game = get_game(interaction.guild_id)
        
        if game.day_number in game.votes:
            game.votes[game.day_number] = {}
        
        await interaction.response.send_message("✅ All votes cleared!")
    
    @app_commands.command(name="end_phase", description="[GM/IM] Manually end the current phase")
    @gm_only()
    @require_game(status='active')
    async def end_phase(self, interaction: discord.Interaction):
        """End current phase and transition to next."""
        game = get_game(interaction.guild_id)
        
        await interaction.response.defer()
        await self._auto_end_phase(interaction.guild, game)
        await interaction.followup.send("✅ Phase manually ended.")


async def setup(bot: commands.Bot):
    await bot.add_cog(GameplayCog(bot))