//! Análisis del equipo del jugador (docs/09-deteccion-de-equipo-y-perfiles.md, "Qué se detecta").
//!
//! Solo se ejecuta con permiso explícito del jugador, todo en local, y el resultado nunca sale del
//! equipo. Cuando la detección de gráfica no es fiable se devuelve la gráfica sin VRAM y el cálculo
//! de perfiles la ignora: tirar a la baja es el comportamiento seguro.

use serde::{Deserialize, Serialize};
use std::path::Path;
use sysinfo::{Disks, System};

const MB: u64 = 1024 * 1024;

/// Por debajo de esto una "VRAM dedicada" es en realidad la reserva de una gráfica integrada
/// (la Steam Deck, por ejemplo, reserva 1 GB de la RAM compartida).
const VRAM_MINIMA_DEDICADA_MB: u64 = 2048;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Gpu {
    pub nombre: String,
    pub fabricante: Fabricante,
    /// `None` si no se pudo leer de forma fiable.
    pub vram_mb: Option<u64>,
    /// Comparte memoria con el sistema (iGPU, APU de la Steam Deck).
    pub integrada: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum Fabricante {
    Nvidia,
    Amd,
    Intel,
    Otro,
}

impl Fabricante {
    pub fn desde_vendor_id(id: u32) -> Self {
        match id {
            0x10de => Self::Nvidia,
            0x1002 | 0x1022 => Self::Amd,
            0x8086 => Self::Intel,
            _ => Self::Otro,
        }
    }

    #[cfg(target_os = "linux")]
    fn nombre(self) -> &'static str {
        match self {
            Self::Nvidia => "NVIDIA",
            Self::Amd => "AMD",
            Self::Intel => "Intel",
            Self::Otro => "Gráfica",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Equipo {
    pub ram_total_mb: u64,
    pub ram_libre_mb: u64,
    pub cpu_modelo: String,
    pub nucleos: usize,
    pub hilos: usize,
    pub gpus: Vec<Gpu>,
    /// Espacio libre en el disco donde vive la carpeta de datos.
    pub disco_libre_mb: u64,
    pub sistema: String,
}

impl Equipo {
    /// La gráfica dedicada con más VRAM fiable, si la hay. Es la que usaría Ollama.
    pub fn gpu_dedicada(&self) -> Option<&Gpu> {
        self.gpus
            .iter()
            .filter(|g| !g.integrada && g.vram_mb.is_some())
            .max_by_key(|g| g.vram_mb)
    }
}

/// Analiza el equipo. `carpeta_datos` decide qué disco se mira para el espacio libre.
pub fn analizar(carpeta_datos: &Path) -> Equipo {
    let mut sys = System::new();
    sys.refresh_memory();
    sys.refresh_cpu_all();

    let cpu_modelo = sys
        .cpus()
        .first()
        .map(|c| c.brand().trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "Procesador desconocido".into());
    let hilos = sys.cpus().len().max(1);
    let nucleos = System::physical_core_count().unwrap_or(hilos).max(1);

    Equipo {
        ram_total_mb: sys.total_memory() / MB,
        ram_libre_mb: sys.available_memory() / MB,
        cpu_modelo,
        nucleos,
        hilos,
        gpus: gpus(),
        disco_libre_mb: disco_libre_mb(carpeta_datos),
        sistema: System::long_os_version().unwrap_or_else(|| std::env::consts::OS.into()),
    }
}

/// Espacio libre del disco cuyo punto de montaje es el prefijo más largo de `ruta`.
fn disco_libre_mb(ruta: &Path) -> u64 {
    let disks = Disks::new_with_refreshed_list();
    // La carpeta de datos puede no existir todavía: se sube hasta un ancestro que exista.
    let ruta = ruta
        .ancestors()
        .find(|p| p.exists())
        .and_then(|p| p.canonicalize().ok())
        .unwrap_or_else(|| ruta.to_path_buf());
    disks
        .list()
        .iter()
        .filter(|d| ruta.starts_with(d.mount_point()))
        .max_by_key(|d| d.mount_point().as_os_str().len())
        .map(|d| d.available_space() / MB)
        .unwrap_or(0)
}

/// Clasifica una gráfica a partir de lo leído del sistema.
pub fn clasificar_gpu(fabricante: Fabricante, nombre: String, vram_mb: Option<u64>) -> Gpu {
    let integrada = fabricante == Fabricante::Intel
        || vram_mb.is_none_or(|v| v < VRAM_MINIMA_DEDICADA_MB);
    Gpu {
        nombre,
        fabricante,
        vram_mb: vram_mb.filter(|_| !integrada),
        integrada,
    }
}

#[cfg(target_os = "linux")]
fn gpus() -> Vec<Gpu> {
    linux::gpus()
}

#[cfg(windows)]
fn gpus() -> Vec<Gpu> {
    windows_dxgi::gpus()
}

#[cfg(not(any(target_os = "linux", windows)))]
fn gpus() -> Vec<Gpu> {
    Vec::new()
}

#[cfg(target_os = "linux")]
mod linux {
    use super::{clasificar_gpu, Fabricante, Gpu, MB};
    use std::fs;
    use std::process::Command;

    /// Lee `/sys/class/drm/card*/device`. AMD expone `mem_info_vram_total`; NVIDIA con el driver
    /// propietario no, así que se consulta `nvidia-smi` si está instalado.
    pub fn gpus() -> Vec<Gpu> {
        let mut out = Vec::new();
        let Ok(entradas) = fs::read_dir("/sys/class/drm") else { return out };
        let mut nvidia = None;
        for e in entradas.flatten() {
            let nombre = e.file_name().to_string_lossy().into_owned();
            // Solo "cardN", no los conectores ("card0-HDMI-A-1").
            if !nombre.starts_with("card") || nombre.contains('-') {
                continue;
            }
            let dev = e.path().join("device");
            let Some(vendor) = leer_hex(&dev.join("vendor")) else { continue };
            let fabricante = Fabricante::desde_vendor_id(vendor);
            let device = leer_hex(&dev.join("device")).unwrap_or(0);
            let mut vram_mb = fs::read_to_string(dev.join("mem_info_vram_total"))
                .ok()
                .and_then(|s| s.trim().parse::<u64>().ok())
                .map(|b| b / MB);
            let mut etiqueta = format!("{} {:04x}", fabricante.nombre(), device);
            if fabricante == Fabricante::Nvidia {
                let datos = nvidia.get_or_insert_with(nvidia_smi);
                if let Some((n, v)) = datos.first() {
                    etiqueta = n.clone();
                    vram_mb = Some(*v);
                }
            }
            out.push(clasificar_gpu(fabricante, etiqueta, vram_mb));
        }
        out
    }

    fn leer_hex(ruta: &std::path::Path) -> Option<u32> {
        let s = fs::read_to_string(ruta).ok()?;
        u32::from_str_radix(s.trim().trim_start_matches("0x"), 16).ok()
    }

    fn nvidia_smi() -> Vec<(String, u64)> {
        let Ok(salida) = Command::new("nvidia-smi")
            .args(["--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
            .output()
        else {
            return Vec::new();
        };
        String::from_utf8_lossy(&salida.stdout)
            .lines()
            .filter_map(|l| {
                let (n, v) = l.split_once(',')?;
                Some((n.trim().to_string(), v.trim().parse().ok()?))
            })
            .collect()
    }
}

#[cfg(windows)]
mod windows_dxgi {
    use super::{clasificar_gpu, Fabricante, Gpu, MB};
    use windows::Win32::Graphics::Dxgi::{
        CreateDXGIFactory1, IDXGIFactory1, DXGI_ADAPTER_FLAG_SOFTWARE,
    };

    /// DXGI da la VRAM dedicada real (a diferencia de WMI, que la corta en 4 GB).
    pub fn gpus() -> Vec<Gpu> {
        let mut out = Vec::new();
        let Ok(factory) = (unsafe { CreateDXGIFactory1::<IDXGIFactory1>() }) else { return out };
        let mut i = 0;
        while let Ok(adapter) = unsafe { factory.EnumAdapters1(i) } {
            i += 1;
            let Ok(desc) = (unsafe { adapter.GetDesc1() }) else { continue };
            if desc.Flags & (DXGI_ADAPTER_FLAG_SOFTWARE.0 as u32) != 0 {
                continue; // "Microsoft Basic Render Driver"
            }
            let fin = desc.Description.iter().position(|&c| c == 0).unwrap_or(desc.Description.len());
            let nombre = String::from_utf16_lossy(&desc.Description[..fin]);
            let vram = desc.DedicatedVideoMemory as u64 / MB;
            out.push(clasificar_gpu(Fabricante::desde_vendor_id(desc.VendorId), nombre, Some(vram)));
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn intel_siempre_integrada() {
        let g = clasificar_gpu(Fabricante::Intel, "Intel Arc".into(), Some(8192));
        assert!(g.integrada);
        assert_eq!(g.vram_mb, None);
    }

    #[test]
    fn reserva_pequena_de_apu_cuenta_como_integrada() {
        // Steam Deck: AMD con 1 GB de "VRAM" que en realidad es RAM compartida.
        let g = clasificar_gpu(Fabricante::Amd, "AMD 163f".into(), Some(1024));
        assert!(g.integrada);
        assert_eq!(g.vram_mb, None);
    }

    #[test]
    fn dedicada_con_vram_fiable() {
        let g = clasificar_gpu(Fabricante::Nvidia, "RTX 3060 Ti".into(), Some(8192));
        assert!(!g.integrada);
        assert_eq!(g.vram_mb, Some(8192));
    }

    #[test]
    fn sin_vram_leida_no_se_asume_dedicada() {
        let g = clasificar_gpu(Fabricante::Nvidia, "NVIDIA".into(), None);
        assert!(g.integrada);
    }

    #[test]
    fn analizar_devuelve_datos_coherentes() {
        let e = analizar(&std::env::temp_dir());
        assert!(e.ram_total_mb > 0);
        assert!(e.hilos >= 1 && e.nucleos >= 1);
        assert!(e.ram_libre_mb <= e.ram_total_mb);
    }
}
