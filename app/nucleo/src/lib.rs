//! Núcleo sin interfaz del instalador de Tarkor.
//!
//! Vive separado de la app de Tauri para poder probarlo sin webview y comprobar que compila para
//! Windows desde Linux. Cada módulo corresponde a un documento de `docs/`:
//!
//! - [`catalogo`]: modelos, perfiles y reglas, leídos de `catalogo/catalogo.json` (docs/12).
//! - [`equipo`]: análisis del equipo (docs/09, "Qué se detecta").
//! - [`perfiles`]: evaluación de perfiles y cálculo del máximo seguro (docs/09).
//! - [`rendimiento`]: ajustes de Ollama y del backend para cada equipo y perfil (docs/12).
//! - [`config`]: `config.json` en la carpeta de datos (docs/07 y docs/09, "Dónde se guarda").

pub mod catalogo;
pub mod config;
pub mod equipo;
pub mod motor;
pub mod ollama;
pub mod perfiles;
pub mod procesos;
pub mod rendimiento;
