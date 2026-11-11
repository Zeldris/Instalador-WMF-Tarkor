# INS-44: instala el .exe de NSIS en silencio, siembra datos y comprueba qué borra el desinstalador en cada caso
# (docs/07, "Desinstalación"). Lo corre el job `instalador-windows` de .github/workflows/app.yml.
# Uso: pwsh tools/qa/desinstalar-windows.ps1 <ruta al *-setup.exe>
param([Parameter(Mandatory)][string]$Setup)
$ErrorActionPreference = 'Stop'

$programa = Join-Path $env:LOCALAPPDATA 'Programs\Tarkor'
$exe = Join-Path $programa 'tarkor.exe'
$datos = Join-Path $env:APPDATA 'Tarkor'
$local = Join-Path $env:LOCALAPPDATA 'Tarkor'
$ia = Join-Path $local 'ia'
$registros = Join-Path $local 'registros'
$fallos = 0

function Comprobar([bool]$bien, [string]$que) {
    if ($bien) { Write-Host "ok     $que" } else { Write-Host "FALLO  $que"; $script:fallos++ }
}

function Ejecutar([string]$ruta, [string[]]$argumentos) {
    $p = Start-Process -FilePath $ruta -ArgumentList $argumentos -Wait -PassThru
    return $p.ExitCode
}

function Instalar {
    $codigo = Ejecutar $Setup @('/S')
    Comprobar ($codigo -eq 0) "el instalador sale con 0 (salió con $codigo)"
    Comprobar (Test-Path $exe) "tarkor.exe en $programa"
}

function Sembrar {
    New-Item -ItemType Directory -Force $datos, $ia, $registros | Out-Null
    Set-Content (Join-Path $datos 'partida.json') '{}'
    Set-Content (Join-Path $registros 'tarkor.log') 'registro'
    # 0,2 GB: lo bastante para que el tamaño no salga «<0,1 GB»
    $f = [IO.File]::Create((Join-Path $ia 'modelo.bin')); $f.SetLength(214748365); $f.Close()
}

# El desinstalador de NSIS se copia a %TEMP% y se relanza: se espera a que desaparezca la carpeta del programa
# (o, al actualizar, a que el proceso copiado termine).
function Desinstalar([string[]]$opciones) {
    $codigo = Ejecutar (Join-Path $programa 'uninstall.exe') (@('/S') + $opciones)
    Comprobar ($codigo -eq 0) "el desinstalador sale con 0 (salió con $codigo, opciones: $opciones)"
    $limite = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $limite) {
        $copias = Get-Process | Where-Object { $_.Name -match '^(Un_\w|Un|Au_)$' }
        if (-not $copias -and (($opciones -contains '/UPDATE') -or -not (Test-Path $exe))) { break }
        Start-Sleep -Seconds 1
    }
    Start-Sleep -Seconds 2
}

Write-Host '--- 1. Instalación y --info-desinstalar'
Instalar
Sembrar
$ini = Join-Path $env:TEMP 'tarkor-info.ini'
$codigo = Ejecutar $exe @('--info-desinstalar', "`"$ini`"")
Comprobar ($codigo -eq 0) "--info-desinstalar sale con 0 (salió con $codigo)"
$texto = Get-Content $ini -Encoding Unicode -Raw
Comprobar ($texto -match 'tamano=0,2 GB') "el INI trae tamano=0,2 GB: $texto"
Comprobar ($texto -match [regex]::Escape("ruta=$ia")) "el INI trae la ruta de la IA ($ia)"

Write-Host '--- 2. Desinstalar sin casillas: solo los registros'
Desinstalar @()
Comprobar (-not (Test-Path $programa)) 'la carpeta del programa ya no está'
Comprobar (-not (Test-Path $registros)) 'los registros se borran siempre'
Comprobar (Test-Path (Join-Path $datos 'partida.json')) 'las partidas siguen'
Comprobar (Test-Path (Join-Path $ia 'modelo.bin')) 'el motor de IA sigue'

Write-Host '--- 3. Actualizar (/UPDATE) no borra nada, aunque se pidan las casillas'
Instalar
Sembrar
Desinstalar @('/UPDATE', '/BORRARPARTIDAS', '/BORRARIA')
Comprobar (Test-Path $registros) 'los registros siguen'
Comprobar (Test-Path (Join-Path $datos 'partida.json')) 'las partidas siguen'
Comprobar (Test-Path (Join-Path $ia 'modelo.bin')) 'el motor de IA sigue'

Write-Host '--- 4. Desinstalar con /BORRARPARTIDAS y /BORRARIA: no queda nada'
Instalar
Sembrar
Desinstalar @('/BORRARPARTIDAS', '/BORRARIA')
Comprobar (-not (Test-Path $programa)) 'la carpeta del programa ya no está'
Comprobar (-not (Test-Path $datos)) "no queda $datos"
Comprobar (-not (Test-Path $local)) "no queda $local"

if ($fallos -gt 0) { Write-Host "$fallos comprobaciones fallidas"; exit 1 }
Write-Host 'todo bien'
