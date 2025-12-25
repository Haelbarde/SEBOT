"""Player name matching utilities for voting and kill targeting."""

from typing import Optional
from helpers.game_state import Game


class MatchResult:
    """Result of a player matching attempt."""
    def __init__(
        self,
        success: bool,
        target_id: Optional[int | str] = None,
        target_display: Optional[str] = None,
        error: Optional[str] = None
    ):
        self.success = success
        self.target_id = target_id
        self.target_display = target_display
        self.error = error


def find_player_by_name(
    game: Game,
    target_name: str,
    alive_only: bool = True
) -> MatchResult:
    """
    Find a player by name with flexible matching.
    
    Matching priority:
    1. Exact match on full name
    2. Exact match on color (anon) or display name
    3. Exact match on animal (anon)
    4. Partial match (4+ chars) on any component
    
    Args:
        game: The game instance
        target_name: The name to search for (case-insensitive)
        alive_only: If True, only match living players
        
    Returns:
        MatchResult with success status and either target info or error message
    """
    target_name = target_name.strip().lower()
    matches = []
    
    for uid, player in game.players.items():
        # Skip dead players if alive_only
        if alive_only and not player.is_alive:
            continue
        
        if game.anon_mode:
            # Anonymous mode: match against anon identity
            if not player.anon_identity:
                continue
            
            anon_full = player.anon_identity.lower()
            anon_parts = player.anon_identity.split()
            
            if len(anon_parts) == 2:
                color = anon_parts[0].lower()
                animal = anon_parts[1].lower()
                
                # Exact match on full name
                if anon_full == target_name:
                    matches.append((uid, player.anon_identity, 'exact'))
                # Exact match on color only
                elif color == target_name:
                    matches.append((uid, player.anon_identity, 'color'))
                # Exact match on animal only
                elif animal == target_name:
                    matches.append((uid, player.anon_identity, 'animal'))
                # Partial match (4+ characters)
                elif len(target_name) >= 4:
                    if target_name in anon_full:
                        matches.append((uid, player.anon_identity, 'partial'))
                    elif target_name in color:
                        matches.append((uid, player.anon_identity, 'partial_color'))
                    elif target_name in animal:
                        matches.append((uid, player.anon_identity, 'partial_animal'))
        else:
            # Non-anon mode: match display name or username
            check_name = player.display_name.lower()
            check_username = player.username.lower()
            
            # Exact match
            if check_name == target_name or check_username == target_name:
                matches.append((uid, player.display_name, 'exact'))
            # Partial match (4+ characters)
            elif len(target_name) >= 4:
                if target_name in check_name or target_name in check_username:
                    matches.append((uid, player.display_name, 'partial'))
    
    # Process matches
    if len(matches) == 0:
        return MatchResult(
            success=False,
            error=f"❌ Could not find {'alive ' if alive_only else ''}player matching: {target_name}"
        )
    
    if len(matches) == 1:
        return MatchResult(
            success=True,
            target_id=matches[0][0],
            target_display=matches[0][1]
        )
    
    # Multiple matches - prioritize exact matches
    exact_matches = [m for m in matches if m[2] in ['exact', 'color', 'animal']]
    
    if len(exact_matches) == 1:
        return MatchResult(
            success=True,
            target_id=exact_matches[0][0],
            target_display=exact_matches[0][1]
        )
    
    if len(exact_matches) > 1:
        match_names = [m[1] for m in exact_matches]
        return MatchResult(
            success=False,
            error=f"❌ Multiple players match '{target_name}': {', '.join(match_names)}\nPlease be more specific."
        )
    
    # Multiple partial matches
    match_names = [m[1] for m in matches]
    return MatchResult(
        success=False,
        error=f"❌ Multiple players match '{target_name}': {', '.join(match_names)}\nPlease be more specific."
    )


def parse_vote_target(game: Game, target_str: str) -> MatchResult:
    """
    Parse a vote target string.
    Handles special 'none' voting and player matching.
    
    Returns MatchResult with target_id being either:
    - 'vote_none' for no elimination vote
    - player user_id for player vote
    """
    target_name = target_str.strip().lower()
    
    # Handle "vote none"
    if target_name in ['none', 'no one', 'no elimination', 'no lynch']:
        if not game.allow_no_elimination:
            return MatchResult(
                success=False,
                error="❌ Voting for no elimination is not allowed in this game!"
            )
        return MatchResult(
            success=True,
            target_id='vote_none',
            target_display="No One"
        )
    
    return find_player_by_name(game, target_name)


def parse_kill_target(game: Game, target_str: str) -> MatchResult:
    """
    Parse a kill target string.
    Handles special 'none' kill and player matching.
    
    Returns MatchResult with target_id being either:
    - 'kill_none' for no kill
    - player user_id for player kill
    """
    target_name = target_str.strip().lower()
    
    # Handle "kill none"
    if target_name in ['none', 'no one', 'no kill']:
        return MatchResult(
            success=True,
            target_id='kill_none',
            target_display="No One"
        )
    
    return find_player_by_name(game, target_name)