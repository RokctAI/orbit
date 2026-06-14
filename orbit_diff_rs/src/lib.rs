use pyo3::prelude::*;
use similar::udiff::UnifiedDiff;

#[pyfunction]
#[pyo3(signature = (a, b, from_file="", to_file=""))]
fn compute_diff(a: &str, b: &str, from_file: &str, to_file: &str) -> PyResult<String> {
    let diff = UnifiedDiff::from_str(a, b, 3, Some((from_file, to_file)));
    Ok(diff.to_string())
}

#[pymodule]
fn orbit_diff_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_diff, m)?)?;
    Ok(())
}
