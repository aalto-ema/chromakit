"""Scientific import invariants, malformed inputs, locale and encoding cases."""

import hashlib

import numpy as np
import pytest

from chromakit.importers.text import (
    ColumnMapping,
    ImportCancelled,
    ImportProblem,
    ParseOptions,
    build_trace,
    load_source,
    parse_source,
    suggest_mapping,
)


def table_from(tmp_path, content, options=None, suffix=".txt"):
    path = tmp_path / f"trace{suffix}"
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return parse_source(load_source(path), options or ParseOptions())


@pytest.mark.parametrize("delimiter", [",", "\t", ";", "|", "  "])
def test_delimiters_and_units_preserve_samples(tmp_path, delimiter):
    header = delimiter.join(['"Time (min)"', '"UV (mAU)"'])
    body = "\n".join(delimiter.join(row) for row in [("0", "-2"), ("0.2", "3"), ("0.5", "4")])
    table = table_from(tmp_path, f"{header}\n{body}\n")
    trace = build_trace(table, suggest_mapping(table))
    np.testing.assert_array_equal(trace.time, [0, 12, 30])
    np.testing.assert_array_equal(trace.source_time, [0, 0.2, 0.5])
    np.testing.assert_array_equal(trace.signal, [-2, 3, 4])
    assert trace.signal_unit == "mAU"
    assert trace.time_unit == "min"
    assert trace.source_hash == hashlib.sha256(table.source.content).hexdigest()
    assert "nonuniform" in " ".join(trace.warnings)
    with pytest.raises(ValueError):
        trace.signal[0] = 99
    with pytest.raises(ValueError):
        trace.time.setflags(write=True)


def test_no_header_and_categorical_extra_column_retains_first_sample(tmp_path):
    table = table_from(tmp_path, "0,2,sample_A\n1,3,sample_A\n2,4,sample_A\n")
    trace = build_trace(table, ColumnMapping(time_unit="s"))
    assert len(trace.time) == 3
    assert trace.signal[0] == 2


def test_decimal_comma_and_preamble(tmp_path):
    table = table_from(
        tmp_path,
        "Instrument report\nTime (min);Signal (nA)\n0,0;1,2\n0,5;2,3\n",
        ParseOptions(decimal=",", skip_rows=1),
    )
    trace = build_trace(table, suggest_mapping(table))
    np.testing.assert_allclose(trace.time, [0, 30])
    np.testing.assert_allclose(trace.signal, [1.2, 2.3])
    assert dict(trace.import_settings)["decimal"] == ","
    assert dict(trace.import_settings)["skip_rows"] == "1"


def test_bom_and_comments_reported(tmp_path):
    table = table_from(tmp_path, b"\xef\xbb\xbf# exported signal\nTime (s)\tSignal\n0\t1\n\n1\t2\n")
    assert table.line_numbers == (3, 5)
    assert "2 blank/comment" in table.warnings[0]
    assert len(table.rows) == 2


@pytest.mark.parametrize("encoding", ["utf-16", "cp1252"])
def test_explicit_or_bom_encoding(tmp_path, encoding):
    content = "Time (s);Signal (µV)\n0;1\n1;2\n".encode(encoding)
    options = ParseOptions(encoding="Auto" if encoding == "utf-16" else encoding)
    table = table_from(tmp_path, content, options)
    assert suggest_mapping(table).signal_unit == "µV"


def test_unknown_encoding_requires_choice(tmp_path):
    with pytest.raises(ImportProblem, match="encoding"):
        table_from(tmp_path, "Time;Signal (µV)\n0;1\n1;2".encode("cp1252"))


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("0,1\n0,2\n", "strictly increase"),
        ("1,1\n0,2\n", "strictly increase"),
        ("0,1\n1,nan\n", "nonfinite"),
        ("0,1\n1,inf\n", "nonfinite"),
        ("0,1\n1,\n", "missing"),
        ("0,1\n1,broken\n", "not numeric"),
    ],
)
def test_invalid_samples_are_never_silently_repaired(tmp_path, body, message):
    table = table_from(tmp_path, "Time,Signal\n" + body)
    with pytest.raises(ImportProblem, match=message):
        build_trace(table, ColumnMapping())


def test_ragged_rows_have_source_line_number(tmp_path):
    with pytest.raises(ImportProblem, match="Line 3 has 3 columns"):
        table_from(tmp_path, "Time,Signal\n0,1\n1,2,3\n")


def test_quote_error_is_actionable(tmp_path):
    with pytest.raises(ImportProblem, match="quoting"):
        table_from(tmp_path, 'Time,Signal\n0,1\n1,"2\n', ParseOptions(delimiter="Comma"))


def test_channel_mapping_and_gap_flags(tmp_path):
    table = table_from(tmp_path, "Time (s),UV (mAU),PAD (nA)\n0,1,5\n1,2,6\n2,3,7\n20,4,8\n")
    trace = build_trace(table, ColumnMapping(time=0, signal=2, time_unit="s", signal_unit="nA"))
    np.testing.assert_array_equal(trace.signal, [5, 6, 7, 8])
    np.testing.assert_array_equal(trace.gap_after, [False, False, True])
    assert "sampling gap" in " ".join(trace.warnings)


def test_same_column_and_unknown_units(tmp_path):
    table = table_from(tmp_path, "0 1\n1 2\n")
    with pytest.raises(ImportProblem, match="different columns"):
        build_trace(table, ColumnMapping(time=0, signal=0))
    trace = build_trace(table, ColumnMapping())
    assert len(trace.warnings) == 2


def test_flat_negative_signal_is_valid(tmp_path):
    table = table_from(tmp_path, "Time (s),Signal\n0,-4\n1,-4\n2,-4\n")
    trace = build_trace(table, suggest_mapping(table))
    np.testing.assert_array_equal(trace.signal, [-4, -4, -4])


def test_binary_empty_and_single_row_inputs(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    with pytest.raises(ImportProblem, match="empty"):
        load_source(path)
    with pytest.raises(ImportProblem, match="binary"):
        table_from(tmp_path, b"abc\x00def")
    with pytest.raises(ImportProblem, match="two sampled"):
        table_from(tmp_path, "Time,Signal\n0,1\n")


def test_cancellation_at_read_parse_and_conversion(tmp_path):
    table = table_from(tmp_path, "Time,Signal\n0,1\n1,2\n")
    with pytest.raises(ImportCancelled):
        load_source(table.source.path, lambda: True)
    with pytest.raises(ImportCancelled):
        parse_source(table.source, table.options, lambda: True)
    with pytest.raises(ImportCancelled):
        build_trace(table, ColumnMapping(), lambda: True)


def test_file_limit_checked_even_without_stat(tmp_path, monkeypatch):
    monkeypatch.setattr("chromakit.importers.text.MAX_BYTES", 5)
    path = tmp_path / "large.csv"
    path.write_bytes(b"0,1\n1,2\n")
    with pytest.raises(ImportProblem, match="64 MiB"):
        load_source(path)


def test_extreme_coordinate_overflow_is_reported(tmp_path):
    table = table_from(tmp_path, "Time,Signal\n0,1\n1e308,2\n")
    with pytest.raises(ImportProblem, match="numerical range"):
        build_trace(table, ColumnMapping(time_unit="min"))


def test_commented_digitization_header_and_explicit_missing_signal_policy(tmp_path):
    table = table_from(
        tmp_path,
        "# time_min_assumed\tred_Pt2h_mAU\tblue_Au2h_mAU\n"
        "0\tnan\t2\n1\t3\t4\n2\t5\tnan\n3\t6\t8\n4\tnan\t9\n",
    )
    mapping = suggest_mapping(table)
    assert mapping.time_unit == "min" and mapping.signal_unit == "mAU"
    assert table.line_numbers == (2, 3, 4, 5, 6)
    with pytest.raises(ImportProblem, match="Omit with gaps"):
        build_trace(table, mapping)
    red = build_trace(
        table, ColumnMapping(time_unit="min", signal_unit="mAU", missing_signal="Omit with gaps")
    )
    np.testing.assert_array_equal(red.source_time, [1, 2, 3])
    np.testing.assert_array_equal(red.signal, [3, 5, 6])
    assert dict(red.import_settings)["omitted_signal_lines"] == "2,6"
    blue = build_trace(
        table,
        ColumnMapping(
            signal=2, time_unit="min", signal_unit="mAU", missing_signal="Omit with gaps"
        ),
    )
    np.testing.assert_array_equal(blue.source_time, [0, 1, 3, 4])
    np.testing.assert_array_equal(blue.gap_after, [False, True, False])
    assert blue.source_hash == table.source.sha256
    assert dict(blue.import_settings)["omitted_signal_lines"] == "4"
    assert "internal break" in " ".join(blue.warnings)


@pytest.mark.parametrize("token", ["", "NaN", "NA", "N/A"])
def test_missing_tokens_can_only_be_omitted_explicitly(tmp_path, token):
    table = table_from(tmp_path, f"Time,Signal\n0,1\n1,{token}\n2,3\n")
    trace = build_trace(table, ColumnMapping(missing_signal="Omit with gaps"))
    assert list(trace.gap_after) == [True]
    np.testing.assert_array_equal(trace.signal, [1, 3])


@pytest.mark.parametrize(
    "rows", ["0,1\n1,inf\n2,3", "0,1\nnan,2\n2,3", "0,1\n1,error\n2,3", "0,1\n-1,nan\n2,3"]
)
def test_omission_does_not_hide_invalid_times_infinity_or_malformed_data(tmp_path, rows):
    table = table_from(tmp_path, "Time,Signal\n" + rows + "\n")
    with pytest.raises(ImportProblem):
        build_trace(table, ColumnMapping(missing_signal="Omit with gaps"))


def test_all_missing_trace_is_not_importable_and_comments_are_not_generic_headers(tmp_path):
    table = table_from(tmp_path, "# ordinary metadata\n0,nan\n1,nan\n")
    assert table.columns == ("Column 1", "Column 2")
    with pytest.raises(ImportProblem, match="two finite"):
        build_trace(table, ColumnMapping(missing_signal="Omit with gaps"))
    table = table_from(tmp_path, "# time_min_assumed uv_mAU\n0 1\n1 2\n")
    assert table.columns == ("time_min_assumed", "uv_mAU")
