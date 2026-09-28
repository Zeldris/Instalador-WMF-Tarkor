//! Ajustes de rendimiento de Ollama y del backend para un equipo y un perfil
//! (docs/12-catalogo-y-rendimiento.md). Se calculan en cada arranque, así que si el jugador cambia
//! de perfil o de hardware se adaptan solos.
//!
//! Variables comprobadas contra `envconfig/config.go` de Ollama (septiembre 2026).

use crate::catalogo::{Catalogo, Perfil};
use crate::equipo::Equipo;
use crate::perfiles::{memoria_para_ia_gb, UsoCpu};
use serde::Serialize;

/// Por debajo de este margen de memoria se aprieta más: caché de contexto en 4 bits y lotes más
/// pequeños.
const MARGEN_JUSTO_GB: f64 = 1.0;
/// VRAM que Ollama deja libre en gráficas dedicadas, para que el escritorio no se entrecorte.
const RESERVA_VRAM_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Ajustes {
    /// Para el proceso de Ollama.
    pub ollama: Vec<(String, String)>,
    /// Para el backend del juego, que los pasa a cada petición (fase 3.5 del plan).
    pub backend: Vec<(String, String)>,
    /// Resumen para Ajustes → Rendimiento de la IA.
    pub resumen: Resumen,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Resumen {
    pub hilos: usize,
    pub cache_contexto: &'static str,
    pub usa_gpu_dedicada: bool,
    pub margen_justo: bool,
}

/// Hilos de CPU que usa la IA según la elección del jugador.
pub fn hilos_para_ia(uso: UsoCpu, hilos_equipo: usize) -> usize {
    match uso {
        UsoCpu::Moderado => (hilos_equipo / 2).max(1),
        UsoCpu::Alto => hilos_equipo.saturating_sub(1).max(1),
    }
}

pub fn calcular(catalogo: &Catalogo, perfil: &Perfil, equipo: Option<&Equipo>, uso: UsoCpu) -> Ajustes {
    // Sin análisis no sabemos el margen: se asume justo, que es lo seguro.
    let margen_justo = equipo.is_none_or(|e| memoria_para_ia_gb(&catalogo.reglas, e) - perfil.memoria_gb < MARGEN_JUSTO_GB);
    let gpu_dedicada = equipo.and_then(|e| e.gpu_dedicada()).is_some();
    let hilos = hilos_para_ia(uso, equipo.map_or(4, |e| e.hilos));
    let cache = if margen_justo { "q4_0" } else { "q8_0" };

    let mut ollama: Vec<(&str, String)> = vec![
        // Reduce mucho la memoria del contexto; necesaria para cuantizar la caché.
        ("OLLAMA_FLASH_ATTENTION", "1".into()),
        // q8_0: la mitad de memoria que f16 casi sin pérdida. q4_0: un cuarto, algo de pérdida.
        ("OLLAMA_KV_CACHE_TYPE", cache.into()),
        // Un solo jugador: cada petición en paralelo multiplica la memoria del contexto.
        ("OLLAMA_NUM_PARALLEL", "1".into()),
        ("OLLAMA_MAX_QUEUE", "16".into()),
        ("OLLAMA_MAX_LOADED_MODELS", perfil.max_modelos_cargados.to_string()),
        ("OLLAMA_KEEP_ALIVE", perfil.keep_alive.clone()),
        // El narrador necesita 8192 (con 4096 se desestabilizó, ver backend/Modelfile del juego).
        ("OLLAMA_CONTEXT_LENGTH", catalogo.reglas.contexto_narrador.to_string()),
        // Vulkan cubre gráficas AMD e Intel (y la Steam Deck) que no tienen CUDA ni ROCm.
        ("OLLAMA_VULKAN", "1".into()),
        ("OLLAMA_IGPU_ENABLE", "1".into()),
        // Privacidad (docs/08): ni funciones en la nube ni modelos de otros servidores.
        ("OLLAMA_NO_CLOUD", "1".into()),
        // Los modelos a medio descargar se conservan entre arranques para reanudar.
        ("OLLAMA_NOPRUNE", "1".into()),
    ];
    if gpu_dedicada {
        ollama.push(("OLLAMA_GPU_OVERHEAD", RESERVA_VRAM_BYTES.to_string()));
    }

    let backend: Vec<(&str, String)> = vec![
        ("OLLAMA_MODEL_NARRADOR", perfil.narrador.clone()),
        ("OLLAMA_MODEL_CRONISTA", perfil.cronista.clone()),
        ("OLLAMA_MODEL_SUGERENCIAS", perfil.sugerencias.clone()),
        ("OLLAMA_MODEL_EMBEDDINGS", perfil.embeddings.clone()),
        ("OLLAMA_KEEP_ALIVE", perfil.keep_alive.clone()),
        // Opciones por petición que el backend empaquetado tiene que leer (fase 3.5).
        ("TARKOR_NUM_THREAD", hilos.to_string()),
        ("TARKOR_NUM_BATCH", if margen_justo { "256" } else { "512" }.into()),
        ("TARKOR_NUM_CTX_NARRADOR", catalogo.reglas.contexto_narrador.to_string()),
        ("TARKOR_MODELOS_SIN_PENSAR", catalogo.modelos_que_piensan(perfil).join(",")),
    ];

    let a_string = |v: Vec<(&str, String)>| v.into_iter().map(|(k, x)| (k.to_string(), x)).collect();
    Ajustes {
        ollama: a_string(ollama),
        backend: a_string(backend),
        resumen: Resumen { hilos, cache_contexto: cache, usa_gpu_dedicada: gpu_dedicada, margen_justo },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::perfiles::tests::equipo;

    fn valor<'a>(v: &'a [(String, String)], k: &str) -> Option<&'a str> {
        v.iter().find(|(a, _)| a == k).map(|(_, b)| b.as_str())
    }

    #[test]
    fn hilos_segun_uso() {
        assert_eq!(hilos_para_ia(UsoCpu::Moderado, 8), 4);
        assert_eq!(hilos_para_ia(UsoCpu::Alto, 8), 7);
        assert_eq!(hilos_para_ia(UsoCpu::Moderado, 1), 1);
        assert_eq!(hilos_para_ia(UsoCpu::Alto, 1), 1);
    }

    #[test]
    fn con_margen_amplio_cache_en_8_bits_y_reserva_de_vram() {
        let c = Catalogo::incrustado();
        let e = equipo(32, Some(12), 400);
        let a = calcular(&c, c.perfil("equilibrado").unwrap(), Some(&e), UsoCpu::Moderado);
        assert_eq!(valor(&a.ollama, "OLLAMA_KV_CACHE_TYPE"), Some("q8_0"));
        assert_eq!(valor(&a.ollama, "OLLAMA_GPU_OVERHEAD"), Some("536870912"));
        assert_eq!(valor(&a.backend, "TARKOR_NUM_BATCH"), Some("512"));
        assert!(a.resumen.usa_gpu_dedicada);
    }

    #[test]
    fn con_margen_justo_se_aprieta() {
        let c = Catalogo::incrustado();
        // Deck: 11 GB para la IA; Máximo pide 11 → margen 0.
        let e = equipo(16, None, 200);
        let a = calcular(&c, c.perfil("maximo").unwrap(), Some(&e), UsoCpu::Alto);
        assert_eq!(valor(&a.ollama, "OLLAMA_KV_CACHE_TYPE"), Some("q4_0"));
        assert_eq!(valor(&a.ollama, "OLLAMA_GPU_OVERHEAD"), None);
        assert_eq!(valor(&a.backend, "TARKOR_NUM_BATCH"), Some("256"));
        assert_eq!(valor(&a.backend, "TARKOR_NUM_THREAD"), Some("7"));
    }

    #[test]
    fn siempre_privado_y_un_solo_jugador() {
        let c = Catalogo::incrustado();
        for p in &c.perfiles {
            let a = calcular(&c, p, None, UsoCpu::Moderado);
            assert_eq!(valor(&a.ollama, "OLLAMA_NO_CLOUD"), Some("1"));
            assert_eq!(valor(&a.ollama, "OLLAMA_NUM_PARALLEL"), Some("1"));
            assert_eq!(valor(&a.ollama, "OLLAMA_CONTEXT_LENGTH"), Some("8192"));
            assert_eq!(valor(&a.backend, "OLLAMA_MODEL_NARRADOR"), Some(p.narrador.as_str()));
        }
    }

    #[test]
    fn qwen35_sin_pensar() {
        let c = Catalogo::incrustado();
        let a = calcular(&c, c.perfil("maximo").unwrap(), None, UsoCpu::Moderado);
        assert_eq!(valor(&a.backend, "TARKOR_MODELOS_SIN_PENSAR"), Some("qwen3.5:4b"));
    }
}
