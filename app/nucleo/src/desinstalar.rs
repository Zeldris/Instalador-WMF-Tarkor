//! Borrado de datos al desinstalar (docs/04 y docs/07, "Dónde vive cada cosa").
//!
//! Lo usa el desinstalador de Windows a través de dos opciones del ejecutable (`--info-desinstalar`
//! y `--desinstalar`, ver [`analizar_args`]). Las reglas de seguridad: la carpeta de la IA solo se
//! borra si es la de por defecto o se llama `Tarkor IA` (la que crea `cambiar_carpeta_ia`), para
//! que una `config.json` rara nunca lleve a borrar `C:\` ni la carpeta personal.
//!
//! Con `partidas` se borra también `config.json`, el único sitio donde vive `carpeta_ia`: si la
//! carpeta de la IA elegida sobrevive (no se pidió borrarla, o no era borrable), se deja un
//! `config.json` que solo conserva esa ruta, para que la IA no quede huérfana.
//! Con solo `ia`, `config.json` se queda pero vuelve al asistente para descargarla otra vez (`INS-59`).

use crate::carpetas::normalizada;
use crate::config::{Config, Rutas};
use std::ffi::OsString;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

/// Nombre de la carpeta que crea el asistente dentro de la elegida por la usuaria.
const NOMBRE_IA_ELEGIDA: &str = "Tarkor IA";

/// Paso «Elige perfil» del asistente (`App.tsx`): el anterior a la descarga.
const PASO_ELEGIR_PERFIL: u8 = 4;

/// Qué se le enseña a la usuaria antes de borrar.
#[derive(Debug, Clone, PartialEq)]
pub struct Info {
    pub ruta_ia: PathBuf,
    pub bytes_ia: u64,
}

/// La carpeta de la IA en uso y su tamaño (0 si no existe).
pub fn info(rutas: &Rutas, config: &Config) -> Info {
    let ruta_ia = config.ia_efectiva(rutas);
    let bytes_ia = tamano(&ruta_ia);
    Info { ruta_ia, bytes_ia }
}

/// Tamaño recursivo sin seguir enlaces simbólicos.
fn tamano(ruta: &Path) -> u64 {
    let Ok(meta) = fs::symlink_metadata(ruta) else { return 0 };
    if meta.is_file() {
        return meta.len();
    }
    if !meta.is_dir() {
        return 0;
    }
    let Ok(entradas) = fs::read_dir(ruta) else { return 0 };
    entradas.flatten().map(|e| tamano(&e.path())).sum()
}

/// "9,6 GB", como el asistente (`formato.ts`: un decimal, coma). Vacío si no hay nada.
pub fn texto_gb(bytes: u64) -> String {
    if bytes == 0 {
        return String::new();
    }
    let gb = bytes as f64 / (1024.0 * 1024.0 * 1024.0);
    let decimas = (gb * 10.0).round() / 10.0;
    if decimas == 0.0 {
        return "<0,1 GB".into();
    }
    format!("{decimas:.1} GB").replace('.', ",")
}

/// Escribe el INI que lee NSIS (`ReadINIStr`): UTF-16LE con BOM y `\r\n`.
pub fn escribir_ini(info: &Info, archivo: &Path) -> io::Result<()> {
    let texto = format!("[ia]\r\nruta={}\r\ntamano={}\r\n", info.ruta_ia.display(), texto_gb(info.bytes_ia));
    let mut bytes = vec![0xFF, 0xFE];
    for u in texto.encode_utf16() {
        bytes.extend_from_slice(&u.to_le_bytes());
    }
    fs::write(archivo, bytes)
}

fn ia_borrable(rutas: &Rutas, ia: &Path) -> bool {
    normalizada(ia) == normalizada(&rutas.ia) || ia.file_name().is_some_and(|n| n == NOMBRE_IA_ELEGIDA)
}

/// Guarda el primer error y sigue.
fn anotar(primero: &mut Option<io::Error>, r: io::Result<()>) {
    if let Err(e) = r {
        primero.get_or_insert(e);
    }
}

/// Borra todo lo de `dir` salvo `salvar` y sus ancestros; `dir` solo si queda vacía. Un fallo en una
/// entrada no impide intentar las demás: se devuelve el primero.
fn borrar_salvo(dir: &Path, salvar: &Path) -> io::Result<()> {
    let mut error = None;
    match fs::read_dir(dir) {
        Err(e) => return Err(e),
        Ok(entradas) => {
            for e in entradas {
                let p = match e {
                    Ok(e) => e.path(),
                    Err(e) => {
                        anotar(&mut error, Err(e));
                        continue;
                    }
                };
                if p == salvar {
                    continue;
                }
                let r = if salvar.starts_with(&p) { borrar_salvo(&p, salvar) } else { quitar(&p) };
                anotar(&mut error, r);
            }
        }
    }
    let _ = fs::remove_dir(dir); // solo si quedó vacía
    error.map_or(Ok(()), Err)
}

/// Borra los registros siempre; con `ia`, la carpeta de la IA en uso (solo si es la de por defecto
/// o se llama `Tarkor IA`); con `partidas`, la carpeta de datos salvo la IA si vive dentro. Quita
/// después los padres que queden vacíos. Cada paso se intenta siempre, aunque otro haya fallado:
/// se devuelve el primer error (la IA con otro nombre no se toca y cuenta como error).
pub fn borrar(rutas: &Rutas, config: &Config, partidas: bool, ia: bool) -> io::Result<()> {
    let ia_en_uso = config.ia_efectiva(rutas);
    // Antes de borrar: escrita con `..` o a través de un enlace, la ruta puede pasar por algo que se va a ir.
    let ia_normalizada = normalizada(&ia_en_uso);
    let mut error = None;

    anotar(&mut error, quitar(&rutas.registros));
    if ia {
        if ia_borrable(rutas, &ia_en_uso) {
            anotar(&mut error, quitar(&ia_en_uso));
        } else {
            anotar(
                &mut error,
                Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!(
                        "no se borra la carpeta de la IA «{}»: no es la de por defecto ni se llama «{NOMBRE_IA_ELEGIDA}»",
                        ia_en_uso.display()
                    ),
                )),
            );
        }
    }
    if partidas && rutas.datos.is_dir() {
        anotar(&mut error, borrar_salvo(&normalizada(&rutas.datos), &ia_normalizada));
    }
    if ia && !partidas && !ia_normalizada.exists() && rutas.datos.join("config.json").exists() {
        anotar(&mut error, sin_ia(config).guardar(&rutas.datos));
    }
    if partidas && config.carpeta_ia.is_some() && ia_normalizada.exists() {
        let conservar = Config { carpeta_ia: Some(ia_normalizada), ..Config::default() };
        anotar(&mut error, conservar.guardar(&rutas.datos));
    }
    for padre in [rutas.registros.parent(), rutas.ia.parent()].into_iter().flatten() {
        if !padre.as_os_str().is_empty() {
            let _ = fs::remove_dir(padre); // falla si tiene contenido: se deja
        }
    }
    error.map_or(Ok(()), Err)
}

/// La configuración tras borrar solo la IA (`INS-59`): las partidas y lo elegido se quedan, pero el
/// asistente deja de darse por completado y vuelve a «Elige perfil» para descargarla otra vez, como
/// Steam o itch.io cuando faltan los archivos de un juego. Los modelos vivían en la IA: ya no están.
fn sin_ia(config: &Config) -> Config {
    Config {
        asistente_completado: false,
        modelos_descargados: Vec::new(),
        paso_asistente: config.paso_asistente.min(PASO_ELEGIR_PERFIL),
        ..config.clone()
    }
}

/// El mensaje que ve la usuaria cuando el borrado falla (sin rutas internas, salvo la de la IA que ella eligió).
pub fn mensaje_error(e: &io::Error) -> String {
    if e.kind() == io::ErrorKind::InvalidInput {
        format!("{e}. Si quieres liberar ese espacio, bórrala a mano desde el explorador de archivos.")
    } else {
        "No se pudo borrar todo. Cierra los programas que usen las carpetas de Tarkor y vuelve a intentarlo.".into()
    }
}

fn quitar(ruta: &Path) -> io::Result<()> {
    match fs::symlink_metadata(ruta) {
        Ok(m) if m.is_dir() => fs::remove_dir_all(ruta),
        Ok(_) => fs::remove_file(ruta),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e),
    }
}

/// Lo que pide la línea de órdenes.
#[derive(Debug, Clone, PartialEq)]
pub enum Orden {
    /// Sin opciones de desinstalación: arranque normal.
    Normal,
    InfoDesinstalar(PathBuf),
    Desinstalar {
        partidas: bool,
        ia: bool,
    },
}

/// Analiza los argumentos (sin el nombre del programa).
pub fn analizar_args(args: impl IntoIterator<Item = OsString>) -> Result<Orden, String> {
    let mut args = args.into_iter();
    let Some(primero) = args.next() else { return Ok(Orden::Normal) };
    match primero.to_str() {
        Some("--info-desinstalar") => {
            let archivo = args.next().ok_or("--info-desinstalar necesita un archivo de destino")?;
            if let Some(sobra) = args.next() {
                return Err(format!("argumento de más tras el archivo: {}", sobra.to_string_lossy()));
            }
            Ok(Orden::InfoDesinstalar(PathBuf::from(archivo)))
        }
        Some("--desinstalar") => {
            let (mut partidas, mut ia) = (false, false);
            for a in args {
                match a.to_str() {
                    Some("--partidas") => partidas = true,
                    Some("--ia") => ia = true,
                    _ => return Err(format!("opción desconocida: {}", a.to_string_lossy())),
                }
            }
            Ok(Orden::Desinstalar { partidas, ia })
        }
        _ => Ok(Orden::Normal),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rutas(base: &Path) -> Rutas {
        Rutas {
            datos: base.join("datos"),
            ia: base.join("local/Tarkor/ia"),
            registros: base.join("local/Tarkor/registros"),
        }
    }

    fn archivo(p: &Path, bytes: usize) {
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, vec![b'x'; bytes]).unwrap();
    }

    /// Windows: datos aparte, IA y registros bajo `local/Tarkor`.
    fn montar(r: &Rutas) {
        archivo(&r.datos.join("partida.json"), 5);
        archivo(&r.ia.join("modelo.bin"), 100);
        archivo(&r.registros.join("log.txt"), 3);
    }

    #[test]
    fn nada_que_borrar_no_falla() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        borrar(&r, &Config::default(), true, true).unwrap();
        assert!(!r.datos.exists());
    }

    #[test]
    fn solo_registros_sin_partidas_ni_ia() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        borrar(&r, &Config::default(), false, false).unwrap();
        assert!(!r.registros.exists());
        assert!(r.datos.join("partida.json").exists());
        assert!(r.ia.join("modelo.bin").exists());
    }

    #[test]
    fn ia_por_defecto_y_quita_el_padre_vacio() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        borrar(&r, &Config::default(), false, true).unwrap();
        assert!(!r.ia.exists() && !r.registros.exists());
        assert!(!d.path().join("local/Tarkor").exists(), "el padre vacío se quita");
        assert!(r.datos.join("partida.json").exists());
    }

    #[test]
    fn el_padre_con_contenido_se_deja() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        archivo(&d.path().join("local/Tarkor/otra.txt"), 1);
        borrar(&r, &Config::default(), false, true).unwrap();
        assert!(d.path().join("local/Tarkor/otra.txt").exists());
    }

    #[test]
    fn partidas_sin_ia_deja_la_ia_que_vive_dentro_de_datos() {
        let d = tempfile::tempdir().unwrap();
        let mut r = rutas(d.path());
        r.ia = r.datos.join("ia");
        montar(&r);
        archivo(&r.datos.join("sub/otra.json"), 2);
        borrar(&r, &Config::default(), true, false).unwrap();
        assert!(r.ia.join("modelo.bin").exists(), "la IA sobrevive");
        assert!(!r.datos.join("partida.json").exists());
        assert!(!r.datos.join("sub").exists());
    }

    #[test]
    fn partidas_e_ia_dentro_de_datos_borra_todo() {
        let d = tempfile::tempdir().unwrap();
        let mut r = rutas(d.path());
        r.ia = r.datos.join("ia");
        montar(&r);
        borrar(&r, &Config::default(), true, true).unwrap();
        assert!(!r.datos.exists());
    }

    #[test]
    fn ia_movida_a_tarkor_ia_se_borra() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        let movida = d.path().join("disco/Tarkor IA");
        archivo(&movida.join("modelo.bin"), 10);
        let c = Config { carpeta_ia: Some(movida.clone()), ..Config::default() };
        borrar(&r, &c, false, true).unwrap();
        assert!(!movida.exists());
        assert!(d.path().join("disco").exists(), "la carpeta elegida no se toca");
        assert!(r.ia.join("modelo.bin").exists(), "la de por defecto no era la en uso");
    }

    #[test]
    fn ia_con_otro_nombre_no_se_borra_y_da_error_pero_se_hace_el_resto() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        let rara = d.path().join("Documentos");
        archivo(&rara.join("importante.txt"), 10);
        let c = Config { carpeta_ia: Some(rara.clone()), ..Config::default() };
        let e = borrar(&r, &c, true, true).unwrap_err();
        assert_eq!(e.kind(), io::ErrorKind::InvalidInput);
        assert!(e.to_string().contains("no es la de por defecto"), "{e}");
        assert!(rara.join("importante.txt").exists());
        assert!(!r.registros.exists());
        assert!(!r.datos.join("partida.json").exists(), "las partidas sí se borran");
        // Se guarda normalizada: en Windows la carpeta temporal llega con nombre corto (`RUNNER~1`).
        assert_eq!(
            Config::cargar(&r.datos).carpeta_ia,
            Some(normalizada(&rara)),
            "la IA que sobrevive no queda huérfana"
        );
    }

    #[test]
    fn ia_con_otro_nombre_dentro_de_datos_sobrevive_a_partidas() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        let rara = r.datos.join("cosas");
        archivo(&rara.join("importante.txt"), 10);
        let c = Config { carpeta_ia: Some(rara.clone()), ..Config::default() };
        borrar(&r, &c, true, false).unwrap();
        assert!(rara.join("importante.txt").exists());
    }

    #[test]
    fn partidas_conserva_solo_la_carpeta_ia_elegida_que_sobrevive() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        let elegida = d.path().join("disco/Tarkor IA");
        archivo(&elegida.join("modelo.bin"), 10);
        let c = Config { carpeta_ia: Some(elegida.clone()), perfil: Some("x".into()), ..Config::default() };
        c.guardar(&r.datos).unwrap();
        borrar(&r, &c, true, false).unwrap();
        assert!(!r.datos.join("partida.json").exists());
        assert_eq!(Config::cargar(&r.datos), Config { carpeta_ia: Some(normalizada(&elegida)), ..Config::default() });
        assert!(elegida.join("modelo.bin").exists());
    }

    #[test]
    fn partidas_con_ia_por_defecto_no_deja_config() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        Config::default().guardar(&r.datos).unwrap();
        borrar(&r, &Config::default(), true, false).unwrap();
        assert!(!r.datos.join("config.json").exists());
        assert!(!r.datos.exists());
    }

    fn completada(carpeta_ia: Option<PathBuf>) -> Config {
        Config {
            consentimiento_aceptado: true,
            perfil: Some("equilibrado".into()),
            modelos_descargados: vec!["llama3.1:8b".into()],
            paso_asistente: 7,
            asistente_completado: true,
            carpeta_ia,
            ..Config::default()
        }
    }

    #[test]
    fn solo_ia_vuelve_al_asistente_en_elegir_perfil_sin_modelos() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        let c = completada(None);
        c.guardar(&r.datos).unwrap();
        borrar(&r, &c, false, true).unwrap();
        assert!(r.datos.join("partida.json").exists());
        assert_eq!(
            Config::cargar(&r.datos),
            Config { asistente_completado: false, modelos_descargados: vec![], paso_asistente: 4, ..c }
        );
    }

    #[test]
    fn solo_ia_elegida_borrada_conserva_la_carpeta_en_la_config() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        let elegida = d.path().join("disco/Tarkor IA");
        archivo(&elegida.join("modelo.bin"), 10);
        let c = completada(Some(elegida.clone()));
        c.guardar(&r.datos).unwrap();
        borrar(&r, &c, false, true).unwrap();
        let tras = Config::cargar(&r.datos);
        assert!(!tras.asistente_completado);
        assert_eq!(tras.carpeta_ia, Some(elegida));
    }

    #[test]
    fn solo_ia_que_no_se_pudo_borrar_deja_la_config_igual() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        let rara = d.path().join("disco/Otra");
        archivo(&rara.join("modelo.bin"), 10);
        let c = completada(Some(rara));
        c.guardar(&r.datos).unwrap();
        let e = borrar(&r, &c, false, true).unwrap_err();
        assert!(e.to_string().contains("no se borra la carpeta de la IA"), "{e}");
        assert_eq!(Config::cargar(&r.datos), c);
    }

    #[test]
    fn solo_ia_sin_config_no_la_crea() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        borrar(&r, &completada(None), false, true).unwrap();
        assert!(!r.datos.join("config.json").exists());
    }

    #[test]
    fn partidas_con_ia_borrada_no_deja_config() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        montar(&r);
        let elegida = d.path().join("disco/Tarkor IA");
        archivo(&elegida.join("modelo.bin"), 10);
        let c = Config { carpeta_ia: Some(elegida), ..Config::default() };
        borrar(&r, &c, true, true).unwrap();
        assert!(!r.datos.exists());
    }

    #[test]
    fn ia_dentro_de_datos_escrita_con_punto_punto_sobrevive_a_partidas() {
        let d = tempfile::tempdir().unwrap();
        let mut r = rutas(d.path());
        r.ia = r.datos.join("ia");
        montar(&r);
        archivo(&r.datos.join("sub/otra.json"), 2);
        let rara = r.datos.join("sub/../ia");
        let c = Config { carpeta_ia: Some(rara), ..Config::default() };
        borrar(&r, &c, true, false).unwrap();
        assert!(r.ia.join("modelo.bin").exists(), "la IA sobrevive");
        assert!(!r.datos.join("sub").exists());
        // La ruta guardada ya no pasa por `sub`, que se ha borrado: la IA no queda huérfana.
        let guardada = Config::cargar(&r.datos).carpeta_ia.expect("se conserva la carpeta de la IA");
        assert!(guardada.join("modelo.bin").exists(), "la ruta guardada lleva a la IA: {guardada:?}");
    }

    #[cfg(unix)]
    #[test]
    fn ia_dentro_de_datos_por_enlace_simbolico_sobrevive_a_partidas() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        archivo(&r.datos.join("ia/modelo.bin"), 100);
        archivo(&r.datos.join("partida.json"), 5);
        let enlace = d.path().join("enlace");
        std::os::unix::fs::symlink(&r.datos, &enlace).unwrap();
        let c = Config { carpeta_ia: Some(enlace.join("ia")), ..Config::default() };
        borrar(&r, &c, true, false).unwrap();
        assert!(r.datos.join("ia/modelo.bin").exists(), "la IA sobrevive");
        assert!(!r.datos.join("partida.json").exists());
    }

    #[test]
    fn mensajes_de_error_para_la_usuaria() {
        let rara = io::Error::new(
            io::ErrorKind::InvalidInput,
            "no se borra la carpeta de la IA «/x/Docs»: no es la de por defecto",
        );
        let m = mensaje_error(&rara);
        assert!(m.contains("«/x/Docs»") && m.contains("bórrala a mano"), "{m}");
        let otro = mensaje_error(&io::Error::new(io::ErrorKind::PermissionDenied, "/secreto/ruta: denegado"));
        assert!(otro.contains("Cierra los programas") && !otro.contains("secreto"), "{otro}");
    }

    #[cfg(unix)]
    #[test]
    fn un_fallo_en_los_registros_no_impide_borrar_la_ia_ni_las_partidas() {
        let d = tempfile::tempdir().unwrap();
        let mut r = rutas(d.path());
        montar(&r);
        // Fallo provocable también como root: `registros` cuelga de un archivo (ENOTDIR).
        archivo(&d.path().join("bloqueo"), 1);
        r.registros = d.path().join("bloqueo/registros");
        let e = borrar(&r, &Config::default(), true, true).unwrap_err();
        assert_ne!(e.kind(), io::ErrorKind::InvalidInput, "debe ser el error de los registros: {e}");
        assert!(!r.ia.exists(), "la IA se borra aunque fallen los registros");
        assert!(!r.datos.exists(), "las partidas se borran aunque fallen los registros");
    }

    #[cfg(unix)]
    #[test]
    fn se_devuelve_el_primer_error_aunque_falle_tambien_la_ia() {
        let d = tempfile::tempdir().unwrap();
        let mut r = rutas(d.path());
        montar(&r);
        archivo(&d.path().join("bloqueo"), 1);
        r.registros = d.path().join("bloqueo/registros");
        let rara = d.path().join("Documentos");
        archivo(&rara.join("x.txt"), 1);
        let c = Config { carpeta_ia: Some(rara.clone()), ..Config::default() };
        let e = borrar(&r, &c, true, true).unwrap_err();
        assert_ne!(e.kind(), io::ErrorKind::InvalidInput, "el primero es el de los registros: {e}");
        assert!(rara.join("x.txt").exists());
        assert!(!r.datos.join("partida.json").exists());
    }

    #[test]
    fn info_suma_el_tamano_de_varios_archivos() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        assert_eq!(info(&r, &Config::default()), Info { ruta_ia: r.ia.clone(), bytes_ia: 0 });
        archivo(&r.ia.join("a.bin"), 100);
        archivo(&r.ia.join("sub/b.bin"), 250);
        archivo(&r.ia.join("sub/hondo/c.bin"), 7);
        assert_eq!(info(&r, &Config::default()).bytes_ia, 357);
    }

    #[cfg(unix)]
    #[test]
    fn info_no_sigue_enlaces_simbolicos() {
        let d = tempfile::tempdir().unwrap();
        let r = rutas(d.path());
        archivo(&d.path().join("fuera/grande.bin"), 1000);
        archivo(&r.ia.join("a.bin"), 10);
        std::os::unix::fs::symlink(d.path().join("fuera"), r.ia.join("enlace")).unwrap();
        let bytes = info(&r, &Config::default()).bytes_ia;
        assert!(bytes < 1000, "no debe contar lo apuntado: {bytes}");
    }

    #[test]
    fn texto_gb_como_el_asistente() {
        let gb = 1024u64 * 1024 * 1024;
        assert_eq!(texto_gb(0), "");
        assert_eq!(texto_gb(gb * 96 / 10), "9,6 GB");
        assert_eq!(texto_gb(gb * 12), "12,0 GB");
        assert_eq!(texto_gb(1000), "<0,1 GB");
    }

    fn leer_ini(p: &Path) -> String {
        let b = fs::read(p).unwrap();
        assert_eq!(&b[..2], &[0xFF, 0xFE], "BOM UTF-16LE");
        let u: Vec<u16> = b[2..].chunks(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
        String::from_utf16(&u).unwrap()
    }

    #[test]
    fn ini_en_utf16le_con_bom_y_tilde() {
        let d = tempfile::tempdir().unwrap();
        let f = d.path().join("info.ini");
        let i = Info { ruta_ia: PathBuf::from("C:\\Users\\José\\Tarkor IA"), bytes_ia: 1024 * 1024 * 1024 * 3 / 2 };
        escribir_ini(&i, &f).unwrap();
        assert_eq!(leer_ini(&f), "[ia]\r\nruta=C:\\Users\\José\\Tarkor IA\r\ntamano=1,5 GB\r\n");
    }

    #[test]
    fn ini_con_tamano_vacio_si_no_hay_nada() {
        let d = tempfile::tempdir().unwrap();
        let f = d.path().join("info.ini");
        escribir_ini(&Info { ruta_ia: PathBuf::from("/x/ia"), bytes_ia: 0 }, &f).unwrap();
        assert!(leer_ini(&f).ends_with("tamano=\r\n"));
    }

    fn args(a: &[&str]) -> Result<Orden, String> {
        analizar_args(a.iter().map(OsString::from))
    }

    #[test]
    fn sin_opciones_arranque_normal() {
        assert_eq!(args(&[]), Ok(Orden::Normal));
        assert_eq!(args(&["--otra"]), Ok(Orden::Normal));
    }

    #[test]
    fn desinstalar_con_cada_combinacion() {
        let o = |partidas, ia| Ok(Orden::Desinstalar { partidas, ia });
        assert_eq!(args(&["--desinstalar"]), o(false, false));
        assert_eq!(args(&["--desinstalar", "--partidas"]), o(true, false));
        assert_eq!(args(&["--desinstalar", "--ia"]), o(false, true));
        assert_eq!(args(&["--desinstalar", "--ia", "--partidas"]), o(true, true));
    }

    #[test]
    fn desinstalar_con_opcion_desconocida_es_error() {
        let e = args(&["--desinstalar", "--partidas", "--todo"]).unwrap_err();
        assert!(e.contains("opción desconocida") && e.contains("--todo"), "{e}");
    }

    #[test]
    fn info_desinstalar_pide_archivo() {
        assert_eq!(args(&["--info-desinstalar", "a.ini"]), Ok(Orden::InfoDesinstalar("a.ini".into())));
        let e = args(&["--info-desinstalar"]).unwrap_err();
        assert!(e.contains("necesita un archivo"), "{e}");
        assert!(args(&["--info-desinstalar", "a.ini", "b"]).is_err());
    }
}
