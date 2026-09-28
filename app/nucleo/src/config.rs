//! `config.json` y carpetas de la app (docs/07, "Dónde vive cada cosa"; docs/09, "Dónde se
//! guarda").
//!
//! Los datos viven fuera de la carpeta de la app para que actualizar o reinstalar nunca toque las
//! partidas.

use crate::equipo::Equipo;
use crate::perfiles::UsoCpu;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

pub const VERSION_CONFIG: u32 = 1;
const NOMBRE_CONFIG: &str = "config.json";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Config {
    pub version: u32,
    /// Casilla del paso 2 del asistente.
    pub consentimiento_aceptado: bool,
    /// `None` = todavía no se ha preguntado; `Some(false)` = eligió "a mano".
    pub permiso_analisis: Option<bool>,
    pub equipo: Option<Equipo>,
    /// Id de un perfil del catálogo.
    pub perfil: Option<String>,
    pub uso_cpu: UsoCpu,
    pub modelos_descargados: Vec<String>,
    /// Último paso alcanzado, para continuar si se cerró la app a medias.
    pub paso_asistente: u8,
    pub asistente_completado: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            version: VERSION_CONFIG,
            consentimiento_aceptado: false,
            permiso_analisis: None,
            equipo: None,
            perfil: None,
            uso_cpu: UsoCpu::default(),
            modelos_descargados: Vec::new(),
            paso_asistente: 1,
            asistente_completado: false,
        }
    }
}

impl Config {
    /// Lee la configuración. Si no existe, la de por defecto. Si está corrupta, se aparta como
    /// `config.json.corrupto` y se empieza de cero en vez de impedir que la app arranque.
    pub fn cargar(carpeta_datos: &Path) -> Config {
        let ruta = carpeta_datos.join(NOMBRE_CONFIG);
        match fs::read_to_string(&ruta) {
            Ok(texto) => serde_json::from_str(&texto).unwrap_or_else(|_| {
                let _ = fs::rename(&ruta, ruta.with_extension("json.corrupto"));
                Config::default()
            }),
            Err(_) => Config::default(),
        }
    }

    /// Guarda de forma atómica (fichero temporal + renombrado): un corte de luz a mitad de
    /// escritura no deja un `config.json` a medias.
    pub fn guardar(&self, carpeta_datos: &Path) -> io::Result<()> {
        fs::create_dir_all(carpeta_datos)?;
        let ruta = carpeta_datos.join(NOMBRE_CONFIG);
        let tmp = carpeta_datos.join(format!("{NOMBRE_CONFIG}.tmp"));
        let texto = serde_json::to_string_pretty(self).map_err(io::Error::other)?;
        fs::write(&tmp, texto)?;
        fs::rename(&tmp, &ruta)
    }
}

/// Carpetas de la app según la plataforma (tabla de docs/07).
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Rutas {
    /// Partidas y `config.json`.
    pub datos: PathBuf,
    /// Ollama y modelos.
    pub ia: PathBuf,
    pub registros: PathBuf,
}

impl Rutas {
    /// `TARKOR_DATOS` sustituye la carpeta base (para pruebas y para quien quiera moverla).
    pub fn del_sistema() -> Rutas {
        if let Some(base) = std::env::var_os("TARKOR_DATOS").map(PathBuf::from) {
            return Rutas { ia: base.join("ia"), registros: base.join("registros"), datos: base };
        }
        Self::por_plataforma(|k| std::env::var_os(k).map(PathBuf::from))
    }

    fn por_plataforma(env: impl Fn(&str) -> Option<PathBuf>) -> Rutas {
        if cfg!(windows) {
            let roaming = env("APPDATA").unwrap_or_else(|| PathBuf::from("."));
            let local = env("LOCALAPPDATA").unwrap_or_else(|| roaming.clone());
            Rutas {
                datos: roaming.join("Tarkor"),
                ia: local.join("Tarkor").join("ia"),
                registros: local.join("Tarkor").join("registros"),
            }
        } else {
            let home = env("HOME").unwrap_or_else(|| PathBuf::from("."));
            let data = env("XDG_DATA_HOME").unwrap_or_else(|| home.join(".local/share"));
            let state = env("XDG_STATE_HOME").unwrap_or_else(|| home.join(".local/state"));
            Rutas {
                datos: data.join("tarkor"),
                ia: data.join("tarkor").join("ia"),
                registros: state.join("tarkor").join("registros"),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sin_fichero_da_la_de_por_defecto() {
        let dir = tempfile::tempdir().unwrap();
        let c = Config::cargar(dir.path());
        assert_eq!(c, Config::default());
        assert!(!c.asistente_completado);
        assert_eq!(c.paso_asistente, 1);
    }

    #[test]
    fn guarda_y_carga_igual() {
        let dir = tempfile::tempdir().unwrap();
        let c = Config {
            consentimiento_aceptado: true,
            permiso_analisis: Some(false),
            perfil: Some("equilibrado".into()),
            uso_cpu: UsoCpu::Alto,
            modelos_descargados: vec!["qwen2.5:7b".into()],
            paso_asistente: 5,
            ..Config::default()
        };
        c.guardar(&dir.path().join("sub")).unwrap();
        assert_eq!(Config::cargar(&dir.path().join("sub")), c);
    }

    #[test]
    fn campos_nuevos_o_ausentes_toman_valor_por_defecto() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join(NOMBRE_CONFIG), r#"{"version":1,"perfil":"maximo"}"#).unwrap();
        let c = Config::cargar(dir.path());
        assert_eq!(c.perfil.as_deref(), Some("maximo"));
        assert_eq!(c.uso_cpu, UsoCpu::Moderado);
    }

    #[test]
    fn corrupto_se_aparta_y_no_bloquea() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join(NOMBRE_CONFIG), "{ esto no es json").unwrap();
        assert_eq!(Config::cargar(dir.path()), Config::default());
        assert!(dir.path().join("config.json.corrupto").exists());
    }

    #[test]
    fn formato_json_en_camel_case() {
        let json = serde_json::to_value(Config { perfil: Some("ligero".into()), ..Config::default() }).unwrap();
        assert_eq!(json["perfil"], "ligero");
        assert_eq!(json["asistenteCompletado"], false);
        assert_eq!(json["usoCpu"], "moderado");
    }

    #[test]
    fn rutas_linux() {
        if cfg!(windows) {
            return;
        }
        let r = Rutas::por_plataforma(|k| (k == "HOME").then(|| PathBuf::from("/home/ana")));
        assert_eq!(r.datos, PathBuf::from("/home/ana/.local/share/tarkor"));
        assert_eq!(r.ia, PathBuf::from("/home/ana/.local/share/tarkor/ia"));
        assert_eq!(r.registros, PathBuf::from("/home/ana/.local/state/tarkor/registros"));
    }
}
