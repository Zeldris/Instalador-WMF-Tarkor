//! Perfiles de IA y cálculo del máximo seguro (docs/09-deteccion-de-equipo-y-perfiles.md).
//!
//! Las cifras de memoria y descarga son estimaciones a validar en la fase 0.8 del plan; cuando se
//! midan en equipos reales, se cambian aquí y en la tabla de docs/09 a la vez.

use crate::equipo::Equipo;
use serde::{Deserialize, Serialize};

const MB_POR_GB: f64 = 1024.0;
/// Memoria que se reserva siempre para el sistema: `max(3 GB, 25 % de la RAM)`.
const RESERVA_MINIMA_GB: f64 = 3.0;
const RESERVA_PROPORCION: f64 = 0.25;
/// Webview + backend + SQLite.
const MEMORIA_JUEGO_GB: f64 = 1.0;
/// Parte de la VRAM dedicada que se cuenta como disponible para capas del modelo.
const PROPORCION_VRAM_UTIL: f64 = 0.9;
/// Si el máximo seguro deja menos margen que esto, se recomienda el perfil de debajo.
const MARGEN_COMODO_GB: f64 = 1.5;
/// Margen de disco sobre el tamaño de la descarga.
const MARGEN_DISCO: f64 = 1.1;

pub const CRONISTA: &str = "qwen2.5:1.5b-instruct";
pub const EMBEDDINGS: &str = "nomic-embed-text";

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum PerfilId {
    Ligero,
    Equilibrado,
    Maximo,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum UsoCpu {
    #[default]
    Moderado,
    Alto,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Perfil {
    pub id: PerfilId,
    pub nombre: &'static str,
    /// Pico estimado de memoria solo de la IA.
    pub memoria_gb: f64,
    pub descarga_gb: f64,
    /// 1-3, para las marcas de la tarjeta.
    pub velocidad: u8,
    pub calidad: u8,
    pub narrador: &'static str,
    pub cronista: &'static str,
    pub sugerencias: &'static str,
    pub embeddings: &'static str,
    pub max_modelos_cargados: u8,
    pub keep_alive: &'static str,
}

impl Perfil {
    /// Modelos a descargar, sin repetir (en Ligero y Equilibrado "Sugerir" reutiliza el cronista).
    pub fn modelos(&self) -> Vec<&'static str> {
        let mut v: Vec<&'static str> = Vec::new();
        for m in [self.narrador, self.cronista, self.sugerencias, self.embeddings] {
            if !v.contains(&m) {
                v.push(m);
            }
        }
        v
    }
}

pub const PERFILES: [Perfil; 3] = [
    Perfil {
        id: PerfilId::Ligero,
        nombre: "Ligero",
        memoria_gb: 3.5,
        descarga_gb: 3.3,
        velocidad: 3,
        calidad: 1,
        narrador: "qwen2.5:3b",
        cronista: CRONISTA,
        sugerencias: CRONISTA,
        embeddings: EMBEDDINGS,
        max_modelos_cargados: 1,
        keep_alive: "2m",
    },
    Perfil {
        id: PerfilId::Equilibrado,
        nombre: "Equilibrado",
        memoria_gb: 7.0,
        descarga_gb: 6.0,
        velocidad: 2,
        calidad: 2,
        narrador: "qwen2.5:7b",
        cronista: CRONISTA,
        sugerencias: CRONISTA,
        embeddings: EMBEDDINGS,
        max_modelos_cargados: 2,
        keep_alive: "5m",
    },
    Perfil {
        id: PerfilId::Maximo,
        nombre: "Máximo",
        memoria_gb: 10.5,
        descarga_gb: 9.0,
        velocidad: 2,
        calidad: 3,
        narrador: "qwen2.5:7b",
        cronista: CRONISTA,
        sugerencias: "qwen3.5:4b",
        embeddings: EMBEDDINGS,
        max_modelos_cargados: 4,
        keep_alive: "5m",
    },
];

pub fn perfil(id: PerfilId) -> &'static Perfil {
    PERFILES.iter().find(|p| p.id == id).expect("todos los PerfilId están en PERFILES")
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PerfilEvaluado {
    #[serde(flatten)]
    pub perfil: Perfil,
    pub cabe_en_memoria: bool,
    pub cabe_en_disco: bool,
}

impl PerfilEvaluado {
    pub fn cabe(&self) -> bool {
        self.cabe_en_memoria && self.cabe_en_disco
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Evaluacion {
    /// `None` si el jugador eligió "a mano" (sin análisis).
    pub memoria_para_ia_gb: Option<f64>,
    pub perfiles: Vec<PerfilEvaluado>,
    pub maximo_seguro: Option<PerfilId>,
    pub recomendado: PerfilId,
    /// Se analizó el equipo y no cabe ni el perfil más ligero.
    pub equipo_insuficiente: bool,
}

/// Memoria que el equipo puede dedicar a la IA sin quedarse corto.
pub fn memoria_para_ia_gb(equipo: &Equipo) -> f64 {
    let ram = equipo.ram_total_mb as f64 / MB_POR_GB;
    let reserva = RESERVA_MINIMA_GB.max(ram * RESERVA_PROPORCION);
    let mut para_ia = ram - reserva - MEMORIA_JUEGO_GB;
    if let Some(vram) = equipo.gpu_dedicada().and_then(|g| g.vram_mb) {
        para_ia += vram as f64 / MB_POR_GB * PROPORCION_VRAM_UTIL;
    }
    para_ia.max(0.0)
}

/// Evalúa los perfiles para un equipo, o sin equipo si el jugador prefirió elegir a mano.
pub fn evaluar(equipo: Option<&Equipo>) -> Evaluacion {
    let Some(equipo) = equipo else {
        return Evaluacion {
            memoria_para_ia_gb: None,
            perfiles: PERFILES
                .iter()
                .map(|p| PerfilEvaluado { perfil: p.clone(), cabe_en_memoria: true, cabe_en_disco: true })
                .collect(),
            maximo_seguro: None,
            recomendado: PerfilId::Ligero,
            equipo_insuficiente: false,
        };
    };

    let para_ia = memoria_para_ia_gb(equipo);
    let disco_gb = equipo.disco_libre_mb as f64 / MB_POR_GB;
    let perfiles: Vec<PerfilEvaluado> = PERFILES
        .iter()
        .map(|p| PerfilEvaluado {
            perfil: p.clone(),
            cabe_en_memoria: p.memoria_gb <= para_ia,
            cabe_en_disco: p.descarga_gb * MARGEN_DISCO <= disco_gb,
        })
        .collect();

    let caben: Vec<&PerfilEvaluado> = perfiles.iter().filter(|p| p.cabe()).collect();
    let maximo = caben.last().map(|p| p.perfil.id);
    let recomendado = match caben.as_slice() {
        [] => PerfilId::Ligero,
        [.., anterior, ultimo] if para_ia - ultimo.perfil.memoria_gb < MARGEN_COMODO_GB => anterior.perfil.id,
        [.., ultimo] => ultimo.perfil.id,
    };

    Evaluacion {
        memoria_para_ia_gb: Some(para_ia),
        equipo_insuficiente: maximo.is_none(),
        perfiles,
        maximo_seguro: maximo,
        recomendado,
    }
}

/// Hilos de CPU que usa la IA según la elección del jugador.
pub fn hilos_para_ia(uso: UsoCpu, hilos_equipo: usize) -> usize {
    match uso {
        UsoCpu::Moderado => (hilos_equipo / 2).max(1),
        UsoCpu::Alto => hilos_equipo.saturating_sub(1).max(1),
    }
}

/// Variables de entorno del sidecar de Ollama para un perfil (docs/03, "Decisión").
pub fn entorno_ollama(p: &Perfil) -> Vec<(&'static str, String)> {
    vec![
        ("OLLAMA_MAX_LOADED_MODELS", p.max_modelos_cargados.to_string()),
        ("OLLAMA_KEEP_ALIVE", p.keep_alive.to_string()),
        // Mismos ajustes que iniciar-tarkor.sh en desarrollo.
        ("OLLAMA_FLASH_ATTENTION", "1".into()),
        ("OLLAMA_KV_CACHE_TYPE", "q8_0".into()),
        ("OLLAMA_IGPU_ENABLE", "1".into()),
    ]
}

/// Variables de entorno del backend del juego para un perfil. `TARKOR_NUM_THREAD` es nueva: la
/// lee el backend en modo empaquetado (fase 3 del plan) y la manda como `options.num_thread`.
pub fn entorno_backend(p: &Perfil, uso: UsoCpu, hilos_equipo: usize) -> Vec<(&'static str, String)> {
    vec![
        ("OLLAMA_MODEL_NARRADOR", p.narrador.into()),
        ("OLLAMA_MODEL_CRONISTA", p.cronista.into()),
        ("OLLAMA_MODEL_SUGERENCIAS", p.sugerencias.into()),
        ("OLLAMA_MODEL_EMBEDDINGS", p.embeddings.into()),
        ("OLLAMA_KEEP_ALIVE", p.keep_alive.into()),
        ("TARKOR_NUM_THREAD", hilos_para_ia(uso, hilos_equipo).to_string()),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::equipo::{Fabricante, Gpu};

    fn equipo(ram_gb: u64, vram_gb: Option<u64>, disco_gb: u64) -> Equipo {
        let gpus = match vram_gb {
            Some(v) => vec![Gpu { nombre: "dedicada".into(), fabricante: Fabricante::Nvidia, vram_mb: Some(v * 1024), integrada: false }],
            None => vec![Gpu { nombre: "integrada".into(), fabricante: Fabricante::Amd, vram_mb: None, integrada: true }],
        };
        Equipo {
            ram_total_mb: ram_gb * 1024,
            ram_libre_mb: ram_gb * 512,
            cpu_modelo: "prueba".into(),
            nucleos: 4,
            hilos: 8,
            gpus,
            disco_libre_mb: disco_gb * 1024,
            sistema: "prueba".into(),
        }
    }

    // Los cuatro ejemplos de la tabla de docs/09.

    #[test]
    fn portatil_8gb_solo_ligero() {
        let ev = evaluar(Some(&equipo(8, None, 100)));
        assert_eq!(ev.memoria_para_ia_gb, Some(4.0));
        assert_eq!(ev.maximo_seguro, Some(PerfilId::Ligero));
        assert_eq!(ev.recomendado, PerfilId::Ligero);
        assert!(!ev.equipo_insuficiente);
    }

    #[test]
    fn deck_16gb_maximo_justo_recomienda_equilibrado() {
        let ev = evaluar(Some(&equipo(16, None, 200)));
        assert_eq!(ev.memoria_para_ia_gb, Some(11.0));
        assert_eq!(ev.maximo_seguro, Some(PerfilId::Maximo));
        assert_eq!(ev.recomendado, PerfilId::Equilibrado);
    }

    #[test]
    fn pc_16gb_con_gpu_8gb_recomienda_maximo() {
        let ev = evaluar(Some(&equipo(16, Some(8), 400)));
        let m = ev.memoria_para_ia_gb.unwrap();
        assert!((m - 18.2).abs() < 0.01, "{m}");
        assert_eq!(ev.maximo_seguro, Some(PerfilId::Maximo));
        assert_eq!(ev.recomendado, PerfilId::Maximo);
    }

    #[test]
    fn equipo_6gb_insuficiente_pero_propone_ligero() {
        let ev = evaluar(Some(&equipo(6, None, 100)));
        assert_eq!(ev.memoria_para_ia_gb, Some(2.0));
        assert_eq!(ev.maximo_seguro, None);
        assert!(ev.equipo_insuficiente);
        assert_eq!(ev.recomendado, PerfilId::Ligero);
    }

    #[test]
    fn el_disco_tambien_limita() {
        // Memoria de sobra pero solo 7 GB libres: Máximo necesita 9 × 1,1 = 9,9 GB y no cabe;
        // Equilibrado necesita 6 × 1,1 = 6,6 GB y sí.
        let ev = evaluar(Some(&equipo(32, Some(12), 7)));
        assert_eq!(ev.maximo_seguro, Some(PerfilId::Equilibrado));
        let max = ev.perfiles.iter().find(|p| p.perfil.id == PerfilId::Maximo).unwrap();
        assert!(max.cabe_en_memoria && !max.cabe_en_disco);
    }

    #[test]
    fn sin_analisis_todo_disponible_y_ligero_por_defecto() {
        let ev = evaluar(None);
        assert_eq!(ev.memoria_para_ia_gb, None);
        assert_eq!(ev.maximo_seguro, None);
        assert_eq!(ev.recomendado, PerfilId::Ligero);
        assert!(ev.perfiles.iter().all(|p| p.cabe()));
    }

    #[test]
    fn la_integrada_no_suma_vram() {
        let mut e = equipo(16, None, 200);
        e.gpus[0].vram_mb = Some(1024); // aunque viniera con dato, está marcada como integrada
        assert_eq!(memoria_para_ia_gb(&e), 11.0);
    }

    #[test]
    fn modelos_sin_repetidos() {
        assert_eq!(perfil(PerfilId::Ligero).modelos(), vec!["qwen2.5:3b", CRONISTA, EMBEDDINGS]);
        assert_eq!(perfil(PerfilId::Maximo).modelos(), vec!["qwen2.5:7b", CRONISTA, "qwen3.5:4b", EMBEDDINGS]);
    }

    #[test]
    fn embeddings_en_todos_los_perfiles() {
        // El juego lo necesita en partida, no solo al indexar (docs/03).
        assert!(PERFILES.iter().all(|p| p.modelos().contains(&EMBEDDINGS)));
    }

    #[test]
    fn hilos_segun_uso() {
        assert_eq!(hilos_para_ia(UsoCpu::Moderado, 8), 4);
        assert_eq!(hilos_para_ia(UsoCpu::Alto, 8), 7);
        assert_eq!(hilos_para_ia(UsoCpu::Moderado, 1), 1);
        assert_eq!(hilos_para_ia(UsoCpu::Alto, 1), 1);
    }

    #[test]
    fn serializa_en_camel_case_para_el_asistente() {
        let json = serde_json::to_value(evaluar(Some(&equipo(16, None, 200)))).unwrap();
        assert_eq!(json["recomendado"], "equilibrado");
        assert_eq!(json["maximoSeguro"], "maximo");
        assert_eq!(json["perfiles"][0]["memoriaGb"], 3.5);
        assert_eq!(json["perfiles"][0]["cabeEnMemoria"], true);
    }
}
