"""
carregar_base.py — lê o leads.csv e devolve a lista de domínios, telefones
e e-mails já conhecidos, para evitar reprocessar na próxima rodada.

Saída (stdout em JSON):
  {
    "ok": true,
    "total_linhas": 42,
    "conhecidos": {
      "dominios": ["site1.com.br", "site2.com.br"],
      "telefones": ["5511999990001"],
      "emails": ["contato@site1.com.br"]
    }
  }
  { "ok": false, "erro": "..." }
"""

import sys
import os
import csv
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEADS_PATH = os.path.join(BASE_DIR, "leads.csv")

COLUNAS_ESPERADAS = {"dominio", "telefone", "email"}


def main():
    if not os.path.isfile(LEADS_PATH):
        saida = {
            "ok": True,
            "total_linhas": 0,
            "conhecidos": {"dominios": [], "telefones": [], "emails": []},
        }
        print(json.dumps(saida, ensure_ascii=False, indent=2))
        return

    try:
        with open(LEADS_PATH, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)

            colunas_presentes = set(reader.fieldnames or [])
            faltando = COLUNAS_ESPERADAS - colunas_presentes
            if faltando:
                saida = {
                    "ok": False,
                    "erro": (
                        f"leads.csv está faltando colunas obrigatórias: "
                        f"{', '.join(sorted(faltando))}"
                    ),
                }
                print(json.dumps(saida, ensure_ascii=False, indent=2))
                sys.exit(1)

            dominios = set()
            telefones = set()
            emails = set()
            total = 0

            for linha in reader:
                total += 1

                dominio = (linha.get("dominio") or "").strip().lower()
                if dominio:
                    dominios.add(dominio)

                telefone = (linha.get("telefone") or "").strip()
                telefone = "".join(c for c in telefone if c.isdigit())
                if telefone:
                    telefones.add(telefone)

                email = (linha.get("email") or "").strip().lower()
                if email:
                    emails.add(email)

    except Exception as e:
        saida = {"ok": False, "erro": f"Erro ao ler leads.csv: {e}"}
        print(json.dumps(saida, ensure_ascii=False, indent=2))
        sys.exit(1)

    saida = {
        "ok": True,
        "total_linhas": total,
        "conhecidos": {
            "dominios": sorted(dominios),
            "telefones": sorted(telefones),
            "emails": sorted(emails),
        },
    }
    print(json.dumps(saida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
