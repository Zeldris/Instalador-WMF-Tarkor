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
/// Si la ruta todavía no existe se sube hasta el primer antepasado que exista. `None` si no se
/// encuentra el disco (un montaje que sysinfo no lista): no medido, que no es lo mismo que lleno.
pub fn espacio_libre_mb(ruta: &Path) -> Option<u64> {
    let disks = Disks::new_with_refreshed_list();
    let ruta = absoluta(ruta);
    disks
        .list()
        .iter()
        .filter(|d| ruta.starts_with(d.mount_point()))
        .max_by_key(|d| d.mount_point().as_os_str().len())
        .map(|d| d.available_space() / MB)
}

/// `canonicalize` en Windows devuelve `\\?\C:\...`, que no empieza por el punto de montaje
/// (`C:\`) que da sysinfo. Se quita el prefijo de disco; uno de red (`\\?\UNC\`) se deja.
fn sin_verbatim(ruta: PathBuf) -> PathBuf {
    match ruta.to_str().and_then(|s| s.strip_prefix(r"\\?\")) {
        Some(resto) if !resto.starts_with("UNC\\") => PathBuf::from(resto),
        _ => ruta,
    }
}

/// Ruta canónica aunque no exista del todo: se canoniza el primer antepasado que exista y se le
/// añade el resto. Sirve para comparar rutas con enlaces simbólicos de por medio.
fn absoluta(ruta: &Path) -> PathBuf {
    let mut resto: Vec<&std::ffi::OsStr> = Vec::new();
    let mut actual = ruta;
    loop {
        if actual.exists() {
            if let Ok(base) = actual.canonicalize() {
                let mut fin = sin_verbatim(base);
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
pub(crate) fn normalizada(ruta: &Path) -> PathBuf {
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
        let tipo = entrada.file_type()?;
        if tipo.is_dir() {
            copiar_recursivo(&entrada.path(), &a)?;
        } else if tipo.is_symlink() {
            copiar_enlace(&entrada.path(), &a)?;
        } else {
            fs::copy(entrada.path(), &a)?;
        }
    }
    Ok(())
}

/// El paquete de Ollama para Linux trae las bibliotecas como enlaces (`libX.so -> libX.so.12`):
/// se copia el enlace, no lo que apunta, para no duplicar cientos de MB.
#[cfg(unix)]
fn copiar_enlace(origen: &Path, destino: &Path) -> io::Result<()> {
    std::os::unix::fs::symlink(fs::read_link(origen)?, destino)
}

/// En Windows el paquete del motor no trae enlaces; si hubiera uno, se copia su contenido.
#[cfg(not(unix))]
fn copiar_enlace(origen: &Path, destino: &Path) -> io::Result<()> {
    fs::copy(origen, destino).map(|_| ())
}

/// Mueve la carpeta de la IA de `origen` a `destino`, con mensajes pensados para el jugador.
///
/// - Si `origen` no existe (nada instalado todavía), solo se crea `destino`.
/// - `destino` no puede ser `origen` ni estar dentro, y debe no existir o estar vacío.
/// - Se intenta renombrar (instantáneo en el mismo disco, no necesita espacio); si no se puede
///   (otro disco), se comprueba que cabe, se copia y después se borra el origen. Si la copia
///   falla, se borra la copia parcial y el origen queda intacto.
/// - Ya copiado, el movimiento cuenta como hecho aunque no se pueda borrar del todo el origen
///   (un archivo bloqueado en Windows): la configuración debe pasar a la carpeta nueva, que es la
///   completa. Lo que quede del origen se devuelve como aviso.
pub fn mover_carpeta(origen: &Path, destino: &Path) -> Result<Option<String>, String> {
    mover_con(origen, destino, |a, b| fs::rename(a, b), copiar_recursivo, espacio_libre_mb)
}

fn mover_con(
    origen: &Path,
    destino: &Path,
    renombrar: impl Fn(&Path, &Path) -> io::Result<()>,
    copiar: impl Fn(&Path, &Path) -> io::Result<()>,
    espacio: impl Fn(&Path) -> Option<u64>,
) -> Result<Option<String>, String> {
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
        return fs::create_dir_all(destino).map(|_| None).map_err(falla);
    }
    if let Some(padre) = destino.parent() {
        fs::create_dir_all(padre).map_err(falla)?;
    }
    // En Windows renombrar sobre una carpeta existente (aunque esté vacía) falla.
    let estaba = destino.exists();
    if estaba {
        fs::remove_dir(destino).map_err(falla)?;
    }
    if renombrar(origen, destino).is_ok() {
        return Ok(None);
    }
    if estaba {
        fs::create_dir(destino).map_err(falla)?;
    }
    let necesario = tamano_bytes(origen).map_err(|e| format!("No se pudo medir la carpeta actual: {e}"))?;
    if let Some(libre) = espacio(destino) {
        if necesario.div_ceil(MB) > libre {
            return Err(format!(
                "No hay espacio suficiente en el disco de {}: hacen falta {} MB y hay {libre} MB libres.",
                destino.display(),
                necesario.div_ceil(MB)
            ));
        }
    }
    if let Err(e) = copiar(origen, destino) {
        if estaba {
            let _ = fs::remove_dir_all(destino).and_then(|_| fs::create_dir(destino));
        } else {
            let _ = fs::remove_dir_all(destino);
        }
        return Err(format!("No se pudo copiar a {}: {e}. La carpeta actual sigue como estaba.", destino.display()));
    }
    Ok(fs::remove_dir_all(origen).err().map(|e| {
        format!(
            "Se movió a {}, pero quedó parte de la carpeta anterior ({}): {e}. Puedes borrarla a mano.",
            destino.display(),
            origen.display()
        )
    }))
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
        let real = espacio_libre_mb(dir.path()).unwrap();
        assert!(real > 0);
        let de_futura = espacio_libre_mb(&futura).unwrap();
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
        mover_con(&o, &d, rename_falla, copiar_recursivo, espacio_libre_mb).unwrap();
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
        let e = mover_con(&o, &d, rename_falla, copiar_recursivo, |_| Some(0)).unwrap_err();
        assert!(e.contains("No hay espacio suficiente"), "{e}");
        assert!(o.join("a.txt").exists() && !d.exists());
    }

    #[test]
    fn si_la_copia_falla_se_borra_lo_parcial_y_el_origen_queda_intacto() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        let d = dir.path().join("otro-disco");
        // Copia a medias: deja un archivo y falla.
        let copia_rota = |_: &Path, b: &Path| {
            fs::create_dir_all(b)?;
            fs::write(b.join("a.txt"), "ho")?;
            Err(io::Error::other("disco desconectado"))
        };
        let e = mover_con(&o, &d, rename_falla, copia_rota, espacio_libre_mb).unwrap_err();
        assert!(e.contains("No se pudo copiar") && e.contains("sigue como estaba"), "{e}");
        assert!(!d.exists(), "la copia parcial se borra");
        assert_eq!(fs::read_to_string(o.join("a.txt")).unwrap(), "hola");
        assert!(o.join("modelos/sub/b.bin").exists());
    }

    #[test]
    fn renombrar_en_el_mismo_disco_no_pide_espacio() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        let d = dir.path().join("nueva");
        assert_eq!(mover_con(&o, &d, |a, b| fs::rename(a, b), copiar_recursivo, |_| Some(0)), Ok(None));
        assert!(d.join("a.txt").exists() && !o.exists());
    }

    #[test]
    fn un_disco_sin_medir_no_bloquea_la_copia() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        let d = dir.path().join("nueva");
        assert_eq!(mover_con(&o, &d, rename_falla, copiar_recursivo, |_| None), Ok(None));
        assert!(d.join("modelos/sub/b.bin").exists() && !o.exists());
    }

    #[cfg(unix)]
    #[test]
    fn los_enlaces_se_copian_como_enlaces() {
        let dir = tempfile::tempdir().unwrap();
        let o = con_contenido(dir.path());
        std::os::unix::fs::symlink("b.bin", o.join("modelos/sub/b.so")).unwrap();
        std::os::unix::fs::symlink("sub", o.join("modelos/enlace-a-carpeta")).unwrap();
        let d = dir.path().join("otro-disco");
        mover_con(&o, &d, rename_falla, copiar_recursivo, espacio_libre_mb).unwrap();
        assert_eq!(fs::read_link(d.join("modelos/sub/b.so")).unwrap(), Path::new("b.bin"));
        assert_eq!(fs::read_link(d.join("modelos/enlace-a-carpeta")).unwrap(), Path::new("sub"));
    }

    #[test]
    fn quita_el_prefijo_verbatim_de_windows() {
        assert_eq!(sin_verbatim(PathBuf::from(r"\\?\C:\Users\a")), PathBuf::from(r"C:\Users\a"));
        assert_eq!(sin_verbatim(PathBuf::from(r"\\?\UNC\srv\c")), PathBuf::from(r"\\?\UNC\srv\c"));
        assert_eq!(sin_verbatim(PathBuf::from("/home/a")), PathBuf::from("/home/a"));
    }
}
