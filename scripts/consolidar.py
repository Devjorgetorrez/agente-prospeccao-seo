"""
consolidar.py — dedup contra a base, dedup interno, fusão Search + GMN.

Uso:
  python scripts/consolidar.py <execucao_id>

Lê:
  coletas/qualificacao_<execucao_id>.json  — keyword, cidade, resultados pág. 1
  coletas/serp_<execucao_id>.json          — resultados págs. 2 e 3
  coletas/maps_<execucao_id>.json          — cards do Maps (opcional)
  leads.csv                                — histórico para dedup (opcional)

Escreve:
  coletas/candidatos_<execucao_id>.json

Regras de consolidação:
  1. Conta orgânicos da pág. 1 para derivar posições globais da SERP (págs. 2–3).
  2. Descarta duplicados contra a base (domínio ou telefone já em leads.csv).
  3. Junta duplicatas internas na SERP (mesmo domínio em págs. 2 e 3 → entrada única).
  4. Funde Search + Maps pelo domínio: mesma empresa nos dois → origem "ambos".
     Casamento por telefone não é feito aqui — candidatos SERP não têm telefone nesta fase.

Portão 1C (pago_maps já dominante no Maps orgânico) requer cruzamento com
cards_nao_coletados_posicoes_1_a_5 — feito em portoes.py (Fase 9), não aqui.
"""

import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LEADS_PATH = BASE_DIR / "leads.csv"
COLETAS_DIR = BASE_DIR / "coletas"

_PRIORIDADE_ORIGEM = {"ambos": 0, "search": 1, "gmn": 2, "pago": 3, "pago_maps": 4}


def _norm_dominio(s) -> str:
    if not s:
        return ""
    s = str(s).strip().lower()
    if s.startswith("www."):
        s = s[4:]
    return s


def _norm_fone(s) -> str:
    return re.sub(r"\D", "", s or "")


def _id_lead(dominio, telefone) -> str:
    chave = _norm_dominio(dominio or "") or _norm_fone(telefone or "")
    if not chave:
        return "sem_id"
    return hashlib.md5(chave.encode()).hexdigest()[:8]


def _carregar_base():
    """Retorna (set_dominios, set_telefones, set_emails) do leads.csv."""
    dominios, fones, emails = set(), set(), set()
    if not LEADS_PATH.exists():
        return dominios, fones, emails
    try:
        with open(LEADS_PATH, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for linha in reader:
                d = _norm_dominio(linha.get("dominio", ""))
                if d:
                    dominios.add(d)
                t = _norm_fone(linha.get("telefone", ""))
                if t:
                    fones.add(t)
                e = (linha.get("email") or "").strip().lower()
                if e:
                    emails.add(e)
    except Exception as exc:
        _fatal(f"Erro ao ler leads.csv: {exc}")
    return dominios, fones, emails


def _n_organicos_pag1(resultados: list) -> int:
    """Conta orgânicos na lista de resultados da página 1 (qualificação)."""
    return sum(1 for r in resultados if r.get("tipo") == "organico")


def _candidatos_serp(serp: dict, offset_pag1: int) -> list:
    """
    Deriva posições orgânicas globais a partir das págs. 2 e 3.
    O contador começa em offset_pag1 (qtd. de orgânicos da pág. 1).
    Resultados pagos recebem posicao_organica=null e origem="pago".
    """
    cands = []
    cont_organico = offset_pag1

    for nome_pag in ("pagina_2", "pagina_3"):
        pag = serp.get("paginas", {}).get(nome_pag, {})
        for res in pag.get("resultados", []):
            tipo = res.get("tipo", "organico")
            dominio = _norm_dominio(res.get("dominio") or "")

            if tipo == "organico":
                cont_organico += 1
                posicao_organica = cont_organico
                origem = "search"
            else:
                posicao_organica = None
                origem = "pago"

            cands.append({
                "dominio": dominio or None,
                "nome": res.get("titulo", ""),
                "telefone": None,
                "instagram": None,
                "origem": origem,
                "posicao_organica": posicao_organica,
                "posicao_maps": None,
                "cidade_mencionada_diferente": res.get("cidade_mencionada_diferente"),
                "status_tecnico": "ok",
                "motivo": None,
                "_fonte": "serp",
            })
    return cands


def _candidatos_maps(maps: dict) -> list:
    """
    Extrai candidatos de cards[] — ignora cards_nao_coletados_posicoes_1_a_5.
    (Posições 1–5 já são bem posicionados, não são prospects.)
    """
    cands = []
    for card in maps.get("cards", []):
        tipo = card.get("tipo", "organico")
        dominio = _norm_dominio(card.get("site") or "")
        telefone = card.get("telefone") or None

        origem = "pago_maps" if tipo == "pago_maps" else "gmn"

        cands.append({
            "dominio": dominio or None,
            "nome": card.get("nome", ""),
            "telefone": telefone,
            "instagram": card.get("instagram") or None,
            "origem": origem,
            "posicao_organica": None,
            "posicao_maps": card.get("posicao_maps"),
            "cidade_mencionada_diferente": card.get("cidade_mencionada_diferente"),
            "status_tecnico": "ok",
            "motivo": None,
            "_fonte": "maps",
        })
    return cands


def _dedup_contra_base(cands: list, dominios_b: set, fones_b: set) -> None:
    """Marca como 'duplicado' quem já está na base. Altera in-place."""
    for c in cands:
        if c["status_tecnico"] != "ok":
            continue
        d = _norm_dominio(c.get("dominio") or "")
        t = _norm_fone(c.get("telefone") or "")
        if d and d in dominios_b:
            c["status_tecnico"] = "duplicado"
            c["motivo"] = "ja_na_base_por_dominio"
        elif t and t in fones_b:
            c["status_tecnico"] = "duplicado"
            c["motivo"] = "ja_na_base_por_telefone"


def _dedup_interno_serp(cands: list) -> list:
    """
    Merge mesmo domínio dentro da SERP.
    Orgânico prevalece sobre pago; entre orgânicos, a menor posição fica.
    """
    por_dominio = {}
    sem_dominio = []

    for c in cands:
        d = _norm_dominio(c.get("dominio") or "")
        if d:
            por_dominio.setdefault(d, []).append(c)
        else:
            sem_dominio.append(c)

    resultado = list(sem_dominio)
    for _, grupo in por_dominio.items():
        if len(grupo) == 1:
            resultado.append(grupo[0])
            continue
        organicos = [c for c in grupo if c["origem"] == "search"]
        if organicos:
            # Menor posição orgânica — já tem o dado garantido por tipo
            resultado.append(min(organicos, key=lambda c: c["posicao_organica"]))
        else:
            resultado.append(grupo[0])

    return resultado


def _fundir(serp_cands: list, maps_cands: list) -> list:
    """
    Funde SERP + Maps pelo domínio (não por nome — grafia varia demais).
    Candidato que aparece nos dois canais → origem "ambos", ambas as posições.
    Candidatos sem fusão mantêm origem original.
    """
    serp_por_dom = {
        _norm_dominio(c.get("dominio") or ""): c
        for c in serp_cands
        if _norm_dominio(c.get("dominio") or "")
    }

    fundidos = set()
    resultado = []

    for mc in maps_cands:
        d = _norm_dominio(mc.get("dominio") or "")
        if d and d in serp_por_dom:
            sc = serp_por_dom[d]
            fundidos.add(d)
            is_dup = (sc["status_tecnico"] == "duplicado" or
                      mc["status_tecnico"] == "duplicado")
            resultado.append({
                "dominio": d,
                "nome": mc.get("nome") or sc.get("nome", ""),
                "telefone": mc.get("telefone"),
                "instagram": mc.get("instagram"),  # Maps; coletar-contatos sobrescreve se encontrar no site
                "origem": "ambos",
                "posicao_organica": sc.get("posicao_organica"),
                "posicao_maps": mc.get("posicao_maps"),
                "cidade_mencionada_diferente": (
                    mc.get("cidade_mencionada_diferente")
                    or sc.get("cidade_mencionada_diferente")
                ),
                "status_tecnico": "duplicado" if is_dup else "ok",
                "motivo": sc.get("motivo") or mc.get("motivo"),
                "_fonte": "ambos",
            })
        else:
            resultado.append(mc)

    for c in serp_cands:
        d = _norm_dominio(c.get("dominio") or "")
        if not d or d not in fundidos:
            resultado.append(c)

    return resultado


def _ordenar(cands: list) -> list:
    """Ok primeiro (por prioridade de origem), duplicados por último."""
    def chave(c):
        ok = 0 if c["status_tecnico"] == "ok" else 1
        return (ok, _PRIORIDADE_ORIGEM.get(c["origem"], 9))
    return sorted(cands, key=chave)


def _fatal(msg: str):
    print(json.dumps({"erro": msg}, ensure_ascii=False))
    sys.exit(1)


def consolidar(execucao_id: str):
    # 1. Qualificação
    arq_qual = COLETAS_DIR / f"qualificacao_{execucao_id}.json"
    if not arq_qual.exists():
        _fatal(f"Qualificação não encontrada: {arq_qual.name}")
    with open(arq_qual, encoding="utf-8") as f:
        qual = json.load(f)

    keyword = qual.get("keyword", "")
    cidade = qual.get("cidade", "")
    offset_pag1 = _n_organicos_pag1(qual.get("resultados", []))

    # 2. SERP
    arq_serp = COLETAS_DIR / f"serp_{execucao_id}.json"
    if not arq_serp.exists():
        _fatal(f"SERP não encontrada: {arq_serp.name}")
    with open(arq_serp, encoding="utf-8") as f:
        serp = json.load(f)

    serp_cands = _candidatos_serp(serp, offset_pag1)
    serp_cands = _dedup_interno_serp(serp_cands)

    # 3. Maps (opcional — pode não existir se rodada for só SERP)
    arq_maps = COLETAS_DIR / f"maps_{execucao_id}.json"
    if arq_maps.exists():
        with open(arq_maps, encoding="utf-8") as f:
            maps_cands = _candidatos_maps(json.load(f))
    else:
        maps_cands = []

    # 4. Base
    dominios_base, fones_base, _ = _carregar_base()

    # 5. Dedup contra a base (antes da fusão)
    _dedup_contra_base(serp_cands, dominios_base, fones_base)
    _dedup_contra_base(maps_cands, dominios_base, fones_base)

    # 6. Fusão Search + Maps
    todos = _fundir(serp_cands, maps_cands)

    # 7. Limpar campo interno e atribuir id_lead
    for c in todos:
        c.pop("_fonte", None)
        c["id_lead"] = _id_lead(c.get("dominio"), c.get("telefone"))

    # 8. Ordenar: ok primeiro, depois duplicados
    todos = _ordenar(todos)

    # 9. Estatísticas
    n_ok = sum(1 for c in todos if c["status_tecnico"] == "ok")
    n_dup = sum(1 for c in todos if c["status_tecnico"] == "duplicado")
    por_origem = {
        "ambos": sum(1 for c in todos if c["origem"] == "ambos"),
        "search": sum(1 for c in todos if c["origem"] == "search"),
        "gmn": sum(1 for c in todos if c["origem"] == "gmn"),
        "pago": sum(1 for c in todos if c["origem"] == "pago"),
        "pago_maps": sum(1 for c in todos if c["origem"] == "pago_maps"),
    }

    saida = {
        "execucao_id": execucao_id,
        "keyword": keyword,
        "cidade": cidade,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "resumo": {
            "total": len(todos),
            "ok": n_ok,
            "duplicados_base": n_dup,
            "por_origem": por_origem,
        },
        "candidatos": todos,
    }

    arq_saida = COLETAS_DIR / f"candidatos_{execucao_id}.json"
    with open(arq_saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "ok": True,
        "execucao_id": execucao_id,
        "total": len(todos),
        "ok_count": n_ok,
        "duplicados_base": n_dup,
        "por_origem": por_origem,
        "arquivo": arq_saida.name,
    }, ensure_ascii=False, indent=2))


def main():
    if len(sys.argv) != 2:
        _fatal("Uso: python scripts/consolidar.py <execucao_id>")
    consolidar(sys.argv[1])


if __name__ == "__main__":
    main()
