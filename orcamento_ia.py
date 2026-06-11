"""
Módulo de Orçamento / Metas com IA — Empresa Exemplo
===============================================
Usa o Claude API para analisar o histórico do DRE (Conta Azul / BigQuery)
e gerar metas mensais para cada linha do DRE do ano solicitado.
O orçamento é armazenado em BigQuery (ca_orcamentos.budget_lines)
e pode ser editado manualmente pelo usuário na tela de Orçamentos.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache

import anthropic
import pandas as pd
from google.cloud import bigquery

from dre_queries import DRE_LINES, SALDOS_INICIAIS, _CONSOLIDADO_DATASETS, get_dre, get_dre_categorias

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------

PROJECT         = os.environ.get("BQ_PROJECT", "meu-projeto-gcp")
DATASET         = "ca_orcamentos"
TABLE           = "budget_lines"
FULL_TABLE      = f"{PROJECT}.{DATASET}.{TABLE}"

MONTH_LABELS    = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                   "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

# Linhas que a IA deve gerar (não-fórmula, exceto L19 Saldo Final que é cumulativo)
_LINHAS_IA = [l for l in DRE_LINES if not l.get("is_formula") and l["id"] != 19]


# ---------------------------------------------------------------------------
# BigQuery helpers
# ---------------------------------------------------------------------------

def _get_bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT, location="us-central1")


# Shape dos valores:
#   valores_nested: {linha_dre: {categoria_id_str: {mes(1-12): valor_float}}}
#   onde categoria_id="" representa "sem categoria / outros" (catch-all)


def _flatten_valores(valores_nested: dict) -> dict[int, dict[int, float]]:
    """Soma valores por categoria → {lid: {mes: total}} para cálculo de DRE."""
    flat: dict[int, dict[int, float]] = {}
    for lid, por_cat in (valores_nested or {}).items():
        lid_int = int(lid)
        flat.setdefault(lid_int, {})
        for cat_id, meses in (por_cat or {}).items():
            for mes, valor in (meses or {}).items():
                mes_int = int(mes)
                flat[lid_int][mes_int] = flat[lid_int].get(mes_int, 0.0) + float(valor or 0)
    return flat


def _read_existing_rows(client) -> pd.DataFrame:
    """Lê todos os registros de budget_lines sem usar to_dataframe() (evita dep de db-dtypes).
    Retorna DataFrame com categoria_id normalizado a "".
    Tenta schema novo (com categoria_id), cai pra schema antigo, e finalmente tabela vazia.
    Se a query falhar por motivo DIFERENTE de schema antigo, PROPAGA a exceção — nunca silencia.
    """
    def _iter_rows_safe(sql: str) -> list[dict]:
        """Executa query e retorna lista de dicts. Propaga falhas inesperadas."""
        rows = list(client.query(sql).result())
        return [dict(r.items()) for r in rows]

    sql_new = f"SELECT empresa, ano, mes, linha_dre, categoria_id, valor, fonte, updated_at FROM `{FULL_TABLE}`"
    sql_old = f"SELECT empresa, ano, mes, linha_dre, valor, fonte, updated_at FROM `{FULL_TABLE}`"

    try:
        data = _iter_rows_safe(sql_new)
    except Exception as e:
        # Só tolera erro "coluna categoria_id não existe" (schema antigo)
        msg = str(e)
        if "Unrecognized name: categoria_id" not in msg and "categoria_id" not in msg:
            # Outro erro — propaga pra não apagar dados
            raise
        # Fallback: schema antigo
        data = _iter_rows_safe(sql_old)
        for r in data:
            r["categoria_id"] = ""

    if not data:
        return pd.DataFrame(columns=["empresa", "ano", "mes", "linha_dre",
                                     "categoria_id", "valor", "fonte", "updated_at"])
    return pd.DataFrame(data)


def salvar_orcamento(ano: int, empresa: str, valores_nested: dict,
                     fonte: str = "manual") -> None:
    """
    Salva o orçamento per (linha, categoria, mês) no BigQuery.
    valores_nested: {linha_dre: {categoria_id: {mes(1-12): valor}}}
    categoria_id="" representa o catch-all (sem categoria).
    Usa load_table_from_dataframe (WRITE_TRUNCATE) para simplificar permissões
    e migrar schema automaticamente (adiciona categoria_id se ainda não existe).

    SEGURANÇA: se a leitura dos dados existentes falhar, ABORTA em vez de apagar tudo.
    """
    client = _get_bq_client()

    # Ler registros existentes — se falhar, propaga (não silencia)
    existing = _read_existing_rows(client)

    # Remover o ano/empresa atual (vamos reescrever)
    if not existing.empty:
        existing["categoria_id"] = existing["categoria_id"].fillna("")
        existing = existing[~((existing["empresa"] == empresa) & (existing["ano"] == ano))]

    # Construir novas linhas
    now = datetime.now(timezone.utc)
    rows = []
    for lid, por_cat in (valores_nested or {}).items():
        for cat_id, meses in (por_cat or {}).items():
            for mes, valor in (meses or {}).items():
                rows.append({
                    "empresa":      empresa,
                    "ano":          int(ano),
                    "mes":          int(mes),
                    "linha_dre":    int(lid),
                    "categoria_id": str(cat_id or ""),
                    "valor":        float(valor) if valor is not None else 0.0,
                    "fonte":        fonte,
                    "updated_at":   now,
                })

    new_df = pd.DataFrame(rows)

    final_df = pd.concat([existing, new_df], ignore_index=True)
    if final_df.empty:
        # evita erro do load_table ao salvar tabela vazia
        final_df = pd.DataFrame({
            "empresa": pd.Series(dtype="object"),
            "ano": pd.Series(dtype="int64"),
            "mes": pd.Series(dtype="int64"),
            "linha_dre": pd.Series(dtype="int64"),
            "categoria_id": pd.Series(dtype="object"),
            "valor": pd.Series(dtype="float64"),
            "fonte": pd.Series(dtype="object"),
            "updated_at": pd.Series(dtype="datetime64[ns, UTC]"),
        })
    else:
        final_df["ano"]          = final_df["ano"].astype("int64")
        final_df["mes"]          = final_df["mes"].astype("int64")
        final_df["linha_dre"]    = final_df["linha_dre"].astype("int64")
        final_df["categoria_id"] = final_df["categoria_id"].fillna("").astype("string")
        final_df["valor"]        = final_df["valor"].astype("float64")

    schema = [
        bigquery.SchemaField("empresa",      "STRING"),
        bigquery.SchemaField("ano",          "INT64"),
        bigquery.SchemaField("mes",          "INT64"),
        bigquery.SchemaField("linha_dre",    "INT64"),
        bigquery.SchemaField("categoria_id", "STRING"),
        bigquery.SchemaField("valor",        "FLOAT64"),
        bigquery.SchemaField("fonte",        "STRING"),
        bigquery.SchemaField("updated_at",   "TIMESTAMP"),
    ]
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_dataframe(final_df, FULL_TABLE, job_config=job_config).result()


def carregar_orcamento(ano: int, empresa: str):
    """
    Carrega o orçamento do BigQuery.
    Retorna tupla (valores_nested, df) ou (None, None) se não houver orçamento.

    valores_nested: {linha_dre: {categoria_id: {mes: valor}}}
    df: DataFrame agregado por linha (formato get_dre compatível)
    """
    client = _get_bq_client()

    # Tenta schema novo primeiro (com categoria_id)
    try:
        sql_new = f"""
            SELECT linha_dre, categoria_id, mes, valor
            FROM `{FULL_TABLE}`
            WHERE empresa = @empresa AND ano = @ano
            ORDER BY linha_dre, mes
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("empresa", "STRING", empresa),
                bigquery.ScalarQueryParameter("ano",     "INT64",  ano),
            ]
        )
        rows = list(client.query(sql_new, job_config=job_config).result())
        has_cat_column = True
    except Exception:
        # Fallback — schema antigo sem categoria_id
        sql_old = f"""
            SELECT linha_dre, mes, valor
            FROM `{FULL_TABLE}`
            WHERE empresa = @empresa AND ano = @ano
            ORDER BY linha_dre, mes
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("empresa", "STRING", empresa),
                bigquery.ScalarQueryParameter("ano",     "INT64",  ano),
            ]
        )
        rows = list(client.query(sql_old, job_config=job_config).result())
        has_cat_column = False

    if not rows:
        return None, None

    # Montar estrutura nested {lid: {cat_id: {mes: valor}}}
    nested: dict[int, dict[str, dict[int, float]]] = {}
    for row in rows:
        lid = int(row.linha_dre)
        mes = int(row.mes)
        cat_id = str(getattr(row, "categoria_id", "") or "") if has_cat_column else ""
        nested.setdefault(lid, {}).setdefault(cat_id, {})[mes] = float(row.valor or 0)

    # Flatten para gerar o DataFrame agregado
    flat = _flatten_valores(nested)
    df = _valores_para_df(flat, empresa, ano)
    return nested, df


def orcamento_existe(ano: int, empresa: str) -> bool:
    """Verifica se existe orçamento salvo para o ano/empresa."""
    client = _get_bq_client()
    sql = f"""
        SELECT COUNT(*) as cnt
        FROM `{FULL_TABLE}`
        WHERE empresa = @empresa AND ano = @ano
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("empresa", "STRING", empresa),
            bigquery.ScalarQueryParameter("ano",     "INT64",  ano),
        ]
    )
    result = list(client.query(sql, job_config=job_config).result())
    return result[0].cnt > 0


# ---------------------------------------------------------------------------
# Conversão de valores para DataFrame DRE
# ---------------------------------------------------------------------------

def _valores_para_df(valores: dict[int, dict[int, float]],
                     empresa: str = "", ano: int = 0) -> pd.DataFrame:
    """
    Converte dict {linha_dre: {mes(1-12): valor}} para um DataFrame
    no formato compatível com get_dre() (colunas Jan…Dez, TOTAL, etc.).
    Fórmulas (linhas totalizadoras) são recalculadas.
    """
    valores_completos = _aplicar_formulas(valores, empresa, ano)

    _despesa_lids = {l["id"] for l in DRE_LINES
                     if not l.get("is_formula") and l.get("sinal") == -1}

    records = []
    for line in DRE_LINES:
        lid = line["id"]
        meses = valores_completos.get(lid, {})
        row: dict = {
            "id":          lid,
            "label":       line["label"],
            "quadro":      line["quadro"],
            "totalizador": line.get("totalizador", False),
        }
        vals = [meses.get(m, 0.0) for m in range(1, 13)]
        # Despesas devem ser positivas no DataFrame (convenção do realizado)
        if lid in _despesa_lids:
            vals = [abs(v) for v in vals]
        for i, label in enumerate(MONTH_LABELS):
            row[label] = vals[i]
        row["TOTAL"] = sum(vals)

        # AV/AH ficam None (previsto não tem análise vertical/horizontal)
        for label in MONTH_LABELS:
            row[f"AV_{label}"]    = None
            row[f"AH_MoM_{label}"] = None
            row[f"AH_YoY_{label}"] = None
        row["AV_TOTAL"] = None
        row["AH_YTD"]   = None

        records.append(row)

    return pd.DataFrame(records)


def _aplicar_formulas(valores: dict[int, dict[int, float]],
                      empresa: str = "", ano: int = 0) -> dict[int, dict[int, float]]:
    """Recalcula linhas-fórmula do DRE a partir dos valores base."""
    import re

    result = {lid: dict(meses) for lid, meses in valores.items()}

    # Garantir que todas as linhas existam
    for line in DRE_LINES:
        if line["id"] not in result:
            result[line["id"]] = {m: 0.0 for m in range(1, 13)}

    # Normalizar linhas de despesa (sinal == -1) para positivo.
    # O usuário pode digitar -75.000 ou +75.000 para L2 Custos; a fórmula
    # "1 - 2" espera L2 positivo. Usamos abs() aqui para aceitar ambos.
    _despesa_lids = {l["id"] for l in DRE_LINES
                     if not l.get("is_formula") and l.get("sinal") == -1}
    for lid in _despesa_lids:
        if lid in result:
            result[lid] = {m: abs(v) for m, v in result[lid].items()}

    formula_lines = sorted(
        [l for l in DRE_LINES if l.get("is_formula")],
        key=lambda x: x["id"]
    )

    for line in formula_lines:
        lid = line["id"]
        if lid == 19:
            # L19 Saldo Final: cumulativo — saldo_ini + acumulado de (L16 + L17 - L18)
            if empresa == "consolidado":
                saldo_ini = sum(
                    SALDOS_INICIAIS.get(d, {}).get(ano, 0.0)
                    for d in _CONSOLIDADO_DATASETS
                )
            else:
                saldo_ini = SALDOS_INICIAIS.get(empresa, {}).get(ano, 0.0)
            acum = saldo_ini
            for mes in range(1, 13):
                geracao = (result.get(16, {}).get(mes, 0.0)
                           + result.get(17, {}).get(mes, 0.0)
                           - result.get(18, {}).get(mes, 0.0))
                acum += geracao
                result[lid][mes] = acum
            continue

        expr = line["formula"]
        tokens = re.split(r"(\s*[+\-]\s*)", expr)

        for mes in range(1, 13):
            parts = []
            for tok in tokens:
                tok_s = tok.strip()
                if tok_s in ("+", "-"):
                    parts.append(f" {tok_s} ")
                elif re.match(r"^\d+$", tok_s):
                    parts.append(str(result.get(int(tok_s), {}).get(mes, 0.0)))
                else:
                    parts.append(tok)
            result[lid][mes] = float(eval("".join(parts)))  # safe: gerado internamente

    return result


def df_para_valores(df: pd.DataFrame) -> dict[int, dict[int, float]]:
    """
    Converte um DataFrame DRE (com colunas Jan…Dez) de volta para
    dict {linha_dre: {mes(1-12): valor}} — usado ao salvar edições da tabela.
    """
    valores: dict[int, dict[int, float]] = {}
    for _, row in df.iterrows():
        lid = int(row["id"])
        if not DRE_LINES[lid - 1].get("is_formula", False):
            valores[lid] = {
                i + 1: float(row.get(label, 0) or 0)
                for i, label in enumerate(MONTH_LABELS)
            }
    return valores


# ---------------------------------------------------------------------------
# Geração de Orçamento com IA (Claude API)
# ---------------------------------------------------------------------------

def _formatar_historico(empresa: str, ano_meta: int) -> str:
    """Busca DRE histórico e formata como texto estruturado para o prompt."""
    anos_hist = [ano_meta - 3, ano_meta - 2, ano_meta - 1]
    linhas_nao_formula = [l for l in DRE_LINES if not l.get("is_formula")]

    blocos = []
    for ano in anos_hist:
        try:
            df = get_dre(ano, empresa)
        except Exception:
            continue

        blocos.append(f"\n## Ano {ano}")
        for line in linhas_nao_formula:
            lid = line["id"]
            row = df[df["id"] == lid]
            if row.empty:
                continue
            vals = [row[m].values[0] or 0 for m in MONTH_LABELS]
            total = sum(vals)
            if total == 0:
                continue
            vals_str = ", ".join(f"{v:,.0f}" for v in vals)
            blocos.append(f"  L{lid} {line['label']}: [{vals_str}] | Total={total:,.0f}")

    return "\n".join(blocos)


def _normalizar_label(s: str) -> str:
    """Normaliza label para deduplicação: remove acentos, espaços extras, lowercase,
    'e/and' equivalente, e tenta colapsar singular/plural.
    'Marketing e Publicidade' == 'marketing & publicidade' == 'Marketing  E  Publicidade'.
    'Software' == 'Softwares', 'Material' == 'Materiais', 'Obra' == 'Obras'.
    """
    import unicodedata
    s = str(s or "").strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    s = s.replace("&", "e")
    s = re.sub(r"[\s\-_/]+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    # Singular/plural simples (palavra a palavra): remove "s"/"es"/"is" final
    words = []
    for w in s.split():
        if len(w) > 3:
            if w.endswith("oes"):    w = w[:-3] + "ao"
            elif w.endswith("ais"):  w = w[:-2] + "l"
            elif w.endswith("eis"):  w = w[:-2] + "l"
            elif w.endswith("res"):  w = w[:-2]
            elif w.endswith("es") and not w.endswith("oes"): w = w[:-2]
            elif w.endswith("s") and len(w) > 4: w = w[:-1]
        words.append(w)
    return " ".join(words).strip()


@lru_cache(maxsize=32)
def _categorias_ativas_por_linha(empresa: str, ano_ref: int) -> dict[int, list[dict]]:
    """
    Retorna as categorias com movimentação histórica para cada linha.
    Usa o ano anterior como referência.
    Retorno: {lid: [{"cat_id", "label", "hist_ano": {mes: valor}}, ...]}
    Ordenado por magnitude do total histórico (mais relevante primeiro).
    Cacheado pois é chamado a cada rebuild da tabela de orçamento (que dispara em cada edição).

    Para `consolidado`, deduplica categorias por label normalizado (ex: "Marketing e
    Publicidade" das 3 subsidiárias vira 1 só, somando os totais).
    """
    result: dict[int, list[dict]] = {}
    try:
        cats_prev = get_dre_categorias(ano_ref, empresa)
    except Exception:
        return result

    for lid_str, cat_list in cats_prev.items():
        lid = int(lid_str)
        # Dedup por label normalizado: somar hist mensal e total
        agrupado: dict[str, dict] = {}
        for c in cat_list:
            total = sum(abs(c.get(f"{m}_real", 0) or 0) for m in MONTH_LABELS)
            if total < 0.01:
                continue
            hist = {m + 1: float(c.get(f"{MONTH_LABELS[m]}_real", 0) or 0)
                    for m in range(12)}
            label = c.get("label", c.get("cat_id", "—"))
            key = _normalizar_label(label)
            if key in agrupado:
                # Soma hist mensal + total; mantém cat_id do que tem maior total
                ag = agrupado[key]
                for m, v in hist.items():
                    ag["hist"][m] = ag["hist"].get(m, 0.0) + v
                ag["total"] += sum(hist.values())
                if sum(hist.values()) > ag.get("_max_total", 0):
                    ag["cat_id"] = c.get("cat_id", ag["cat_id"])
                    ag["_max_total"] = sum(hist.values())
            else:
                agrupado[key] = {
                    "cat_id": c.get("cat_id", ""),
                    "label":  label,
                    "hist":   hist,
                    "total":  sum(hist.values()),
                    "_max_total": sum(hist.values()),
                }

        clean = list(agrupado.values())
        for c in clean:
            c.pop("_max_total", None)
        clean.sort(key=lambda x: -abs(x["total"]))
        if clean:
            result[lid] = clean
    return result


def gerar_orcamento_ia(ano: int, empresa: str, contexto_usuario: str = "") -> dict:
    """
    Gera orçamento por subitem (categoria) usando Claude API.
    Retorna: {linha_dre: {categoria_id: {mes(1-12): valor}}}
    categoria_id="" representa 'sem categoria / outros'.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("Variável ANTHROPIC_API_KEY não configurada.")

    historico_geral = _formatar_historico(empresa, ano)
    categorias_por_linha = _categorias_ativas_por_linha(empresa, ano - 1)

    empresa_label = {
        "ca_empresa_a":  "Empresa A",
        "ca_empresa_b":      "Empresa B",
        "ca_empresa_c":     "Empresa C",
        "consolidado": "Consolidado Empresa Exemplo",
    }.get(empresa, empresa)

    # Descritivo das linhas + suas categorias com histórico
    linhas_blocks = []
    cat_label_map: dict[str, str] = {}  # para validar depois
    for line in _LINHAS_IA:
        lid = line["id"]
        cats = categorias_por_linha.get(lid, [])
        if cats:
            # Linha com categorias — IA deve orçar por categoria
            cat_lines = []
            for c in cats[:20]:  # top 20 por magnitude (controle de tokens)
                cid = c["cat_id"]
                cat_label_map[cid] = c["label"]
                hist_vals = ", ".join(f"{c['hist'][m]:,.0f}" for m in range(1, 13))
                cat_lines.append(f"    - cat_id=\"{cid}\" ({c['label']}): [{hist_vals}]")
            linhas_blocks.append(
                f"L{lid} {line['label']} — categorias ({len(cats)} itens):\n"
                + "\n".join(cat_lines)
            )
        else:
            # Linha sem categorias históricas — usar cat_id=""
            linhas_blocks.append(
                f"L{lid} {line['label']} — sem categorias históricas. "
                f"Use cat_id=\"\" para orçar no total da linha."
            )
    linhas_desc = "\n\n".join(linhas_blocks)

    contexto_adicional = ""
    if contexto_usuario.strip():
        contexto_adicional = f"\nContexto adicional do usuário: {contexto_usuario.strip()}"

    prompt = f"""Você é um analista financeiro especialista em planejamento orçamentário \
do setor de eventos. Gere o orçamento detalhado POR SUBITEM (categoria) do ano {ano} para \
a empresa **{empresa_label}**.

## Histórico do DRE (últimos 3 anos) — linhas agregadas
{historico_geral}

---

## Categorias ativas por linha (histórico do ano {ano - 1})
Cada categoria abaixo é um subitem de sua linha. Os 12 valores entre colchetes são \
[Jan, Fev, ..., Dez] do ano {ano - 1}.

{linhas_desc}

---

## Instruções
- Gere o orçamento mensal de CADA categoria listada acima para o ano {ano}.
- Considere: crescimento/tendência entre anos, sazonalidade (setor de eventos tem picos \
concentrados em Set-Dez), contexto específico.
- **TODOS os valores devem ser POSITIVOS** (incluindo despesas, custos e impostos). \
O sistema aplica automaticamente o sinal correto nas fórmulas do DRE — você só fornece o valor absoluto.
- Para linhas sem categorias, use cat_id="" (valor único agregado da linha).
- Seja conservador mas realista.{contexto_adicional}

## Formato de saída (APENAS JSON, sem texto ou markdown):
{{
  "<linha_id>": {{
    "<categoria_id>": [jan, fev, mar, abr, mai, jun, jul, ago, set, out, nov, dez],
    "<outro_categoria_id>": [12 valores],
    ...
  }},
  ...
}}

Exemplo (abstrato — note que despesas também são positivas):
{{
  "1": {{
    "cat-uuid-aaa": [100000, 120000, 95000, 80000, 90000, 110000, 150000, 180000, 220000, 210000, 180000, 160000],
    "cat-uuid-bbb": [20000, 20000, 20000, 20000, 25000, 25000, 25000, 30000, 30000, 30000, 30000, 30000]
  }},
  "14": {{
    "": [5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000]
  }}
}}
"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if "```" in raw:
        import re as _re
        match = _re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        if match:
            raw = match.group(1).strip()

    parsed = json.loads(raw)

    # Normalizar: chaves de linha para int, valores [12 floats] para dict {mes: valor}
    result: dict[int, dict[str, dict[int, float]]] = {}
    for lid_str, categorias in parsed.items():
        lid = int(str(lid_str).lstrip("Ll"))
        result[lid] = {}
        if not isinstance(categorias, dict):
            continue
        for cat_id, vals in categorias.items():
            cat_id_str = str(cat_id or "")
            if isinstance(vals, list) and len(vals) == 12:
                result[lid][cat_id_str] = {i + 1: float(v or 0) for i, v in enumerate(vals)}
            elif isinstance(vals, dict):
                # Caso a IA devolva no formato {mes: valor}
                result[lid][cat_id_str] = {int(m): float(v or 0) for m, v in vals.items()}

    # Despesas devem ser sempre positivas no storage (defensive: se a IA retornar negativos,
    # aplicamos abs para manter consistência com edição manual via _coletar_inputs_para_nested)
    _despesa_lids = {l["id"] for l in DRE_LINES
                     if not l.get("is_formula") and l.get("sinal") == -1}
    for lid, cats in result.items():
        if lid in _despesa_lids:
            for cat_id in list(cats.keys()):
                cats[cat_id] = {m: abs(v) for m, v in cats[cat_id].items()}

    return result


# ---------------------------------------------------------------------------
# Narrativa Automática do DRE (Claude API)
# ---------------------------------------------------------------------------

def gerar_narrativa_dre(ano: int, empresa: str, metricas: dict) -> str:
    """
    Gera uma narrativa executiva em PT-BR sobre os resultados financeiros.

    metricas esperado:
      rb, lucro_bruto, lucro_op, lucro_liq,
      margem_bruta, margem_op, margem_liq,
      rb_ytd, op_ytd, liq_ytd, saldo_caixa
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "⚠️ ANTHROPIC_API_KEY não configurada."

    empresa_label = {
        "ca_empresa_a":  "Empresa A",
        "ca_empresa_b":      "Empresa B",
        "ca_empresa_c":     "Empresa C",
        "consolidado": "Consolidado Empresa Exemplo",
    }.get(empresa, empresa)

    def _fmt(v):
        if v is None:
            return "n/d"
        av = abs(v)
        if av >= 1e6:
            return f"R$ {v/1e6:.1f}M"
        if av >= 1e3:
            return f"R$ {v/1e3:.0f}K"
        return f"R$ {v:.0f}"

    def _pct(v):
        return f"{v:+.1f}%" if v is not None else "n/d"

    rb           = metricas.get("rb", 0)
    lucro_bruto  = metricas.get("lucro_bruto", 0)
    lucro_op     = metricas.get("lucro_op", 0)
    lucro_liq    = metricas.get("lucro_liq", 0)
    margem_bruta = metricas.get("margem_bruta", 0)
    margem_op    = metricas.get("margem_op", 0)
    margem_liq   = metricas.get("margem_liq", 0)
    rb_ytd       = metricas.get("rb_ytd")
    op_ytd       = metricas.get("op_ytd")
    liq_ytd      = metricas.get("liq_ytd")
    saldo        = metricas.get("saldo_caixa", 0)
    n_meses      = metricas.get("meses_ytd", 12)
    periodo      = metricas.get("periodo", str(ano))
    ano_ant      = ano - 1

    comparativo = (
        f"{periodo}/{ano} vs {periodo}/{ano_ant} ({n_meses} meses)"
        if n_meses < 12
        else f"ano completo {ano}"
    )

    prompt = f"""Você é um analista financeiro CFO-level especialista em empresas do setor de eventos e feiras.
Escreva uma narrativa executiva CONCISA em português (máximo 4 frases curtas) sobre os resultados abaixo.

Empresa: {empresa_label}
Período: {comparativo}

CONTEXTO IMPORTANTE:
- Esta é uma empresa do setor de EVENTOS, com receitas altamente sazonais
- Os maiores eventos e feiras concentram-se no 2º semestre (principalmente Set–Dez)
- O início do ano (Jan–Abr) tem naturalmente baixa receita — isso é esperado e normal
- Comparações devem ser SEMPRE período a período (mesmo meses do ano anterior), nunca ano completo vs parcial

RESULTADOS ({periodo}/{ano}):
Receita Bruta: {_fmt(rb)} ({_pct(rb_ytd)} vs {periodo}/{ano_ant})
Lucro Bruto: {_fmt(lucro_bruto)} | Margem Bruta: {margem_bruta:.1f}%
Lucro Operacional: {_fmt(lucro_op)} | Margem Operacional: {margem_op:.1f}%
Lucro Líquido: {_fmt(lucro_liq)} | Margem Líquida: {margem_liq:.1f}%
Saldo de Caixa atual: {_fmt(saldo)}
Crescimento vs mesmo período {ano_ant} — Operacional: {_pct(op_ytd)} | Líquido: {_pct(liq_ytd)}

Diretrizes:
- Máximo 4 frases objetivas
- Se os primeiros meses do ano têm receita baixa, explique que é sazonalidade esperada
- Compare sempre o mesmo período do ano anterior, não o ano inteiro
- Destaque o que está bem E o que merece atenção executiva
- Varie o início das frases (não comece todas com "A empresa")
- Responda APENAS com o texto da narrativa, sem markdown ou listas"""

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ---------------------------------------------------------------------------
# Chat com os Dados (Claude API)
# ---------------------------------------------------------------------------

def chat_com_dados(
    mensagens: list[dict],
    contexto_dre: str,
    empresa_label: str,
    ano: int,
) -> str:
    """
    Chat conversacional com os dados do DRE.
    mensagens: lista de {"role": "user"|"assistant", "content": "..."}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "⚠️ ANTHROPIC_API_KEY não configurada."

    system = f"""Você é um assistente financeiro especialista nos resultados da {empresa_label} ({ano}).
Responda perguntas baseando-se exclusivamente nos dados do DRE abaixo.
Use valores em R$ com formatação legível (ex: R$ 1,2M ou R$ 850K).
Seja objetivo e prático — o usuário é um gestor financeiro tomando decisões.
Se a pergunta não puder ser respondida com os dados disponíveis, diga claramente.

=== DRE {ano} — {empresa_label} ===
{contexto_dre}
====================================="""

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=system,
        messages=mensagens[-20:],  # limite de contexto conversacional
    )
    return msg.content[0].text.strip()


# ---------------------------------------------------------------------------
# Chat com BigQuery — acesso direto via tool use (Claude gera SQL)
# ---------------------------------------------------------------------------

_BQ_SCHEMA_DOC = """
=== BigQuery Empresa Exemplo — projeto: meu-projeto-gcp ===

DATASETS:  ca_empresa_a (Empresa A) | ca_empresa_b (Empresa B) | ca_empresa_c (Empresa C)
Para consolidado: consulte os 3 e use UNION ALL.

TABELAS (mesma estrutura em cada dataset):

financeiro_parcelas_receitas  — parcelas de receita
  _pk                  STRING   chave primária
  _erathos_deleted_at  TIMESTAMP  NULL=ativo, NOT NULL=deletado (SEMPRE filtrar IS NULL)
  data_vencimento      DATE     data de vencimento prevista
  baixas               JSON ARRAY  pagamentos realizados
    cada elemento: { "data_pagamento":"YYYY-MM-DD", "valor_composicao":{"valor_liquido":float} }
  evento__rateio       JSON ARRAY  rateio por categoria
    cada elemento: { "id_categoria":"uuid", "valor":float }

financeiro_parcelas_despesas  — mesma estrutura acima

categorias
  id           STRING  UUID (referenciado por evento__rateio.id_categoria)
  nome         STRING  nome da categoria (ex: "Remuneração Funcionários")
  entrada_dre  STRING  código de mapeamento no DRE

=== entrada_dre → Linha DRE ===
RECEITA_VENDA_PRODUTOS_SERVICOS  → L1 Receita Bruta
CUSTO_VENDAS_PRODUTOS            → L2 Custos Operacionais
CUSTO_SERVICOS_PRESTADOS         → L2 Custos Operacionais
IMPOSTOS_SOBRE_VENDAS            → L4 Impostos
DESPESAS_OPERACIONAIS_NIVEL_2    → L6 Despesas Operacionais (equipe/folha)
DESPESAS_ADMINISTRATIVAS         → L8 Despesas Holding (overhead)
OUTRAS_RECEITAS_NAO_OPERACIONAIS → L17 Entradas Não Operacionais
OUTRAS_DESPESAS_NAO_OPERACIONAIS → L18 Saídas Não Operacionais

=== Padrões de Query ===

# Realizado — pagamentos efetivos (usar baixas):
SELECT
  FORMAT_DATE('%Y-%m', DATE(JSON_VALUE(b, '$.data_pagamento'))) AS mes,
  c.nome AS categoria,
  c.entrada_dre,
  SUM(
    CAST(JSON_VALUE(r, '$.valor') AS FLOAT64)
    * SAFE_DIVIDE(
        CAST(JSON_VALUE(b, '$.valor_composicao.valor_liquido') AS FLOAT64),
        NULLIF(SUM(CAST(JSON_VALUE(r,'$.valor') AS FLOAT64)) OVER (PARTITION BY p._pk), 0)
      )
  ) AS valor_realizado
FROM `meu-projeto-gcp.{dataset}.financeiro_parcelas_receitas` p,
     UNNEST(JSON_QUERY_ARRAY(p.baixas)) AS b,
     UNNEST(JSON_QUERY_ARRAY(p.evento__rateio)) AS r
LEFT JOIN `meu-projeto-gcp.{dataset}.categorias` c ON c.id = JSON_VALUE(r, '$.id_categoria')
WHERE p._erathos_deleted_at IS NULL
  AND JSON_VALUE(b, '$.data_pagamento') BETWEEN '2025-01-01' AND '2025-12-31'
GROUP BY mes, categoria, entrada_dre
ORDER BY mes, valor_realizado DESC

# Previsto — por vencimento (sem baixas):
SELECT
  FORMAT_DATE('%Y-%m', DATE(p.data_vencimento)) AS mes,
  c.nome AS categoria,
  SUM(CAST(JSON_VALUE(r, '$.valor') AS FLOAT64)) AS valor_previsto
FROM `meu-projeto-gcp.{dataset}.financeiro_parcelas_despesas` p,
     UNNEST(JSON_QUERY_ARRAY(p.evento__rateio)) AS r
LEFT JOIN `meu-projeto-gcp.{dataset}.categorias` c ON c.id = JSON_VALUE(r, '$.id_categoria')
WHERE p._erathos_deleted_at IS NULL
  AND p.data_vencimento BETWEEN '2025-01-01' AND '2025-12-31'
GROUP BY mes, categoria

REGRAS OBRIGATÓRIAS:
- Sempre filtrar `_erathos_deleted_at IS NULL`
- Sempre CAST(...AS FLOAT64) para valores JSON
- Usar SAFE_DIVIDE ou NULLIF para divisões
- Para consolidado: fazer UNION ALL de ca_empresa_a + ca_empresa_b + ca_empresa_c
- Limitar resultados com LIMIT quando desnecessário retornar muitas linhas
- Usar ROUND(valor, 2) para valores monetários finais
"""


def _execute_bq_safe(sql: str) -> str:
    """Executa query SELECT com validação de segurança."""
    sql_stripped = sql.strip()
    sql_upper    = sql_stripped.upper()

    # Bloquear DDL/DML
    for forbidden in ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
                      "ALTER", "TRUNCATE", "MERGE", "CALL", "EXECUTE"]:
        if re.search(rf"\b{forbidden}\b", sql_upper):
            return f"ERRO: operação '{forbidden}' não permitida. Apenas SELECT/WITH."

    if not (sql_upper.lstrip().startswith("SELECT") or
            sql_upper.lstrip().startswith("WITH")):
        return "ERRO: a query deve começar com SELECT ou WITH."

    try:
        bq = bigquery.Client(project=PROJECT, location="us-central1")
        job_config = bigquery.QueryJobConfig(
            maximum_bytes_billed=200_000_000,  # 200 MB
        )
        rows = list(bq.query(sql_stripped, job_config=job_config, timeout=55).result())
        if not rows:
            return "Consulta executada. Nenhum resultado encontrado."

        sample = rows[:300]
        df = pd.DataFrame([dict(r) for r in sample])
        total = len(rows)
        header = f"Resultado: {total} linha(s)"
        if total > 300:
            header += f" — exibindo primeiras 300"
        return f"{header}\n\n{df.to_string(index=False)}"
    except Exception as exc:
        return f"ERRO ao executar query: {str(exc)[:400]}"


def _dre_to_text(df: "pd.DataFrame", ano: int, empresa: str) -> str:
    """Formata um DataFrame DRE como texto estruturado para o tool result do chat."""
    labels = {"ca_empresa_a": "Empresa A", "ca_empresa_b": "Empresa B",
              "ca_empresa_c": "Empresa C", "consolidado": "Consolidado"}
    nome = labels.get(empresa, empresa)

    def _t(lid):
        row = df[df["id"] == lid]
        if row.empty: return 0.0
        v = row["TOTAL"].values[0]
        try: return float(v) if str(v) != "nan" else 0.0
        except: return 0.0

    rb = _t(1); lb = _t(5); lo = _t(9); ll = _t(13)
    pct = lambda n, d: f"{n/d*100:.1f}%" if d else "n/d"
    brl = lambda v: f"R$ {v:,.0f}"

    lines = [
        f"=== DRE {nome} {ano} ===",
        f"Receita Bruta:       {brl(rb)}",
        f"Resultado Bruto:     {brl(lb)}  | Margem Bruta:       {pct(lb, rb)}",
        f"Lucro Operacional:   {brl(lo)}  | Margem Operacional: {pct(lo, rb)}",
        f"Lucro Líquido:       {brl(ll)}  | Margem Líquida:     {pct(ll, rb)}",
        "",
        "Linhas completas (TOTAL acumulado):",
    ]
    for _, row in df.iterrows():
        lid = int(row["id"])
        label = str(row["label"])
        total = row.get("TOTAL", 0) or 0
        ytd = row.get("AH_YTD")
        ytd_s = f"  YTD {ytd:+.1f}%" if (ytd is not None and str(ytd) != "nan") else ""
        lines.append(f"  L{lid:2d} {label}: {brl(total)}{ytd_s}")
    return "\n".join(lines)


def chat_bigquery(
    mensagens: list[dict],
    empresa: str,
    ano: int,
    contexto_dre: str = "",  # mantido por compatibilidade, não usado no prompt
) -> str:
    """
    Chat com acesso direto ao BigQuery via tool use.
    Claude gera e executa queries SQL para responder perguntas.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "⚠️ ANTHROPIC_API_KEY não configurada."

    _labels = {
        "ca_empresa_a":  "Empresa A",
        "ca_empresa_b":      "Empresa B",
        "ca_empresa_c":     "Empresa C",
        "consolidado": "Consolidado Empresa Exemplo",
    }
    empresa_label = _labels.get(empresa, empresa)
    dataset_info  = (
        "Para consolidado use UNION ALL de ca_empresa_a + ca_empresa_b + ca_empresa_c"
        if empresa == "consolidado"
        else f"Dataset atual: `meu-projeto-gcp.{empresa}.*`"
    )

    system = f"""Você é um assistente financeiro com acesso direto aos dados do Empresa Exemplo.
Empresa/ano atual no dashboard: {empresa_label} ({ano}) | {dataset_info}

Você tem duas ferramentas:
1. `get_dre` — retorna o DRE completo (19 linhas + margens calculadas) para qualquer empresa e ano.
   Use para: receitas, lucros, margens, saldo de caixa, comparativos entre empresas/anos.
   SEMPRE use esta ferramenta para métricas do DRE — ela garante números corretos.

2. `execute_sql` — executa SQL direto no BigQuery.
   Use para: detalhar por fornecedor/cliente, listar transações, top categorias de despesa, dados granulares.
   NUNCA use para calcular margens ou lucros — o mapeamento de categorias é complexo e dará resultado errado.

Formate valores como R$ 1,2M ou R$ 850K. Seja direto e objetivo.

{_BQ_SCHEMA_DOC}"""

    tools = [
        {
            "name": "get_dre",
            "description": (
                "Retorna o DRE completo com 19 linhas e margens (%) para uma empresa e ano. "
                "Use para qualquer pergunta sobre receita, lucro, margens, saldo de caixa, "
                "comparativos entre anos ou entre empresas. Garante cálculos corretos."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "empresa": {
                        "type": "string",
                        "enum": ["ca_empresa_a", "ca_empresa_b", "ca_empresa_c", "consolidado"],
                        "description": "Dataset da empresa: ca_empresa_a, ca_empresa_b, ca_empresa_c ou consolidado",
                    },
                    "ano": {
                        "type": "integer",
                        "description": "Ano de 2022 a 2025",
                    },
                },
                "required": ["empresa", "ano"],
            },
        },
        {
            "name": "execute_sql",
            "description": (
                "Executa uma query SELECT no BigQuery do Empresa Exemplo para dados granulares. "
                "Use apenas para detalhar transações, fornecedores, categorias específicas. "
                "NÃO use para calcular margens ou lucros — use get_dre para isso."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "Query SELECT/WITH em BigQuery Standard SQL",
                    },
                },
                "required": ["sql"],
            },
        },
    ]

    client      = anthropic.Anthropic(api_key=api_key)
    messages    = [{"role": m["role"], "content": m["content"]}
                   for m in mensagens[-12:]]
    tool_errors = 0
    last_texts: list[str] = []

    for _iteration in range(10):
        tool_choice = {"type": "auto"} if tool_errors < 3 else {"type": "none"}

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system,
            tools=tools,
            tool_choice=tool_choice,
            messages=messages,
        )

        texts = [b.text for b in response.content if hasattr(b, "text")]
        if texts:
            last_texts = texts

        if response.stop_reason in ("end_turn", "stop_sequence"):
            return "\n".join(last_texts).strip() or "Sem resposta."

        if response.stop_reason == "max_tokens":
            return "\n".join(last_texts).strip() or "Resposta incompleta (limite de tokens)."

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                # ── Despachar ferramenta correta ──────────────────────────
                if block.name == "get_dre":
                    try:
                        emp  = block.input.get("empresa", "ca_empresa_a")
                        yr   = int(block.input.get("ano", ano))
                        df_r = get_dre(yr, emp)
                        resultado = _dre_to_text(df_r, yr, emp)
                        tool_errors = 0
                    except Exception as e:
                        resultado = f"ERRO ao buscar DRE: {e}"
                        tool_errors += 1
                else:  # execute_sql
                    resultado = _execute_bq_safe(block.input.get("sql", ""))
                    if resultado.startswith("ERRO"):
                        tool_errors += 1
                    else:
                        tool_errors = 0

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": resultado,
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return "\n".join(last_texts).strip() or "Não foi possível obter resposta do assistente."
