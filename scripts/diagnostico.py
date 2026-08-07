"""
diagnostico.py — monta SEO, GEO e GMN para cada candidato ok/revisar.

Uso:
  python scripts/diagnostico.py <execucao_id>

Lê:
  coletas/candidatos_<execucao_id>.json
  coletas/qualificacao_<execucao_id>.json
  coletas/maps_<execucao_id>.json
  coletas/perfis_<execucao_id>_lote_*.json

Escreve de volta ao candidatos_<execucao_id>.json, adicionando em cada
candidato ok/revisar:
  diag_seo, gap_posicao, gap_autoridade
  diag_geo, ai_overview_presente, ai_overview_cita_conc, ai_overview_cita_lead
  diag_gmn, gmn_sinais, gmn_avaliacoes, gmn_nota
  diagnostico_resumo, ganho_rapido, ancora
"""

import sys
import os
import json
import yaml
import re
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
COLETAS_DIR = os.path.join(BASE_DIR, "coletas")

_ORIGENS_MAPS = {"gmn", "ambos", "pago_maps"}

# ── Utilitários de data ───────────────────────────────────────────────────────

_MESES_PT = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12
}


def _parse_data_pt(s, data_ref):
    """Converte string de data PT-BR para date. None se não conseguir."""
    if not s:
        return None
    s2 = s.strip().lower()

    m = re.match(r"h[aá]\s+(\d+)\s+dias?", s2)
    if m:
        return data_ref - timedelta(days=int(m.group(1)))

    m = re.match(r"h[aá]\s+(\d+)\s+semanas?", s2)
    if m:
        return data_ref - timedelta(weeks=int(m.group(1)))

    m = re.match(r"h[aá]\s+(\d+)\s+m[eê]ses?", s2)
    if m:
        return data_ref - timedelta(days=int(m.group(1)) * 30)

    m = re.match(r"h[aá]\s+(\d+)\s+anos?", s2)
    if m:
        return data_ref - timedelta(days=int(m.group(1)) * 365)

    if s2 == "ontem":
        return data_ref - timedelta(days=1)

    m = re.match(r"(\d{1,2})\s+de\s+(\w+)\.?\s+de\s+(\d{4})", s2)
    if m:
        dia = int(m.group(1))
        mes_str = m.group(2)[:3]
        ano = int(m.group(3))
        mes = _MESES_PT.get(mes_str)
        if mes:
            try:
                return date(ano, mes, dia)
            except ValueError:
                pass

    return None


# ── Derivação dos sinais GMN ──────────────────────────────────────────────────

def _derivar_sinais_gmn(card, keyword, cfg, data_ref):
    """
    Deriva lista de sinais GMN disparados a partir dos campos de um card.
    Funciona para cards do maps JSON (todos os campos) e do perfis JSON (subset).
    Retorna (sinais: list[str], frases: list[str]).
    """
    limiares = cfg.get("gmn_limiares", {})
    sinais = []
    frases = []

    # Sem site
    site = card.get("site")
    if not site:
        sinais.append("sem_site")
        frases.append("sem site cadastrado")

    # WhatsApp invisível — maps usa "tem_whatsapp"; perfis usa "tem_whatsapp_botao"
    tem_wa = card.get("tem_whatsapp") if "tem_whatsapp" in card else card.get("tem_whatsapp_botao")
    if not tem_wa:
        sinais.append("whatsapp_invisivel")
        frases.append("WhatsApp não visível no perfil")

    # Poucas avaliações
    avaliacoes = card.get("avaliacoes")
    av_min = limiares.get("avaliacoes_min", 30)
    if avaliacoes is not None and avaliacoes < av_min:
        sinais.append("poucas_avaliacoes")
        frases.append(f"poucas avaliações ({avaliacoes})")

    # Nota baixa
    nota = card.get("nota")
    nota_min = limiares.get("nota_min", 4.0)
    if nota is not None and nota < nota_min:
        sinais.append("nota_baixa")
        frases.append(f"nota baixa ({nota})")

    # Sem posts recentes — só quando o campo existe no card (maps JSON)
    if "data_ultimo_post" in card:
        data_post_str = card.get("data_ultimo_post")
        meses_post = limiares.get("meses_sem_post", 6)
        if data_post_str is not None:
            data_post = _parse_data_pt(data_post_str, data_ref)
            if data_post and (data_ref - data_post).days / 30.44 > meses_post:
                sinais.append("sem_posts_recentes")
                frases.append(f"último post em {data_post.strftime('%b/%Y').lower()}")

    # Sem produtos — só quando o campo existe E tem valor explícito False
    if "tem_produtos" in card and card.get("tem_produtos") is False:
        sinais.append("sem_produtos")
        frases.append("sem produtos cadastrados")

    # Descrição sem keyword — só quando descrição foi capturada (não é null)
    if "descricao" in card and card.get("descricao") is not None:
        descricao = card["descricao"]
        if keyword.lower() not in descricao.lower():
            sinais.append("descricao_sem_keyword")
            frases.append("descrição sem a palavra-chave")

    # Fotos antigas — só quando foto_data_confirmada = True
    if "foto_data_mais_recente" in card:
        foto_confirmada = card.get("foto_data_confirmada", False)
        foto_data_str = card.get("foto_data_mais_recente")
        meses_foto = limiares.get("meses_foto_antiga", 12)
        if foto_confirmada and foto_data_str:
            data_foto = _parse_data_pt(foto_data_str, data_ref)
            if data_foto and (data_ref - data_foto).days / 30.44 > meses_foto:
                sinais.append("fotos_antigas")
                frases.append(f"fotos de {data_foto.strftime('%b/%Y').lower()}")

    # Não responde avaliações
    if "avaliacoes_respondidas_5" in card:
        respondidas = card.get("avaliacoes_respondidas_5")
        total_vis = card.get("total_avaliacoes_visiveis")
        ordem = card.get("avaliacoes_ordem", "relevantes")
        if respondidas is not None and total_vis is not None and total_vis > 0 and respondidas == 0:
            suf = " (baseado nas avaliações mais relevantes, não as mais recentes)" if ordem == "relevantes" else ""
            sinais.append("nao_responde_avaliacoes")
            frases.append(f"não responde avaliações{suf}")

    return sinais, frases


# ── SEO ───────────────────────────────────────────────────────────────────────

def _diag_seo(cand):
    """Retorna (texto_seo, gap_posicao, gap_autoridade)."""
    origem = cand.get("origem", "search")
    posicao = cand.get("posicao_organica")

    if origem == "pago":
        return ("empresa paga por tráfego nessa busca sem presença orgânica na 1ª página",
                None, None)

    if origem == "pago_maps":
        return ("empresa paga por destaque no Maps — não encontrado na busca orgânica",
                None, None)

    if origem == "gmn":
        return ("não encontrado na busca orgânica — visibilidade apenas pelo Google Maps",
                None, None)

    # search ou ambos
    if posicao:
        gap = posicao - 1
        return (
            f"fora da 1ª página ({posicao}ª posição) — dado de autoridade não disponível no fluxo padrão",
            gap,
            None
        )
    return ("posição na busca orgânica não disponível", None, None)


# ── GEO ───────────────────────────────────────────────────────────────────────

def _diag_geo(cand, qual_data):
    """Retorna (texto_geo, ai_presente, ai_cita_conc, ai_cita_lead)."""
    ai = qual_data.get("ai_overview", {})
    presente = bool(ai.get("presente"))
    dominios_citados = [d for d in (ai.get("dominios_citados") or []) if d]
    n = len(dominios_citados)

    top3 = qual_data.get("top3_organicos") or []
    conc_dom = top3[0].get("dominio", "") if top3 else ""
    lead_dom = cand.get("dominio", "")

    cita_conc = conc_dom in dominios_citados
    cita_lead = lead_dom in dominios_citados

    if not presente:
        return ("sem AI Overview para esta busca", False, False, False)

    if cita_lead:
        return (f"AI Overview cita {n} domínios, incluindo este", True, cita_conc, True)

    if cita_conc:
        return (
            f"AI Overview cita {n} domínios, o 1º colocado entre eles. Este lead não aparece.",
            True, True, False
        )

    return (f"AI Overview cita {n} domínios, nenhum dos dois presentes", True, False, False)


# ── GMN ───────────────────────────────────────────────────────────────────────

def _diag_gmn(cand, maps_idx, perfis_idx, keyword, cfg, data_ref):
    """
    Retorna (texto_gmn, sinais, gmn_avaliacoes, gmn_nota).
    maps_idx: dominio → card do maps JSON.
    perfis_idx: dominio_candidato → card do perfis JSON.
    """
    origem = cand.get("origem", "search")
    dominio = cand.get("dominio", "")

    # pago_maps: frase de patrocínio + sinais quando disponíveis
    if origem == "pago_maps":
        card = maps_idx.get(dominio, {})
        sinais, frases = _derivar_sinais_gmn(card, keyword, cfg, data_ref)
        nota = card.get("nota")
        av = card.get("avaliacoes")
        base = "empresa paga por destaque no Maps sem estar bem posicionada organicamente aqui"
        if sinais:
            return (f"{base}. Sinais: {'; '.join(frases)}", sinais, av, nota)
        return (base, sinais, av, nota)

    # gmn ou ambos: usa card do maps JSON para sinal completo
    if origem in ("gmn", "ambos"):
        card = maps_idx.get(dominio, {})
        if not card:
            # Candidato sem site (dominio null): posicao_maps preenchida prova que o
            # perfil foi localizado na lista — só não há site para confirmar os sinais.
            pos_maps = cand.get("posicao_maps")
            if pos_maps is not None:
                return (
                    f"perfil encontrado no Maps ({pos_maps}ª posição), "
                    "mas sem site para confirmar os demais sinais",
                    [], None, None
                )
            return ("perfil não localizado no Maps", [], None, None)
        sinais, frases = _derivar_sinais_gmn(card, keyword, cfg, data_ref)
        nota = card.get("nota")
        av = card.get("avaliacoes")
        if sinais:
            return ("; ".join(frases), sinais, av, nota)
        # Sem sinais — verificar se foto não foi confirmada
        foto_conf = card.get("foto_data_confirmada")
        foto_data = card.get("foto_data_mais_recente")
        if "foto_data_mais_recente" in card and not foto_conf and foto_data is None:
            return (
                "perfil bem otimizado; não foi possível confirmar a data da foto",
                sinais, av, nota
            )
        return ("perfil bem otimizado, sem pontos de melhoria óbvios", sinais, av, nota)

    # search ou pago: usa perfis JSON (subset de sinais — sem posts, produtos, fotos, avaliações)
    card_perfil = perfis_idx.get(dominio, {})
    if not card_perfil:
        return ("perfil não localizado no Maps", [], None, None)

    sinais, frases = _derivar_sinais_gmn(card_perfil, keyword, cfg, data_ref)
    nota = card_perfil.get("nota")
    av = card_perfil.get("avaliacoes")

    if sinais:
        return ("; ".join(frases), sinais, av, nota)
    return (
        "perfil bem otimizado (diagnóstico completo requer segundo toque no Maps)",
        sinais, av, nota
    )


# ── Ganho mais rápido ─────────────────────────────────────────────────────────

def _ganho_rapido(texto_geo, sinais_gmn, posicao_organica, gap_autoridade, cfg):
    """
    Aplica as quatro regras em ordem. Retorna "SEO", "GEO" ou "GMN".
    """
    gr_cfg = cfg.get("ganho_rapido", {})
    min_sinais_gmn = gr_cfg.get("min_sinais_gmn_para_gmn", 3)
    pos_max_seo = gr_cfg.get("posicao_max_seo", 15)
    gap_max_seo = gr_cfg.get("gap_autoridade_max_seo", 15)

    # Regra 1
    if len(sinais_gmn) >= min_sinais_gmn:
        return "GMN"

    # Regra 2 — AI Overview existe E candidato não aparece nele
    ai_existe = "AI Overview cita" in texto_geo
    cita_lead = "incluindo este" in texto_geo
    if ai_existe and not cita_lead:
        return "GEO"

    # Regra 3 — posição até pos_max_seo e gap de autoridade confirmado
    if (posicao_organica is not None and posicao_organica <= pos_max_seo
            and gap_autoridade is not None and gap_autoridade <= gap_max_seo):
        return "SEO"

    # Regra 4 — padrão
    return "GMN"


# ── Principal ─────────────────────────────────────────────────────────────────

def diagnostico(execucao_id):
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cand_path = os.path.join(COLETAS_DIR, f"candidatos_{execucao_id}.json")
    with open(cand_path, encoding="utf-8") as f:
        cand_data = json.load(f)

    keyword = cand_data.get("keyword", "")
    candidatos = cand_data.get("candidatos", [])

    qual_path = os.path.join(COLETAS_DIR, f"qualificacao_{execucao_id}.json")
    with open(qual_path, encoding="utf-8") as f:
        qual_data = json.load(f)

    # Data de referência = timestamp do maps JSON (para parsear "há X dias")
    maps_path = os.path.join(COLETAS_DIR, f"maps_{execucao_id}.json")
    data_ref = date.today()
    maps_idx = {}
    if os.path.exists(maps_path):
        with open(maps_path, encoding="utf-8") as f:
            maps_data = json.load(f)
        ts = maps_data.get("timestamp", "")
        if ts:
            try:
                data_ref = date.fromisoformat(ts[:10])
            except ValueError:
                pass
        for card in maps_data.get("cards", []):
            dom = card.get("site") or ""
            if dom:
                maps_idx[dom] = card

    # Perfis indexados por dominio_candidato (que bate com candidatos["dominio"])
    perfis_idx = {}
    for fn in sorted(os.listdir(COLETAS_DIR)):
        if fn.startswith(f"perfis_{execucao_id}_lote_") and fn.endswith(".json"):
            with open(os.path.join(COLETAS_DIR, fn), encoding="utf-8") as f:
                perfis_data = json.load(f)
            for card in perfis_data.get("cards", []):
                dom = card.get("dominio_candidato") or ""
                if dom:
                    perfis_idx[dom] = card

    ancoras = cfg.get("ancoras", {})
    processados = []
    ignorados = 0

    for cand in candidatos:
        st = cand.get("status_tecnico", "")
        if st not in ("ok", "revisar"):
            ignorados += 1
            continue

        # SEO
        texto_seo, gap_pos, gap_aut = _diag_seo(cand)
        cand["diag_seo"] = texto_seo
        cand["gap_posicao"] = gap_pos
        cand["gap_autoridade"] = gap_aut

        # GEO
        texto_geo, ai_pres, ai_conc, ai_lead = _diag_geo(cand, qual_data)
        cand["diag_geo"] = texto_geo
        cand["ai_overview_presente"] = ai_pres
        cand["ai_overview_cita_conc"] = ai_conc
        cand["ai_overview_cita_lead"] = ai_lead

        # GMN
        texto_gmn, sinais, av, nota = _diag_gmn(
            cand, maps_idx, perfis_idx, keyword, cfg, data_ref
        )
        cand["diag_gmn"] = texto_gmn
        cand["gmn_sinais"] = sinais
        cand["gmn_avaliacoes"] = av
        cand["gmn_nota"] = nota

        # Ganho mais rápido e âncora
        gr = _ganho_rapido(texto_geo, sinais, cand.get("posicao_organica"), gap_aut, cfg)
        cand["ganho_rapido"] = gr
        cand["ancora"] = ancoras.get(gr, "")

        cand["diagnostico_resumo"] = (
            f"SEO: {texto_seo} | GEO: {texto_geo} | GMN: {texto_gmn}"
        )

        processados.append(cand)

    with open(cand_path, "w", encoding="utf-8") as f:
        json.dump(cand_data, f, ensure_ascii=False, indent=2)

    # Tabela de resultado
    print(f"\n{'─'*110}")
    print(f"{'DOMÍNIO':<35} {'ORIGEM':<8} {'GANHO':<5} {'SINAIS GMN':<3}  FRASE GMN / MOTIVO SEO")
    print(f"{'─'*110}")
    for c in processados:
        dom = (c.get("dominio") or "")[:34]
        orig = c.get("origem", "")[:7]
        gr = c.get("ganho_rapido", "")[:5]
        n_sin = len(c.get("gmn_sinais") or [])
        gmn_resumo = c.get("diag_gmn", "")[:55]
        print(f"{dom:<35} {orig:<8} {gr:<5} {n_sin:<3}  {gmn_resumo}")
    print(f"{'─'*110}")
    print(f"\nProcessados: {len(processados)} | Ignorados (status!=ok/revisar): {ignorados}")
    print(json.dumps({
        "status": "ok",
        "execucao_id": execucao_id,
        "processados": len(processados),
        "ignorados": ignorados
    }, ensure_ascii=False))


def main():
    if len(sys.argv) < 2:
        print("Uso: python diagnostico.py <execucao_id>", file=sys.stderr)
        sys.exit(1)
    diagnostico(sys.argv[1])


if __name__ == "__main__":
    main()
