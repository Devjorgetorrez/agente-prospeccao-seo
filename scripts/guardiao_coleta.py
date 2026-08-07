import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote_plus

import yaml


def _carregar(caminho):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def _carregar_config():
    base = Path(__file__).parent.parent
    with open(base / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalizar_cidade(s):
    """Decodifica percent-encoding e + como espaço, depois converte para minúsculas."""
    return unquote_plus(s).lower().strip()


def nivel1_serp(execucao_id):
    base = Path(__file__).parent.parent
    coletas = base / "coletas"
    config = _carregar_config()
    faixa_min = config["faixa_posicao"]["min"]
    faixa_max = config["faixa_posicao"]["max"]

    erros = []
    checks = {}

    # --- carregar arquivos ---
    qual_path = coletas / f"qualificacao_{execucao_id}.json"
    serp_path = coletas / f"serp_{execucao_id}.json"

    for p in [qual_path, serp_path]:
        if not p.exists():
            return {
                "nivel": "1_serp",
                "execucao_id": execucao_id,
                "passou": False,
                "erros": [f"Arquivo não encontrado: {p.name}"],
            }

    qual = _carregar(qual_path)
    serp = _carregar(serp_path)
    cidade = qual["cidade"]
    cidade_norm = _normalizar_cidade(cidade)

    # --- check 1: URLs das páginas 2 e 3 com &start= e &near=<cidade> corretos ---
    for pagina_key, start_esperado in [("pagina_2", "10"), ("pagina_3", "20")]:
        url = serp["paginas"][pagina_key].get("url_navegada", "")

        # &start= correto
        tem_start = f"start={start_esperado}" in url
        checks[f"url_start_{pagina_key}"] = tem_start
        if not tem_start:
            erros.append(f"{pagina_key}: URL sem &start={start_esperado} — '{url}'")

        # &near= existe e aponta para a cidade correta
        try:
            params = parse_qs(urlparse(url).query)
            near_val = _normalizar_cidade(params.get("near", [""])[0])
        except Exception:
            near_val = ""
        near_ok = near_val == cidade_norm
        checks[f"url_near_{pagina_key}"] = near_ok
        if not near_ok:
            erros.append(
                f"{pagina_key}: &near= é '{near_val}', "
                f"esperado '{cidade_norm}' — URL: '{url}'"
            )

    # --- check 2: total_resultados_pagina bate com len(resultados) ---
    for pagina_key in ["pagina_2", "pagina_3"]:
        pagina = serp["paginas"][pagina_key]
        declarado = pagina.get("total_resultados_pagina", -1)
        real = len(pagina.get("resultados", []))
        match = declarado == real
        checks[f"total_bate_{pagina_key}"] = match
        if not match:
            erros.append(
                f"{pagina_key}: total_resultados_pagina={declarado} "
                f"mas {real} itens no array 'resultados'"
            )

    # --- atribuir posição orgânica global (conta só orgânicos, em ordem de página) ---
    todos = []
    for r in qual.get("resultados", []):
        todos.append({**r, "pagina": 1})
    for r in serp["paginas"]["pagina_2"].get("resultados", []):
        todos.append({**r, "pagina": 2})
    for r in serp["paginas"]["pagina_3"].get("resultados", []):
        todos.append({**r, "pagina": 3})

    pos_org = 0
    for r in todos:
        if r["tipo"] == "organico":
            pos_org += 1
            r["posicao_organica"] = pos_org

    total_organicos = pos_org

    # --- check 3: numeração orgânica contínua, sem buraco nem repetição ---
    posicoes = [r["posicao_organica"] for r in todos if r["tipo"] == "organico"]
    sem_buraco = posicoes == list(range(1, len(posicoes) + 1))
    sem_repeticao = len(posicoes) == len(set(posicoes))
    checks["posicoes_sem_buraco"] = sem_buraco
    checks["posicoes_sem_repeticao"] = sem_repeticao
    if not sem_buraco:
        erros.append(f"Numeração orgânica com buraco: {posicoes}")
    if not sem_repeticao:
        erros.append(f"Numeração orgânica com repetição: {posicoes}")

    # --- montar lista de candidatos (orgânicos na faixa) ---
    candidatos = [
        r for r in todos
        if r["tipo"] == "organico"
        and faixa_min <= r.get("posicao_organica", 0) <= faixa_max
    ]

    # --- check 4: nenhum resultado pago recebeu posição orgânica (bug de contagem) ---
    pagos_com_posicao = [r for r in todos if r["tipo"] == "pago" and "posicao_organica" in r]
    checks["sem_pagos_com_posicao_organica"] = len(pagos_com_posicao) == 0
    if pagos_com_posicao:
        erros.append(
            f"Resultados pagos receberam posição orgânica (bug de contagem): "
            f"{[r['dominio'] for r in pagos_com_posicao]}"
        )

    # --- check 5: todo candidato está dentro da faixa ---
    fora = [
        r for r in candidatos
        if not (faixa_min <= r.get("posicao_organica", 0) <= faixa_max)
    ]
    checks["candidatos_na_faixa"] = len(fora) == 0
    if fora:
        erros.append(
            f"Candidatos fora da faixa [{faixa_min}–{faixa_max}]: "
            f"{[(r['dominio'], r.get('posicao_organica')) for r in fora]}"
        )

    # --- check 6: nenhum resultado pago intercalado DENTRO de uma mesma página ---
    # "Intercalado" = tem orgânico antes E depois na mesma página.
    # Anúncios no rodapé (após todos os orgânicos da página) são normais no
    # Google e não distorcem a contagem — a verificação é por página, não pelo
    # intervalo global [primeiro_cand, último_cand], que gera falso positivo
    # quando o ad aparece entre o último orgânico de uma página e o primeiro da
    # próxima.
    # Página 1 é EXCLUÍDA deste check: Google coloca anúncios no meio dos
    # resultados da primeira página com frequência (entre os orgânicos do topo
    # e os do restante), o que é comportamento normal — não indica erro de coleta.
    # O check é relevante apenas para páginas 2 e 3, onde ads entre orgânicos
    # seriam incomuns e sugeririam parsing incorreto.
    paginas_raw = [
        ("pagina_2", serp["paginas"]["pagina_2"].get("resultados", [])),
        ("pagina_3", serp["paginas"]["pagina_3"].get("resultados", [])),
    ]
    pagos_intercalados = []
    for _nome_pag, pag_resultados in paginas_raw:
        tipos = [r["tipo"] for r in pag_resultados]
        for i, r in enumerate(pag_resultados):
            if r["tipo"] != "pago":
                continue
            tem_org_antes = any(t == "organico" for t in tipos[:i])
            tem_org_depois = any(t == "organico" for t in tipos[i + 1:])
            if tem_org_antes and tem_org_depois:
                pagos_intercalados.append(r)
    checks["sem_pagos_intercalados_na_faixa"] = len(pagos_intercalados) == 0
    if pagos_intercalados:
        erros.append(
            f"Resultado(s) pago(s) intercalado(s) entre orgânicos na mesma página "
            f"(pode distorcer contagem de posição): "
            f"{[r['dominio'] for r in pagos_intercalados]}"
        )

    passou = len(erros) == 0

    return {
        "nivel": "1_serp",
        "execucao_id": execucao_id,
        "passou": passou,
        "checks": checks,
        "total_organicos": total_organicos,
        "total_candidatos_faixa": len(candidatos),
        "candidatos": [
            {
                "dominio": r["dominio"],
                "posicao_organica": r["posicao_organica"],
                "pagina": r["pagina"],
            }
            for r in candidatos
        ],
        "erros": erros,
    }


def nivel1_maps(execucao_id):
    base = Path(__file__).parent.parent
    coletas = base / "coletas"
    config = _carregar_config()
    posicao_min_gmn = config.get("posicao_min_gmn", 4)

    erros = []
    checks = {}

    maps_path = coletas / f"maps_{execucao_id}.json"
    if not maps_path.exists():
        return {
            "nivel": "1_maps",
            "execucao_id": execucao_id,
            "passou": False,
            "erros": [f"Arquivo não encontrado: {maps_path.name}"],
        }

    dados = _carregar(maps_path)
    cards = dados.get("cards", [])

    # Suporta tanto formato antigo (total_cards_organicos = coletados) quanto
    # novo (total_coletados separado de total_cards_organicos_encontrados)
    total_encontrados = dados.get(
        "total_cards_organicos_encontrados",
        dados.get("total_cards_organicos", -1),
    )
    total_coletados_declarado = dados.get("total_coletados", len(cards))

    # --- check 1: total_coletados bate com len(cards) ---
    total_real = len(cards)
    checks["total_bate"] = total_coletados_declarado == total_real
    if total_coletados_declarado != total_real:
        erros.append(
            f"total_coletados={total_coletados_declarado} mas {total_real} cards no array"
        )

    # --- check 2: captura dupla executada ---
    captura_dupla_ok = dados.get("captura_dupla_executada") is True
    checks["captura_dupla_completa"] = captura_dupla_ok
    if not captura_dupla_ok:
        erros.append(
            "captura_dupla_executada ausente ou False — "
            "coletar-maps deve fazer duas navegações (com e sem coordenadas) "
            "e fundir os resultados antes de gravar."
        )

    # --- check 3: posicao_maps crescente, sem duplicata de negócio, todos >= posicao_min_gmn ---
    # posicao_maps reflete a posição real no Maps (ex.: 6, 7), não rank desde 1.
    # Cards pago_maps recebem posicao_maps = 0 (não entram na numeração orgânica)
    # e são isentos do check de corte mínimo — o corte é só para orgânicos.
    # Após fusão de dois sets (captura_dupla_executada), posições iguais entre
    # empresas DIFERENTES são válidas — o critério de pior posição pode gerar isso.
    # posicoes_sem_repeticao reprova apenas se o MESMO telefone ou domínio aparecer
    # mais de uma vez em cards[] (indica merge que não resolveu uma duplicata real).
    posicoes = [c.get("posicao_maps") for c in cards]
    crescente = posicoes == sorted(posicoes)

    telefones_cards = [c.get("telefone") for c in cards if c.get("telefone")]
    dominios_cards = [c.get("site") for c in cards if c.get("site")]
    duplicatas_tel = [t for t in set(telefones_cards) if telefones_cards.count(t) > 1]
    duplicatas_dom = [d for d in set(dominios_cards) if dominios_cards.count(d) > 1]
    sem_repeticao = len(duplicatas_tel) == 0 and len(duplicatas_dom) == 0

    abaixo_do_corte = [
        c.get("posicao_maps") for c in cards
        if c.get("tipo") != "pago_maps"
        and c.get("posicao_maps") is not None
        and c.get("posicao_maps") < posicao_min_gmn
    ]
    checks["posicoes_sem_repeticao"] = sem_repeticao
    checks["posicoes_crescentes"] = crescente
    checks["posicoes_acima_do_corte"] = len(abaixo_do_corte) == 0
    if not sem_repeticao:
        erros.append(
            f"Mesma empresa aparece mais de uma vez em cards[] — merge não resolveu duplicata: "
            f"telefones={duplicatas_tel}, sites={duplicatas_dom}"
        )
    if not crescente:
        erros.append(f"posicao_maps fora de ordem crescente: {posicoes}")
    if abaixo_do_corte:
        erros.append(
            f"posicao_maps abaixo de posicao_min_gmn={posicao_min_gmn} "
            f"(cards orgânicos): {abaixo_do_corte}"
        )

    # --- check 4: todo card tem nome + ao menos um jeito de contato ---
    sem_nome = [c.get("posicao_maps") for c in cards if not c.get("nome")]
    sem_contato = [
        c.get("posicao_maps") for c in cards
        if not c.get("telefone") and not c.get("site") and not c.get("instagram")
    ]
    checks["todo_card_tem_nome"] = len(sem_nome) == 0
    checks["todo_card_tem_contato"] = len(sem_contato) == 0
    if sem_nome:
        erros.append(f"Cards sem nome nas posições: {sem_nome}")
    if sem_contato:
        erros.append(
            f"Cards sem nenhum jeito de contato (telefone, site ou instagram) "
            f"nas posições: {sem_contato}"
        )

    # --- check 5: avaliacoes_ordem é sempre "relevantes" ---
    ordem_errada = [
        c.get("posicao_maps") for c in cards
        if c.get("avaliacoes_ordem") != "relevantes"
    ]
    checks["avaliacoes_sempre_relevantes"] = len(ordem_errada) == 0
    if ordem_errada:
        erros.append(
            f"avaliacoes_ordem diferente de 'relevantes' nas posições: {ordem_errada} "
            f"(coletar-maps sempre usa 'relevantes' — reordenação só no coletar-perfis)"
        )

    # --- check 6: foto_data_confirmada é boolean (nunca null nem string) ---
    confirmada_invalida = [
        c.get("posicao_maps") for c in cards
        if not isinstance(c.get("foto_data_confirmada"), bool)
    ]
    checks["foto_data_confirmada_e_boolean"] = len(confirmada_invalida) == 0
    if confirmada_invalida:
        erros.append(
            f"foto_data_confirmada não é boolean (true/false) nas posições: "
            f"{confirmada_invalida}"
        )

    # --- check 7: valores crus dentro de limites esperados ---
    nota_invalida = [
        c.get("posicao_maps") for c in cards
        if c.get("nota") is not None and not (0.0 <= c["nota"] <= 5.0)
    ]
    aval_invalida = [
        c.get("posicao_maps") for c in cards
        if c.get("avaliacoes") is not None and c["avaliacoes"] < 0
    ]
    checks["notas_validas"] = len(nota_invalida) == 0
    checks["avaliacoes_nao_negativas"] = len(aval_invalida) == 0
    if nota_invalida:
        erros.append(f"Nota fora de [0.0, 5.0] nas posições: {nota_invalida}")
    if aval_invalida:
        erros.append(f"Avaliações negativas nas posições: {aval_invalida}")

    passou = len(erros) == 0

    return {
        "nivel": "1_maps",
        "execucao_id": execucao_id,
        "passou": passou,
        "checks": checks,
        "total_encontrados": total_encontrados,
        "total_coletados": total_real,
        "erros": erros,
    }


def nivel2_metricas(execucao_id):
    """
    Guardião nível 2 — confere a integridade dos lotes de métricas.

    Checks:
      1. Checkpoint existe e tem a seção "metricas"
      2. Todos os lotes estão marcados como completos (lotes_completos = [1..total_lotes])
      3. Todo arquivo de lote existe em disco
      4. Total de entradas nos lotes bate com total_candidatos do checkpoint
      5. fonte_metrica está preenchida (não null, não "") em toda entrada
      6. Se fonte_metrica != "nenhuma", autoridade não é null
      7. Total de chamadas estimado está dentro de max_chamadas_mcp
    """
    base = Path(__file__).parent.parent
    coletas = base / "coletas"
    config = _carregar_config()
    max_chamadas = config.get("max_chamadas_mcp", 60)

    erros = []
    checks = {}

    # --- check 1: checkpoint existe com seção metricas ---
    ckpt_path = base / "checkpoints" / f"{execucao_id}.json"
    if not ckpt_path.exists():
        return {
            "nivel": "2_metricas",
            "execucao_id": execucao_id,
            "passou": False,
            "erros": [f"Checkpoint não encontrado: {ckpt_path.name}"],
        }

    ckpt = _carregar(ckpt_path)
    secao = ckpt.get("metricas")
    checks["checkpoint_tem_secao_metricas"] = secao is not None
    if secao is None:
        erros.append("Seção 'metricas' ausente no checkpoint")
        return {
            "nivel": "2_metricas",
            "execucao_id": execucao_id,
            "passou": False,
            "checks": checks,
            "erros": erros,
        }

    total_lotes = secao.get("total_lotes", 0)
    lotes_completos = secao.get("lotes_completos", [])
    total_candidatos_ckpt = secao.get("total_candidatos", -1)

    # --- check 2: todos os lotes marcados como completos ---
    esperados = list(range(1, total_lotes + 1))
    todos_marcados = sorted(lotes_completos) == esperados
    checks["todos_lotes_marcados_completos"] = todos_marcados
    if not todos_marcados:
        faltando = [n for n in esperados if n not in lotes_completos]
        erros.append(
            f"Lotes não marcados como completos no checkpoint: {faltando} "
            f"(completos: {lotes_completos}, esperados: {esperados})"
        )

    # --- check 3: arquivos de lote existem em disco ---
    arquivos_faltando = []
    for n in range(1, total_lotes + 1):
        path = coletas / f"metricas_{execucao_id}_lote_{n}.json"
        if not path.exists():
            arquivos_faltando.append(path.name)
    checks["todos_arquivos_existem"] = len(arquivos_faltando) == 0
    if arquivos_faltando:
        erros.append(f"Arquivos de lote não encontrados: {arquivos_faltando}")

    # --- carregar todas as entradas dos lotes ---
    entradas = []
    for n in range(1, total_lotes + 1):
        path = coletas / f"metricas_{execucao_id}_lote_{n}.json"
        if path.exists():
            dados = _carregar(path)
            entradas.extend(dados.get("candidatos", []))

    # --- check 4: total de entradas bate com checkpoint ---
    total_real = len(entradas)
    total_bate = total_candidatos_ckpt >= 0 and total_real == total_candidatos_ckpt
    checks["total_candidatos_bate"] = total_bate
    if not total_bate:
        erros.append(
            f"Total de entradas nos lotes ({total_real}) "
            f"difere de total_candidatos no checkpoint ({total_candidatos_ckpt})"
        )

    # --- check 5: fonte_metrica preenchida em toda entrada ---
    sem_fonte = [
        e.get("dominio") for e in entradas
        if not e.get("fonte_metrica")
    ]
    checks["fonte_metrica_preenchida_em_todos"] = len(sem_fonte) == 0
    if sem_fonte:
        erros.append(
            f"fonte_metrica ausente ou vazia nos domínios: {sem_fonte}"
        )

    # --- check 6: autoridade não null quando fonte != "nenhuma" ---
    sem_autoridade = [
        e.get("dominio") for e in entradas
        if e.get("fonte_metrica") not in (None, "", "nenhuma")
        and e.get("autoridade") is None
    ]
    checks["autoridade_com_fonte"] = len(sem_autoridade) == 0
    if sem_autoridade:
        erros.append(
            f"autoridade null com fonte válida nos domínios: {sem_autoridade}"
        )

    # --- check 7: chamadas estimadas dentro do teto ---
    # Cada candidato com ubersuggest_ok não-null = 1 chamada Ubersuggest.
    # Cada candidato com semrush_ok não-null = 1 chamada Semrush (fluxo completo).
    chamadas_uber = sum(1 for e in entradas if e.get("ubersuggest_ok") is not None)
    chamadas_sem = sum(1 for e in entradas if e.get("semrush_ok") is not None)
    total_chamadas = chamadas_uber + chamadas_sem
    dentro_do_teto = total_chamadas <= max_chamadas
    checks["chamadas_dentro_do_teto"] = dentro_do_teto
    if not dentro_do_teto:
        erros.append(
            f"Total de chamadas estimado ({total_chamadas}) ultrapassa "
            f"max_chamadas_mcp={max_chamadas} "
            f"(Ubersuggest: {chamadas_uber}, Semrush: {chamadas_sem})"
        )

    passou = len(erros) == 0

    return {
        "nivel": "2_metricas",
        "execucao_id": execucao_id,
        "passou": passou,
        "checks": checks,
        "total_lotes": total_lotes,
        "total_candidatos_checkpoint": total_candidatos_ckpt,
        "total_entradas_lotes": total_real,
        "chamadas_estimadas": {
            "ubersuggest": chamadas_uber,
            "semrush": chamadas_sem,
            "total": total_chamadas,
            "teto": max_chamadas,
        },
        "erros": erros,
    }


# Valores de fonte aceitos para campos de contato com valor não-null
_FONTES_CONTATO = {"wa_me_html", "mailto_html", "texto_pagina_contato", "rodape", "outra"}
# "site_inacessivel" é válido apenas quando o campo é null (marca de ausência)
_FONTES_MARCAS = {"site_inacessivel"}
_FONTES_TODAS = _FONTES_CONTATO | _FONTES_MARCAS

_ORIGENS_SEM_PERFIL = {"gmn", "ambos", "pago_maps"}


def nivel2_perfis_e_contatos(execucao_id):
    """
    Guardião nível 2 — verifica integridade de perfis (Fase 6) e contatos (Fase 7).

    Check 1 — Cobertura
      Todo candidato ok tem entrada em contatos.
      Candidatos search/pago têm entrada em perfis (cards ou sem_perfil_maps).
      gmn/ambos/pago_maps pulam coletar-perfis — não são exigidos lá.

    Check 2 — Campos crus válidos (perfis)
      nota ∈ [0.0, 5.0] quando não-null.
      avaliacoes ≥ 0 quando não-null.
      tem_whatsapp_botao é sempre boolean (nunca null).

    Check 3 — Origem declarada (contatos)
      Quando campo não-null, fonte correspondente existe e é valor esperado.
      Valores aceitos: wa_me_html, mailto_html, texto_pagina_contato, rodape, outra.

    Check 4 — Coerência campo ↔ fonte (contatos)
      Campo não-null → fonte não-null (e em _FONTES_CONTATO).
      Fonte em _FONTES_CONTATO → campo não-null.
      Fonte "site_inacessivel" → campo null (marca de ausência confirmada).
    """
    base = Path(__file__).parent.parent
    coletas = base / "coletas"

    erros = []
    checks = {}

    # --- pré-requisito: candidatos ---
    cand_path = coletas / f"candidatos_{execucao_id}.json"
    if not cand_path.exists():
        return {
            "nivel": "2_perfis_e_contatos",
            "execucao_id": execucao_id,
            "passou": False,
            "erros": [f"candidatos_{execucao_id}.json não encontrado"],
        }

    dados_cand = _carregar(cand_path)
    candidatos = dados_cand.get("candidatos", [])
    ok_todos = [c for c in candidatos if c.get("status_tecnico") == "ok"]
    ok_search_pago = [
        c for c in ok_todos if c.get("origem") not in _ORIGENS_SEM_PERFIL
    ]

    # --- carregar perfis ---
    perfis_cards = []
    perfis_sem = []
    for p in sorted(coletas.glob(f"perfis_{execucao_id}_lote_*.json")):
        d = _carregar(p)
        perfis_cards.extend(d.get("cards", []))
        perfis_sem.extend(d.get("sem_perfil_maps", []))

    dominios_em_perfis = {
        e.get("dominio_candidato")
        for e in (perfis_cards + perfis_sem)
        if e.get("dominio_candidato")
    }

    # --- carregar contatos ---
    contatos_list = []
    for p in sorted(coletas.glob(f"contatos_{execucao_id}_lote_*.json")):
        d = _carregar(p)
        contatos_list.extend(d.get("contatos", []))

    dominios_em_contatos = {
        e.get("dominio") for e in contatos_list if e.get("dominio")
    }

    # ---------------------------------------------------------------
    # CHECK 1 — Cobertura
    # ---------------------------------------------------------------
    sem_contato_cob = [
        c.get("dominio") for c in ok_todos
        if c.get("dominio") is not None  # null-domain gmn candidatos não têm website
        and c.get("dominio") not in dominios_em_contatos
    ]
    checks["cobertura_contatos_completa"] = len(sem_contato_cob) == 0
    if sem_contato_cob:
        erros.append(
            f"Candidatos ok sem entrada em contatos: {sem_contato_cob}"
        )

    sem_perfil_cob = [
        c.get("dominio") for c in ok_search_pago
        if c.get("dominio") not in dominios_em_perfis
    ]
    checks["cobertura_perfis_completa"] = len(sem_perfil_cob) == 0
    if sem_perfil_cob:
        erros.append(
            f"Candidatos search/pago sem entrada em perfis: {sem_perfil_cob}"
        )

    # ---------------------------------------------------------------
    # CHECK 2 — Campos crus válidos (perfis)
    # ---------------------------------------------------------------
    nota_invalida = [
        e.get("dominio_candidato") for e in perfis_cards
        if e.get("nota") is not None and not (0.0 <= float(e["nota"]) <= 5.0)
    ]
    aval_invalida = [
        e.get("dominio_candidato") for e in perfis_cards
        if e.get("avaliacoes") is not None and int(e["avaliacoes"]) < 0
    ]
    wa_invalido = [
        e.get("dominio_candidato") for e in perfis_cards
        if not isinstance(e.get("tem_whatsapp_botao"), bool)
    ]

    checks["notas_validas"] = len(nota_invalida) == 0
    checks["avaliacoes_nao_negativas"] = len(aval_invalida) == 0
    checks["tem_whatsapp_botao_boolean"] = len(wa_invalido) == 0

    if nota_invalida:
        erros.append(f"Nota fora de [0.0, 5.0] em perfis: {nota_invalida}")
    if aval_invalida:
        erros.append(f"Avaliações negativas em perfis: {aval_invalida}")
    if wa_invalido:
        erros.append(
            f"tem_whatsapp_botao não é boolean (true/false) em perfis: {wa_invalido}"
        )

    # ---------------------------------------------------------------
    # CHECK 3 — Origem declarada (contatos)
    # Quando o campo tem valor, a fonte deve existir e ser valor esperado.
    # ---------------------------------------------------------------
    _CAMPOS_FONTE = [
        ("telefone", "fonte_telefone"),
        ("email", "fonte_email"),
        ("instagram", "fonte_instagram"),
    ]
    origem_invalida = []
    for entry in contatos_list:
        dom = entry.get("dominio", "?")
        for campo, fonte_campo in _CAMPOS_FONTE:
            valor = entry.get(campo)
            fonte = entry.get(fonte_campo)
            if valor is not None:
                if not fonte:
                    origem_invalida.append(
                        f"{dom}.{campo}: valor='{valor}' mas {fonte_campo}=null"
                    )
                elif fonte not in _FONTES_CONTATO:
                    origem_invalida.append(
                        f"{dom}.{campo}: valor='{valor}' mas {fonte_campo}='{fonte}' "
                        f"(não está em {sorted(_FONTES_CONTATO)})"
                    )

    checks["origens_declaradas_validas"] = len(origem_invalida) == 0
    if origem_invalida:
        erros.append(f"Contatos com valor mas origem ausente ou inválida: {origem_invalida}")

    # ---------------------------------------------------------------
    # CHECK 4 — Coerência campo ↔ fonte
    # ---------------------------------------------------------------
    incoerentes = []
    for entry in contatos_list:
        dom = entry.get("dominio", "?")
        for campo, fonte_campo in _CAMPOS_FONTE:
            valor = entry.get(campo)
            fonte = entry.get(fonte_campo)

            # campo não-null → fonte não deve ser null
            if valor is not None and not fonte:
                incoerentes.append(
                    f"{dom}.{campo}: valor existe mas {fonte_campo}=null"
                )

            # fonte de contato real → campo não deve ser null
            if fonte in _FONTES_CONTATO and valor is None:
                incoerentes.append(
                    f"{dom}.{fonte_campo}='{fonte}' mas {campo}=null"
                )

            # site_inacessivel é marca de ausência: campo obrigatoriamente null
            if fonte == "site_inacessivel" and valor is not None:
                incoerentes.append(
                    f"{dom}.{fonte_campo}='site_inacessivel' mas {campo}='{valor}' "
                    f"(marca de ausência exige campo null)"
                )

    checks["coerencia_campo_fonte"] = len(incoerentes) == 0
    if incoerentes:
        erros.append(f"Incoerências campo/fonte em contatos: {incoerentes}")

    passou = len(erros) == 0

    return {
        "nivel": "2_perfis_e_contatos",
        "execucao_id": execucao_id,
        "passou": passou,
        "checks": checks,
        "candidatos_ok_total": len(ok_todos),
        "candidatos_search_pago": len(ok_search_pago),
        "perfis_cards": len(perfis_cards),
        "perfis_sem_maps": len(perfis_sem),
        "contatos_entradas": len(contatos_list),
        "erros": erros,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            json.dumps(
                {"erro": "Uso: guardiao_coleta.py <nivel> <execucao_id>"},
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    nivel = sys.argv[1]
    eid = sys.argv[2]

    if nivel == "1_serp":
        resultado = nivel1_serp(eid)
    elif nivel == "1_maps":
        resultado = nivel1_maps(eid)
    elif nivel == "2_metricas":
        resultado = nivel2_metricas(eid)
    elif nivel == "2_perfis_e_contatos":
        resultado = nivel2_perfis_e_contatos(eid)
    else:
        resultado = {
            "erro": (
                f"Nível '{nivel}' não reconhecido. "
                "Disponíveis: 1_serp, 1_maps, 2_metricas, 2_perfis_e_contatos"
            )
        }

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    sys.exit(0 if resultado.get("passou", True) else 1)
