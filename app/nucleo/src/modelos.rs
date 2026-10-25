//! Los modelos tal como los guarda Ollama en su carpeta (`OLLAMA_MODELS`, docs/12), para
//! «Reparar» (`INS-49`, docs/11).
//!
//! Cada modelo tiene un manifiesto en `manifests/<registro>/<espacio>/<nombre>/<etiqueta>` que
//! lista sus capas por suma, y cada capa vive en `blobs/sha256-<suma>`. `/api/pull` no vuelve a
//! comprobar las capas que ya tiene: aquí se comprueban todas y se borran las dañadas, y el
//! `/api/pull` de después solo baja esas (el «healing» de itch.io).

use crate::motor::sha256;
use serde_json::Value;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

/// Ruta del manifiesto: `qwen2.5:7b` → `manifests/registry.ollama.ai/library/qwen2.5/7b`; sin
/// etiqueta es `latest`, y sin espacio, `library`.
pub fn manifiesto(carpeta: &Path, modelo: &str) -> PathBuf {
    let (nombre, etiqueta) = match modelo.rsplit_once(':') {
        Some((n, e)) if !e.contains('/') => (n, e),
        _ => (modelo, "latest"),
    };
    let partes: Vec<&str> = nombre.split('/').collect();
    let mut ruta = carpeta.join("manifests");
    match partes.as_slice() {
        [n] => ruta.extend(["registry.ollama.ai", "library", n]),
        [espacio, n] => ruta.extend(["registry.ollama.ai", espacio, n]),
        otras => ruta.extend(otras),
    }
    ruta.join(etiqueta)
}

/// Comprueba la suma de cada capa del modelo y borra las que no coinciden. Si el manifiesto está
/// dañado, lo borra a él (y el modelo se vuelve a pedir entero). Devuelve cuántos archivos borró;
/// un modelo que no está no es un error: `/api/pull` lo bajará.
pub fn borrar_capas_danadas(carpeta: &Path, modelo: &str) -> io::Result<usize> {
    let ruta = manifiesto(carpeta, modelo);
    let Ok(texto) = fs::read_to_string(&ruta) else { return Ok(0) };
    let Some(sumas) = capas(&texto) else {
        fs::remove_file(&ruta)?;
        return Ok(1);
    };
    let mut borradas = 0;
    for suma in sumas {
        let blob = carpeta.join("blobs").join(format!("sha256-{suma}"));
        match sha256(&blob) {
            Ok(s) if s == suma => {}
            Ok(_) => {
                fs::remove_file(&blob)?;
                borradas += 1;
            }
            // Una capa que falta también se cuenta: el modelo no estaba completo.
            Err(e) if e.kind() == io::ErrorKind::NotFound => borradas += 1,
            Err(e) => return Err(e),
        }
    }
    Ok(borradas)
}

/// Sumas de la configuración y de las capas (`sha256:<hex>` → `<hex>`); `None` si el manifiesto
/// no se entiende.
fn capas(manifiesto: &str) -> Option<Vec<String>> {
    let v: Value = serde_json::from_str(manifiesto).ok()?;
    let mut sumas = Vec::new();
    for capa in std::iter::once(&v["config"]).chain(v["layers"].as_array()?) {
        let hex = capa["digest"].as_str()?.strip_prefix("sha256:")?;
        if hex.len() != 64 || !hex.bytes().all(|b| b.is_ascii_hexdigit()) {
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
        assert_eq!(manifiesto(c, "qwen2.5:7b"), m("registry.ollama.ai/library/qwen2.5/7b"));
        assert_eq!(manifiesto(c, "nomic-embed-text"), m("registry.ollama.ai/library/nomic-embed-text/latest"));
        assert_eq!(manifiesto(c, "usuaria/modelo:q4"), m("registry.ollama.ai/usuaria/modelo/q4"));
        assert_eq!(manifiesto(c, "hf.co/org/modelo"), m("hf.co/org/modelo/latest"));
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
        let ruta = manifiesto(carpeta, modelo);
        fs::create_dir_all(ruta.parent().unwrap()).unwrap();
        let json = serde_json::json!({ "config": { "digest": digests[0] }, "layers": [{ "digest": digests[1] }] });
        fs::write(ruta, json.to_string()).unwrap();
        capas
    }

    #[test]
    fn un_modelo_sano_no_se_toca() {
        let dir = tempfile::tempdir().unwrap();
        let capas = guardar(dir.path(), "qwen2.5:7b");
        assert_eq!(borrar_capas_danadas(dir.path(), "qwen2.5:7b").unwrap(), 0);
        assert!(capas.iter().all(|c| c.exists()));
    }

    #[test]
    fn una_capa_danada_se_borra_y_las_sanas_no() {
        let dir = tempfile::tempdir().unwrap();
        let capas = guardar(dir.path(), "qwen2.5:7b");
        fs::write(&capas[1], "pesas").unwrap();
        assert_eq!(borrar_capas_danadas(dir.path(), "qwen2.5:7b").unwrap(), 1);
        assert!(capas[0].exists());
        assert!(!capas[1].exists());
    }

    #[test]
    fn una_capa_que_falta_cuenta_como_danada() {
        let dir = tempfile::tempdir().unwrap();
        let capas = guardar(dir.path(), "nomic-embed-text");
        fs::remove_file(&capas[0]).unwrap();
        assert_eq!(borrar_capas_danadas(dir.path(), "nomic-embed-text").unwrap(), 1);
    }

    #[test]
    fn un_manifiesto_ilegible_se_borra() {
        let dir = tempfile::tempdir().unwrap();
        guardar(dir.path(), "qwen2.5:7b");
        let ruta = manifiesto(dir.path(), "qwen2.5:7b");
        fs::write(&ruta, "{\"layers\":[{\"digest\":\"sha256:corta\"}]}").unwrap();
        assert_eq!(borrar_capas_danadas(dir.path(), "qwen2.5:7b").unwrap(), 1);
        assert!(!ruta.exists());
    }

    #[test]
    fn un_modelo_que_no_esta_no_es_un_error() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(borrar_capas_danadas(dir.path(), "qwen3.5:9b").unwrap(), 0);
    }
}
