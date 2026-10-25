//! Espacio libre en disco y movimiento de la carpeta de la IA (docs/07, "Dónde vive cada cosa").
//!
//! El motor de IA y los modelos son lo más pesado de la instalación, así que el jugador puede
//! elegir en qué disco viven y moverlos después (docs/11, pantalla 4). La carpeta de las
//! partidas (`datos`) no se mueve nunca desde aquí.

use std::fs;
use std::io;
use std::path::{Component, Path, PathBuf};
use sysinfo::Disks;

const MB: u64 = 1024 * 1024;

/// Espacio libre, en MB, del disco cuyo punto de montaje es el prefijo más largo de `ruta`.
/// Si la ruta todavía no existe se sube hasta el primer antepasado que exista. Devuelve 0 si no
/// se encuentra el disco.
pub fn espacio_libre_mb(ruta: &Path) -> u64 {
    let disks = Disks::new_with_refreshed_list();
    let ruta = absoluta(ruta);
    disks
        .list()
        .iter()
        .filter(|d| ruta.starts_with(d.mount_point()))
        .max_by_key(|d| d.mount_point().as_os_str().len())
        .map(|d| d.available_space() / MB)
        .unwrap_or(0)
}

/// Ruta canónica aunque no exista del todo: se canoniza el primer antepasado que exista y se le
/// añade el resto. Sirve para comparar rutas con enlaces simbólicos de por medio.
fn absoluta(ruta: &Path) -> PathBuf {
    let mut resto: Vec<&std::ffi::OsStr> = Vec::new();
    let mut actual = ruta;
    loop {
        if actual.exists() {
            if let Ok(base) = actual.canonicalize() {
                let mut fin = base;
                for parte in resto.iter().rev() {
                    fin.push(parte);
                }
                return fin;
            }
        }
        match (actual.parent(), actual.file_name()) {
            (Some(padre), Some(nombre)) => {
                resto.push(nombre);
                actual = padre;
            }
            _ => return ruta.to_path_buf(),
        }
    }
}

/// Sin `.` ni `..` ni enlaces: lo que hace falta para decidir si una carpeta está dentro de otra.
fn normalizada(ruta: &Path) -> PathBuf {
    let mut fin = PathBuf::new();
    for c in absoluta(ruta).components() {
        match c {
            Component::CurDir => {}
            Component::ParentDir => {
                fin.pop();
            }
            otro => fin.push(otro),
        }
    }
    fin
}

fn tamano_bytes(ruta: &Path) -> io::Result<u64> {
    let mut total = 0;
    for entrada in fs::read_dir(ruta)? {
        let entrada = entrada?;
        let meta = entrada.metadata()?;
        total += if meta.is_dir() { tamano_bytes(&entrada.path())? } else { meta.len() };
    }
    Ok(total)
}

fn copiar_recursivo(origen: &Path, destino: &Path) -> io::Result<()> {
    fs::create_dir_all(destino)?;
    for entrada in fs::read_dir(origen)? {
        let entrada = entrada?;
        let a = destino.join(entrada.file_name());
        if entrada.file_type()?.is_dir() {
            copiar_recursivo(&entrada.path(), &a)?;
        } else {
            fs::copy(entrada.path(), &a)?;
        }
    }
    Ok(())
}

/// Mueve la carpeta de la IA de `origen` a `destino`, con mensajes pensados para el jugador.
///
/// - Si `origen` no existe (nada instalado todavía), solo se crea `destino`.
/// - `destino` no puede ser `origen` ni estar dentro, y debe no existir o estar vacío.
/// - Antes de tocar nada se comprueba que lo de `origen` cabe en el disco de `destino`.
/// - Se intenta renombrar (instantáneo en el mismo disco); si no se puede (otro disco), se copia
///   y después se borra el origen. Si la copia falla, se borra la copia parcial y el origen
///   queda intacto.
pub fn mover_carpeta(origen: &Path, destino: &Path) -> Result<(), String> {
    mover_con(origen, destino, |a, b| fs::rename(a, b), espacio_libre_mb)
}

fn mover_con(
    origen: &Path,
    destino: &Path,
    renombrar: impl Fn(&Path, &Path) -> io::Result<()>,
    espacio: impl Fn(&Path) -> u64,
) -> Result<(), String> {
    let (o, d) = (normalizada(origen), normalizada(destino));
    if o == d {
        return Err("La carpeta nueva es la misma que la actual.".into());
    }
    if d.starts_with(&o) {
        return Err("La carpeta nueva no puede estar dentro de la actual. Elige otro sitio.".into());
    }
    if destino.exists() {
        let vacia = destino.is_dir() && fs::read_dir(destino).map_err(|e| e.to_string())?.next().is_none();
        if !vacia {
            return Err(format!("La carpeta {} ya existe y no está vacía. Elige otra.", destino.display()));
        }
    }
    let falla = |e: io::Error| format!("No se pudo preparar la carpeta {}: {e}", destino.display());
    if !origen.exists() {
        return fs::create_dir_all(destino).map_err(falla);
    }
    let necesario = tamano_bytes(origen).map_err(|e| format!("No se pudo medir la carpeta actual: {e}"))?;
    let libre = espacio(destino);
    if necesario.div_ceil(MB) > libre {
        return Err(format!(
            "No hay espacio suficiente en el disco de {}: hacen falta {} MB y hay {libre} MB libres.",
            destino.display(),
            necesario.div_ceil(MB)
        ));
    }
    if let Some(padre) = destino.parent() {
        fs::create_dir_all(padre).map_err(falla)?;
    }
    // En Windows renombrar sobre una carpeta existente (aunque esté vacía) falla.
    if destino.exists() {
        fs::remove_dir(destino).map_err(falla)?;
    }
    if renombrar(origen, destino).is_ok() {
        return Ok(());
    }
    if let Err(e) = copiar_recursivo(origen, destino) {
        let _ = fs::remove_dir_all(destino);
        return Err(format!("No se pudo copiar a {}: {e}. La carpeta actual sigue como estaba.", destino.display()));
    }
    fs::remove_dir_all(origen).map_err(|e| {
        format!("Se copió a {}, pero no se pudo borrar la carpeta anterior ({}): {e}. Bórrala a mano.", destino.display(), origen.display())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn con_contenido(dir: &Path) -> PathBuf {
        let o = dir.join("origen");
        fs::create_dir_all(o.join("modelos/sub")).unwrap();
        fs::write(o.join("a.txt"), "hola").unwrap();
        fs::write(o.join("modelos/sub/b.bin"), vec![7u8; 4096]).unwrap();
        o
    }

    fn rename_falla(_: &Path, _: &Path) -> io::Result<()> {
        Err(io::Error::other("otro disco"))
    }

    #[test]
    fn espacio_libre_de_ruta_inexistente_sube_al_antepasado() {
        let dir = tempfile::tempdir().unwrap();
        let futura = dir.path().join("no/existe/todavia");
        let real = espacio_libre_mb(dir.path());
        assert!(real > 0);
        let de_futura = espacio_libre_mb(&futura);
        assert!(de_futura > 0, "una ruta que no existe debe dar el espacio de su disco");
        // Mismo disco: dos lecturas pueden variar un poco, no a cero.
        assert!(de_futura.abs_diff(real) < 100, "{de_futura} frente a {real}");
    }

    #[test]
    fn mueve_con_rename() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        let d = dir.path().join("nueva/Tarkor IA");
        mover_carpeta(&o, &d).unwrap();
        assert!(!o.exists());
        assert_eq!(fs::read_to_string(d.join("a.txt")).unwrap(), "hola");
        assert_eq!(fs::read(d.join("modelos/sub/b.bin")).unwrap().len(), 4096);
    }

    #[test]
    fn mueve_sobre_destino_vacio() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        let d = dir.path().join("vacia");
        fs::create_dir(&d).unwrap();
        mover_carpeta(&o, &d).unwrap();
        assert!(d.join("a.txt").exists() && !o.exists());
    }

    #[test]
    fn si_el_rename_falla_copia_y_borra_el_origen() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        let d = dir.path().join("otro-disco");
        mover_con(&o, &d, rename_falla, espacio_libre_mb).unwrap();
        assert!(!o.exists());
        assert_eq!(fs::read_to_string(d.join("a.txt")).unwrap(), "hola");
        assert!(d.join("modelos/sub/b.bin").exists());
    }

    #[test]
    fn origen_inexistente_solo_crea_el_destino() {
        let dir = tempfile::tempdir().unwrap();
        let d = dir.path().join("x/y");
        mover_carpeta(&dir.path().join("nada"), &d).unwrap();
        assert!(d.is_dir());
    }

    #[test]
    fn rechaza_la_misma_carpeta_y_una_dentro_de_la_otra() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        let e = mover_carpeta(&o, &o).unwrap_err();
        assert!(e.contains("la misma"), "{e}");
        let e = mover_carpeta(&o, &o.join("modelos/nueva")).unwrap_err();
        assert!(e.contains("dentro de la actual"), "{e}");
        let e = mover_carpeta(&o, &dir.path().join("origen/../origen/x")).unwrap_err();
        assert!(e.contains("dentro de la actual"), "{e}");
        assert!(o.join("a.txt").exists());
    }

    #[test]
    fn rechaza_destino_con_contenido() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        let d = dir.path().join("ocupada");
        fs::create_dir(&d).unwrap();
        fs::write(d.join("mia.txt"), "no tocar").unwrap();
        let e = mover_carpeta(&o, &d).unwrap_err();
        assert!(e.contains("no está vacía"), "{e}");
        assert!(o.join("a.txt").exists() && d.join("mia.txt").exists());
    }

    #[test]
    fn rechaza_si_no_hay_espacio() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        let d = dir.path().join("nueva");
        let e = mover_con(&o, &d, |a, b| fs::rename(a, b), |_| 0).unwrap_err();
        assert!(e.contains("No hay espacio suficiente"), "{e}");
        assert!(o.join("a.txt").exists() && !d.exists());
    }

    #[cfg(unix)]
    #[test]
    fn si_la_copia_falla_se_borra_lo_parcial_y_el_origen_queda_intacto() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        // Un enlace roto hace fallar `fs::copy` (aunque se ejecute como root, a diferencia de un
        // permiso denegado).
        std::os::unix::fs::symlink(dir.path().join("no-existe"), o.join("zzz-roto")).unwrap();
        let d = dir.path().join("otro-disco");
        let e = mover_con(&o, &d, rename_falla, espacio_libre_mb).unwrap_err();
        assert!(e.contains("No se pudo copiar") && e.contains("sigue como estaba"), "{e}");
        assert!(!d.exists(), "la copia parcial se borra");
        assert_eq!(fs::read_to_string(o.join("a.txt")).unwrap(), "hola");
        assert!(o.join("modelos/sub/b.bin").exists());
    }
}
