"""Validate persisted feature metadata before any loaded session replaces the UI."""

import math

from chromakit.analysis.calibration import CalibrationPoint, CalibrationRecipe, CalibrationResult
from chromakit.compounds.library import Compound, validate
from chromakit.digitization.core import DigitizeRecipe
from chromakit.digitization.repair import validate_cleanup
from chromakit.export.figures import FigureSpec
from chromakit.importers.text import ImportProblem


def validate_labels(mapping):
    if not isinstance(mapping, dict):
        raise ImportProblem("Invalid saved labels.")
    for trace_id, labels in mapping.items():
        if not isinstance(trace_id, str) or not isinstance(labels, list) or len(labels) > 10000:
            raise ImportProblem("Invalid label collection.")
        for label in labels:
            for key in ["id", "trace_id", "peak_id", "name", "origin", "status", "result_key"]:
                if not isinstance(label.get(key), str):
                    raise ImportProblem("Invalid label identity or name.")
            if label["origin"] not in {"Measured peaks", "Fitted components"} or label[
                "status"
            ] not in {"Tentative", "Confirmed"}:
                raise ImportProblem("Invalid label origin/review status.")
            for key in [
                "time",
                "height",
                "raw_height",
                "dx",
                "dy",
                "rotation",
                "label_x",
                "label_y",
                "label_y_raw",
            ]:
                if key in label and (
                    not isinstance(label[key], (int, float)) or not math.isfinite(label[key])
                ):
                    raise ImportProblem("Invalid annotation coordinates.")


def validate_extras(extras, validate_record):
    validate_labels(extras.get("labels", {}))
    for key in ("labels_undo", "labels_redo"):
        if not isinstance(extras.get(key, []), list):
            raise ImportProblem("Invalid label history.")
        for labels in extras.get(key, []):
            validate_labels(labels)
    compounds = []
    for item in extras.get("compound_library", []):
        compound = Compound(**dict(item, aliases=tuple(item.get("aliases", ()))))
        if not all(
            isinstance(text, str)
            for text in [compound.id, compound.name, compound.formula, *compound.aliases]
        ):
            raise ImportProblem("Invalid compound library text fields.")
        compounds.append(compound)
    validate(compounds)
    if "figure_spec" in extras:
        validate_record(
            FigureSpec(
                **dict(
                    extras["figure_spec"],
                    x_limits=tuple(extras["figure_spec"]["x_limits"])
                    if extras["figure_spec"].get("x_limits")
                    else None,
                )
            )
        )
    for key, entry in extras.get("calibrations", {}).items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise ImportProblem("Invalid calibration record.")
        for point in entry["points"]:
            validate_record(CalibrationPoint(**point))
        recipe = CalibrationRecipe(**entry.get("recipe", {}))
        validate_record(recipe)
        result = entry.get("result")
        if result:
            validate_record(
                CalibrationResult(
                    **dict(
                        result,
                        recipe=CalibrationRecipe(**result["recipe"]),
                        points=tuple(CalibrationPoint(**p) for p in result["points"]),
                        diagnostics=tuple(result["diagnostics"]),
                        warnings=tuple(result["warnings"]),
                    )
                )
            )
    for _trace_id, record in extras.get("digitizations", {}).items():
        if not isinstance(record.get("original_image"), bytes):
            raise ImportProblem("Original digitization image is missing.")
        recipe = dict(record["recipe"])
        recipe.update(
            crop=tuple(recipe["crop"]),
            color=tuple(recipe["color"]),
            masks=tuple(tuple(mask) for mask in recipe["masks"]),
        )
        digitization_recipe = DigitizeRecipe(**recipe)
        validate_record(digitization_recipe)
        validate_cleanup(digitization_recipe)
    # Unknown feature namespaces are retained, never executed.
    if any(name.startswith("__") for name in extras):
        raise ImportProblem("Unsupported project extension namespace.")
