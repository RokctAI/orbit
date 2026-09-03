use pyo3::prelude::*;
use pyo3::types::PyBytes;
use qbsdiff::{Bsdiff, Bspatch};
use similar::TextDiff;
use std::io::Cursor;

/// Unified diff of `a` -> `b` with 3 lines of context.
///
/// `similar` builds a `TextDiff` first and renders it through
/// `unified_diff()`; the `---`/`+++` header is only emitted when file names
/// are supplied, matching the previous behaviour of this function.
#[pyfunction]
#[pyo3(signature = (a, b, from_file="", to_file=""))]
fn compute_diff(a: &str, b: &str, from_file: &str, to_file: &str) -> PyResult<String> {
    let diff = TextDiff::from_lines(a, b);
    let mut unified = diff.unified_diff();
    unified.context_radius(3);
    if !from_file.is_empty() || !to_file.is_empty() {
        unified.header(from_file, to_file);
    }
    Ok(unified.to_string())
}

/// zstd-compressed bsdiff patch turning `old_bytes` into `new_bytes`.
///
/// Returned as Python `bytes` (a `Vec<u8>` would surface as a `list` of
/// ints, which callers such as gravity's `apply_binary_patch` cannot write
/// to a file or base64-encode).
#[pyfunction]
fn compute_binary_diff(py: Python<'_>, old_bytes: &[u8], new_bytes: &[u8]) -> PyResult<PyObject> {
    let mut raw_patch = Vec::new();
    // qbsdiff: `Bsdiff::new(source)` then `compare(target, writer)`.
    Bsdiff::new(old_bytes)
        .compare(new_bytes, Cursor::new(&mut raw_patch))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("bsdiff failed: {}", e)))?;

    let compressed_patch = zstd::encode_all(Cursor::new(raw_patch), 3)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("zstd compression failed: {}", e)))?;
    Ok(PyBytes::new(py, &compressed_patch).into())
}

/// Apply a patch produced by `compute_binary_diff` to `old_bytes`; returns `bytes`.
#[pyfunction]
fn apply_binary_patch_rs(py: Python<'_>, old_bytes: &[u8], patch_bytes: &[u8]) -> PyResult<PyObject> {
    let decompressed_patch = zstd::decode_all(Cursor::new(patch_bytes))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("zstd decompression failed: {}", e)))?;

    let mut output = Cursor::new(Vec::new());
    Bspatch::new(&decompressed_patch)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("invalid patch: {}", e)))?
        .apply(old_bytes, &mut output)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("bspatch failed: {}", e)))?;
    Ok(PyBytes::new(py, &output.into_inner()).into())
}

#[pymodule]
fn orbit_diff_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_diff, m)?)?;
    m.add_function(wrap_pyfunction!(compute_binary_diff, m)?)?;
    m.add_function(wrap_pyfunction!(apply_binary_patch_rs, m)?)?;
    Ok(())
}
