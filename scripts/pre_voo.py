"""
pre_voo.py — verifica o ambiente antes de cada rodada e gera o execucao_id.

Saída (stdout em JSON):
  { "ok": true, "execucao_id": "20260130_143022" }
  { "ok": false, "erros": ["...", "..."] }
"""

import sys
import os
import json
import datetime
import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
LEADS_PATH = os.path.join(BASE_DIR, "leads.csv")
COLETAS_DIR = os.path.join(BASE_DIR, "coletas")
CHECKPOINTS_DIR = os.path.join(BASE_DIR, "checkpoints")


def checar_config(erros):
    if not os.path.isfile(CONFIG_PATH):
        erros.append(f"config.yaml não encontrado em {CONFIG_PATH}")
        return None

    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        erros.append(f"config.yaml com erro de sintaxe: {e}")
        return None

    campos_obrigatorios = [
        "faixa_posicao", "trafego_min", "tamanho_lote",
        "max_keywords_portal", "teto_por_concorrente", "janela_teto_dias",
        "max_chamadas_mcp", "gmn_limiares", "ganho_rapido",
        "remetente", "ancoras", "telefone", "ordem_canal_preferencial",
    ]
    for campo in campos_obrigatorios:
        if campo not in cfg:
            erros.append(f"config.yaml está faltando o campo: {campo}")

    avisos = []
    remetente = cfg.get("remetente", {})
    if not remetente.get("nome") or not remetente.get("agencia"):
        avisos.append(
            "AVISO: remetente.nome e/ou remetente.agencia estão vazios no config.yaml. "
            "As mensagens de WhatsApp ficarão com espaço em branco."
        )

    ancoras = cfg.get("ancoras", {})
    if not any(ancoras.get(k) for k in ("SEO", "GEO", "GMN")):
        avisos.append(
            "AVISO: ancoras estão vazias no config.yaml. "
            "Preencha com os serviços reais da agência antes do primeiro uso."
        )

    return cfg, avisos


def checar_pastas(erros):
    for pasta in [COLETAS_DIR, CHECKPOINTS_DIR]:
        if not os.path.isdir(pasta):
            erros.append(f"Pasta obrigatória não existe: {pasta}")


def checar_leads_csv(erros):
    if not os.path.isfile(LEADS_PATH):
        # Primeira rodada: arquivo ainda não existe. Não é erro.
        return

    try:
        with open(LEADS_PATH, encoding="utf-8") as f:
            f.read(1)
    except Exception as e:
        erros.append(f"leads.csv existe mas não pode ser lido: {e}")


def checar_python(erros):
    major, minor = sys.version_info.major, sys.version_info.minor
    if major < 3 or (major == 3 and minor < 11):
        erros.append(
            f"Python 3.11 ou mais novo é obrigatório. "
            f"Versão atual: {major}.{minor}"
        )


def checar_dependencias(erros):
    pacotes = ["yaml", "csv"]
    for pacote in pacotes:
        try:
            __import__(pacote)
        except ImportError:
            erros.append(f"Pacote Python necessário não encontrado: {pacote}")


def gerar_execucao_id():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def main():
    erros = []
    avisos = []

    checar_python(erros)
    checar_dependencias(erros)
    checar_pastas(erros)
    checar_leads_csv(erros)

    resultado_config = checar_config(erros)
    if resultado_config and len(resultado_config) == 2:
        _, avisos_config = resultado_config
        avisos.extend(avisos_config)

    if erros:
        saida = {"ok": False, "erros": erros}
        if avisos:
            saida["avisos"] = avisos
        print(json.dumps(saida, ensure_ascii=False, indent=2))
        sys.exit(1)

    execucao_id = gerar_execucao_id()
    saida = {"ok": True, "execucao_id": execucao_id}
    if avisos:
        saida["avisos"] = avisos

    print(json.dumps(saida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
