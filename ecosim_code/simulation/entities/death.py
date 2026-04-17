def mark_dead(entity, cause: str, grid, tod: float, is_night: bool = False) -> None:
    """Marque une entité comme morte et renseigne ses métadonnées de décès."""
    cx, cy = int(entity.x), int(entity.y)
    on_water = (0 <= cx < grid.width and 0 <= cy < grid.height
                and grid.soil_type[cy, cx] == "water")
    entity.alive = False
    entity.death_cause = cause
    entity.death_tod = tod
    entity.death_is_night = is_night
    entity.death_on_water = on_water
    entity.death_state = getattr(entity, "state", None)
    entity.state = "dead"
