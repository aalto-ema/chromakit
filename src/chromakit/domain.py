"""Qt-free trace records. Source samples remain unchanged and read-only."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

TIME_SCALES = {"s": 1.0, "min": 60.0, "h": 3600.0, "unknown": 1.0}


@dataclass(frozen=True)
class Trace:
    name: str
    source: Path
    source_hash: str
    time: NDArray[np.float64]  # seconds when known; source coordinates otherwise
    source_time: NDArray[np.float64]
    signal: NDArray[np.float64]
    time_unit: str
    signal_unit: str
    channel: str
    detector: str
    encoding: str
    delimiter: str
    time_column: str
    warnings: tuple[str, ...]
    gap_after: NDArray[np.bool_]
    import_settings: tuple[tuple[str, str], ...]

    @property
    def display_time(self) -> NDArray[np.float64]:
        return self.source_time


def readonly_array(values, dtype=np.float64) -> NDArray:
    """Use immutable backing bytes so callers cannot re-enable writes."""
    return np.frombuffer(np.asarray(values, dtype=dtype).tobytes(), dtype=dtype)
