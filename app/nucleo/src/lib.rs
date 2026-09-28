//! Núcleo sin interfaz del instalador de Tarkor.
//!
//! Vive separado de la app de Tauri para poder probarlo sin webview y comprobar que compila para
//! Windows desde Linux. Cada módulo corresponde a un documento de `docs/`:
//!
//! - [`equipo`]: análisis del equipo (docs/09, "Qué se detecta").
//! - [`perfiles`]: perfiles de IA y cálculo del máximo seguro (docs/09).
//! - [`config`]: `config.json` en la carpeta de datos (docs/07 y docs/09, "Dónde se guarda").

pub mod config;
pub mod equipo;
pub mod perfiles;
