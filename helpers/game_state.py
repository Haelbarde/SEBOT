"""Game state management and data structures."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from data.identities import ANON_IDENTITIES


# Global games storage (indexed by guild_id)
games: dict[int, 'Game'] = {}


@dataclass
class Player:
    """Represents a player in the game."""
    user_id: int
    username: str
    display_name: str
    anon_identity: Optional[str] = None
    private_channel_id: Optional[int] = None
    alignment: Optional[str] = None  # 'village' or 'elims'
    role: Optional[str] = None
    is_alive: bool = True
    character_name: Optional[str] = None


@dataclass
class Game:
    """Represents an elimination game instance."""
    guild_id: int
    gm_ids: list[int] = field(default_factory=list)
    players: dict[int, Player] = field(default_factory=dict)
    spectators: list[int] = field(default_factory=list)
    
    # Game state
    status: str = 'setup'  # 'setup', 'active', 'ended'
    phase: str = 'Day 0'   # 'Day' or 'Night'
    day_number: int = 0
    phase_end_time: Optional[datetime] = None
    warnings_sent: set = field(default_factory=set)
    
    # Configuration
    anon_mode: bool = False
    day_length_minutes: int = 2880  # 48 hours
    night_length_minutes: int = 1440  # 24 hours
    win_condition: str = 'parity'  # 'parity' or 'overparity'
    auto_phase_transition: bool = True
    allow_no_elimination: bool = True
    min_votes_to_eliminate: int = 0  # 0=plurality, -1=force RNG if 0 votes
    
    # Channel IDs
    game_channel_id: Optional[int] = None
    dead_spec_thread_id: Optional[int] = None
    elim_discussion_thread_id: Optional[int] = None
    
    # Game metadata
    game_tag: Optional[str] = None
    flavor_name: Optional[str] = None
    
    # Game data
    votes: dict[int, dict[int, int | str]] = field(default_factory=dict)  # day_num -> {voter_id: target_id}
    eliminated: list[int] = field(default_factory=list)
    night_actions: dict[int, dict] = field(default_factory=dict)
    available_identities: list[str] = field(default_factory=lambda: list(ANON_IDENTITIES.keys()))
    
    def get_player_display_name(self, user_id: int) -> str:
        """Get the appropriate display name based on game mode."""
        player = self.players.get(user_id)
        if not player:
            return "Unknown"
        
        if self.anon_mode and player.anon_identity:
            return player.anon_identity
        return player.display_name
    
    def get_alive_players(self) -> list[Player]:
        """Get all living players."""
        return [p for p in self.players.values() if p.is_alive]
    
    def get_alive_count(self) -> tuple[int, int]:
        """Get count of alive village and elim players."""
        alive = self.get_alive_players()
        village = sum(1 for p in alive if p.alignment == 'village')
        elims = sum(1 for p in alive if p.alignment == 'elims')
        return village, elims
    
    def check_win_condition(self) -> Optional[str]:
        """Check if either side has won. Returns 'village', 'elims', or None."""
        village_count, elim_count = self.get_alive_count()
        
        # Village wins if all elims dead
        if elim_count == 0:
            return 'village'
        
        # Elims win at parity or overparity
        if self.win_condition == 'parity':
            if elim_count >= village_count:
                return 'elims'
        else:  # overparity
            if elim_count > village_count:
                return 'elims'
        
        return None
    
    def get_day_votes(self) -> dict[int, int | str]:
        """Get votes for current day."""
        return self.votes.get(self.day_number, {})
    
    def tally_votes(self) -> dict[int | str, list[int]]:
        """Tally votes for current day. Returns {target_id: [voter_ids]}."""
        day_votes = self.get_day_votes()
        tally = {}
        for voter_id, target_id in day_votes.items():
            if target_id not in tally:
                tally[target_id] = []
            tally[target_id].append(voter_id)
        return tally


def get_game(guild_id: int) -> Optional[Game]:
    """Get the game for a guild, or None if no game exists."""
    return games.get(guild_id)


def create_game(guild_id: int, creator_id: int) -> Game:
    """Create a new game for a guild."""
    game = Game(guild_id=guild_id, gm_ids=[creator_id])
    games[guild_id] = game
    return game


def delete_game(guild_id: int) -> bool:
    """Delete a game. Returns True if game existed."""
    if guild_id in games:
        del games[guild_id]
        return True
    return False