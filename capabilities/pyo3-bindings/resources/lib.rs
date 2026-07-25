//! Thin Python adapter. Domain behavior remains in the pure core crate.

use pyo3::prelude::*;

#[pyfunction]
fn native_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pyfunction]
fn add(py: Python<'_>, left: i64, right: i64) -> i64 {
    py.detach(move || {{ module_name }}_core::add(left, right))
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(native_version, module)?)?;
    module.add_function(wrap_pyfunction!(add, module)?)?;
    Ok(())
}
