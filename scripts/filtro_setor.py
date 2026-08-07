"""
filtro_setor.py — aplica os sinais de setor sobre os candidatos.

Parte 1 (Fase 5, roda após coletar-metricas):
  Sinal 1 — portal    : keywords_organicas > max_keywords_portal
  Sinal 2 — agregador : trafego > trafego do concorrente de referência

Parte 2 (Fase 6, roda após coletar-perfis):
  Sinal 3 — sem presença local : sem perfil no Maps com endereço na cidade

Uso:
  python scripts/filtro_setor.py 1 <execucao_id>
  python scripts/filtro_setor.py 2 <execucao_id>
"""

import json
import re
import sys
from pathlib import Path

import yaml


def _carregar(caminho):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def _carregar_config():
    base = Path(__file__).parent.parent
    with open(base / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _norm_dominio(s):
    return (s or "").lower().strip().rstrip("/")


def _norm_telefone(s):
    return re.sub(r"\D", "", s or "")


def _dominio_raiz(d):
    """Segmento antes do primeiro ponto — 'memdesa' de 'memdesa.adv.br'."""
    if not d:
        return ""
    idx = d.find(".")
    return d[:idx] if idx > 0 else ""


def _edit_distance_1(a, b):
    """
    True se a distância de edição (Levenshtein) entre a e b for ≤ 1.
    Retorna False imediatamente quando |len(a) - len(b)| > 1.
    """
    if not a or not b:
        return False
    if abs(len(a) - len(b)) > 1:
        return False
    if a == b:
        return True
    if len(a) > len(b):
        a, b = b, a
    if len(a) == len(b):
        return sum(ca != cb for ca, cb in zip(a, b)) == 1
    # len(b) == len(a) + 1: b sem um char deve igualar a
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))


def _tem_presenca_local(candidato, cidade_norm, todas_cards):
    """
    Retorna True se algum card do Maps confirma presença física na cidade.

    Ordem de casamento (quando o candidato tem domínio):
      1. Exato          : card.site == dominio
      2. Mesma raiz     : segmento antes do primeiro ponto é idêntico
                          (ex.: memdesa.com.br ↔ memdesa.adv.br)
      3. Edição ≤ 1     : distância de Levenshtein entre domínios completos ≤ 1
                          (ex.: msadvogados.com.br ↔ msadvogado.com.br)
    Quando não há domínio: casamento por telefone (dígitos apenas).
    Nunca por nome da empresa.
    """
    dominio = _norm_dominio(candidato.get("dominio"))
    telefone = _norm_telefone(candidato.get("telefone"))

    for card in todas_cards:
        card_site = _norm_dominio(card.get("site"))
        card_tel = _norm_telefone(card.get("telefone"))

        if dominio:
            raiz_card = _dominio_raiz(card_site)
            raiz_cand = _dominio_raiz(dominio)
            match = (
                card_site == dominio                                    # 1. exato
                or (bool(raiz_card) and raiz_card == raiz_cand)        # 2. mesma raiz
                or _edit_distance_1(card_site, dominio)                # 3. edição ≤ 1
            )
        elif telefone:
            match = bool(telefone) and card_tel == telefone
        else:
            match = False

        if not match:
            continue

        endereco = (card.get("endereco") or "").lower()
        if cidade_norm in endereco:
            return True

    return False


def _carregar_metricas(base, execucao_id):
    """Lê todos os lotes de métricas e retorna dict dominio → campos."""
    coletas = base / "coletas"
    metricas = {}
    lote = 1
    while True:
        path = coletas / f"metricas_{execucao_id}_lote_{lote}.json"
        if not path.exists():
            break
        dados = _carregar(path)
        for c in dados.get("candidatos", []):
            metricas[c["dominio"]] = c
        lote += 1
    return metricas


def _concorrente_trafego(base, execucao_id):
    """Tráfego do primeiro colocado qualificado (topo do top3)."""
    qual_path = base / "coletas" / f"qualificacao_{execucao_id}.json"
    if not qual_path.exists():
        return None
    qual = _carregar(qual_path)
    top3 = qual.get("top3_organicos", [])
    return top3[0].get("trafego_mensal") if top3 else None


def sinais1_e_2(execucao_id):
    """
    Sinal 1 — portal    : keywords_organicas > max_keywords_portal
    Sinal 2 — agregador : trafego > trafego do concorrente de referência

    Candidatos com origem=pago_maps pulam os dois sinais.
    Candidatos sem métrica ficam em lista separada (sem_metrica) —
    não são descartados nem aprovados até métricas chegarem.

    Atualiza status_tecnico e motivo em candidatos.json (in-place).
    """
    base = Path(__file__).parent.parent
    coletas = base / "coletas"
    config = _carregar_config()
    max_keywords = config.get("max_keywords_portal", 5000)

    cand_path = coletas / f"candidatos_{execucao_id}.json"
    if not cand_path.exists():
        return {
            "sinais": "1_e_2",
            "passou": False,
            "erros": [f"candidatos_{execucao_id}.json não encontrado"],
        }

    dados_cand = _carregar(cand_path)
    candidatos = dados_cand["candidatos"]

    metricas = _carregar_metricas(base, execucao_id)
    if not metricas:
        return {
            "sinais": "1_e_2",
            "passou": False,
            "erros": ["Nenhum lote de métricas encontrado — rodar coletar-metricas primeiro"],
        }

    trafego_conc = _concorrente_trafego(base, execucao_id)
    if trafego_conc is None:
        return {
            "sinais": "1_e_2",
            "passou": False,
            "erros": ["top3_organicos ausente ou vazio na qualificação — tráfego do concorrente indisponível"],
        }

    descartados_s1 = []
    descartados_s2 = []
    sem_metrica = []
    pago_maps_pularam = []
    aprovados = []

    for cand in candidatos:
        if cand.get("status_tecnico") != "ok":
            continue

        dominio = cand.get("dominio")
        origem = cand.get("origem", "")

        if origem == "pago_maps":
            pago_maps_pularam.append(dominio)
            continue

        m = metricas.get(dominio)
        if m is None or m.get("fonte_metrica") == "nenhuma":
            sem_metrica.append(dominio)
            continue

        keywords = m.get("keywords_organicas")
        trafego = m.get("trafego")

        # sinal 1 — portal
        if keywords is not None and keywords > max_keywords:
            cand["status_tecnico"] = "nao_e_do_setor"
            cand["motivo"] = f"sinal1_portal: {keywords} keywords > limite {max_keywords}"
            descartados_s1.append({
                "dominio": dominio,
                "keywords_organicas": keywords,
                "limite": max_keywords,
            })
            continue

        # sinal 2 — agregador
        if trafego is not None and trafego > trafego_conc:
            cand["status_tecnico"] = "nao_e_do_setor"
            cand["motivo"] = (
                f"sinal2_agregador: trafego {trafego} > concorrente_referencia {trafego_conc}"
            )
            descartados_s2.append({
                "dominio": dominio,
                "trafego": trafego,
                "trafego_concorrente": trafego_conc,
            })
            continue

        aprovados.append(dominio)

    with open(cand_path, "w", encoding="utf-8") as f:
        json.dump(dados_cand, f, ensure_ascii=False, indent=2)

    return {
        "sinais": "1_e_2",
        "execucao_id": execucao_id,
        "trafego_concorrente_referencia": trafego_conc,
        "max_keywords_portal": max_keywords,
        "total_avaliados": len(descartados_s1) + len(descartados_s2) + len(sem_metrica) + len(pago_maps_pularam) + len(aprovados),
        "aprovados": aprovados,
        "descartados_sinal1_portal": descartados_s1,
        "descartados_sinal2_agregador": descartados_s2,
        "sem_metrica": sem_metrica,
        "pago_maps_pularam": pago_maps_pularam,
    }


def sinal3(execucao_id):
    """
    Sinal 3 do filtro de setor: ausência de presença local no Maps.

    Lê:
      candidatos_<execucao_id>.json   — lista de candidatos
      maps_<execucao_id>.json         — cards coletados pela busca direta no Maps
      perfis_<execucao_id>_lote_*.json — perfis coletados pelo coletar-perfis (Fase 6)

    Candidatos com status_tecnico já preenchido (descartados por portão anterior)
    são ignorados — o sinal não sobrescreve decisões anteriores.

    Candidatos sem presença local confirmada recebem status_tecnico = "nao_e_do_setor".

    Grava o candidatos.json atualizado.
    """
    base = Path(__file__).parent.parent
    coletas = base / "coletas"

    cand_path = coletas / f"candidatos_{execucao_id}.json"
    if not cand_path.exists():
        return {
            "sinal": "3",
            "passou": False,
            "erros": [f"Arquivo não encontrado: {cand_path.name}"],
        }

    dados = _carregar(cand_path)
    candidatos = dados.get("candidatos", [])
    cidade = dados.get("cidade", "")
    cidade_norm = cidade.lower().strip()

    if not cidade_norm:
        return {
            "sinal": "3",
            "passou": False,
            "erros": ["Campo 'cidade' ausente em candidatos.json"],
        }

    # Cards da busca direta no Maps (coletar-maps, Fase 3)
    maps_path = coletas / f"maps_{execucao_id}.json"
    maps_cards = []
    if maps_path.exists():
        maps_cards = _carregar(maps_path).get("cards", [])

    # Perfis individuais coletados pelo coletar-perfis (Fase 6)
    perfis_cards = []
    for p in sorted(coletas.glob(f"perfis_{execucao_id}_lote_*.json")):
        perfis_cards.extend(_carregar(p).get("cards", []))

    todas_cards = maps_cards + perfis_cards

    avaliados = 0
    passaram = 0
    descartados_dominios = []

    for c in candidatos:
        # Candidatos já descartados por portão ou filtro anterior: não toca
        if c.get("status_tecnico") not in (None, "", "ok"):
            continue

        # pago_maps já É um card do Maps — o sinal 3 nunca seria falso, é redundante
        if c.get("origem") == "pago_maps":
            c["sinal3_resultado"] = "pula_pago_maps"
            passaram += 1
            avaliados += 1
            continue

        avaliados += 1
        tem_local = _tem_presenca_local(c, cidade_norm, todas_cards)
        c["sinal3_resultado"] = "passou" if tem_local else "descarta"

        if tem_local:
            passaram += 1
        else:
            c["status_tecnico"] = "nao_e_do_setor"
            c["motivo"] = "sinal3: sem perfil no Maps com endereço na cidade"
            descartados_dominios.append(
                c.get("dominio") or c.get("telefone") or "?"
            )

    dados["candidatos"] = candidatos
    with open(cand_path, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    return {
        "sinal": "3",
        "descricao": "ausência de presença local no Maps",
        "execucao_id": execucao_id,
        "cidade": cidade,
        "avaliados": avaliados,
        "passaram": passaram,
        "descartados": len(descartados_dominios),
        "descartados_dominios": descartados_dominios,
        "erros": [],
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            json.dumps(
                {"erro": "Uso: filtro_setor.py <parte> <execucao_id>"},
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    parte = sys.argv[1]
    eid = sys.argv[2]

    if parte == "1":
        resultado = sinais1_e_2(eid)
    elif parte == "2":
        resultado = sinal3(eid)
    else:
        resultado = {"erro": f"Parte '{parte}' não reconhecida. Usar: 1 ou 2"}

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    sys.exit(0)
