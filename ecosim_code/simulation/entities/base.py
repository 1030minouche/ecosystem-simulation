from dataclasses import dataclass
from entities.species import Species


@dataclass
class Entity:
    """Classe de base commune aux plantes et aux individus animaux."""
    species: Species
    x: float
    y: float
    age: int = 0
    energy: float = 100.0
    alive: bool = True
    reproduction_cooldown: int = 0
    state: str = "idle"
