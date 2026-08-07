"""
filtro_exclusao.py — filtro grátis antes de coletar-metricas.

Lê lista_exclusao.yaml e descarta candidatos que:
  - pertencem a diretorios_e_guias, redes_sociais ou marketplaces
    (correspondência exata ou subdomínio — ex.: br.linkedin.com bate com linkedin.com)
  - têm sufixo institucional (.gov.br, .org.br, etc.)
    (casamento por sufixo — o domínio termina com o sufixo)

Zero chamadas de MCP. Decisão só em texto.
Candidatos já com status_tecnico != "ok" são ignorados.
Candidatos descartados recebem status_tecnico = "diretorio".

Uso:
  python scripts/filtro_exclusao.py <execucao_id>
"""

import json
import sys
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent


def _carregar_exclusao() -> dict:
    with open(BASE_DIR / "lista_exclusao.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _norm_dominio(s: str) -> str:
    s = (s or "").strip().lower()
    if s.startswith("www."):
        s = s[4:]
    return s


def _na_lista(dominio: str, lista: list) -> str | None:
    """
    Retorna a entrada da lista que casou, ou None.
    Casamento: exato (dominio == entrada) ou subdomínio (br.linkedin.com → linkedin.com).
    """
    for entrada in lista:
        if dominio == entrada or dominio.endswith("." + entrada):
            return entrada
    return None


def _tem_sufixo(dominio: str, sufixos: list) -> str | None:
    """Retorna o sufixo que casou, ou None. Sufixos já têm ponto inicial (.org.br)."""
    for suf in sufixos:
        if dominio.endswith(suf):
            return suf
    return None


def filtrar(execucao_id: str) -> dict:
    coletas = BASE_DIR / "coletas"
    cand_path = coletas / f"candidatos_{execucao_id}.json"

    if not cand_path.exists():
        return {
            "passou": False,
            "erros": [f"candidatos_{execucao_id}.json não encontrado"],
        }

    exclusao = _carregar_exclusao()
    sufixos = exclusao.get("sufixos_institucionais", [])
    diretorios = exclusao.get("diretorios_e_guias", [])
    redes = exclusao.get("redes_sociais", [])
    marketplaces = exclusao.get("marketplaces", [])
    listas_dominio = diretorios + redes + marketplaces

    with open(cand_path, encoding="utf-8") as f:
        dados = json.load(f)

    candidatos = dados.get("candidatos", [])

    descartados = []
    ignorados_status = 0

    for c in candidatos:
        if c.get("status_tecnico") != "ok":
            ignorados_status += 1
            continue

        dominio = _norm_dominio(c.get("dominio") or "")
        if not dominio:
            continue

        entrada_casada = _na_lista(dominio, listas_dominio)
        if entrada_casada:
            categoria = (
                "diretorios_e_guias" if entrada_casada in diretorios
                else "redes_sociais" if entrada_casada in redes
                else "marketplaces"
            )
            c["status_tecnico"] = "diretorio"
            c["motivo"] = f"lista_exclusao:{categoria} — casa com '{entrada_casada}'"
            descartados.append({"dominio": dominio, "motivo": c["motivo"]})
            continue

        suf_casado = _tem_sufixo(dominio, sufixos)
        if suf_casado:
            c["status_tecnico"] = "diretorio"
            c["motivo"] = f"sufixo_institucional:{suf_casado}"
            descartados.append({"dominio": dominio, "motivo": c["motivo"]})

    with open(cand_path, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    aprovados = [
        c.get("dominio") for c in candidatos if c.get("status_tecnico") == "ok"
    ]

    return {
        "passou": True,
        "execucao_id": execucao_id,
        "avaliados": len(candidatos) - ignorados_status,
        "descartados": len(descartados),
        "aprovados_count": len(aprovados),
        "ignorados_status_anterior": ignorados_status,
        "descartados_detalhe": descartados,
        "aprovados": aprovados,
    }


def main():
    if len(sys.argv) != 2:
        print(json.dumps({"erro": "Uso: filtro_exclusao.py <execucao_id>"}, ensure_ascii=False))
        sys.exit(1)

    resultado = filtrar(sys.argv[1])
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    sys.exit(0 if resultado.get("passou") else 1)


if __name__ == "__main__":
    main()
