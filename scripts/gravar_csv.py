"""
gravar_csv.py — grava candidatos da rodada no leads.csv.

Uso normal:
  python scripts/gravar_csv.py <execucao_id>

Modo update (recalcula rodada já gravada, preserva colunas do operador):
  python scripts/gravar_csv.py <execucao_id> --update

No modo update, linhas da execucao_id são substituídas com os dados
recalculados; status_venda, data_abordagem e observacao são preservados
do CSV existente.

Escreve num arquivo temporário e substitui leads.csv atomicamente só após
escrita completa. Tudo de uma vez ou nada — leads.csv nunca fica parcial.

Pré-condição: guardiao_saida.py deve ter passado antes desta chamada.
"""

import sys
import io
import os
import json
import csv
import yaml
from datetime import date

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
COLETAS_DIR = os.path.join(BASE_DIR, "coletas")
LEADS_CSV = os.path.join(BASE_DIR, "leads.csv")

COLUNAS = [
    # Identificação
    "id_lead", "data_captura", "execucao_id", "origem", "keyword", "cidade",
    "rodada_parcial",
    # Prova (concorrente de referência)
    "conc_dominio", "conc_posicao", "conc_trafego", "conc_autoridade",
    "fonte_trafego", "media_top3",
    # Empresa prospectada
    "empresa", "dominio", "posicao", "posicao_maps",
    "trafego", "autoridade", "keywords_organicas",
    # Contatos
    "telefone", "email", "instagram",
    "canal_preferencial", "confianca_contato",
    # SEO
    "diag_seo", "gap_posicao", "gap_autoridade",
    # GEO
    "diag_geo", "ai_overview_presente", "ai_overview_cita_conc",
    "ai_overview_cita_lead",
    # GMN
    "diag_gmn", "gmn_sinais", "gmn_avaliacoes", "gmn_nota",
    # Síntese
    "diagnostico_resumo", "ganho_rapido", "ancora",
    # Ação
    "link_whatsapp", "status_tecnico", "motivo",
    "status_venda", "data_abordagem", "observacao",
]


def _v(val):
    """Converte None → ''; bool → minúsculo; tudo mais → str."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


def _carregar_lotes(execucao_id, prefixo, chave):
    """Indexa lotes de contatos ou perfis por domínio."""
    idx = {}
    for fn in sorted(os.listdir(COLETAS_DIR)):
        if fn.startswith(f"{prefixo}_{execucao_id}_lote_") and fn.endswith(".json"):
            with open(os.path.join(COLETAS_DIR, fn), encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get(chave, []):
                dom = (
                    item.get("dominio")
                    or item.get("dominio_candidato")
                    or ""
                ).lower()
                if dom:
                    idx[dom] = item
    return idx


def _candidato_para_linha(cand, execucao_id, keyword, cidade, rodada_parcial,
                          conc, perfis_idx, contatos_idx, data_captura):
    """
    Converte um candidato (dict) para uma lista de valores na ordem de COLUNAS.
    """
    dom = (cand.get("dominio") or "").lower()
    ct = contatos_idx.get(dom, {})
    pf = perfis_idx.get(dom, {})

    # Empresa: prefere nome do Maps (perfis), mais limpo que título de SERP
    empresa = pf.get("nome") or cand.get("nome") or dom

    # Contatos: telefone do candidato (Maps card, Fase 4) ou perfis (profile Maps, coletar-perfis)
    # Ambas as fontes são Maps — perfis é fallback quando o card compacto não tinha o número
    telefone = cand.get("telefone") or pf.get("telefone")
    email = ct.get("email")
    # Instagram: site (coletar-contatos) sobrescreve Maps se encontrado
    instagram = ct.get("instagram") or cand.get("instagram")

    # gmn_sinais é lista no JSON → string separada por ";" no CSV
    sinais = cand.get("gmn_sinais") or []
    gmn_sinais_str = "; ".join(sinais) if sinais else ""

    # posicao = organica (search/ambos); em branco para gmn/pago/pago_maps
    origem = cand.get("origem", "")
    posicao = cand.get("posicao_organica") if origem in ("search", "ambos") else None
    posicao_maps = (
        cand.get("posicao_maps")
        if origem in ("gmn", "ambos", "pago_maps")
        else None
    )

    return [
        _v(cand.get("id_lead")),
        _v(data_captura),
        _v(execucao_id),
        _v(origem),
        _v(keyword),
        _v(cidade),
        _v(rodada_parcial),
        # conc_*
        _v(conc.get("dominio")),
        _v(conc.get("ordem_na_pagina")),
        _v(conc.get("trafego_mensal")),
        "",                              # conc_autoridade: não coletada no fluxo padrão
        _v(conc.get("fonte_trafego")),
        _v(conc.get("media_top3")),      # preenchido pelo chamador a partir de qual_data
        # empresa
        _v(empresa),
        _v(cand.get("dominio")),
        _v(posicao),
        _v(posicao_maps),
        "",                              # trafego: não coletado por candidato no fluxo padrão
        "",                              # autoridade: idem
        "",                              # keywords_organicas: idem
        # contatos
        _v(telefone),
        _v(email),
        _v(instagram),
        _v(cand.get("canal_preferencial")),
        _v(cand.get("confianca_contato")),
        # SEO
        _v(cand.get("diag_seo")),
        _v(cand.get("gap_posicao")),
        _v(cand.get("gap_autoridade")),
        # GEO
        _v(cand.get("diag_geo")),
        _v(cand.get("ai_overview_presente")),
        _v(cand.get("ai_overview_cita_conc")),
        _v(cand.get("ai_overview_cita_lead")),
        # GMN
        _v(cand.get("diag_gmn")),
        gmn_sinais_str,
        _v(cand.get("gmn_avaliacoes")),
        _v(cand.get("gmn_nota")),
        # Síntese
        _v(cand.get("diagnostico_resumo")),
        _v(cand.get("ganho_rapido")),
        _v(cand.get("ancora")),
        # Ação
        _v(cand.get("link_whatsapp")),
        _v(cand.get("status_tecnico")),
        _v(cand.get("motivo")),
        "",   # status_venda — só o operador escreve
        "",   # data_abordagem — só o operador escreve
        "",   # observacao — só o operador escreve
    ]


def gravar_csv(execucao_id, update=False):
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cand_path = os.path.join(COLETAS_DIR, f"candidatos_{execucao_id}.json")
    with open(cand_path, encoding="utf-8") as f:
        cand_data = json.load(f)

    qual_path = os.path.join(COLETAS_DIR, f"qualificacao_{execucao_id}.json")
    with open(qual_path, encoding="utf-8") as f:
        qual_data = json.load(f)

    top3 = qual_data.get("top3_organicos") or []
    if not top3:
        print("ERRO: qualificacao.json não tem top3_organicos — sem concorrente de referência.",
              file=sys.stderr)
        sys.exit(1)

    _trafecos = [t.get("trafego_mensal") for t in top3
                 if isinstance(t.get("trafego_mensal"), (int, float))]
    # Concorrente de referência = domínio de maior tráfego entre os três
    # (conc_dominio e conc_trafego sempre descrevem a mesma empresa)
    conc = max(top3, key=lambda t: t.get("trafego_mensal") or 0).copy()
    conc["media_top3"] = round(sum(_trafecos) / len(_trafecos), 1) if _trafecos else None

    keyword = cand_data.get("keyword", "")
    cidade = cand_data.get("cidade", "")
    rodada_parcial = cand_data.get("rodada_parcial", False)
    candidatos = cand_data.get("candidatos", [])
    data_captura = date.today().isoformat()

    perfis_idx = _carregar_lotes(execucao_id, "perfis", "cards")
    contatos_idx = _carregar_lotes(execucao_id, "contatos", "contatos")

    # ── Ler leads.csv existente (para append seguro ou update) ───────────────
    ids_existentes = set()
    linhas_existentes = []
    # Índice id_lead → colunas do operador (status_venda, data_abordagem, observacao)
    operador_idx = {}
    col_sv = col_da = col_obs = None  # índices das colunas do operador

    if os.path.exists(LEADS_CSV):
        with open(LEADS_CSV, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            cabecalho = next(reader, None)
            if cabecalho:
                try:
                    col_sv  = cabecalho.index("status_venda")
                    col_da  = cabecalho.index("data_abordagem")
                    col_obs = cabecalho.index("observacao")
                except ValueError:
                    pass
            for row in reader:
                if not row:
                    continue
                id_lead_row = row[0]
                exec_row = row[COLUNAS.index("execucao_id")] if len(row) > COLUNAS.index("execucao_id") else ""

                if update and exec_row == execucao_id:
                    # Em modo update: guardar colunas do operador e descartar a linha
                    operador_idx[id_lead_row] = {
                        "status_venda":    row[col_sv]  if col_sv  is not None and len(row) > col_sv  else "",
                        "data_abordagem":  row[col_da]  if col_da  is not None and len(row) > col_da  else "",
                        "observacao":      row[col_obs] if col_obs is not None and len(row) > col_obs else "",
                    }
                    continue  # não preserva — será regenerada

                linhas_existentes.append(row)
                ids_existentes.add(id_lead_row)

    if update:
        print(f"Modo update: {len(operador_idx)} linha(s) da execucao_id '{execucao_id}' serão substituídas.")

    # ── Gerar novas linhas ────────────────────────────────────────────────────
    novas_linhas = []
    pulados = 0

    for cand in candidatos:
        id_lead = cand.get("id_lead", "")
        if id_lead in ids_existentes:
            # Existe em outra rodada — nunca criar duplicata, nem em --update
            if not update:
                print(f"  AVISO: id_lead {id_lead} ({cand.get('dominio')}) já existe — pulando.")
            pulados += 1
            continue

        linha = _candidato_para_linha(
            cand, execucao_id, keyword, cidade, rodada_parcial,
            conc, perfis_idx, contatos_idx, data_captura
        )

        # Restaurar colunas do operador se existiam antes
        if update and id_lead in operador_idx:
            op = operador_idx[id_lead]
            linha[-3] = op["status_venda"]
            linha[-2] = op["data_abordagem"]
            linha[-1] = op["observacao"]

        novas_linhas.append(linha)

    if not novas_linhas:
        print(f"Nenhuma linha nova para gravar ({pulados} já existiam). Encerrando.")
        return

    # ── Escrever: temp+replace (normal) ou direto no arquivo (update/fallback) ──
    import uuid
    tmp_path = os.path.join(BASE_DIR, f"leads_tmp_{uuid.uuid4().hex[:8]}.csv")

    def _escrever(dest):
        with open(dest, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(COLUNAS)
            # Novas linhas primeiro — rodada mais recente aparece no topo da planilha
            for linha in novas_linhas:
                writer.writerow(linha)
            for linha in linhas_existentes:
                writer.writerow(linha)

    try:
        _escrever(tmp_path)
        try:
            os.replace(tmp_path, LEADS_CSV)
        except OSError:
            # Fallback 1: copia conteúdo do tmp para leads.csv
            import shutil
            try:
                shutil.copy2(tmp_path, LEADS_CSV)
                os.remove(tmp_path)
            except OSError:
                # Fallback 2: escreve diretamente no leads.csv (sem atomicidade)
                try:
                    os.remove(tmp_path)
                    _escrever(LEADS_CSV)
                except OSError:
                    # Fallback 3: leads.csv bloqueado — salva como arquivo alternativo
                    alt_path = LEADS_CSV.replace("leads.csv", "leads_atualizado.csv")
                    _escrever(alt_path)
                    print(
                        f"\nATENCAO: leads.csv esta bloqueado pelo OneDrive ou Excel.\n"
                        f"Dados gravados em: {alt_path}\n"
                        f"Quando o OneDrive terminar de sincronizar, feche o Excel se aberto\n"
                        f"e renomeie 'leads_atualizado.csv' para 'leads.csv' manualmente.",
                        file=sys.stderr
                    )
                    LEADS_CSV_USADO = alt_path
    except Exception as e:
        if os.path.exists(tmp_path):
            print(f"Arquivo temporário mantido em: {tmp_path}", file=sys.stderr)
        print(f"ERRO durante escrita: {e}", file=sys.stderr)
        sys.exit(1)

    total_novas = len(novas_linhas)
    total_existentes = len(linhas_existentes)
    total_csv = total_existentes + total_novas

    print(f"\nleads.csv gravado com sucesso.")
    print(f"  Linhas novas desta rodada : {total_novas}")
    print(f"  Linhas anteriores mantidas: {total_existentes}")
    print(f"  Total no CSV              : {total_csv}")
    if pulados:
        print(f"  Pulados (já existiam)     : {pulados}")

    # Contagem por status na rodada atual
    status_count = {}
    for c in candidatos:
        s = c.get("status_tecnico", "desconhecido")
        status_count[s] = status_count.get(s, 0) + 1
    print("\n  Status nesta rodada:")
    for s, n in sorted(status_count.items(), key=lambda x: -x[1]):
        print(f"    {s}: {n}")

    print(json.dumps({
        "status": "ok",
        "execucao_id": execucao_id,
        "linhas_novas": total_novas,
        "linhas_existentes": total_existentes,
        "total_csv": total_csv,
        "pulados": pulados,
    }, ensure_ascii=False))


def main():
    if len(sys.argv) < 2:
        print("Uso: python gravar_csv.py <execucao_id> [--update]", file=sys.stderr)
        sys.exit(1)
    update = "--update" in sys.argv[2:]
    gravar_csv(sys.argv[1], update=update)


if __name__ == "__main__":
    main()
