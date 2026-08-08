# Instalador do Agente de Prospecção SEO + GEO + GMN
# Rode com botão direito -> "Executar com o PowerShell"

$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot

Write-Host ""
Write-Host "=== Instalador do Agente de Prospeccao SEO + GEO + GMN ===" -ForegroundColor Cyan
Write-Host ""

# --- Passo 1: pasta certa? ---
if (-not (Test-Path "$dir\config.yaml") -or
    -not (Test-Path "$dir\CLAUDE.md") -or
    -not (Test-Path "$dir\scripts")) {
    Write-Host "ERRO: nao encontrei os arquivos esperados (config.yaml, CLAUDE.md, scripts/)." -ForegroundColor Red
    Write-Host "Confirma se voce extraiu o ZIP certo e esta rodando este instalador" -ForegroundColor Red
    Write-Host "de dentro da pasta correta." -ForegroundColor Red
    Write-Host ""
    Read-Host "Pressione Enter para fechar"
    exit 1
}
Write-Host "[1/4] Pasta correta encontrada." -ForegroundColor Green

# --- Passo 2: Python 3.11+? ---
$pythonCmd = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $raw = & $cmd --version 2>&1
        if ($raw -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                $pythonCmd = $cmd
                Write-Host "[2/4] Python $major.$minor encontrado." -ForegroundColor Green
                break
            } else {
                Write-Host "ERRO: Python $major.$minor encontrado, mas precisa ser 3.11 ou mais novo." -ForegroundColor Red
                Write-Host "Baixe a versao atual em: https://www.python.org/downloads/" -ForegroundColor Yellow
                Write-Host "Durante a instalacao, marque 'Add Python to PATH'." -ForegroundColor Yellow
                Write-Host ""
                Read-Host "Pressione Enter para fechar"
                exit 1
            }
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "ERRO: Python nao encontrado." -ForegroundColor Red
    Write-Host "Baixe em: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "Durante a instalacao, marque 'Add Python to PATH'." -ForegroundColor Yellow
    Write-Host "Depois de instalar, rode este instalador de novo." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Pressione Enter para fechar"
    exit 1
}

# --- Passo 3: instalar dependencias ---
Write-Host "[3/4] Instalando dependencias Python (PyYAML)..." -ForegroundColor Cyan
$null = & $pythonCmd -m pip install pyyaml --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO ao instalar dependencias (pip retornou $LASTEXITCODE)." -ForegroundColor Red
    Write-Host "Tente rodar este instalador como Administrador (botao direito -> Executar como administrador)." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Pressione Enter para fechar"
    exit 1
}

# --- Passo 4: garantir .claude/commands/prospeccao-de-leads.md ---
$commandsDir  = "$dir\.claude\commands"
$sourceFile   = "$dir\commands\prospeccao-de-leads.md"
$targetFile   = "$commandsDir\prospeccao-de-leads.md"

if (-not (Test-Path $commandsDir)) {
    New-Item -ItemType Directory -Path $commandsDir -Force | Out-Null
}

if (-not (Test-Path $targetFile)) {
    if (Test-Path $sourceFile) {
        Copy-Item $sourceFile $targetFile
        Write-Host "[4/4] Comando /prospeccao-de-leads copiado para .claude\commands\." -ForegroundColor Green
    } else {
        Write-Host "AVISO: nao encontrei commands\prospeccao-de-leads.md para copiar." -ForegroundColor Yellow
        Write-Host "O comando pode nao aparecer no Claude Code. Verifique se o ZIP foi extraido corretamente." -ForegroundColor Yellow
    }
} else {
    Write-Host "[4/4] Comando /prospeccao-de-leads ja esta no lugar certo." -ForegroundColor Green
}

# --- Sucesso ---
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Instalacao concluida!" -ForegroundColor Green
Write-Host " Abra o Claude Code nesta pasta e" -ForegroundColor Green
Write-Host " digite /prospeccao-de-leads para comecar." -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Read-Host "Pressione Enter para fechar"
