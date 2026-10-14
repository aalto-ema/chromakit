"""Recorded image geometry: arbitrary deskew and four-corner projective rectification."""

import numpy as np
from PIL import Image

from chromakit.importers.text import ImportProblem


def transform_image(image, deskew=0.0, perspective=(), size=(0, 0)):
    if not np.isfinite(deskew) or not -45 <= deskew <= 45:
        raise ImportProblem("Deskew must be between −45° and 45°.")
    if deskew:
        image = image.rotate(
            deskew, expand=True, resample=Image.Resampling.BICUBIC, fillcolor="white"
        )
    if perspective:
        corners = np.asarray(perspective, dtype=float)
        width, height = size
        if (
            corners.shape != (4, 2)
            or not np.isfinite(corners).all()
            or type(width) is not int
            or type(height) is not int
            or not 2 <= width <= 20000
            or not 2 <= height <= 20000
            or width * height > 25_000_000
        ):
            raise ImportProblem(
                "Use four corners, sizes 2–20,000 pixels and at most 25 million pixels."
            )
        if not (
            (corners[:, 0] >= 0)
            & (corners[:, 0] < image.width)
            & (corners[:, 1] >= 0)
            & (corners[:, 1] < image.height)
        ).all():
            raise ImportProblem("Perspective corners must lie inside the deskewed image.")
        edges = np.roll(corners, -1, axis=0) - corners
        cross = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(edges[:, 0], -1)
        if not (cross > 1e-6).all():
            raise ImportProblem(
                "Pick convex corners: top-left, top-right, bottom-right, bottom-left."
            )
        destination = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
        matrix = []
        values = []
        for (x, y), (u, v) in zip(destination, corners, strict=True):
            matrix.extend([[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]])
            values.extend([u, v])
        try:
            coefficients = np.linalg.solve(np.asarray(matrix), values)
        except np.linalg.LinAlgError as error:
            raise ImportProblem(
                "Perspective corners are degenerate; pick a larger plot rectangle."
            ) from error
        if not np.isfinite(coefficients).all():
            raise ImportProblem("Invalid perspective transform.")
        image = image.transform(
            (width, height),
            Image.Transform.PERSPECTIVE,
            tuple(coefficients),
            resample=Image.Resampling.BICUBIC,
            fillcolor="white",
        )
    if image.width * image.height > 25_000_000 or max(image.size) > 20000:
        raise ImportProblem(
            "Limit transformed images to 25 million pixels and 20,000 pixels per side."
        )
    return image
