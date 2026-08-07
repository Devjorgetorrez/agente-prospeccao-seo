"""
portoes.py — aplica os portões de qualificação em ordem.

Uso:
  python scripts/portoes.py <numero_portao> <execucao_id>

Mapa de portões (implementados à medida que as fases avançam):

  0  — Keyword vale a pena: média de tráfego dos top3 orgânicos >= trafego_min_media.
        Lê coletas/qualificacao_<execucao_id>.json.
        O top3 chega pré-filtrado pela skill: sem sufixos públicos (.gov.br etc.),
        sem domínios da lista_exclusao.yaml, sem portais (keywords_organicas >
        max_keywords_portal). Cada entrada do top3 inclui o campo keywords_organicas.
        Saída: { "portao": 0, "passou": true, "media_trafego_top3": 2100.0,
                 "limite": 200, "n_organicos_com_dado": 3, "top3": [...], "motivo": "..." }

  1  — Posição na faixa (só candidatos com origem não em {"pago", "pago_maps"}):
        Candidato deve estar entre faixa_posicao.min e faixa_posicao.max.
        Candidatos com origem = "pago" ou "pago_maps" pulam este portão.

  1B — Pago SERP já dominante (só candidatos com origem = "pago"):
        Se o mesmo domínio também aparece organicamente em posição < faixa_posicao.min,
        a empresa já domina os dois lados — não é prospect. Marco como "ja_posicionado".

  1C — Pago Maps já dominante (só candidatos com origem = "pago_maps"):
        Se o mesmo negócio também aparece no Maps organicamente em posição < posicao_min_gmn
        (posições 1–5), já domina os dois lados — não é prospect. Marco como "ja_posicionado".

  2  — Não é diretório conhecido: domínio não está em lista_exclusao.yaml.

  3  — É do setor: nenhum dos três sinais de filtro de setor disparou.
        Candidatos com origem = "pago" (SERP) passam apenas pelo sinal 3 (ausência no Maps).
        Sinais 1 (portal) e 2 (agregador) não se aplicam a eles.
        Candidatos com origem = "pago_maps" pulam portão 3 inteiro — já são Maps por definição.

  4  — Tem algum contato: telefone, e-mail ou Instagram, ao menos um.

  5  — Número de WhatsApp válido: se canal preferido é WhatsApp, número deve ser celular.
        Não reprova — só troca o canal para Instagram ou e-mail.

  6  — Não estourou o teto: no máximo teto_por_concorrente abordagens
        citando o mesmo concorrente na janela_teto_dias mais recente.

Portões 1 a 6 são implementados na Fase 9.
"""

import sys
import os
import json
import yaml
import csv
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
COLETAS_DIR = os.path.join(BASE_DIR, "coletas")
LEADS_PATH = os.path.join(BASE_DIR, "leads.csv")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_digs(s):
    return "".join(c for c in (s or "") if c.isdigit())


def _eh_celular(tel, cfg_tel):
    """True se o número bate com o padrão de celular brasileiro (13 dígitos, quinto = '9')."""
    d = _strip_digs(tel)
    prefixo = str(cfg_tel.get("prefixo_pais", "55"))
    if not d.startswith(prefixo):
        d = prefixo + d
    total = int(cfg_tel.get("digitos_totais", 13))
    quinto = str(cfg_tel.get("quinto_digito_deve_ser", "9"))
    return len(d) == total and len(d) > 4 and d[4] == quinto


def _dom_email(email):
    if email and "@" in email:
        return email.split("@", 1)[-1].lower().strip()
    return None


def _confianca(canal, ct, dominio_site, wa_site, cfg_tel):
    """
    Retorna 'alta', 'media' ou 'baixa' com base na ORIGEM DO CANAL ESCOLHIDO.

    canal = 'whatsapp':
      - fonte_telefone == 'wa_me_html'             → Alta (número direto na URL)
      - fonte_telefone == 'wa_me_message_html'     → Média (link curto confirmado; número do texto)
      - fonte_telefone == 'texto_pagina_contato'
        + número é celular válido                 → Média
      - confirmado só via Maps, rodapé ou outra   → Baixa

    canal = 'instagram':
      - fonte_instagram == 'texto_pagina_contato' → Média
      - qualquer outra origem                     → Baixa

    canal = 'email':
      - domínio do e-mail == domínio do site      → Alta
      - domínio diferente                         → Baixa

    canal = None:
      - sem canal digital                         → Baixa
    """
    if canal == "whatsapp":
        fonte_tel = ct.get("fonte_telefone")
        if fonte_tel == "wa_me_html":
            return "alta"
        if fonte_tel == "wa_me_message_html":
            return "media"  # link curto wa.me/message/ confirmado; número extraído do texto
        if fonte_tel == "texto_pagina_contato":
            tel = ct.get("telefone")
            if tel and _eh_celular(tel, cfg_tel):
                return "media"
        return "baixa"  # Maps-only, rodapé, outra, site_inacessivel, null

    if canal == "instagram":
        if ct.get("fonte_instagram") == "texto_pagina_contato":
            return "media"
        return "baixa"

    if canal == "email":
        email = ct.get("email")
        dom_e = _dom_email(email) if email else ""
        dom_s = (dominio_site or "").lower().lstrip("www.")
        if dom_e and dom_s and dom_e == dom_s:
            return "alta"
        return "baixa"

    return "baixa"  # canal is None


def _carregar_json_lotes(prefixo, execucao_id, chave_lista):
    """Agrega todas as entradas de todos os lotes de um tipo de arquivo."""
    entradas = []
    for fn in sorted(os.listdir(COLETAS_DIR)):
        if fn.startswith(f"{prefixo}_{execucao_id}_lote_") and fn.endswith(".json"):
            with open(os.path.join(COLETAS_DIR, fn), encoding="utf-8") as f:
                entradas.extend(json.load(f).get(chave_lista, []))
    return entradas


def carregar_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def portao_0(execucao_id):
    """Portão de valor da keyword: pelo menos um dos top3 tem trafego >= trafego_min.
    Regra decidida explicitamente pelo operador — simples, sem média."""
    arquivo = os.path.join(COLETAS_DIR, f"qualificacao_{execucao_id}.json")

    if not os.path.isfile(arquivo):
        saida = {
            "portao": 0,
            "passou": False,
            "erro": f"Arquivo não encontrado: {arquivo}",
        }
        print(json.dumps(saida, ensure_ascii=False, indent=2))
        sys.exit(1)

    try:
        with open(arquivo, encoding="utf-8") as f:
            dados = json.load(f)
    except Exception as e:
        saida = {
            "portao": 0,
            "passou": False,
            "erro": f"Erro ao ler o arquivo de qualificação: {e}",
        }
        print(json.dumps(saida, ensure_ascii=False, indent=2))
        sys.exit(1)

    cfg = carregar_config()
    limite = cfg.get("trafego_min", cfg.get("trafego_min_media", 200))  # suporta chave antiga

    top3 = dados.get("top3_organicos", [])

    if not top3:
        saida = {
            "portao": 0,
            "passou": False,
            "max_trafego_top3": 0,
            "limite": limite,
            "n_organicos_com_dado": 0,
            "top3": [],
            "motivo": (
                "keyword sem valor: nenhum resultado orgânico encontrado na "
                "primeira página, ou nenhum tráfego coletado"
            ),
        }
        print(json.dumps(saida, ensure_ascii=False, indent=2))
        return

    # Extrair tráfegos — inclui zeros (dado real) mas exclui None (ausência de dado)
    trafecos = []
    for item in top3:
        t = item.get("trafego_mensal")
        if isinstance(t, (int, float)):
            trafecos.append(t)

    if not trafecos:
        max_trafego = 0.0
        n_com_dado = 0
    else:
        max_trafego = max(trafecos)
        n_com_dado = len(trafecos)

    # Regra (decisão do operador): basta que PELO MENOS UM dos top3 atinja o limite.
    passou = max_trafego >= limite

    if passou:
        motivo = (
            f"keyword com valor: maior tráfego entre os {n_com_dado} orgânico(s) "
            f"coletado(s) ({max_trafego:.0f}) atinge o mínimo de {limite}"
        )
    else:
        motivo = (
            f"keyword sem valor: nenhum dos {n_com_dado} orgânico(s) coletado(s) "
            f"atingiu o mínimo de {limite} (maior tráfego encontrado: {max_trafego:.0f})"
        )

    saida = {
        "portao": 0,
        "passou": passou,
        "max_trafego_top3": round(max_trafego, 2),
        "limite": limite,
        "n_organicos_com_dado": n_com_dado,
        "top3": top3,
        "motivo": motivo,
    }
    print(json.dumps(saida, ensure_ascii=False, indent=2))


def portoes_completos(execucao_id):
    """
    Aplica portões 1–6 a todos os candidatos com status_tecnico == 'ok'.
    Atualiza candidatos_<execucao_id>.json em disco e imprime resumo.

    Portão 1   — posição orgânica na faixa [min, max]  (pula pago/pago_maps)
    Portão 1B  — pago SERP também orgânico < faixa.min → ja_posicionado
    Portão 1C  — pago Maps também orgânico no Maps < posicao_min_gmn → ja_posicionado
    Portão 2   — auditoria: ninguém com status != ok deve chegar aqui
    Portão 3   — confirma sinal3_resultado vindo da Fase 6
    Portão 4   — tem ao menos um contato (telefone / e-mail / instagram)
    Portão 5   — canal_preferencial: WhatsApp exige confirmação + celular válido
    Portão 6   — teto de repetição do concorrente na janela configurada
    """
    cfg = carregar_config()
    faixa = cfg["faixa_posicao"]
    posicao_min_gmn = int(cfg.get("posicao_min_gmn", 4))
    cfg_tel = cfg["telefone"]
    teto_conc = int(cfg.get("teto_por_concorrente", 6))
    janela_dias = int(cfg.get("janela_teto_dias", 7))
    ordem_canal = cfg.get("ordem_canal_preferencial", ["whatsapp", "instagram", "email"])

    # ── Candidatos ────────────────────────────────────────────────────────────
    cand_path = os.path.join(COLETAS_DIR, f"candidatos_{execucao_id}.json")
    if not os.path.isfile(cand_path):
        print(json.dumps({"erro": f"candidatos_{execucao_id}.json não encontrado"}, ensure_ascii=False))
        sys.exit(1)
    with open(cand_path, encoding="utf-8") as f:
        dados_cand = json.load(f)
    candidatos = dados_cand.get("candidatos", [])

    # ── Concorrente de referência (portão 6) ──────────────────────────────────
    concorrente_dom = None
    qual_path = os.path.join(COLETAS_DIR, f"qualificacao_{execucao_id}.json")
    if os.path.isfile(qual_path):
        with open(qual_path, encoding="utf-8") as f:
            q = json.load(f)
        top3 = q.get("top3_organicos", [])
        if top3:
            concorrente_dom = max(top3, key=lambda t: t.get("trafego_mensal") or 0).get("dominio")

    # ── Lookup: tem_whatsapp por domínio de site (Maps JSON) ──────────────────
    # Cobre candidatos gmn cujo perfil não passa por coletar-perfis
    maps_wa = {}
    maps_path = os.path.join(COLETAS_DIR, f"maps_{execucao_id}.json")
    if os.path.isfile(maps_path):
        with open(maps_path, encoding="utf-8") as f:
            maps_json = json.load(f)
        for card in maps_json.get("cards", []):
            site = card.get("site") or card.get("dominio") or ""
            if site:
                wa = bool(card.get("tem_whatsapp") or card.get("tem_whatsapp_botao"))
                maps_wa[site.lower()] = wa

    # ── Lookup: perfis por dominio_candidato ──────────────────────────────────
    perfis_idx = {}
    for card in _carregar_json_lotes("perfis", execucao_id, "cards"):
        dc = card.get("dominio_candidato", "").lower()
        if dc:
            perfis_idx[dc] = card

    # ── Lookup: contatos por domínio ──────────────────────────────────────────
    contatos_idx = {}
    for entry in _carregar_json_lotes("contatos", execucao_id, "contatos"):
        dom = (entry.get("dominio") or "").lower()
        if dom:
            contatos_idx[dom] = entry

    # ── Contagem de abordagens recentes por concorrente (portão 6) ────────────
    abordagens = {}
    hoje = date.today()
    corte = hoje - timedelta(days=janela_dias)
    if os.path.isfile(LEADS_PATH):
        with open(LEADS_PATH, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                # Exclui a própria rodada: linhas com a mesma execucao_id serão
                # substituídas pelo gravar_csv --update, então não devem contar
                # no teto — caso contrário, re-rodar portões numa rodada gravada
                # estoura o teto erroneamente.
                if row.get("execucao_id") == execucao_id:
                    continue
                if row.get("status_tecnico") not in ("ok", "revisar"):
                    continue
                try:
                    d = date.fromisoformat(row.get("data_captura", "")[:10])
                except Exception:
                    continue
                if d >= corte:
                    c_dom = row.get("conc_dominio", "")
                    abordagens[c_dom] = abordagens.get(c_dom, 0) + 1

    # ── Reset de re-run: limpa campos gravados por run anterior ──────────────
    # Qualquer status que portoes_completos possa ter atribuído é revertido para "ok"
    # para que os portões sejam reprocessados do zero. Statuses de fases anteriores
    # (diretorio, nao_e_do_setor com sinal3_resultado="falhou") são preservados.
    STATUSES_PORTOES = {"ok", "revisar", "fora_da_faixa", "ja_posicionado",
                        "sem_contato", "teto_concorrente"}
    for c in candidatos:
        if c.get("status_tecnico") in STATUSES_PORTOES:
            c["status_tecnico"] = "ok"
            c["motivo"] = None
            c.pop("canal_preferencial", None)
            c.pop("confianca_contato", None)

    # ── Loop principal ────────────────────────────────────────────────────────
    resultados = []
    nao_ok_encontrados = []

    for c in candidatos:
        dom = (c.get("dominio") or "").lower()
        status = c.get("status_tecnico", "")
        origem = c.get("origem", "")

        # Portão 2 — auditoria: apenas "ok" entra nos portões
        if status != "ok":
            nao_ok_encontrados.append(dom)
            continue

        ct = contatos_idx.get(dom, {})
        pf = perfis_idx.get(dom, {})

        # Fontes de telefone
        tel_site = ct.get("telefone")       # do site (coletar-contatos)
        tel_maps_card = c.get("telefone")   # do card Maps (candidatos.json, gmn/ambos)
        tel_maps_perfil = pf.get("telefone") if pf else None  # do perfil Maps (search)
        tel_maps = tel_maps_card or tel_maps_perfil  # melhor disponível fora do site

        # WhatsApp confirmado?
        # wa_site: link wa.me direto (número na URL) ou link curto wa.me/message/ (confirmado via redirect)
        # wa_texto: celular encontrado em texto da página — per CLAUDE.md, também qualifica (média)
        wa_fonte = ct.get("fonte_telefone")
        wa_site = wa_fonte in ("wa_me_html", "wa_me_message_html")
        wa_texto = wa_fonte == "texto_pagina_contato"
        wa_perfis = bool(pf.get("tem_whatsapp_botao")) if pf else False
        wa_maps_card = bool(maps_wa.get(dom))
        wa_confirmado = wa_site or wa_texto or wa_perfis or wa_maps_card

        # ── Portão 1: posição orgânica na faixa ──────────────────────────────
        if origem not in ("pago", "pago_maps"):
            pos_org = c.get("posicao_organica")
            if pos_org is not None:
                if not (faixa["min"] <= pos_org <= faixa["max"]):
                    c["status_tecnico"] = "fora_da_faixa"
                    c["motivo"] = (
                        f"posição orgânica {pos_org} fora da faixa "
                        f"[{faixa['min']}, {faixa['max']}]"
                    )
                    resultados.append({"dominio": dom, "status": c["status_tecnico"], "motivo": c["motivo"]})
                    continue

        # ── Portão 1B: pago SERP também orgânico nos primeiros ───────────────
        if origem == "pago":
            pos_org = c.get("posicao_organica")
            if pos_org is not None and pos_org < faixa["min"]:
                c["status_tecnico"] = "ja_posicionado"
                c["motivo"] = (
                    f"pago SERP e também orgânico em posição {pos_org} "
                    f"< {faixa['min']} — já domina os dois lados"
                )
                resultados.append({"dominio": dom, "status": c["status_tecnico"], "motivo": c["motivo"]})
                continue

        # ── Portão 1C: pago Maps também orgânico no Maps ──────────────────────
        if origem == "pago_maps":
            pos_maps = c.get("posicao_maps")
            if pos_maps is not None and pos_maps < posicao_min_gmn:
                c["status_tecnico"] = "ja_posicionado"
                c["motivo"] = (
                    f"pago Maps e também orgânico no Maps em posição {pos_maps} "
                    f"< {posicao_min_gmn} — já domina os dois lados"
                )
                resultados.append({"dominio": dom, "status": c["status_tecnico"], "motivo": c["motivo"]})
                continue

        # ── Portão 3: confirma sinal3_resultado da Fase 6 ─────────────────────
        if c.get("sinal3_resultado") == "falhou":
            c["status_tecnico"] = "nao_e_do_setor"
            c["motivo"] = "sinal3 (Fase 6): sem perfil no Maps com endereço na cidade"
            resultados.append({"dominio": dom, "status": c["status_tecnico"], "motivo": c["motivo"]})
            continue

        # ── Portão 4: tem ao menos um contato ────────────────────────────────
        email = ct.get("email")
        instagram = ct.get("instagram")
        tem_contato = bool(tel_site or tel_maps or email or instagram)
        if not tem_contato:
            c["status_tecnico"] = "sem_contato"
            c["motivo"] = "nenhum telefone, e-mail ou Instagram encontrado"
            resultados.append({"dominio": dom, "status": c["status_tecnico"], "motivo": c["motivo"]})
            continue

        # ── Portão 5: canal preferencial ──────────────────────────────────────
        # Percorre a ordem do config.yaml; WhatsApp requer confirmação + celular válido.
        # canal_preferencial só pode ser whatsapp, instagram ou email — nunca telefone.
        canal = None
        for ch in ordem_canal:
            if ch == "whatsapp":
                if wa_confirmado:
                    # Preferir telefone do site quando WhatsApp veio de fonte do site
                    num_wa = tel_site if (wa_site or wa_texto) else tel_maps
                    if num_wa and _eh_celular(num_wa, cfg_tel):
                        canal = "whatsapp"
                        break
            elif ch == "instagram":
                if instagram:
                    canal = "instagram"
                    break
            elif ch == "email":
                if email:
                    canal = "email"
                    break

        # Sem canal digital: registra e encerra (não vai a portão 6 — sem envio)
        if canal is None:
            c["status_tecnico"] = "revisar"
            c["motivo"] = "sem canal digital confirmado — apenas telefone"
            c["canal_preferencial"] = None
            c["confianca_contato"] = "baixa"
            resultados.append({
                "dominio": dom,
                "status": "revisar",
                "canal": None,
                "confianca": "baixa",
                "motivo": c["motivo"],
            })
            continue

        # ── Portão 6: teto do concorrente ────────────────────────────────────
        if concorrente_dom:
            count = abordagens.get(concorrente_dom, 0)
            if count >= teto_conc:
                c["status_tecnico"] = "teto_concorrente"
                c["motivo"] = (
                    f"concorrente '{concorrente_dom}' citado {count}× "
                    f"nos últimos {janela_dias} dias (teto: {teto_conc})"
                )
                resultados.append({"dominio": dom, "status": c["status_tecnico"], "motivo": c["motivo"]})
                continue

        # ── Todos os portões passaram ─────────────────────────────────────────
        conf = _confianca(canal, ct, dom, wa_site, cfg_tel)
        c["canal_preferencial"] = canal
        c["confianca_contato"] = conf

        if conf == "baixa":
            c["status_tecnico"] = "revisar"
            c["motivo"] = "confiança baixa — revisar antes de abordar"
        else:
            c["status_tecnico"] = "ok"
            c["motivo"] = None

        resultados.append({
            "dominio": dom,
            "status": c["status_tecnico"],
            "canal": canal,
            "confianca": conf,
        })

    # ── Salva candidatos.json atualizado ──────────────────────────────────────
    with open(cand_path, "w", encoding="utf-8") as f:
        json.dump(dados_cand, f, ensure_ascii=False, indent=2)

    # ── Resumo ────────────────────────────────────────────────────────────────
    ok_count = sum(1 for r in resultados if r.get("status") == "ok")
    revisar_count = sum(1 for r in resultados if r.get("status") == "revisar")
    reprovados = [r for r in resultados if r.get("status") not in ("ok", "revisar")]

    saida = {
        "portoes": "1 a 6",
        "execucao_id": execucao_id,
        "concorrente_referencia": concorrente_dom,
        "total_ok": ok_count,
        "total_revisar": revisar_count,
        "total_reprovados": len(reprovados),
        "auditoria_nao_ok_pulados": len(nao_ok_encontrados),
        "resultados": resultados,
    }
    print(json.dumps(saida, ensure_ascii=False, indent=2))


PORTOES = {
    0: portao_0,
}


def main():
    if len(sys.argv) != 3:
        print(
            json.dumps(
                {
                    "erro": (
                        "Uso: python scripts/portoes.py <numero_portao|completos> <execucao_id>"
                    )
                },
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    arg = sys.argv[1]
    execucao_id = sys.argv[2]

    if arg == "completos":
        portoes_completos(execucao_id)
        return

    try:
        numero = int(arg)
    except ValueError:
        print(
            json.dumps(
                {"erro": f"Argumento inválido: '{arg}'. Use um número de portão ou 'completos'."},
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    if numero not in PORTOES:
        print(
            json.dumps(
                {"erro": f"Portão {numero} ainda não implementado"},
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    PORTOES[numero](execucao_id)


if __name__ == "__main__":
    main()
