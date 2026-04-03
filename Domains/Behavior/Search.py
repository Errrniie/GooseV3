import threading
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
        self._lock = threading.Lock()

    def apply_runtime_z_bounds(
        self,
        min_z: float,
        max_z: float,
        start_z: float,
        step_size_mm: float | None = None,
    ) -> None:
        """
        Update Z limits and nominal start from config manager / API while running.
        Clamps current position into the new range and refreshes sweep direction.
        Optionally updates per-step size (SEARCH_STEP_MM).
        """
        with self._lock:
            self._config.min_z = min_z
            self._config.max_z = max_z
            self._config.start_z = start_z
            if step_size_mm is not None:
                self._config.step_size = float(step_size_mm)
                self._step_size = float(step_size_mm)
            self._current_z = max(min_z, min(max_z, self._current_z))
            mid = (max_z + min_z) / 2.0
            self._direction = -1 if self._current_z >= mid else 1

    def reset(self) -> None:
        with self._lock:
            self._current_z = self._config.start_z
            self._direction = self._config.initial_direction

    def sync_to_position(self, z_mm: float) -> None:
        """
        Sync the SearchController's internal state to a known Z position.
        Useful when the actual Z position differs from the controller's internal state.
        
        Args:
            z_mm: The actual current Z position in mm
        """
        with self._lock:
            z_mm = max(self._config.min_z, min(self._config.max_z, z_mm))
            self._current_z = z_mm
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
        with self._lock:
            self._current_z = max(
                self._config.min_z, min(self._config.max_z, self._current_z)
            )

            delta = self._step_size * self._direction
            next_z = self._current_z + delta

            if next_z >= self._config.max_z:
                next_z = self._config.max_z
                delta = next_z - self._current_z
                self._direction = -1
            elif next_z <= self._config.min_z:
                next_z = self._config.min_z
                delta = next_z - self._current_z
                self._direction = 1

            next_z = max(self._config.min_z, min(self._config.max_z, next_z))
            delta = next_z - self._current_z

            self._current_z = next_z
            return {"z_delta": delta, "z_absolute": next_z}

    def sync_after_track(self, z_mm: float, step_size_mm: float) -> None:
        """
        After TRACK → SEARCH: align internal Z to snapped physical Z and apply search step from config.
        """
        with self._lock:
            z_mm = max(self._config.min_z, min(self._config.max_z, z_mm))
            self._current_z = z_mm
            self._step_size = step_size_mm
            mid = (self._config.max_z + self._config.min_z) / 2.0
            self._direction = -1 if self._current_z >= mid else 1