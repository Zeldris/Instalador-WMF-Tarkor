// Pantalla «El motor de IA se ha detenido» (docs/11, INS-43): se abre con el evento `motor-detenido`.

import { useState } from 'react'
import { api } from './api'
import { CopiarInforme, Pagina } from './componentes'
import * as tx from './textos'
import type { MotorDetenido, PerfilId } from './tipos'

export function PantallaMotorDetenido({ aviso, masLigero, reintentado, irAAjustes }: {
  aviso: MotorDetenido
  /** El siguiente perfil de menos memoria, o null si ya es el más ligero. */
  masLigero: PerfilId | null
  /** El motor arrancó otra vez: la app vuelve a donde estaba. */
  reintentado: () => void
  irAAjustes: (perfil: PerfilId) => void
}) {
  const t = tx.motorDetenido
  const [reintentando, setReintentando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reintentar = async () => {
    setReintentando(true)
    setError(null)
    try {
      await api.reintentarMotor()
      reintentado()
    } catch (e) {
      setError(String(e))
    } finally {
      setReintentando(false)
    }
  }
  return (
    <div className="ventana">
      <Pagina sola titulo={t.titulo} lead={t.lead}
        barra={<><span className="hueco" />
          {aviso.sinMemoria && masLigero && <button type="button" className="btn" disabled={reintentando} onClick={() => irAAjustes(masLigero)}>{t.masLigero}</button>}
          <button type="button" className="btn pri" disabled={reintentando} onClick={() => void reintentar()}>{reintentando ? t.reintentando : t.reintentar}</button></>}>
        <p>{aviso.motivo}</p>
        {aviso.sinMemoria && <p className="peq tenue">{t.sinMemoria}</p>}
        {error && <div className="error" role="alert">{error}</div>}
        <CopiarInforme />
      </Pagina>
    </div>
  )
}
