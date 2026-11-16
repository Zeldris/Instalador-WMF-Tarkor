//! Órdenes de desinstalación por línea de comandos (`--info-desinstalar`, `--desinstalar`).

use tarkor_nucleo::config::{Config, Rutas};
use tarkor_nucleo::desinstalar::{analizar_args, borrar, escribir_ini, info, Orden};

/// `--info-desinstalar <archivo>` y `--desinstalar [--partidas] [--ia]` (las usa el desinstalador de
/// Windows, `INS-44`): se atienden sin abrir ventana y el proceso termina aquí.
pub(crate) fn ejecutar_orden_de_desinstalacion() {
    let orden = analizar_args(std::env::args_os().skip(1));
    if matches!(orden, Ok(Orden::Normal)) {
        return;
    }
    let rutas = Rutas::del_sistema();
    let config = Config::cargar(&rutas.datos);
    let resultado = match orden {
        Ok(Orden::InfoDesinstalar(archivo)) => escribir_ini(&info(&rutas, &config), &archivo),
        Ok(Orden::Desinstalar { partidas, ia }) => borrar(&rutas, &config, partidas, ia),
        Ok(Orden::Normal) => return,
        Err(e) => {
            eprintln!("tarkor: {e}");
            std::process::exit(1);
        }
    };
    if let Err(e) = resultado {
        eprintln!("tarkor: {e}");
        std::process::exit(1);
    }
    std::process::exit(0);
}
