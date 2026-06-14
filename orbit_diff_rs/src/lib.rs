use pyo3::prelude::*;
use similar::udiff::UnifiedDiff;
use qbsdiff::{Bsdiff, Bspatch};
use std::io::Cursor;

#[pyfunction]
#[pyo3(signature = (a, b, from_file="", to_file=""))]
fn compute_diff(a: &str, b: &str, from_file: &str, to_file: &str) -> PyResult<String> {
    let diff = UnifiedDiff::from_str(a, b, 3, Some((from_file, to_file)));
    Ok(diff.to_string())
}

#[pyfunction]
fn compute_binary_diff(old_bytes: &[u8], new_bytes: &[u8]) -> PyResult<Vec<u8>> {
    let mut raw_patch = Vec::new();
    Bsdiff::new(old_bytes, new_bytes)
        .compare(Cursor::new(&mut raw_patch))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("bsdiff failed: {}", e)))?;
        
    let compressed_patch = zstd::encode_all(Cursor::new(raw_patch), 3)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("zstd compression failed: {}", e)))?;
    Ok(compressed_patch)
}

#[pyfunction]
fn apply_binary_patch_rs(old_bytes: &[u8], patch_bytes: &[u8]) -> PyResult<Vec<u8>> {
    let decompressed_patch = zstd::decode_all(Cursor::new(patch_bytes))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("zstd decompression failed: {}", e)))?;
        
    let mut output = Cursor::new(Vec::new());
    Bspatch::new(&decompressed_patch)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("invalid patch: {}", e)))?
        .apply(old_bytes, &mut output)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("bspatch failed: {}", e)))?;
    Ok(output.into_inner())
}

#[pymodule]
fn orbit_diff_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_diff, m)?)?;
    m.add_function(wrap_pyfunction!(compute_binary_diff, m)?)?;
    m.add_function(wrap_pyfunction!(apply_binary_patch_rs, m)?)?;
    Ok(())
}
