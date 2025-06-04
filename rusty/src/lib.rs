use pyo3::prelude::*;
use std::env;
use std::sync::OnceLock;

/// Environment variable descriptor that mimics Python's property behavior
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

    /// Descriptor protocol implementation
    fn __get__(&self, _obj: Option<&PyAny>, _type: Option<&PyAny>) -> PyResult<PyObject> {
        // Handle both instance access and class-level access
        match (_obj, _type) {
            (Some(obj), _) => {
                let py = obj.py();
                self.get_env_value(py)
            },
            (None, Some(type_obj)) => {
                let py = type_obj.py();
                self.get_env_value(py)
            },
            (None, None) => {
                // Fallback: try to get current Python context
                Python::with_gil(|py| self.get_env_value(py))
            }
        }
    }
    
    /// Helper method to get environment variable value
    fn get_env_value(&self, py: Python) -> PyResult<PyObject> {
        match env::var(&self.env_name) {
            Ok(val) => Ok(val.into_py(py)),
            Err(_) => match &self.default_value {
                Some(val) => Ok(val.clone().into_py(py)),
                None => Ok(py.None()),
            },
        }
    }
}

/// Configuration singleton that provides access to environment variables
#[pyclass(module = "rusty")]
#[derive(Clone)]
pub struct Config {
    // Empty struct - all properties are descriptors
}

static CONFIG_INSTANCE: OnceLock<Py<Config>> = OnceLock::new();

#[pymethods]
impl Config {
    #[new]
    fn py_new() -> Self {
        Config {}
    }
    
    /// Get the singleton instance
    #[staticmethod]
    fn instance(py: Python) -> PyResult<Py<Config>> {
        match CONFIG_INSTANCE.get() {
            Some(instance) => Ok(instance.clone()),
            None => {
                let instance = Py::new(py, Config {})?;
                // Note: This could technically race, but Python GIL prevents it
                let _ = CONFIG_INSTANCE.set(instance.clone());
                Ok(instance)
            }
        }
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
    let snapshot_bucket = Py::new(py, DynamicEnvVar::new("SNAPSHOT_BUCKET".to_string(), None))?;

    // Add descriptors to Config class
    let config_type = py.get_type::<Config>();
    config_type.setattr("builder_token", builder_token)?;
    config_type.setattr("agent_type", agent_type)?;
    config_type.setattr("snapshot_bucket", snapshot_bucket)?;
    
    // Create and expose the singleton CONFIG instance
    let config_instance = Config::instance(py)?;
    m.add("CONFIG", config_instance)?;
    
    Ok(())
}
