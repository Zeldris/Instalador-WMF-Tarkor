//! «Copiar informe» (docs/11): texto plano con lo que hace falta para pedir ayuda. Todo son
//! funciones puras sobre datos ya leídos; leerlos (config, motor, `/api/ps`) es cosa de la app.
//! Nunca sale del equipo si el jugador no lo pega él mismo (docs/08).

use crate::catalogo::Origen;
use crate::equipo::Equipo;
use crate::ollama::{resumen_uso, Cargado};
use crate::perfiles::UsoCpu;
use crate::rendimiento::Ajustes;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

/// Líneas del registro del motor que lleva el informe.
pub const LINEAS_REGISTRO: usize = 200;
/// Del registro solo se lee el final: crece sin límite entre arranques.
const MAX_LECTURA: u64 = 1024 * 1024;

/// Estado del motor de IA tal como lo ve la app.
pub struct EstadoMotor<'a> {
    /// Versión de Ollama que pide el catálogo.
    pub version_catalogo: &'a str,
    /// Versión que responde el motor, si responde.
    pub version_en_marcha: Option<&'a str>,
    pub instalado: bool,
    pub en_marcha: bool,
    pub externo: bool,
    /// Motivo de la última parada, si la hubo.
    pub ultimo_motivo_parada: Option<&'a str>,
}

pub struct Datos<'a> {
    pub version_app: &'a str,
    /// Sistema y arquitectura de esta compilación (`linux x86_64`).
    pub sistema: &'a str,
    pub equipo: Option<&'a Equipo>,
    /// Nombre (id) del perfil elegido.
    pub perfil: Option<&'a str>,
    pub uso_cpu: UsoCpu,
    pub ajustes: Option<&'a Ajustes>,
    pub origen_catalogo: &'a Origen,
    pub motor: EstadoMotor<'a>,
    /// `/api/ps`, o por qué no se pudo leer.
    pub ps: Result<&'a [Cargado], &'a str>,
    /// Últimas líneas de `motor-ia.log`.
    pub registro: &'a str,
}

/// Las últimas `n` líneas del archivo. Si falta, está vacío o no se puede leer: texto vacío.
pub fn ultimas_lineas(ruta: &Path, n: usize) -> String {
    leer_final(ruta, n).unwrap_or_default()
}

fn leer_final(ruta: &Path, n: usize) -> std::io::Result<String> {
    let mut f = File::open(ruta)?;
    let largo = f.metadata()?.len();
    let desde = largo.saturating_sub(MAX_LECTURA);
    f.seek(SeekFrom::Start(desde))?;
    let mut bytes = Vec::new();
    f.take(MAX_LECTURA).read_to_end(&mut bytes)?;
    let texto = String::from_utf8_lossy(&bytes);
    let mut lineas: Vec<&str> = texto.lines().collect();
    // Si se empezó a mitad del archivo, la primera línea está cortada.
    if desde > 0 && !lineas.is_empty() {
        lineas.remove(0);
    }
    let ini = lineas.len().saturating_sub(n);
    Ok(lineas[ini..].join("\n"))
}

/// La carpeta personal del jugador según la plataforma (`USERPROFILE` en Windows, `HOME` en el resto).
pub fn carpeta_personal() -> Option<PathBuf> {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).map(PathBuf::from)
}

fn es_de_nombre(c: char) -> bool {
    c.is_alphanumeric() || c == '_' || c == '-'
}

/// Cambia la carpeta personal por `~`, con una barra o con la otra (Ollama escribe rutas a su
/// manera) y, en Windows, sin distinguir mayúsculas. `/home/ana` no toca `/home/ana2`.
pub fn anonimizar(texto: &str, carpeta_personal: &Path) -> String {
    let c = carpeta_personal.to_string_lossy();
    let c = c.trim_end_matches(['/', '\\']);
    if c.is_empty() || c == "." {
        return texto.to_string();
    }
    let mut formas = vec![c.to_string()];
    for otra in [c.replace('\\', "/"), c.replace('/', "\\")] {
        if !formas.contains(&otra) {
            formas.push(otra);
        }
    }
    let mut salida = texto.to_string();
    for forma in &formas {
        salida = sustituir(&salida, forma);
    }
    salida
}

fn sustituir(texto: &str, forma: &str) -> String {
    // El paso a minúsculas ASCII conserva las posiciones en bytes.
    let (pajar, aguja) = if cfg!(windows) { (texto.to_ascii_lowercase(), forma.to_ascii_lowercase()) } else { (texto.to_string(), forma.to_string()) };
    let mut salida = String::with_capacity(texto.len());
    let mut resto = 0;
    while let Some(pos) = pajar[resto..].find(&aguja) {
        let ini = resto + pos;
        let fin = ini + aguja.len();
        salida.push_str(&texto[resto..ini]);
        if texto[fin..].chars().next().is_some_and(es_de_nombre) {
            salida.push_str(&texto[ini..fin]);
        } else {
            salida.push('~');
        }
        resto = fin;
    }
    salida.push_str(&texto[resto..]);
    salida
}

fn si_no(b: bool) -> &'static str {
    if b {
        "sí"
    } else {
        "no"
    }
}

fn describir_origen(o: &Origen) -> String {
    match o {
        Origen::Incrustado => "incrustado en la app".into(),
        Origen::Externo => "catalogo.json externo (válido)".into(),
        Origen::ExternoInvalido { motivo } => format!("catalogo.json externo no válido ({motivo}); se usa el incrustado"),
    }
}

fn describir_equipo(e: Option<&Equipo>) -> String {
    let Some(e) = e else { return "sin analizar".into() };
    let mut s = format!(
        "{}\nProcesador: {} ({} núcleos, {} hilos)\nMemoria: {} MB en total, {} MB libres\nDisco libre (carpeta de datos): {} MB",
        e.sistema, e.cpu_modelo, e.nucleos, e.hilos, e.ram_total_mb, e.ram_libre_mb, e.disco_libre_mb
    );
    if e.gpus.is_empty() {
        s.push_str("\nGráfica: ninguna detectada");
    }
    for g in &e.gpus {
        let vram = g.vram_mb.map_or("memoria desconocida".to_string(), |v| format!("{v} MB"));
        s.push_str(&format!("\nGráfica: {} ({}, {vram})", g.nombre, if g.integrada { "integrada" } else { "dedicada" }));
    }
    s
}

/// Arma el informe en texto plano, con la carpeta personal cambiada por `~`.
pub fn componer(d: &Datos, carpeta_personal: &Path) -> String {
    let mut t = String::new();
    let mut seccion = |titulo: &str, cuerpo: String| {
        t.push_str(&format!("== {titulo} ==\n{cuerpo}\n\n"));
    };
    seccion("Tarkor", format!("Versión de la app: {}", d.version_app));
    seccion("Sistema", d.sistema.to_string());
    seccion("Equipo analizado", describir_equipo(d.equipo));
    seccion(
        "Perfil",
        format!("Perfil: {}\nUso del procesador: {}", d.perfil.unwrap_or("sin elegir"), match d.uso_cpu {
            UsoCpu::Moderado => "moderado",
            UsoCpu::Alto => "alto",
        }),
    );
    seccion(
        "Ajustes de Ollama del perfil",
        match d.ajustes {
            None => "sin perfil, sin ajustes".into(),
            Some(a) => {
                let mut s: Vec<String> = a.ollama.iter().map(|(k, v)| format!("{k}={v}")).collect();
                s.push(format!(
                    "(hilos {}, caché de contexto {}, gráfica dedicada {}, margen justo {})",
                    a.resumen.hilos,
                    a.resumen.cache_contexto,
                    si_no(a.resumen.usa_gpu_dedicada),
                    si_no(a.resumen.margen_justo)
                ));
                s.join("\n")
            }
        },
    );
    seccion("Catálogo", format!("Origen: {}", describir_origen(d.origen_catalogo)));
    let m = &d.motor;
    seccion(
        "Motor de IA",
        format!(
            "Versión del catálogo: {}\nVersión en marcha: {}\nOllama externo: {}\nInstalado: {}\nEn marcha: {}\nÚltimo motivo de parada: {}",
            m.version_catalogo,
            m.version_en_marcha.unwrap_or("no responde"),
            si_no(m.externo),
            si_no(m.instalado),
            si_no(m.en_marcha),
            m.ultimo_motivo_parada.unwrap_or("ninguno")
        ),
    );
    seccion(
        "Modelos cargados (/api/ps)",
        match d.ps {
            Err(porque) => format!("No se pudo leer: {porque}"),
            Ok([]) => "Nada cargado".into(),
            Ok(c) => {
                let u = resumen_uso(c);
                let mut s: Vec<String> = c.iter().map(|x| format!("{}: {} MB, {} % en la gráfica", x.modelo, x.memoria_mb, x.porcentaje_gpu)).collect();
                s.push(format!("Total: {} MB, {} % en la gráfica", u.memoria_mb, u.porcentaje_gpu.unwrap_or(0)));
                s.join("\n")
            }
        },
    );
    seccion(
        &format!("Últimas {LINEAS_REGISTRO} líneas de motor-ia.log"),
        if d.registro.trim().is_empty() { "(registro vacío o inexistente)".into() } else { d.registro.to_string() },
    );
    anonimizar(t.trim_end(), carpeta_personal)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::equipo::{Fabricante, Gpu};
    use std::fs;

    #[test]
    fn ultimas_lineas_de_un_archivo() {
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("motor-ia.log");
        let texto: String = (1..=300).map(|i| format!("linea {i}\n")).collect();
        fs::write(&f, texto).unwrap();
        let r = ultimas_lineas(&f, 200);
        assert_eq!(r.lines().count(), 200);
        assert!(r.starts_with("linea 101\n") && r.ends_with("linea 300"), "{r}");
        // Menos líneas de las pedidas: todas.
        assert_eq!(ultimas_lineas(&f, 1000).lines().count(), 300);
    }

    #[test]
    fn archivo_que_falta_o_vacio_da_texto_vacio() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(ultimas_lineas(&dir.path().join("no-existe.log"), 200), "");
        let vacio = dir.path().join("vacio.log");
        fs::write(&vacio, "").unwrap();
        assert_eq!(ultimas_lineas(&vacio, 200), "");
    }

    #[test]
    fn registro_enorme_solo_lee_el_final_sin_linea_cortada() {
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("grande.log");
        let texto: String = (0..200_000).map(|i| format!("linea numero {i}\n")).collect();
        assert!(texto.len() as u64 > MAX_LECTURA);
        fs::write(&f, &texto).unwrap();
        let r = ultimas_lineas(&f, 3);
        assert_eq!(r, "linea numero 199997\nlinea numero 199998\nlinea numero 199999");
    }

    #[test]
    fn anonimiza_la_carpeta_personal() {
        let casa = Path::new("/home/ana");
        assert_eq!(anonimizar("cargando /home/ana/.local/share/tarkor/ia y /home/ana", casa), "cargando ~/.local/share/tarkor/ia y ~");
        // Otro usuario con el mismo comienzo no se toca.
        assert_eq!(anonimizar("/home/ana2/x", casa), "/home/ana2/x");
        // Con barra final en la carpeta, igual.
        assert_eq!(anonimizar("/home/ana/x", Path::new("/home/ana/")), "~/x");
        // Sin carpeta personal conocida no se cambia nada (ni se rompe).
        assert_eq!(anonimizar("/home/ana/x", Path::new("")), "/home/ana/x");
    }

    #[test]
    fn anonimiza_rutas_de_windows_con_cualquier_barra() {
        let casa = Path::new(r"C:\Users\Ana");
        let r = anonimizar(r"C:\Users\Ana\AppData\Local y C:/Users/Ana/AppData", casa);
        assert_eq!(r, r"~\AppData\Local y ~/AppData");
    }

    fn equipo() -> Equipo {
        Equipo {
            ram_total_mb: 16000,
            ram_libre_mb: 9000,
            cpu_modelo: "AMD Ryzen 5".into(),
            nucleos: 6,
            hilos: 12,
            gpus: vec![Gpu { nombre: "NVIDIA RTX 3060".into(), fabricante: Fabricante::Nvidia, vram_mb: Some(12288), integrada: false }],
            disco_libre_mb: 200_000,
            sistema: "Linux 6.1".into(),
        }
    }

    fn datos<'a>(equipo: Option<&'a Equipo>, ps: Result<&'a [Cargado], &'a str>, registro: &'a str, origen: &'a Origen) -> Datos<'a> {
        Datos {
            version_app: "0.1.0",
            sistema: "linux x86_64",
            equipo,
            perfil: Some("equilibrado"),
            uso_cpu: UsoCpu::Moderado,
            ajustes: None,
            origen_catalogo: origen,
            motor: EstadoMotor {
                version_catalogo: "0.34.3",
                version_en_marcha: None,
                instalado: true,
                en_marcha: false,
                externo: false,
                ultimo_motivo_parada: Some("El motor de IA se ha cerrado dos veces"),
            },
            ps,
            registro,
        }
    }

    #[test]
    fn el_informe_lleva_todas_las_secciones_y_anonimiza() {
        let e = equipo();
        let o = Origen::Incrustado;
        let ps = [Cargado { modelo: "qwen2.5:7b".into(), porcentaje_gpu: 60, memoria_mb: 5000, tamano_bytes: 5000 * 1024 * 1024, vram_bytes: 3000 * 1024 * 1024 }];
        let i = componer(&datos(Some(&e), Ok(&ps), "error en /home/ana/.local/share/tarkor/ia/ollama\nout of memory", &o), Path::new("/home/ana"));
        for esperado in [
            "Versión de la app: 0.1.0",
            "linux x86_64",
            "AMD Ryzen 5 (6 núcleos, 12 hilos)",
            "Gráfica: NVIDIA RTX 3060 (dedicada, 12288 MB)",
            "Perfil: equilibrado",
            "Uso del procesador: moderado",
            "sin perfil, sin ajustes",
            "Origen: incrustado en la app",
            "Versión en marcha: no responde",
            "En marcha: no",
            "Último motivo de parada: El motor de IA se ha cerrado dos veces",
            "qwen2.5:7b: 5000 MB, 60 % en la gráfica",
            "Total: 5000 MB, 60 % en la gráfica",
            "Últimas 200 líneas de motor-ia.log",
            "error en ~/.local/share/tarkor/ia/ollama\nout of memory",
        ] {
            assert!(i.contains(esperado), "falta «{esperado}» en:\n{i}");
        }
        assert!(!i.contains("/home/ana"), "{i}");
    }

    #[test]
    fn el_informe_sin_analisis_ni_motor_dice_por_que() {
        let o = Origen::ExternoInvalido { motivo: "json roto".into() };
        let i = componer(&datos(None, Err("El motor de IA no está en marcha."), "", &o), Path::new("/home/ana"));
        assert!(i.contains("== Equipo analizado ==\nsin analizar"), "{i}");
        assert!(i.contains("No se pudo leer: El motor de IA no está en marcha."), "{i}");
        assert!(i.contains("(registro vacío o inexistente)"), "{i}");
        assert!(i.contains("catalogo.json externo no válido (json roto)"), "{i}");
    }

    #[test]
    fn el_informe_con_nada_cargado_lo_dice() {
        let o = Origen::Incrustado;
        let i = componer(&datos(None, Ok(&[]), "x", &o), Path::new("/home/ana"));
        assert!(i.contains("Nada cargado"), "{i}");
    }
}
