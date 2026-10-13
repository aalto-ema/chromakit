"""Linear axis calibration and continuity-assisted pixel tracing, with explicit gaps."""

import hashlib
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from chromakit.digitization.repair import repair_pixels, validate_cleanup
from chromakit.domain import TIME_SCALES, Trace, readonly_array
from chromakit.importers.text import ImportCancelled, ImportProblem


@dataclass(frozen=True)
class DigitizeRecipe:
    x1: float
    x2: float
    time1: float
    time2: float
    y1: float
    y2: float
    signal1: float
    signal2: float
    crop: tuple[int, int, int, int]
    color: tuple[int, int, int] = (0, 0, 255)
    tolerance: float = 90
    rotation: int = 0
    seed_y: float | None = None
    masks: tuple[tuple[int, int, int, int], ...] = ()
    time_unit: str = "unknown"
    signal_unit: str = "unknown"
    interpolate_gaps: bool = False
    maximum_gap: int = 25
    remove_spikes: bool = False
    spike_window: int = 11
    spike_threshold: float = 4.0
    spike_minimum: float = 6.0


def image_pixels(data, rotation=0):
    if len(data) > 64 * 1024 * 1024:
        raise ImportProblem("Use an image smaller than 64 MiB.")
    try:
        image = Image.open(io.BytesIO(data))
    except (Image.DecompressionBombError, OSError) as error:
        raise ImportProblem("Cannot safely decode this image.") from error
    if image.format not in {"PNG", "JPEG", "TIFF"}:
        raise ImportProblem("Choose PNG, JPEG or TIFF.")
    if image.width * image.height > 25_000_000 or max(image.width, image.height) > 20000:
        raise ImportProblem("Limit digitization images to 25 million pixels.")
    image = ImageOps.exif_transpose(image).convert("RGBA")
    image = Image.alpha_composite(Image.new("RGBA", image.size, "white"), image).convert("RGB")
    if rotation not in {0, 90, 180, 270}:
        raise ImportProblem("Choose a right-angle image rotation.")
    return np.asarray(image.rotate(rotation, expand=True))


def validate(recipe, shape):
    validate_cleanup(recipe)
    if not np.isfinite(
        [
            recipe.x1,
            recipe.x2,
            recipe.time1,
            recipe.time2,
            recipe.y1,
            recipe.y2,
            recipe.signal1,
            recipe.signal2,
            recipe.tolerance,
        ]
    ).all():
        raise ImportProblem("Axis calibration and tolerance must be finite.")
    if (
        recipe.x1 == recipe.x2
        or recipe.y1 == recipe.y2
        or recipe.time1 == recipe.time2
        or recipe.signal1 == recipe.signal2
    ):
        raise ImportProblem("Each axis needs two distinct pixel positions and known values.")
    if not (
        0 <= recipe.x1 < shape[1]
        and 0 <= recipe.x2 < shape[1]
        and 0 <= recipe.y1 < shape[0]
        and 0 <= recipe.y2 < shape[0]
    ):
        raise ImportProblem("Calibration pixel anchors must lie inside the oriented image.")
    if len(recipe.color) != 3 or any(not 0 <= value <= 255 for value in recipe.color):
        raise ImportProblem("Choose a valid RGB trace color.")
    if any(x0 >= x1 or y0 >= y1 for x0, y0, x1, y1 in recipe.masks):
        raise ImportProblem("Mask rectangles must have increasing x and y bounds.")
    left, top, right, bottom = recipe.crop
    if not (0 <= left < right <= shape[1] and 0 <= top < bottom <= shape[0]):
        raise ImportProblem("Crop bounds must lie inside the oriented image.")
    if (
        recipe.time_unit not in TIME_SCALES
        or recipe.time_unit == "unknown"
        or recipe.signal_unit.strip().casefold() in {"", "unknown", "unspecified"}
    ):
        raise ImportProblem("Confirm calibrated time and signal units before creating a trace.")
    if not 1 <= recipe.tolerance <= 441:
        raise ImportProblem("Color tolerance must be between 1 and 441.")


def trace_pixels(data, recipe, cancel=lambda: False):
    pixels = image_pixels(data, recipe.rotation)
    validate(recipe, pixels.shape)
    left, top, right, bottom = recipe.crop
    selected = (
        np.linalg.norm(pixels[top:bottom, left:right].astype(float) - recipe.color, axis=2)
        <= recipe.tolerance
    )
    for x0, y0, x1, y1 in recipe.masks:
        selected[
            max(y0 - top, 0) : max(min(y1, bottom) - top, 0),
            max(x0 - left, 0) : max(min(x1, right) - left, 0),
        ] = False
    points = []
    previous = recipe.seed_y
    for column in range(right - left):
        if cancel():
            raise ImportCancelled()
        ys = np.flatnonzero(selected[:, column]) + top
        if not len(ys):
            continue
        groups = np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1)
        centers = [float(np.median(group)) for group in groups]
        chosen = (
            min(centers, key=lambda y: abs(y - previous))
            if previous is not None
            else centers[len(centers) // 2]
        )
        points.append((float(column + left), chosen))
        previous = chosen
    if len(points) < 2:
        raise ImportProblem(
            "No usable trace found. Pick its color, adjust tolerance/crop or use manual points."
        )
    return tuple(points)


def create_trace(data, path, recipe, points, name="Digitized chromatogram", manual=False):
    pixels = image_pixels(data, recipe.rotation)
    validate(recipe, pixels.shape)
    array = np.asarray(points, dtype=float)
    if array.ndim != 2 or array.shape[1] != 2 or len(array) < 2 or not np.isfinite(array).all():
        raise ImportProblem("At least two finite pixel points are required.")
    left, top, right, bottom = recipe.crop
    if not (
        (array[:, 0] >= left)
        & (array[:, 0] < right)
        & (array[:, 1] >= top)
        & (array[:, 1] < bottom)
    ).all():
        raise ImportProblem("Trace points must lie inside the selected plot crop.")
    if np.any(np.diff(array[:, 0]) <= 0):
        raise ImportProblem(
            "Pixel x positions must increase without duplicates; edit/reorder the point table."
        )
    original = array.copy()
    recovery = repair_pixels(points, recipe)
    array = np.asarray(recovery.points)
    time = recipe.time1 + (array[:, 0] - recipe.x1) * (recipe.time2 - recipe.time1) / (
        recipe.x2 - recipe.x1
    )
    signal = recipe.signal1 + (array[:, 1] - recipe.y1) * (recipe.signal2 - recipe.signal1) / (
        recipe.y2 - recipe.y1
    )
    gaps = np.diff(array[:, 0]) > 1.5
    if time[-1] < time[0]:
        time, signal = time[::-1], signal[::-1]
        gaps = gaps[::-1]
    digest = hashlib.sha256(data).hexdigest()
    settings = asdict(recipe)
    record = {
        "recipe": settings,
        "pixel_points": array.tolist(),
        "original_pixel_points": original.tolist(),
        "interpolated_pixel_x": list(recovery.interpolated_x),
        "spike_corrected_pixel_x": list(recovery.corrected_x),
        "manual_overrides": manual,
        "image_sha256": digest,
        "original_image": data,
        "source_filename": Path(path).name,
        "time_per_pixel": abs((recipe.time2 - recipe.time1) / (recipe.x2 - recipe.x1)),
        "signal_per_pixel": abs((recipe.signal2 - recipe.signal1) / (recipe.y2 - recipe.y1)),
        "method_version": "image-v2",
    }
    trace = Trace(
        name,
        Path(path),
        digest,
        readonly_array(time * TIME_SCALES[recipe.time_unit]),
        readonly_array(time),
        readonly_array(signal),
        recipe.time_unit,
        recipe.signal_unit,
        "Image-recovered trace",
        "Unspecified",
        "image",
        "image",
        "Calibrated image x",
        (
            "IMAGE-DIGITIZED: pixel recovery is not instrument sampling precision.",
            "Review calibration, trace thickness, occlusion and missing intervals "
            "before quantification.",
            *(
                (
                    f"INTERPOLATED: {len(recovery.interpolated_x)} missing pixel columns; "
                    "linear estimates are not observed image samples.",
                )
                if recovery.interpolated_x
                else ()
            ),
            *(
                (
                    f"SPIKE REPAIR: {len(recovery.corrected_x)} isolated outliers replaced "
                    "by linear estimates. Review narrow peaks against the original image.",
                )
                if recovery.corrected_x
                else ()
            ),
        ),
        readonly_array(gaps, np.bool_),
        (
            ("reader_version", "image-v2"),
            ("recipe", json.dumps(settings, sort_keys=True)),
            ("manual_overrides", str(manual)),
            ("pixel_points_sha256", hashlib.sha256(original.tobytes()).hexdigest()),
        ),
    )
    return trace, record
