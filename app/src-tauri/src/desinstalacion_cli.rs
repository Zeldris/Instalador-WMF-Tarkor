//! Órdenes de desinstalación por línea de comandos (`--info-desinstalar`, `--desinstalar`).

/// `--info-desinstalar <archivo>` y `--desinstalar [--partidas] [--ia]` (las usa el desinstalador de
/// Windows, `INS-44`): se atienden sin abrir ventana y el proceso termina aquí.
pub(crate) fn ejecutar_orden_de_desinstalacion() {
    use tarkor_nucleo::config::{Config, Rutas};
    use tarkor_nucleo::desinstalar::{analizar_args, borrar, escribir_ini, info, Orden};
    let orden = match analizar_args(std::env::args_os().skip(1)) {
        Ok(Orden::Normal) => return,
        Ok(o) => o,
        Err(e) => {
            eprintln!("tarkor: {e}");
            std::process::exit(1);
        }
    };
    let rutas = Rutas::del_sistema();
    let config = Config::cargar(&rutas.datos);
    let resultado = match orden {
        Orden::InfoDesinstalar(archivo) => escribir_ini(&info(&rutas, &config), &archivo),
        Orden::Desinstalar { partidas, ia } => borrar(&rutas, &config, partidas, ia),
        Orden::Normal => Ok(()),
    };
    if let Err(e) = resultado {
        eprintln!("tarkor: {e}");
        std::process::exit(1);
    }
    std::process::exit(0);
}
