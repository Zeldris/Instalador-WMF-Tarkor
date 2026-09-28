//! App de escritorio de Tarkor: expone al asistente el análisis del equipo, el catálogo, la
//! configuración y el motor de IA (instalación, arranque, modelos y comprobaciones). El backend
//! del juego se añadirá como segundo proceso en la fase 4 con el mismo gestor (`procesos`).

use serde::Serialize;
use std::collections::BTreeMap;
use std::fs;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tarkor_nucleo::catalogo::{Catalogo, Origen, Perfil};
use tarkor_nucleo::config::{Config, Rutas};
use tarkor_nucleo::equipo::{self, Equipo};
use tarkor_nucleo::ollama::{self, Cliente, ProgresoModelo};
use tarkor_nucleo::perfiles::{self, Evaluacion, UsoCpu};
use tarkor_nucleo::procesos::{self, Especificacion, Estado as EstadoProceso, Proceso};
use tarkor_nucleo::rendimiento::{self, Ajustes};
use tarkor_nucleo::{motor, rendimiento::hilos_para_ia};
use tauri::ipc::Channel;
use tauri::{Manager, RunEvent, State};

struct Estado {
    rutas: Rutas,
    catalogo: Catalogo,
    origen_catalogo: Origen,
    /// Ollama en marcha, o la URL de uno externo si se indicó `TARKOR_OLLAMA_URL`.
    motor: Mutex<Option<Proceso>>,
    ollama_externo: Option<String>,
    cancelar: Arc<AtomicBool>,
}

impl Estado {
    fn config(&self) -> Config {
        Config::cargar(&self.rutas.datos)
    }

    fn perfil(&self, config: &Config) -> Result<&Perfil, String> {
        let id = config.perfil.as_deref().ok_or("todavía no se ha elegido perfil")?;
        self.catalogo.perfil(id).ok_or_else(|| format!("perfil desconocido: {id}"))
    }

    fn cliente(&self) -> Result<Cliente, String> {
        if let Some(url) = &self.ollama_externo {
            return Ok(Cliente::new(url.clone()));
        }
        let m = self.motor.lock().unwrap();
        m.as_ref().map(|p| Cliente::new(p.url())).ok_or_else(|| "El motor de IA no está en marcha.".to_string())
    }
}

type Res<T> = Result<T, String>;

#[tauri::command]
fn rutas(estado: State<'_, Estado>) -> Rutas {
    estado.rutas.clone()
}

/// De dónde salió el catálogo (incrustado, externo, o externo inválido y por qué).
#[tauri::command]
fn origen_catalogo(estado: State<'_, Estado>) -> Origen {
    estado.origen_catalogo.clone()
}

#[tauri::command]
fn cargar_config(estado: State<'_, Estado>) -> Config {
    estado.config()
}

#[tauri::command]
fn guardar_config(estado: State<'_, Estado>, config: Config) -> Res<()> {
    config.guardar(&estado.rutas.datos).map_err(|e| e.to_string())
}

/// Solo se llama tras el permiso explícito del jugador (pantalla 3 del asistente).
#[tauri::command]
async fn analizar_equipo(estado: State<'_, Estado>) -> Res<Equipo> {
    let datos = estado.rutas.datos.clone();
    tauri::async_runtime::spawn_blocking(move || equipo::analizar(&datos)).await.map_err(|e| e.to_string())
}

#[tauri::command]
fn evaluar_perfiles(estado: State<'_, Estado>, equipo: Option<Equipo>) -> Evaluacion {
    perfiles::evaluar(&estado.catalogo, equipo.as_ref())
}

#[tauri::command]
fn ajustes_rendimiento(estado: State<'_, Estado>, perfil: String, equipo: Option<Equipo>, uso_cpu: UsoCpu) -> Res<Ajustes> {
    let p = estado.catalogo.perfil(&perfil).ok_or_else(|| format!("perfil desconocido: {perfil}"))?;
    Ok(rendimiento::calcular(&estado.catalogo, p, equipo.as_ref(), uso_cpu))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct InfoMotor {
    version: String,
    instalado: bool,
    en_marcha: bool,
    descarga_gb: f64,
    /// Tamaño de cada modelo del catálogo, para mostrarlo antes de descargar.
    modelos_gb: BTreeMap<String, f64>,
}

#[tauri::command]
fn estado_motor(estado: State<'_, Estado>) -> InfoMotor {
    let m = &estado.catalogo.motor;
    InfoMotor {
        version: m.version.clone(),
        instalado: estado.ollama_externo.is_some() || motor::instalado(&estado.rutas.ia, m),
        en_marcha: estado.cliente().and_then(|c| c.version().map_err(|e| e.to_string())).is_ok(),
        descarga_gb: if estado.ollama_externo.is_some() { 0.0 } else { m.paquete().map_or(0.0, |p| p.descarga_gb) },
        modelos_gb: estado.catalogo.modelos.iter().map(|(k, v)| (k.clone(), v.descarga_gb)).collect(),
    }
}

/// Pausa cualquier descarga en curso. Lo descargado se conserva para continuar.
#[tauri::command]
fn cancelar_descargas(estado: State<'_, Estado>) {
    estado.cancelar.store(true, Ordering::Relaxed);
}

#[tauri::command]
async fn instalar_motor(app: tauri::AppHandle, canal: Channel<motor::Progreso>) -> Res<()> {
    let estado = app.state::<Estado>();
    if estado.ollama_externo.is_some() {
        let _ = canal.send(motor::Progreso::Listo);
        return Ok(());
    }
    estado.cancelar.store(false, Ordering::Relaxed);
    let (ia, m, cancelar) = (estado.rutas.ia.clone(), estado.catalogo.motor.clone(), estado.cancelar.clone());
    tauri::async_runtime::spawn_blocking(move || {
        motor::instalar(&ia, &m, &cancelar, &mut |p| {
            let _ = canal.send(p);
        })
        .map(|_| ())
        .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Arranca Ollama con los ajustes del perfil y el equipo guardados (docs/12). Si ya estaba en
/// marcha lo reinicia, para aplicar un perfil nuevo.
#[tauri::command]
async fn iniciar_motor(app: tauri::AppHandle) -> Res<()> {
    let estado = app.state::<Estado>();
    if estado.ollama_externo.is_some() {
        return Ok(());
    }
    let config = estado.config();
    let perfil = estado.perfil(&config)?.clone();
    let m = &estado.catalogo.motor;
    let ejecutable = motor::ejecutable(&motor::carpeta(&estado.rutas.ia, m));
    if !ejecutable.exists() {
        return Err("El motor de IA no está instalado.".into());
    }
    let ajustes = rendimiento::calcular(&estado.catalogo, &perfil, config.equipo.as_ref(), config.uso_cpu);
    let puerto = procesos::puerto_libre().map_err(|e| e.to_string())?;
    let mut entorno: BTreeMap<String, String> = ajustes.ollama.into_iter().collect();
    entorno.insert("OLLAMA_HOST".into(), format!("127.0.0.1:{puerto}"));
    entorno.insert("OLLAMA_MODELS".into(), estado.rutas.ia.join("modelos").to_string_lossy().into_owned());
    let espec = Especificacion {
        nombre: "El motor de IA".into(),
        programa: ejecutable,
        argumentos: vec!["serve".into()],
        entorno,
        registro: estado.rutas.registros.join("motor-ia.log"),
        puerto,
        ruta_salud: "/api/version".into(),
        espera_arranque: Duration::from_secs(30),
    };
    if let Some(mut viejo) = estado.motor.lock().unwrap().take() {
        viejo.parar();
    }
    let proceso = tauri::async_runtime::spawn_blocking(move || Proceso::arrancar(espec))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?;
    *estado.motor.lock().unwrap() = Some(proceso);
    Ok(())
}

#[tauri::command]
fn vigilar_motor(estado: State<'_, Estado>) -> EstadoProceso {
    match estado.motor.lock().unwrap().as_mut() {
        Some(p) => p.vigilar(),
        None => EstadoProceso::Detenido { motivo: "El motor de IA no está en marcha.".into() },
    }
}

/// Descarga los modelos del perfil que falten. Ollama reanuda lo que se quedara a medias.
#[tauri::command]
async fn descargar_modelos(app: tauri::AppHandle, canal: Channel<ProgresoModelo>) -> Res<Vec<String>> {
    let estado = app.state::<Estado>();
    estado.cancelar.store(false, Ordering::Relaxed);
    let perfil = estado.perfil(&estado.config())?.clone();
    let cliente = estado.cliente()?;
    let cancelar = estado.cancelar.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let hay = cliente.modelos().map_err(|e| e.to_string())?;
        let modelos: Vec<String> = perfil.modelos().into_iter().map(String::from).collect();
        for m in &modelos {
            if tiene(&hay, m) {
                let _ = canal.send(ProgresoModelo { modelo: m.clone(), estado: "success".into(), hecho: 1, total: 1 });
                continue;
            }
            cliente
                .descargar_modelo(m, &cancelar, &mut |p| {
                    let _ = canal.send(p);
                })
                .map_err(|e| e.to_string())?;
        }
        Ok(modelos)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// `nomic-embed-text` aparece en Ollama como `nomic-embed-text:latest`.
fn tiene(hay: &[String], modelo: &str) -> bool {
    hay.iter().any(|h| h == modelo || h.strip_suffix(":latest") == Some(modelo))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase", tag = "resultado")]
enum Comprobacion {
    Ok { detalle: String },
    /// Todavía no aplica en esta fase (llega con el juego empaquetado, fase 4).
    Omitida { motivo: String },
}

/// Una de las comprobaciones de docs/07, por id.
#[tauri::command]
async fn comprobar(app: tauri::AppHandle, id: String) -> Res<Comprobacion> {
    let estado = app.state::<Estado>();
    let pendiente = || Ok(Comprobacion::Omitida { motivo: "Llega con el juego empaquetado (fase 4).".into() });
    match id.as_str() {
        "datos" => {
            let prueba = estado.rutas.datos.join(".prueba-escritura");
            fs::create_dir_all(&estado.rutas.datos)
                .and_then(|_| fs::write(&prueba, b"ok"))
                .and_then(|_| fs::remove_file(&prueba))
                .map_err(|e| format!("No se puede escribir en la carpeta de datos ({}): {e}", estado.rutas.datos.display()))?;
            Ok(Comprobacion::Ok { detalle: format!("Se puede escribir en {}.", estado.rutas.datos.display()) })
        }
        "basedatos" | "juego" | "mundo" => pendiente(),
        "motor" => {
            let v = estado.cliente()?.version().map_err(|e| e.to_string())?;
            Ok(Comprobacion::Ok { detalle: format!("En marcha (Ollama {v}).") })
        }
        "modelos" => {
            let perfil = estado.perfil(&estado.config())?.clone();
            let hay = estado.cliente()?.modelos().map_err(|e| e.to_string())?;
            let faltan: Vec<&str> = perfil.modelos().into_iter().filter(|m| !tiene(&hay, m)).collect();
            if !faltan.is_empty() {
                return Err(format!("Faltan modelos: {}. Vuelve al paso de descarga.", faltan.join(", ")));
            }
            Ok(Comprobacion::Ok { detalle: "Todos presentes.".into() })
        }
        "narracion" => {
            let config = estado.config();
            let perfil = estado.perfil(&config)?.clone();
            let piensa = estado.catalogo.modelos.get(&perfil.narrador).is_some_and(|m| m.piensa);
            let hilos = hilos_para_ia(config.uso_cpu, config.equipo.as_ref().map_or(4, |e| e.hilos));
            let cliente = estado.cliente()?;
            let prueba = tauri::async_runtime::spawn_blocking(move || cliente.probar(&perfil.narrador, piensa, hilos))
                .await
                .map_err(|e| e.to_string())?
                .map_err(|e: ollama::Error| e.to_string())?;
            Ok(Comprobacion::Ok {
                detalle: serde_json::json!({ "texto": prueba.texto, "tokensPorSegundo": prueba.tokens_por_segundo }).to_string(),
            })
        }
        otro => Err(format!("comprobación desconocida: {otro}")),
    }
}

pub fn run() {
    let rutas_app = Rutas::del_sistema();
    let (catalogo, origen) = Catalogo::cargar(&rutas_app.datos);
    let app = tauri::Builder::default()
        .manage(Estado {
            rutas: rutas_app,
            catalogo,
            origen_catalogo: origen,
            motor: Mutex::new(None),
            // Para pruebas y desarrollo: usar un Ollama ya en marcha en vez de instalar uno.
            ollama_externo: std::env::var("TARKOR_OLLAMA_URL").ok(),
            cancelar: Arc::new(AtomicBool::new(false)),
        })
        .invoke_handler(tauri::generate_handler![
            rutas,
            origen_catalogo,
            cargar_config,
            guardar_config,
            analizar_equipo,
            evaluar_perfiles,
            ajustes_rendimiento,
            estado_motor,
            cancelar_descargas,
            instalar_motor,
            iniciar_motor,
            vigilar_motor,
            descargar_modelos,
            comprobar
        ])
        .build(tauri::generate_context!())
        .expect("no se pudo iniciar Tarkor");
    app.run(|app, evento| {
        // Al cerrar, el motor se para siempre (docs/08: nada queda funcionando en segundo plano).
        if let RunEvent::Exit = evento {
            if let Some(mut p) = app.state::<Estado>().motor.lock().unwrap().take() {
                p.parar();
            }
        }
    });
}
