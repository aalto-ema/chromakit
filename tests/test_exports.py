import csv
import io
import json
import re
import xml.etree.ElementTree as ET

import pytest
from PIL import Image
from test_projects import populated

from chromakit.export.figures import FigureSpec, figure_bytes
from chromakit.export.results import result_bytes
from chromakit.importers.text import ImportProblem


@pytest.mark.parametrize("format", ["png", "tiff", "pdf", "svg"])
def test_fixed_size_transparent_and_vector_exports(format):
    b, p, f = populated()
    spec = FigureSpec(800, 600, "px", 100, True, view="Fit + residuals")
    data = figure_bytes(b.trace, b.applied, f.result, [], spec, format)
    if format in {"png", "tiff"}:
        image = Image.open(io.BytesIO(data))
        assert image.size == (800, 600)
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0
    elif format == "svg":
        root = ET.fromstring(data)
        assert root.attrib["width"] == "576pt" and root.attrib["height"] == "432pt"
    else:
        assert data.startswith(b"%PDF")
        assert re.search(rb"/MediaBox\s*\[\s*0\s+0\s+576\s+432\s*\]", data)


def test_result_exports_include_units_recipe_and_identity():
    b, p, f = populated()
    data = json.loads(
        result_bytes(b.trace, b.applied, p.result, f.result, "Fitted components", "json")
    )
    assert data["metadata"]["recipe"]["components"][0]["model"] == "Gaussian"
    assert data["rows"][0]["area_unit"] == "mAU × min"
    rows = list(
        csv.DictReader(
            io.StringIO(
                result_bytes(b.trace, b.applied, p.result, f.result, "Measured peaks").decode(
                    "utf-8-sig"
                )
            )
        )
    )
    assert rows[0]["source_hash"] == b.trace.source_hash
    assert rows[0]["origin"] == "Measured peaks"
    with pytest.raises(ImportProblem):
        result_bytes(b.trace, None, p.result, f.result, "Measured peaks")
