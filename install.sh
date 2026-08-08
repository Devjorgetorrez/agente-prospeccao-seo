#!/usr/bin/env bash
# Instalador do Agente de Prospecção SEO + GEO + GMN
# Como usar: abra o Terminal na pasta e rode: bash install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "=== Instalador do Agente de Prospecção SEO + GEO + GMN ==="
echo ""

# --- Passo 1: pasta certa? ---
if [ ! -f "$SCRIPT_DIR/config.yaml" ] || \
   [ ! -f "$SCRIPT_DIR/CLAUDE.md" ] || \
   [ ! -d "$SCRIPT_DIR/scripts" ]; then
    echo "ERRO: não encontrei os arquivos esperados (config.yaml, CLAUDE.md, scripts/)."
    echo "Confirma se você extraiu o ZIP certo e está rodando este instalador"
    echo "de dentro da pasta correta."
    exit 1
fi
echo "[1/4] Pasta correta encontrada."

# --- Passo 2: Python 3.11+? ---
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        raw=$("$cmd" --version 2>&1)
        if [[ "$raw" =~ Python\ ([0-9]+)\.([0-9]+) ]]; then
            major="${BASH_REMATCH[1]}"
            minor="${BASH_REMATCH[2]}"
            if [ "$major" -gt 3 ] || ([ "$major" -eq 3 ] && [ "$minor" -ge 11 ]); then
                PYTHON_CMD="$cmd"
                echo "[2/4] Python $major.$minor encontrado."
                break
            else
                echo "ERRO: Python $major.$minor encontrado, mas precisa ser 3.11 ou mais novo."
                echo "Baixe a versão atual em: https://www.python.org/downloads/"
                exit 1
            fi
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "ERRO: Python não encontrado."
    echo "Baixe em: https://www.python.org/downloads/"
    echo "Depois de instalar, rode este instalador de novo: bash install.sh"
    exit 1
fi

# --- Passo 3: instalar dependencias ---
echo "[3/4] Instalando dependências Python (PyYAML)..."
if "$PYTHON_CMD" -m pip install pyyaml --quiet --disable-pip-version-check --break-system-packages 2>/dev/null; then
    : # sucesso com --break-system-packages
elif "$PYTHON_CMD" -m pip install pyyaml --quiet --disable-pip-version-check 2>/dev/null; then
    : # sucesso sem a flag
else
    echo "ERRO ao instalar dependências."
    echo "Tente rodar com sudo: sudo bash install.sh"
    exit 1
fi
echo "[3/4] Dependências instaladas."

# --- Passo 4: garantir .claude/commands/prospeccao-de-leads.md ---
COMMANDS_DIR="$SCRIPT_DIR/.claude/commands"
SOURCE_FILE="$SCRIPT_DIR/commands/prospeccao-de-leads.md"
TARGET_FILE="$COMMANDS_DIR/prospeccao-de-leads.md"

mkdir -p "$COMMANDS_DIR"

if [ ! -f "$TARGET_FILE" ]; then
    if [ -f "$SOURCE_FILE" ]; then
        cp "$SOURCE_FILE" "$TARGET_FILE"
        echo "[4/4] Comando /prospeccao-de-leads copiado para .claude/commands/."
    else
        echo "AVISO: não encontrei commands/prospeccao-de-leads.md para copiar."
        echo "O comando pode não aparecer no Claude Code. Verifique se o ZIP foi extraído corretamente."
    fi
else
    echo "[4/4] Comando /prospeccao-de-leads já está no lugar certo."
fi

# --- Sucesso ---
echo ""
echo "============================================"
echo " Instalação concluída!"
echo " Abra o Claude Code nesta pasta e"
echo " digite /prospeccao-de-leads para começar."
echo "============================================"
echo ""
