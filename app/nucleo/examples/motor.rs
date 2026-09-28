//! `cargo run -p tarkor-nucleo --example motor [perfil]`: instala el motor de IA real en la
//! carpeta de datos (o en `TARKOR_DATOS`), lo arranca con los ajustes del perfil para este
//! equipo, descarga los modelos del perfil y hace la narración de prueba. Útil en la fase 0.8
//! para medir en la Steam Deck o en un Windows sin pasar por el asistente.

use std::collections::BTreeMap;
use std::sync::atomic::AtomicBool;
use std::time::{Duration, Instant};
use tarkor_nucleo::catalogo::Catalogo;
use tarkor_nucleo::config::Rutas;
use tarkor_nucleo::ollama::Cliente;
use tarkor_nucleo::perfiles::UsoCpu;
use tarkor_nucleo::procesos::{self, Especificacion, Proceso};
use tarkor_nucleo::{equipo, motor, rendimiento};

fn main() {
    let rutas = Rutas::del_sistema();
    let (catalogo, _) = Catalogo::cargar(&rutas.datos);
    let id = std::env::args().nth(1).unwrap_or_else(|| "minimo".into());
    let perfil = catalogo.perfil(&id).expect("perfil desconocido").clone();
    let e = equipo::analizar(&rutas.datos);
    println!("Perfil {} · datos en {}", perfil.nombre, rutas.datos.display());

    let t = Instant::now();
    let mut ultimo = 0u64;
    let exe = motor::instalar(&rutas.ia, &catalogo.motor, &AtomicBool::new(false), &mut |p| match p {
        motor::Progreso::Descargando { hecho, total } if hecho - ultimo > 100 << 20 || hecho == total => {
            ultimo = hecho;
            println!("  motor: {} / {} MB", hecho >> 20, total >> 20);
        }
        motor::Progreso::Descargando { .. } => {}
        otro => println!("  motor: {otro:?}"),
    })
    .unwrap_or_else(|e| panic!("{e}"));
    println!("Motor instalado en {:.0} s: {}", t.elapsed().as_secs_f64(), exe.display());

    let ajustes = rendimiento::calcular(&catalogo, &perfil, Some(&e), UsoCpu::Moderado);
    let puerto = procesos::puerto_libre().unwrap();
    let mut entorno: BTreeMap<String, String> = ajustes.ollama.into_iter().collect();
    entorno.insert("OLLAMA_HOST".into(), format!("127.0.0.1:{puerto}"));
    entorno.insert("OLLAMA_MODELS".into(), rutas.ia.join("modelos").to_string_lossy().into_owned());
    let t = Instant::now();
    let proceso = Proceso::arrancar(Especificacion {
        nombre: "El motor de IA".into(),
        programa: exe,
        argumentos: vec!["serve".into()],
        entorno,
        registro: rutas.registros.join("motor-ia.log"),
        puerto,
        ruta_salud: "/api/version".into(),
        espera_arranque: Duration::from_secs(30),
    })
    .unwrap_or_else(|e| panic!("{e}"));
    let c = Cliente::new(proceso.url());
    println!("Motor en marcha en {:.1} s: Ollama {}", t.elapsed().as_secs_f64(), c.version().unwrap_or_else(|e| e.to_string()));

    for m in perfil.modelos() {
        let r = c.descargar_modelo(m, &AtomicBool::new(false), &mut |p| {
            if p.total > 0 && p.hecho == p.total {
                println!("  {m}: {} ({} MB)", p.estado, p.total >> 20);
            }
        });
        match r {
            Ok(()) => println!("Modelo {m} listo"),
            Err(e) => {
                println!("Modelo {m}: {e}");
                return;
            }
        }
    }
    let piensa = catalogo.modelos.get(&perfil.narrador).is_some_and(|m| m.piensa);
    match c.probar(&perfil.narrador, piensa, rendimiento::hilos_para_ia(UsoCpu::Moderado, e.hilos)) {
        Ok(p) => println!("Narración de prueba: «{}» · {:.1} tokens/s", p.texto, p.tokens_por_segundo),
        Err(e) => println!("Narración de prueba: {e}"),
    }
    if let Ok(cargados) = c.cargados() {
        for m in cargados {
            println!("  {} en la gráfica al {} %", m.modelo, m.porcentaje_gpu);
        }
    }
}
