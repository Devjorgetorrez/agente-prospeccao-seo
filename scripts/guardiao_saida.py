"""
guardiao_saida.py - checagem final antes de gravar o leads.csv.

Uso:
  python scripts/guardiao_saida.py <execucao_id>

Retorna 0 se todas as checagens passaram; 1 se qualquer uma falhou.
Falha -> relatorio com a regra e as linhas afetadas; nada e gravado.
"""

import sys
import io
import os
import json
import re
import yaml

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
COLETAS_DIR = os.path.join(BASE_DIR, "coletas")


def _strip_digs(s):
    return "".join(c for c in (s or "") if c.isdigit())


def _carregar_lotes(execucao_id, prefixo, chave):
    """Carrega todos os lotes de contatos ou perfis, indexados por domínio."""
    idx = {}
    for fn in sorted(os.listdir(COLETAS_DIR)):
        if fn.startswith(f"{prefixo}_{execucao_id}_lote_") and fn.endswith(".json"):
            with open(os.path.join(COLETAS_DIR, fn), encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get(chave, []):
                dom = (item.get("dominio") or item.get("dominio_candidato") or "").lower()
                if dom:
                    idx[dom] = item
    return idx


def _numero_wa_esperado(cand, contatos_idx, perfis_idx, prefixo):
    """
    Retorna o número formatado para wa.me (com prefixo de pais),
    espelhando a prioridade de mensagem.py/_resolver_telefone_wa:
      1. fonte_telefone == 'wa_me_html'          → ct.telefone (alta)
      2. fonte_telefone == 'wa_me_message_html'   → ct.telefone (média)
      3. tem_whatsapp_botao no perfil Maps        → pf.telefone (média)
      4. fonte_telefone == 'texto_pagina_contato' → ct.telefone (média)
      5. fallback                                 → cand.telefone (pode ser fixo)
    """
    dom = (cand.get("dominio") or "").lower()
    ct = contatos_idx.get(dom, {})
    pf = perfis_idx.get(dom, {})
    fonte = ct.get("fonte_telefone")

    if fonte in ("wa_me_html", "wa_me_message_html"):
        num = _strip_digs(ct.get("telefone") or "")
    elif pf.get("tem_whatsapp_botao"):
        num = _strip_digs(pf.get("telefone") or "")
    elif fonte == "texto_pagina_contato":
        num = _strip_digs(ct.get("telefone") or "")
    else:
        num = _strip_digs(cand.get("telefone") or "")

    if num and not num.startswith(prefixo):
        num = prefixo + num
    return num


def guardiao_saida(execucao_id):
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    prefixo = str(cfg.get("telefone", {}).get("prefixo_pais", "55"))

    cand_path = os.path.join(COLETAS_DIR, f"candidatos_{execucao_id}.json")
    with open(cand_path, encoding="utf-8") as f:
        cand_data = json.load(f)
    candidatos = cand_data.get("candidatos", [])

    qual_path = os.path.join(COLETAS_DIR, f"qualificacao_{execucao_id}.json")
    with open(qual_path, encoding="utf-8") as f:
        qual_data = json.load(f)
    top3 = qual_data.get("top3_organicos") or []
    _trafecos = [t.get("trafego_mensal") for t in top3
                 if isinstance(t.get("trafego_mensal"), (int, float))]
    trafego_conc = int(max(_trafecos)) if _trafecos else 0

    contatos_idx = _carregar_lotes(execucao_id, "contatos", "contatos")
    perfis_idx = _carregar_lotes(execucao_id, "perfis", "cards")

    falhas = {}
    total = len(candidatos)

    def falha(check, msg):
        falhas.setdefault(check, []).append(msg)

    # ── Check 1: Reconciliacao ────────────────────────────────────────────────
    # Verifica que nenhum candidato saiu do pipeline sem status definido.
    if total == 0:
        falha("1_reconciliacao", "lista de candidatos esta vazia")

    for c in candidatos:
        if not c.get("status_tecnico"):
            dom = c.get("dominio", "?")
            falha("1_reconciliacao",
                  f"{dom}: status_tecnico ausente — candidato nao passou pelo pipeline completo")

    # ── Check 2: Coerencia de status ─────────────────────────────────────────
    for c in candidatos:
        dom = (c.get("dominio") or "?").lower()
        st = c.get("status_tecnico", "")
        ct = contatos_idx.get(dom, {})
        pf = perfis_idx.get(dom, {})

        tel = (c.get("telefone") or ct.get("telefone") or
               (pf.get("telefone") if pf else None))
        email = ct.get("email")
        instagram = ct.get("instagram")
        tem_contato = bool(tel or email or instagram)

        if st in ("ok", "revisar") and not tem_contato:
            falha("2_coerencia_status",
                  f"{dom}: status={st!r} mas nenhum contato encontrado "
                  f"(tel={bool(tel)}, email={bool(email)}, ig={bool(instagram)})")
        if st == "sem_contato" and tem_contato:
            falha("2_coerencia_status",
                  f"{dom}: status='sem_contato' mas contato presente "
                  f"(tel={bool(tel)}, email={bool(email)}, ig={bool(instagram)})")

    # ── Check 3: Unicidade ────────────────────────────────────────────────────
    vistos_dom = {}
    vistos_tel = {}
    vistos_email = {}

    for c in candidatos:
        dom = (c.get("dominio") or "").lower()
        ct = contatos_idx.get(dom, {})
        tel = _strip_digs(c.get("telefone") or "")
        email = (ct.get("email") or "").lower().strip()

        if dom:
            if dom in vistos_dom:
                falha("3_unicidade", f"dominio duplicado: {dom}")
            else:
                vistos_dom[dom] = True

        if tel:
            if tel in vistos_tel:
                falha("3_unicidade",
                      f"telefone duplicado: {tel} ({dom} e {vistos_tel[tel]})")
            else:
                vistos_tel[tel] = dom

        if email:
            if email in vistos_email:
                falha("3_unicidade",
                      f"e-mail duplicado: {email} ({dom} e {vistos_email[email]})")
            else:
                vistos_email[email] = dom

    # ── Check 4: Slots ────────────────────────────────────────────────────────
    for c in candidatos:
        texto = c.get("texto_mensagem")
        if texto and ("{" in texto or "}" in texto):
            dom = c.get("dominio", "?")
            slots = re.findall(r"\{[^}]*\}", texto)
            falha("4_slots", f"{dom}: slot(s) nao preenchido(s): {slots}")

    # ── Check 5: Numeros na mensagem ─────────────────────────────────────────
    for c in candidatos:
        texto = c.get("texto_mensagem")
        if not texto:
            continue
        dom = c.get("dominio", "?")
        origem = c.get("origem", "search")

        # Trafego — deve bater com max(top3) do concorrente de referencia da rodada
        m_traf = re.search(r"(?:cerca de|recebem at[eé])\s+(\d+)\s+visitas", texto)
        if m_traf:
            traf_msg = int(m_traf.group(1))
            if traf_msg != trafego_conc:
                falha("5_numeros_mensagem",
                      f"{dom}: trafego na mensagem={traf_msg}, esperado={trafego_conc}")
        else:
            falha("5_numeros_mensagem",
                  f"{dom}: trafego nao encontrado na mensagem (esperado: {trafego_conc} visitas)")

        # Posicao — ramifica por origem (Fase 11)
        if origem == "pago":
            if "anuncio patrocinado" not in texto and "anúncio patrocinado" not in texto:
                falha("5_numeros_mensagem",
                      f"{dom}: origem='pago' mas 'anuncio patrocinado' nao encontrado na mensagem")
        else:
            m_pos = re.search(r"aparece na (\d+)", texto)
            if not m_pos:
                falha("5_numeros_mensagem",
                      f"{dom}: posicao nao encontrada na mensagem (origem={origem!r})")
            else:
                pos_msg = int(m_pos.group(1))
                if origem in ("search", "ambos"):
                    pos_esp = c.get("posicao_organica")
                    campo = "posicao_organica"
                elif origem in ("gmn", "pago_maps"):
                    pos_esp = c.get("posicao_maps")
                    campo = "posicao_maps"
                else:
                    pos_esp = None
                    campo = "?"

                if pos_esp is not None and pos_msg != pos_esp:
                    falha("5_numeros_mensagem",
                          f"{dom}: posicao na mensagem={pos_msg}, {campo}={pos_esp}")

    # ── Check 6: Diagnostico presente ────────────────────────────────────────
    for c in candidatos:
        if c.get("status_tecnico") not in ("ok", "revisar"):
            continue
        dom = c.get("dominio", "?")
        for campo in ("diag_seo", "diag_geo", "diag_gmn"):
            if not c.get(campo):
                falha("6_diagnostico_presente",
                      f"{dom}: campo '{campo}' vazio ou ausente")

    # ── Check 7: Link presente/ausente conforme canal ────────────────────────
    for c in candidatos:
        dom = c.get("dominio", "?")
        canal = c.get("canal_preferencial")
        link = c.get("link_whatsapp")

        if canal == "whatsapp":
            if not link:
                falha("7_link_canal",
                      f"{dom}: canal_preferencial='whatsapp' mas link_whatsapp e null/vazio")
        else:
            if link:
                falha("7_link_canal",
                      f"{dom}: canal_preferencial={canal!r} mas link_whatsapp esta "
                      f"preenchido — possivel sobra de teste anterior")

    # ── Check 8: Numero do link bate com a fonte ──────────────────────────────
    for c in candidatos:
        if c.get("canal_preferencial") != "whatsapp":
            continue
        dom = c.get("dominio", "?")
        link = c.get("link_whatsapp") or ""

        m = re.search(r"wa\.me/(\d+)", link)
        if not m:
            falha("8_numero_link",
                  f"{dom}: nao foi possivel extrair numero do link wa.me: {link[:60]}")
            continue

        num_link = m.group(1)
        num_esp = _numero_wa_esperado(c, contatos_idx, perfis_idx, prefixo)

        if not num_esp or num_esp == prefixo:
            falha("8_numero_link",
                  f"{dom}: nao foi possivel determinar o numero WA esperado para comparacao")
            continue

        if num_link != num_esp:
            falha("8_numero_link",
                  f"{dom}: numero no link={num_link}, numero esperado={num_esp}")

    # ── Resultado ─────────────────────────────────────────────────────────────
    CHECKS = [
        ("1_reconciliacao",        "1 — Reconciliacao"),
        ("2_coerencia_status",     "2 — Coerencia de status"),
        ("3_unicidade",            "3 — Unicidade"),
        ("4_slots",                "4 — Slots"),
        ("5_numeros_mensagem",     "5 — Numeros na mensagem"),
        ("6_diagnostico_presente", "6 — Diagnostico presente"),
        ("7_link_canal",           "7 — Link presente/ausente conforme canal"),
        ("8_numero_link",          "8 — Numero do link bate com a fonte"),
    ]

    passou = not falhas

    print()
    for key, label in CHECKS:
        erros = falhas.get(key, [])
        icone = "PASSOU  " if not erros else "REPROVOU"
        print(f"  {icone}  {label}")
        for e in erros:
            print(f"            -> {e}")

    print(f"\n{'=' * 70}")
    if passou:
        print(f"GUARDIAO SAIDA: PASSOU — {total} candidato(s) prontos para gravacao.")
        resultado = {"status": "ok", "execucao_id": execucao_id, "total": total}
    else:
        n_checks = sum(1 for k, _ in CHECKS if k in falhas)
        print(f"GUARDIAO SAIDA: REPROVADO — {n_checks} check(s) falharam. Nada sera gravado.")
        resultado = {
            "status": "reprovado",
            "execucao_id": execucao_id,
            "checks_reprovados": n_checks,
            "detalhes": falhas,
        }

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0 if passou else 1


def main():
    if len(sys.argv) < 2:
        print("Uso: python guardiao_saida.py <execucao_id>", file=sys.stderr)
        sys.exit(1)
    sys.exit(guardiao_saida(sys.argv[1]))


if __name__ == "__main__":
    main()
