"""Explicit image-path repair; preserve observations separately from estimated samples."""

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter

from chromakit.importers.text import ImportCancelled, ImportProblem


@dataclass(frozen=True)
class PixelRepair:
    points: tuple[tuple[float, float], ...]
    interpolated_x: tuple[float, ...] = ()
    corrected_x: tuple[float, ...] = ()


def validate_cleanup(recipe):
    if type(recipe.interpolate_gaps) is not bool or type(recipe.remove_spikes) is not bool:
        raise ImportProblem("Image repair switches must be true or false.")
    if type(recipe.maximum_gap) is not int or not 1 <= recipe.maximum_gap <= 20000:
        raise ImportProblem("Maximum missing gap must be 1–20,000 pixel columns.")
    if (
        type(recipe.spike_window) is not int
        or not 5 <= recipe.spike_window <= 101
        or recipe.spike_window % 2 == 0
    ):
        raise ImportProblem("Spike neighborhood must be an odd number from 5 to 101 columns.")
    if not np.isfinite([recipe.spike_threshold, recipe.spike_minimum]).all() or not (
        1 <= recipe.spike_threshold <= 20 and 1 <= recipe.spike_minimum <= 10000
    ):
        raise ImportProblem("Spike sensitivity must be 1–20 and minimum jump 1–10,000 pixels.")


def repair_pixels(points, recipe, cancel=lambda: False):
    """Hampel-style isolated-spike repair then bounded, interior-only linear gap filling.

    Filter contiguous segments only. Never change broad runs of candidate outliers,
    extrapolate beyond observed endpoints, or claim estimated points were measured.
    """
    validate_cleanup(recipe)
    array = np.asarray(points, dtype=float)
    if (
        array.ndim != 2
        or array.shape[1] != 2
        or len(array) < 2
        or not np.isfinite(array).all()
        or np.any(np.diff(array[:, 0]) <= 0)
    ):
        raise ImportProblem("Use at least two finite points with strictly increasing pixel x.")
    x, y = array[:, 0], array[:, 1].copy()
    corrected = []
    if recipe.remove_spikes:
        edges = np.r_[0, np.flatnonzero(np.diff(x) > 1.5) + 1, len(x)]
        for start, end in zip(edges[:-1], edges[1:], strict=True):
            if cancel():
                raise ImportCancelled()
            values = y[start:end].copy()
            if len(values) < recipe.spike_window:
                continue
            median = median_filter(values, size=recipe.spike_window, mode="nearest")
            residual = np.abs(values - median)
            mad = median_filter(residual, size=recipe.spike_window, mode="nearest")
            candidate = residual > np.maximum(
                recipe.spike_minimum, recipe.spike_threshold * 1.4826 * mad
            )
            indices = np.flatnonzero(candidate)
            runs = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
            for run in runs:
                if cancel():
                    raise ImportCancelled()
                if not len(run) or len(run) > 2 or run[0] == 0 or run[-1] == len(values) - 1:
                    continue
                left, right = start + run[0] - 1, start + run[-1] + 1
                positions = start + run
                y[positions] = np.interp(
                    x[positions], x[[left, right]], values[[run[0] - 1, run[-1] + 1]]
                )
                corrected.extend(x[positions].tolist())
    output = []
    interpolated = []
    for index in range(len(x) - 1):
        if cancel():
            raise ImportCancelled()
        output.append((float(x[index]), float(y[index])))
        distance = x[index + 1] - x[index]
        if recipe.interpolate_gaps and 1.5 < distance <= recipe.maximum_gap + 1:
            missing = np.arange(np.floor(x[index]) + 1, np.ceil(x[index + 1]))
            estimates = np.interp(missing, x[index : index + 2], y[index : index + 2])
            output.extend(zip(missing.tolist(), estimates.tolist(), strict=True))
            interpolated.extend(missing.tolist())
    output.append((float(x[-1]), float(y[-1])))
    return PixelRepair(tuple(output), tuple(interpolated), tuple(corrected))
