from dataclasses import dataclass, field


@dataclass
class SearchConfig:
    """Search pattern configuration. All units in mm."""
    min_z: float = 0.0       # mm (Z_MIN)
    max_z: float = 20.0      # mm (Z_MAX)
    start_z: float = 10.0    # mm (starting position)
    step_size: float = 1.0   # mm per step
    initial_direction: int = field(default=1)  # +1 for up, -1 for down


class SearchController:
    """
    Step-based search pattern.
    Outputs relative Z delta in mm for each step.
    Waits for motion completion before returning next step.
    Pattern: start_z → max_z → min_z → max_z (repeating)
    """

    def __init__(self, config: SearchConfig):
        self._config = config
        self._current_z: float = config.start_z
        self._direction: int = config.initial_direction
        self._step_size: float = config.step_size

    def reset(self) -> None:
        self._current_z = self._config.start_z
        self._direction = self._config.initial_direction

    def sync_to_position(self, z_mm: float) -> None:
        """
        Sync the SearchController's internal state to a known Z position.
        Useful when the actual Z position differs from the controller's internal state.
        
        Args:
            z_mm: The actual current Z position in mm
        """
        # Clamp to valid range
        z_mm = max(self._config.min_z, min(self._config.max_z, z_mm))
        self._current_z = z_mm
        # Set direction based on position (if near max, go down; if near min, go up)
        if z_mm >= (self._config.max_z + self._config.min_z) / 2:
            self._direction = -1
        else:
            self._direction = 1

    def update(self) -> dict:
        """
        Compute next step delta.
        Returns {"z_delta": float} in mm.
        Called once per motion cycle - caller must wait for completion before calling again.
        
        Always ensures the returned delta keeps Z within [min_z, max_z] bounds.
        """
        # Safety: Clamp current position to valid range (in case of desync)
        self._current_z = max(self._config.min_z, min(self._config.max_z, self._current_z))
        
        # Compute next position
        delta = self._step_size * self._direction
        next_z = self._current_z + delta

        # Bounce at bounds - ensure we never exceed limits
        if next_z >= self._config.max_z:
            next_z = self._config.max_z
            delta = next_z - self._current_z
            self._direction = -1
        elif next_z <= self._config.min_z:
            next_z = self._config.min_z
            delta = next_z - self._current_z
            self._direction = 1

        # Final safety check: ensure next_z is within bounds
        next_z = max(self._config.min_z, min(self._config.max_z, next_z))
        delta = next_z - self._current_z

        self._current_z = next_z
        return {"z_delta": delta, "z_absolute": next_z}