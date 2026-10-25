//! Los modelos tal como los guarda Ollama en su carpeta (`OLLAMA_MODELS`, docs/12), para
//! «Reparar» (`INS-49`, docs/11).
//!
//! Cada modelo tiene un manifiesto en `manifests/<registro>/<espacio>/<nombre>/<etiqueta>` que
//! lista sus capas por suma, y cada capa vive en `blobs/sha256-<suma>`. `/api/pull` no vuelve a
//! comprobar las capas que ya tiene: aquí se comprueban todas y se borran las dañadas, y el
//! `/api/pull` de después solo baja esas (el «healing» de itch.io).

use crate::motor::sha256;
use serde_json::Value;
use std::collections::BTreeSet;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Debug)]
pub enum Error {
    Cancelado,
    Disco(io::Error),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Cancelado => write!(f, "Reparación cancelada. Lo ya comprobado sigue en su sitio."),
            Error::Disco(e) => write!(
                f,
                "No se pudieron comprobar los modelos ({e}). Comprueba que la carpeta de la IA sigue en su sitio y que se puede escribir en ella."
            ),
        }
    }
}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Error::Disco(e)
    }
}

/// Carpeta de los modelos dentro de la de la IA (`OLLAMA_MODELS`).
pub fn carpeta(ia: &Path) -> PathBuf {
    ia.join("modelos")
}

/// Ruta del manifiesto: `qwen2.5:7b` → `manifests/registry.ollama.ai/library/qwen2.5/7b`; sin
/// etiqueta es `latest`, y sin espacio, `library`. `None` si el nombre no es de un modelo (una
/// parte vacía, `.`, `..` u otros caracteres): nunca sale de la carpeta.
pub fn manifiesto(carpeta: &Path, modelo: &str) -> Option<PathBuf> {
    let (nombre, etiqueta) = match modelo.rsplit_once(':') {
        Some((n, e)) if !e.contains('/') => (n, e),
        _ => (modelo, "latest"),
    };
    let partes: Vec<&str> = nombre.split('/').collect();
    let valida = |p: &str| !p.is_empty() && p != "." && p != ".." && p.bytes().all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b));
    if !partes.iter().chain([&etiqueta]).all(|p| valida(p)) {
        return None;
    }
    let mut ruta = carpeta.join("manifests");
    match partes.as_slice() {
        [n] => ruta.extend(["registry.ollama.ai", "library", n]),
        [espacio, n] => ruta.extend(["registry.ollama.ai", espacio, n]),
        otras => ruta.extend(otras),
    }
    Some(ruta.join(etiqueta))
}

/// Comprueba los modelos y borra lo dañado para que `/api/pull` lo vuelva a bajar. Un manifiesto
/// que no se entiende se borra (el modelo se pide entero); luego se suma cada capa de
/// `blobs/` (su nombre es su suma, así que sirve también para las capas de un manifiesto
/// ilegible o compartidas entre modelos) y se borra la que no coincide. Devuelve cuántos archivos
/// faltan ahora, cada uno contado una vez: los borrados y las capas que ya faltaban. Un modelo
/// que no está no es un error: `/api/pull` lo bajará. `progreso` recibe (capas comprobadas, total).
pub fn reparar(carpeta: &Path, modelos: &[String], cancelar: &AtomicBool, progreso: &mut dyn FnMut(u64, u64)) -> Result<usize, Error> {
    let mut faltan = 0;
    let mut usadas = BTreeSet::new();
    for modelo in modelos {
        let Some(ruta) = manifiesto(carpeta, modelo) else { continue };
        let Ok(texto) = fs::read_to_string(&ruta) else { continue };
        match capas(&texto) {
            Some(sumas) => usadas.extend(sumas),
            None => {
                fs::remove_file(&ruta)?;
                faltan += 1;
            }
        }
    }
    let blobs = carpeta.join("blobs");
    let mut presentes = Vec::new();
    match fs::read_dir(&blobs) {
        Ok(entradas) => {
            for e in entradas {
                let e = e?;
                let nombre = e.file_name().to_string_lossy().into_owned();
                if let Some(suma) = nombre.strip_prefix("sha256-").filter(|s| es_suma(s)) {
                    if e.file_type()?.is_file() {
                        presentes.push(suma.to_ascii_lowercase());
                    }
                }
            }
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => {}
        Err(e) => return Err(e.into()),
    }
    presentes.sort();
    // Las capas que usan los modelos y no están: el modelo no estaba completo.
    faltan += usadas.iter().filter(|s| presentes.binary_search(s).is_err()).count();
    let total = presentes.len() as u64;
    for (i, suma) in presentes.iter().enumerate() {
        if cancelar.load(Ordering::Relaxed) {
            return Err(Error::Cancelado);
        }
        progreso(i as u64, total);
        let blob = blobs.join(format!("sha256-{suma}"));
        if sha256(&blob)? != *suma {
            fs::remove_file(&blob)?;
            faltan += 1;
        }
    }
    progreso(total, total);
    Ok(faltan)
}

fn es_suma(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit())
}

/// Sumas de la configuración y de las capas (`sha256:<hex>` → `<hex>`); `None` si el manifiesto
/// no se entiende.
fn capas(manifiesto: &str) -> Option<Vec<String>> {
    let v: Value = serde_json::from_str(manifiesto).ok()?;
    let mut sumas = Vec::new();
    for capa in std::iter::once(&v["config"]).chain(v["layers"].as_array()?) {
        let hex = capa["digest"].as_str()?.strip_prefix("sha256:")?;
        if !es_suma(hex) {
            return None;
        }
        sumas.push(hex.to_ascii_lowercase());
    }
    Some(sumas)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ruta_del_manifiesto_segun_el_nombre() {
        let c = Path::new("m");
        let m = |r: &str| c.join("manifests").join(r);
        assert_eq!(manifiesto(c, "qwen2.5:7b"), Some(m("registry.ollama.ai/library/qwen2.5/7b")));
        assert_eq!(manifiesto(c, "nomic-embed-text"), Some(m("registry.ollama.ai/library/nomic-embed-text/latest")));
        assert_eq!(manifiesto(c, "usuaria/modelo:q4"), Some(m("registry.ollama.ai/usuaria/modelo/q4")));
        assert_eq!(manifiesto(c, "hf.co/org/modelo"), Some(m("hf.co/org/modelo/latest")));
    }

    #[test]
    fn un_nombre_raro_no_sale_de_la_carpeta() {
        let c = Path::new("m");
        for raro in ["../../fuera", "a/../b", "qwen:..", "/abs", "a//b", "a\\b", "", "qwen:"] {
            assert_eq!(manifiesto(c, raro), None, "{raro}");
        }
    }

    fn rep(carpeta: &Path, modelos: &[&str]) -> Result<usize, Error> {
        let modelos: Vec<String> = modelos.iter().map(|m| m.to_string()).collect();
        reparar(carpeta, &modelos, &AtomicBool::new(false), &mut |_, _| {})
    }

    /// Guarda un modelo con dos capas y devuelve la ruta de cada una.
    fn guardar(carpeta: &Path, modelo: &str) -> Vec<PathBuf> {
        let mut capas = Vec::new();
        let mut digests = Vec::new();
        fs::create_dir_all(carpeta.join("blobs")).unwrap();
        for contenido in ["config", "pesos"] {
            let tmp = carpeta.join("tmp");
            fs::write(&tmp, contenido).unwrap();
            let suma = sha256(&tmp).unwrap();
            let blob = carpeta.join("blobs").join(format!("sha256-{suma}"));
            fs::rename(&tmp, &blob).unwrap();
            capas.push(blob);
            digests.push(format!("sha256:{suma}"));
        }
        let ruta = manifiesto(carpeta, modelo).unwrap();
        fs::create_dir_all(ruta.parent().unwrap()).unwrap();
        let json = serde_json::json!({ "config": { "digest": digests[0] }, "layers": [{ "digest": digests[1] }] });
        fs::write(ruta, json.to_string()).unwrap();
        capas
    }

    #[test]
    fn un_modelo_sano_no_se_toca() {
        let dir = tempfile::tempdir().unwrap();
        let capas = guardar(dir.path(), "qwen2.5:7b");
        assert_eq!(rep(dir.path(), &["qwen2.5:7b"]).unwrap(), 0);
        assert!(capas.iter().all(|c| c.exists()));
    }

    #[test]
    fn una_capa_danada_se_borra_y_las_sanas_no() {
        let dir = tempfile::tempdir().unwrap();
        let capas = guardar(dir.path(), "qwen2.5:7b");
        fs::write(&capas[1], "pesas").unwrap();
        assert_eq!(rep(dir.path(), &["qwen2.5:7b"]).unwrap(), 1);
        assert!(capas[0].exists());
        assert!(!capas[1].exists());
    }

    #[test]
    fn una_capa_que_falta_cuenta_como_danada() {
        let dir = tempfile::tempdir().unwrap();
        let capas = guardar(dir.path(), "nomic-embed-text");
        fs::remove_file(&capas[0]).unwrap();
        assert_eq!(rep(dir.path(), &["nomic-embed-text"]).unwrap(), 1);
    }

    #[test]
    fn un_manifiesto_ilegible_se_borra() {
        let dir = tempfile::tempdir().unwrap();
        guardar(dir.path(), "qwen2.5:7b");
        let ruta = manifiesto(dir.path(), "qwen2.5:7b").unwrap();
        fs::write(&ruta, "{\"layers\":[{\"digest\":\"sha256:corta\"}]}").unwrap();
        assert_eq!(rep(dir.path(), &["qwen2.5:7b"]).unwrap(), 1);
        assert!(!ruta.exists());
    }

    #[test]
    fn un_modelo_que_no_esta_no_es_un_error() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(rep(dir.path(), &["qwen3.5:9b"]).unwrap(), 0);
    }

    #[test]
    fn una_capa_compartida_danada_cuenta_una_vez() {
        let dir = tempfile::tempdir().unwrap();
        let capas = guardar(dir.path(), "qwen2.5:7b");
        guardar(dir.path(), "qwen2.5:7b-copia");
        fs::write(&capas[1], "pesas").unwrap();
        assert_eq!(rep(dir.path(), &["qwen2.5:7b", "qwen2.5:7b-copia"]).unwrap(), 1);
    }

    #[test]
    fn las_capas_de_un_manifiesto_ilegible_tambien_se_comprueban() {
        let dir = tempfile::tempdir().unwrap();
        let capas = guardar(dir.path(), "qwen2.5:7b");
        fs::write(manifiesto(dir.path(), "qwen2.5:7b").unwrap(), "no es json").unwrap();
        fs::write(&capas[1], "pesas").unwrap();
        assert_eq!(rep(dir.path(), &["qwen2.5:7b"]).unwrap(), 2);
        assert!(capas[0].exists() && !capas[1].exists());
    }

    #[test]
    fn la_comprobacion_de_los_modelos_se_puede_cancelar() {
        let dir = tempfile::tempdir().unwrap();
        guardar(dir.path(), "qwen2.5:7b");
        let r = reparar(dir.path(), &["qwen2.5:7b".into()], &AtomicBool::new(true), &mut |_, _| {});
        assert!(matches!(r, Err(Error::Cancelado)), "{r:?}");
    }
}
