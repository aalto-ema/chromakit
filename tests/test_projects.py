"""Portable round trips, immutable arrays, atomic failure, corrupt/version checks."""

import json
import zipfile
from dataclasses import replace

import numpy as np
import pytest
from test_deconvolution import overlap_fixture

from chromakit.analysis.deconvolution import fit
from chromakit.analysis.peaks import PeakRecipe, detect_peaks
from chromakit.application.baselines import BaselineState
from chromakit.application.deconvolution import FitState
from chromakit.application.peaks import PeakState
from chromakit.importers.text import ImportCancelled
from chromakit.persistence.project import ProjectProblem, load_project, save_project, snapshot


def populated():
    trace, baseline, recipe, _ = overlap_fixture()
    b = BaselineState(trace, draft=baseline.recipe, applied=baseline, undo_history=[None])
    p = PeakState(b, recipe=PeakRecipe(minimum_prominence=0.1))
    p.accept(detect_peaks(trace, baseline, p.recipe))
    f = FitState(b, recipe=recipe, preview=fit(trace, baseline, recipe))
    f.accept()
    return b, p, f


def test_roundtrip_preserves_results_units_history_and_source_independence(tmp_path):
    b, p, f = populated()
    project = tmp_path / "test.chromakit"
    save_project(project, snapshot([b], [p], [f], extras={"labels": {}}))
    bs, ps, fs, selected, extras = load_project(project)
    loaded = bs[0]
    np.testing.assert_array_equal(loaded.trace.signal, b.trace.signal)
    np.testing.assert_array_equal(loaded.applied.corrected, b.applied.corrected)
    assert ps[0].current and fs[0].valid(fs[0].result)
    assert ps[0].result.peaks == p.result.peaks
    assert fs[0].result.peaks == f.result.peaks
    assert fs[0].result.recipe == f.result.recipe
    assert loaded.undo_history == [None] and selected == 0 and extras == {"labels": {}}
    with pytest.raises(ValueError):
        loaded.trace.signal.setflags(write=True)
    loaded.undo()
    assert loaded.applied is None
    loaded.redo()
    assert loaded.applied.source_hash == b.trace.source_hash


def test_stale_results_and_unapplied_drafts_remain_distinct(tmp_path):
    b, p, f = populated()
    b.draft = replace(b.draft, smoothness=4321)
    b.applied = replace(b.applied, corrected=b.applied.corrected + 0.2)
    path = tmp_path / "stale.chromakit"
    save_project(path, snapshot([b], [p], [f]))
    bs, ps, fs, *_ = load_project(path)
    assert bs[0].draft.smoothness == 4321
    assert not ps[0].current and not fs[0].valid(fs[0].result)


def test_cancel_does_not_overwrite_previous_project(tmp_path):
    path = tmp_path / "atomic.chromakit"
    state = snapshot([], [], [])
    save_project(path, state)
    before = path.read_bytes()
    with pytest.raises(ImportCancelled):
        save_project(path, state, cancel=lambda: True)
    assert path.read_bytes() == before


def test_corrupt_unknown_version_and_executable_records_rejected(tmp_path):
    path = tmp_path / "bad.chromakit"
    path.write_bytes(b"invalid file")
    with pytest.raises(ProjectProblem):
        load_project(path)
    for version, session in [(999, {}), (1, {"type": "os.system", "fields": {}})]:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "manifest.json",
                json.dumps({"format": "chromakit", "schema_version": version, "session": session}),
            )
        with pytest.raises(ProjectProblem):
            load_project(path)


def test_embedded_image_bytes_roundtrip_and_checksum(tmp_path):
    path = tmp_path / "image.chromakit"
    save_project(path, snapshot([], [], [], extras={"original_image": b"example bytes"}))
    assert load_project(path)[-1]["original_image"] == b"example bytes"


def test_project_handles_reserved_feature_names_without_codec_collision(tmp_path):
    path = tmp_path / "names.chromakit"
    extras = {
        "notes": {
            "type": "example",
            "path": "example",
            "array": "example",
            "tuple": "example",
            "mapping": "example",
        }
    }
    save_project(path, snapshot([], [], [], extras=extras))
    assert load_project(path)[-1] == extras


def test_invalid_feature_metadata_is_rejected_before_installing_session(tmp_path):
    path = tmp_path / "invalid-label.chromakit"
    save_project(path, snapshot([], [], [], extras={"labels": {"trace": [{"name": "incomplete"}]}}))
    with pytest.raises(ProjectProblem):
        load_project(path)


def test_old_trace_without_stable_id_receives_a_migrated_identifier(tmp_path):
    b, p, f = populated()
    path = tmp_path / "migration.chromakit"
    save_project(path, snapshot([b], [p], [f]))
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    document = json.loads(entries["manifest.json"])
    trace = document["session"]["mapping"]["traces"][0]["mapping"]["trace"]
    trace["fields"].pop("id")
    entries["manifest.json"] = json.dumps(document).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    bs, *_ = load_project(path)
    assert bs[0].trace.id
