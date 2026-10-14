"""Heuristic image recovery flags; neither statistical uncertainty nor instrument precision."""

import numpy as np

from chromakit.importers.text import ImportCancelled


def path_quality(pixels, recipe, points, cancel=lambda: False):
    flags = []
    left, top, right, bottom = recipe.crop
    previous = None
    for x, y in points:
        if cancel():
            raise ImportCancelled()
        column = int(round(x))
        if not left <= column < right:
            continue
        selected = (
            np.flatnonzero(
                np.linalg.norm(pixels[top:bottom, column].astype(float) - recipe.color, axis=1)
                <= recipe.tolerance
            )
            + top
        )
        for x0, y0, x1, y1 in recipe.masks:
            if x0 <= column < x1:
                selected = selected[(selected < y0) | (selected >= y1)]
        groups = (
            np.split(selected, np.flatnonzero(np.diff(selected) > 1) + 1) if len(selected) else []
        )
        centers = np.array([np.median(group) for group in groups])
        reasons = []
        if not len(centers) or np.min(np.abs(centers - y)) > 3:
            reasons.append("Point does not follow selected-color pixels")
        else:
            closest = int(np.argmin(np.abs(centers - y)))
            if len(groups[closest]) > max(6, (bottom - top) * 0.04):
                reasons.append("Thick or crossing trace")
            if np.sum(np.abs(centers - y) < max(8, (bottom - top) * 0.04)) > 1:
                reasons.append("Competing nearby colored paths")
        if previous is not None:
            px, py = previous
            if x - px > 1.5:
                reasons.append("Missing interval before point")
            elif abs(y - py) > max(8, (bottom - top) * 0.06):
                reasons.append("Abrupt pixel jump")
        if reasons:
            flags.append(dict(x=float(x), y=float(y), reasons=reasons))
        previous = x, y
    return flags
