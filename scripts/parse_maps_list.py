"""
parse_maps_list.py — extrai cards de texto bruto do Maps por regex.

O LLM nunca interpreta a lista. A posição de cada card vem da ordem
em que o padrão nome-duplicado aparece no texto, nunca de contagem manual.

Dois padrões de card no texto do Maps:

  Orgânico:
      Nome
      Nome          <- repetição imediata na próxima linha
      X,X(N)        <- rating
      Categoria · Endereço
      Status · Horário · Telefone
      ...

  Patrocinado (pago_maps):
      Nome
      Patrocinado   <- label aparece APÓS o nome, não antes
      [linha vazia]
      Nome          <- repetição (com vazio no meio)
      X,X(N)
      Categoria · Endereço
      Status · Horário · Telefone
      ...

Posição orgânica = ordem de aparição no texto. Patrocinado recebe
posicao_maps = 0 (não entra na numeração orgânica).

Uso:
  python scripts/parse_maps_list.py <execucao_id> <cidade>

Lê:  coletas/maps_raw_<execucao_id>.txt
Escreve para stdout: JSON com os cards extraídos.
"""

import json
import re
import sys
from pathlib import Path

_UFS = {
    'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG',
    'PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO',
}


def _normalizar(s: str) -> str:
    return (s or '').lower().strip()


def _extrair_cidade_endereco(endereco_raw: str):
    """
    Procura padrão 'Cidade - UF' ou ', Cidade - UF' no endereço.
    Retorna (cidade_str, uf_str) ou (None, None) quando não encontrar.
    Não inventa: retorna None se o padrão não aparecer.
    """
    if not endereco_raw:
        return None, None
    for m in re.finditer(
        r'[,\-]\s*([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ][A-Za-záéíóúàâêôãõç ]+?)\s*[-,]\s*([A-Z]{2})\b',
        endereco_raw,
    ):
        uf = m.group(2).upper()
        if uf in _UFS:
            return m.group(1).strip(), uf
    return None, None


def parse_maps_list(texto_bruto: str, cidade_rodada: str) -> list:
    """
    Percorre o texto linha a linha detectando cards pelos dois padrões
    documentados no cabeçalho deste arquivo.
    """
    cidade_norm = _normalizar(cidade_rodada)
    linhas = [l.rstrip() for l in texto_bruto.split('\n')]
    n = len(linhas)
    cards = []
    posicao_organica = 0
    i = 0

    while i < n:
        linha = linhas[i].strip()

        # Pula linha vazia
        if not linha:
            i += 1
            continue

        # ---- Detecta início de card ----------------------------------------
        tipo = None
        nome = None

        proximo = linhas[i + 1].strip() if i + 1 < n else ''

        # Caso A — Orgânico: linha[i] == linha[i+1]
        if proximo == linha:
            tipo = 'organico'
            nome = linha
            i += 2

        # Caso B — Patrocinado: linha[i+1] == "Patrocinado"
        elif proximo == 'Patrocinado':
            tipo = 'pago_maps'
            nome = linha
            i += 2  # consome Nome + "Patrocinado"
            while i < n and not linhas[i].strip():
                i += 1
            # Consome a segunda ocorrência do nome
            if i < n and linhas[i].strip() == nome:
                i += 1

        else:
            i += 1
            continue
        # ----------------------------------------------------------------------

        # Posição: patrocinado = 0; orgânico incrementa
        if tipo == 'organico':
            posicao_organica += 1
            posicao_maps = posicao_organica
        else:
            posicao_maps = 0

        # ---- Rating: "5,0(41)" ou "4,9(54)" ---------------------------------
        nota = None
        avaliacoes = None
        if i < n:
            m = re.match(r'^(\d+[,.]\d+)\(([\d.]+)\)$', linhas[i].strip())
            if m:
                nota = float(m.group(1).replace(',', '.'))
                avaliacoes = int(m.group(2).replace('.', ''))
                i += 1

        # ---- Categoria · Endereço -------------------------------------------
        categoria = None
        endereco_raw = None
        if i < n and '·' in linhas[i]:
            partes = [p.strip() for p in linhas[i].split('·') if p.strip()]
            if partes:
                categoria = partes[0]
                endereco_raw = partes[-1] if len(partes) > 1 else None
            i += 1

        # ---- Status · Horário · Telefone ------------------------------------
        # Padrão primário: (DDD) NNNN-NNNN ou (DDD) NNNNN-NNNN
        # Padrão secundário: NNNN-NNNN sem DDD (números de serviço tipo 4020-XXXX)
        telefone = None
        if i < n:
            linha_status = linhas[i].strip()
            m = re.search(r'\((\d{2})\)\s*(\d{4,5}-\d{4})', linha_status)
            if m:
                telefone = f"({m.group(1)}) {m.group(2)}"
            else:
                m2 = re.search(r'\b(\d{4}-\d{4})\b', linha_status)
                if m2:
                    telefone = m2.group(1)
            i += 1

        # ---- Website: varre as próximas 8 linhas ----------------------------
        tem_website = False
        for j in range(i, min(i + 9, n)):
            if linhas[j].strip() == 'Website':
                tem_website = True
                break

        # ---- cidade_mencionada_diferente ------------------------------------
        # Só detectável quando o endereço parcial inclui "Cidade - UF".
        # Se não aparecer, fica null — o parser não chuta.
        cidade_mencionada_diferente = None
        cidade_extraida, uf_extraida = _extrair_cidade_endereco(endereco_raw)
        if cidade_extraida and _normalizar(cidade_extraida) != cidade_norm:
            cidade_mencionada_diferente = f"{cidade_extraida}, {uf_extraida}"

        cards.append({
            'posicao_maps': posicao_maps,
            'nome': nome,
            'nota': nota,
            'avaliacoes': avaliacoes,
            'categoria': categoria,
            'endereco_raw': endereco_raw,
            'telefone': telefone,
            'tem_website': tem_website,
            'tipo': tipo,
            'cidade_mencionada_diferente': cidade_mencionada_diferente,
        })

    return cards


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(json.dumps(
            {'erro': 'Uso: parse_maps_list.py <execucao_id> <cidade>'},
            ensure_ascii=False,
        ))
        sys.exit(1)

    execucao_id = sys.argv[1]
    cidade = sys.argv[2]

    base = Path(__file__).parent.parent
    raw_path = base / 'coletas' / f'maps_raw_{execucao_id}.txt'

    if not raw_path.exists():
        print(json.dumps(
            {'erro': f'Arquivo não encontrado: {raw_path.name}'},
            ensure_ascii=False,
        ))
        sys.exit(1)

    with open(raw_path, encoding='utf-8') as f:
        texto = f.read()

    cards = parse_maps_list(texto, cidade)

    saida = {
        'execucao_id': execucao_id,
        'cidade': cidade,
        'total_cards': len(cards),
        'cards': cards,
    }
    print(json.dumps(saida, ensure_ascii=False, indent=2))
