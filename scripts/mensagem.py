"""
mensagem.py — monta texto e link de WhatsApp para candidatos com
canal_preferencial == 'whatsapp'.

Uso:
  python scripts/mensagem.py <execucao_id>

Lê:
  coletas/candidatos_<execucao_id>.json
  coletas/qualificacao_<execucao_id>.json
  coletas/contatos_<execucao_id>_lote_*.json
  coletas/perfis_<execucao_id>_lote_*.json
  coletas/maps_<execucao_id>.json
  config.yaml

Escreve de volta ao candidatos_<execucao_id>.json, adicionando em cada
candidato com canal_preferencial == 'whatsapp':
  texto_mensagem, link_whatsapp

Candidatos com canal_preferencial != 'whatsapp' (incluindo null) recebem
texto_mensagem=null e link_whatsapp=null — o operador usa o contato direto.
"""

import sys
import os
import json
import yaml
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
COLETAS_DIR = os.path.join(BASE_DIR, "coletas")


# ── Helpers de telefone ───────────────────────────────────────────────────────

def _strip_digs(s):
    return "".join(c for c in (s or "") if c.isdigit())


def _formatar_wa(tel, cfg_tel):
    """Retorna o número em formato internacional sem '+': 5519912345678."""
    d = _strip_digs(tel)
    prefixo = str(cfg_tel.get("prefixo_pais", "55"))
    if not d.startswith(prefixo):
        d = prefixo + d
    return d


def _resolver_telefone_wa(cand, contatos_idx, perfis_idx, maps_idx):
    """
    Retorna o telefone que deve ir no link wa.me, seguindo a prioridade:
      1. fonte_telefone == 'wa_me_html' — número direto na URL wa.me/<numero> (alta)
      2. fonte_telefone == 'wa_me_message_html' — link curto confirmado via redirect,
         número extraído do texto da mesma página (média)
      3. tem_whatsapp_botao no perfil Maps → telefone do perfil (média)
      4. fonte_telefone == 'texto_pagina_contato' — celular encontrado em texto do site (média)
      5. tem_whatsapp no maps card → telefone do candidato (baixa)
      6. fallback — telefone do candidato (pode ser fixo)
    """
    dom = cand.get("dominio", "")
    ct = contatos_idx.get(dom, {})
    fonte = ct.get("fonte_telefone")

    # 1. Link direto wa.me/<numero> encontrado no site
    if fonte == "wa_me_html":
        return ct.get("telefone")

    # 2. Link curto wa.me/message/ confirmado via redirect; número do texto do site
    if fonte == "wa_me_message_html":
        return ct.get("telefone")

    # 3. Botão de WhatsApp no perfil do Maps
    perf = perfis_idx.get(dom, {})
    if perf.get("tem_whatsapp_botao"):
        return perf.get("telefone")

    # 4. Celular encontrado em texto da página do site (sem link wa.me direto)
    if fonte == "texto_pagina_contato":
        return ct.get("telefone")

    # 5. Maps card indica WhatsApp (sem botão de perfil mas com flag no card)
    card = maps_idx.get(dom, {})
    if card.get("tem_whatsapp") or card.get("tem_whatsapp_botao"):
        return cand.get("telefone")

    # 6. Fallback — pode ser fixo; portoes.py já validou que é celular para canal=whatsapp
    return cand.get("telefone")


# ── Nome da empresa ───────────────────────────────────────────────────────────

def _nome_empresa(cand, perfis_idx):
    """
    Prefere o nome do card do Maps (perfis), mais limpo que o título de SERP.
    Fallback para candidatos.nome se perfis não tiver entrada.
    """
    dom = cand.get("dominio", "")
    perf = perfis_idx.get(dom, {})
    return perf.get("nome") or cand.get("nome") or dom


# ── Segunda linha do template (ramifica por origem) ───────────────────────────

def _frase_posicao(cand, empresa, keyword, cidade):
    """Monta a frase 'Vi que a {empresa} aparece na Xª posição...'"""
    origem = cand.get("origem", "search")
    pos = cand.get("posicao_organica")
    pos_m = cand.get("posicao_maps")

    if origem in ("search", "ambos") and pos:
        return (
            f"Vi que a {empresa} aparece na {pos}ª posição quando "
            f"alguém busca \"{keyword}\" aqui em {cidade}."
        )
    if origem in ("gmn", "pago_maps") and pos_m:
        return (
            f"Vi que a {empresa} aparece na {pos_m}ª posição no Google Maps "
            f"quando alguém busca \"{keyword}\" aqui em {cidade}."
        )
    if origem == "pago":
        return (
            f"Vi que a {empresa} aparece como anúncio patrocinado "
            f"quando alguém busca \"{keyword}\" aqui em {cidade}."
        )
    # ambos sem posicao_organica mas com posicao_maps
    if pos_m:
        return (
            f"Vi que a {empresa} aparece na {pos_m}ª posição no Google Maps "
            f"quando alguém busca \"{keyword}\" aqui em {cidade}."
        )
    return (
        f"Vi que a {empresa} ainda não tem boa visibilidade "
        f"quando alguém busca \"{keyword}\" aqui em {cidade}."
    )


# ── Gancho ────────────────────────────────────────────────────────────────────

# Frases que completam "o perfil de vocês no Google Maps {frase}."
# Cada entrada é um predicado verbal — sem "está com" na frente.
_FRASES_SINAL = {
    "sem_site": "não tem site vinculado",
    "whatsapp_invisivel": "não tem WhatsApp visível",
    "poucas_avaliacoes": "tem poucas avaliações",
    "nota_baixa": "tem nota abaixo de 4.0",
    "sem_posts_recentes": "está sem publicações recentes",
    "sem_produtos": "não tem serviços cadastrados",
    "descricao_sem_keyword": "tem descrição sem o serviço mencionado",
    "fotos_antigas": "tem fotos desatualizadas",
    "nao_responde_avaliacoes": "tem avaliações sem resposta",
}


def _gancho(cand):
    """Gera a frase de abertura a partir do ganho_rapido e gmn_sinais."""
    ganho = cand.get("ganho_rapido", "GMN")
    sinais = cand.get("gmn_sinais") or []
    origem = cand.get("origem", "search")

    # Candidatos gmn/ambos/pago_maps já mencionaram "Google Maps" na linha de
    # posição — o gancho usa "no Maps" para não repetir o nome inteiro.
    maps_label = "no Maps" if origem in ("gmn", "ambos", "pago_maps") else "no Google Maps"

    if ganho == "GEO":
        return (
            "Vi que essa busca já tem um resumo de IA no Google — "
            "e vocês ainda não aparecem nele."
        )

    if ganho == "SEO":
        pos = cand.get("posicao_organica")
        pos_str = f", hoje na {pos}ª posição," if pos else ""
        return (
            f"Com um trabalho focado, vocês{pos_str} podem chegar "
            "à 1ª página dessa busca em alguns meses."
        )

    # GMN — a partir dos sinais disparados
    if not sinais:
        return (
            f"Vi também que o perfil de vocês {maps_label} tem "
            "espaço para melhorar a visibilidade online."
        )

    top = sinais[:2]
    partes = [_FRASES_SINAL.get(s, s) for s in top]

    if len(partes) == 1:
        return f"Notei também que o perfil de vocês {maps_label} {partes[0]}."
    return (
        f"Notei também que o perfil de vocês {maps_label} "
        f"{partes[0]} e {partes[1]}."
    )


# ── Montar texto e link ───────────────────────────────────────────────────────

def _montar_mensagem(cand, remetente, trafego_conc, keyword, cidade,
                     perfis_idx, contatos_idx, maps_idx, cfg):
    """
    Retorna (texto, link_wa) ou (None, None) se não for canal whatsapp.
    """
    if cand.get("canal_preferencial") != "whatsapp":
        return None, None

    empresa = _nome_empresa(cand, perfis_idx)
    nome_rem = remetente.get("nome", "").strip() or "[SEU NOME]"
    agencia = remetente.get("agencia", "").strip() or "[SUA AGÊNCIA]"

    frase_pos = _frase_posicao(cand, empresa, keyword, cidade)
    gancho = _gancho(cand)

    texto = (
        f"Olá! Sou {nome_rem}, da {agencia}.\n\n"
        f"{frase_pos}\n\n"
        f"Os primeiros colocados nessa busca recebem até "
        f"{trafego_conc} visitas por mês — e é gente procurando "
        f"contratar, não pesquisando.\n\n"
        f"{gancho}\n\n"
        f"Posso te mostrar o que os três primeiros fazem diferente?"
    )

    tel = _resolver_telefone_wa(cand, contatos_idx, perfis_idx, maps_idx)
    if not tel:
        return texto, None

    cfg_tel = cfg.get("telefone", {})
    tel_int = _formatar_wa(tel, cfg_tel)
    link = f"https://wa.me/{tel_int}?text={urllib.parse.quote(texto, safe='')}"

    return texto, link


# ── Principal ─────────────────────────────────────────────────────────────────

def mensagem(execucao_id):
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    remetente = cfg.get("remetente", {})
    remetente_vazio = (
        not (remetente.get("nome") or "").strip()
        or not (remetente.get("agencia") or "").strip()
    )
    if remetente_vazio:
        print(
            "AVISO: config.yaml tem 'remetente.nome' ou 'remetente.agencia' vazio. "
            "A mensagem vai usar [SEU NOME] e [SUA AGÊNCIA] como espaço reservado.",
            file=sys.stderr
        )

    cand_path = os.path.join(COLETAS_DIR, f"candidatos_{execucao_id}.json")
    with open(cand_path, encoding="utf-8") as f:
        cand_data = json.load(f)

    keyword = cand_data.get("keyword", "")
    cidade = cand_data.get("cidade", "")
    candidatos = cand_data.get("candidatos", [])

    qual_path = os.path.join(COLETAS_DIR, f"qualificacao_{execucao_id}.json")
    with open(qual_path, encoding="utf-8") as f:
        qual_data = json.load(f)

    top3 = qual_data.get("top3_organicos") or []
    _trafecos = [t.get("trafego_mensal") for t in top3
                 if isinstance(t.get("trafego_mensal"), (int, float))]
    trafego_conc = max(_trafecos) if _trafecos else 0

    # Carregar maps
    maps_idx = {}
    maps_path = os.path.join(COLETAS_DIR, f"maps_{execucao_id}.json")
    if os.path.exists(maps_path):
        with open(maps_path, encoding="utf-8") as f:
            maps_data = json.load(f)
        for card in maps_data.get("cards", []):
            dom = card.get("site") or ""
            if dom:
                maps_idx[dom] = card

    # Carregar perfis (chave = dominio_candidato)
    perfis_idx = {}
    for fn in sorted(os.listdir(COLETAS_DIR)):
        if fn.startswith(f"perfis_{execucao_id}_lote_") and fn.endswith(".json"):
            with open(os.path.join(COLETAS_DIR, fn), encoding="utf-8") as f:
                pdata = json.load(f)
            for card in pdata.get("cards", []):
                dom = card.get("dominio_candidato") or ""
                if dom:
                    perfis_idx[dom] = card

    # Carregar contatos (chave = dominio)
    contatos_idx = {}
    for fn in sorted(os.listdir(COLETAS_DIR)):
        if fn.startswith(f"contatos_{execucao_id}_lote_") and fn.endswith(".json"):
            with open(os.path.join(COLETAS_DIR, fn), encoding="utf-8") as f:
                cdata = json.load(f)
            for ct in cdata.get("contatos", []):
                dom = ct.get("dominio") or ""
                if dom:
                    contatos_idx[dom] = ct

    com_msg = []
    sem_msg = []
    ignorados = 0

    for cand in candidatos:
        st = cand.get("status_tecnico", "")
        if st not in ("ok", "revisar"):
            ignorados += 1
            cand["texto_mensagem"] = None
            cand["link_whatsapp"] = None
            continue

        texto, link = _montar_mensagem(
            cand, remetente, trafego_conc, keyword, cidade,
            perfis_idx, contatos_idx, maps_idx, cfg
        )
        cand["texto_mensagem"] = texto
        cand["link_whatsapp"] = link

        if link:
            com_msg.append(cand)
        else:
            sem_msg.append(cand)

    with open(cand_path, "w", encoding="utf-8") as f:
        json.dump(cand_data, f, ensure_ascii=False, indent=2)

    # Exibir mensagens geradas
    sep = "─" * 80
    for c in com_msg:
        canal = c.get("canal_preferencial", "")
        status = c.get("status_tecnico", "")
        dom = c.get("dominio", "")
        orig = c.get("origem", "")
        pos = c.get("posicao_organica") or c.get("posicao_maps") or "?"
        print(f"\n{sep}")
        print(f"[{orig.upper()} | pos {pos} | {status}] {dom}")
        print(sep)
        print(c.get("texto_mensagem", ""))
        print(f"\nLink: {(c.get('link_whatsapp') or '')[:80]}...")

    print(f"\n{'═'*80}")
    print(f"Mensagens geradas: {len(com_msg)}")
    if sem_msg:
        print(f"Sem mensagem (canal ≠ whatsapp ou sem telefone):")
        for c in sem_msg:
            print(f"  {c.get('dominio')} — canal={c.get('canal_preferencial')!r}, "
                  f"status={c.get('status_tecnico')}")
    print(f"Ignorados (status != ok/revisar): {ignorados}")

    print(json.dumps({
        "status": "ok",
        "execucao_id": execucao_id,
        "com_mensagem": len(com_msg),
        "sem_mensagem": len(sem_msg),
        "ignorados": ignorados
    }, ensure_ascii=False))


def main():
    if len(sys.argv) < 2:
        print("Uso: python mensagem.py <execucao_id>", file=sys.stderr)
        sys.exit(1)
    mensagem(sys.argv[1])


if __name__ == "__main__":
    main()
