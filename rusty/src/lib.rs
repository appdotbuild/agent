use pyo3::prelude::*;
use std::env;

#[pyclass]
struct DynamicEnvVar {
    env_name: String,
    default_value: Option<String>,
}

#[pymethods]
impl DynamicEnvVar {
    #[new]
    fn new(env_name: String, default_value: Option<String>) -> Self {
        Self {
            env_name,
            default_value,
        }
    }

    fn __get__(&self, _obj: PyObject, _type: PyObject, py: Python) -> PyResult<PyObject> {
        match env::var(&self.env_name) {
            Ok(val) => Ok(val.into_py(py)),
            Err(_) => match &self.default_value {
                Some(val) => Ok(val.clone().into_py(py)),
                None => Ok(py.None()),
            },
        }
    }
}

#[pyclass(module = "rusty")]
#[derive(Clone)]
pub struct Config {}

#[pymethods]
impl Config {
    #[new]
    fn py_new() -> Self {
        Config {}
    }
}

#[pymodule]
fn rusty(py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_class::<Config>()?;
    m.add_class::<DynamicEnvVar>()?;

    // Create the descriptor objects
    let builder_token = Py::new(py, DynamicEnvVar::new("BUILDER_TOKEN".to_string(), None))?;
    let agent_type = Py::new(
        py,
        DynamicEnvVar::new("CODEGEN_AGENT".to_string(), Some("trpc_agent".to_string())),
    )?;

    // Add descriptors to Config class
    let config_type = py.get_type::<Config>();
    config_type.setattr("builder_token", builder_token)?;
    config_type.setattr("agent_type", agent_type)?;
    
    Ok(())
}
