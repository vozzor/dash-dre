"""
Dashboard DRE
Plotly Dash + BigQuery
"""

from __future__ import annotations

import json
import os
import re
from datetime import date

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from authlib.integrations.flask_client import OAuth
from dash import ALL, Input, Output, State, callback, ctx, dcc, html
from flask import redirect, render_template_string, request, session
from flask_caching import Cache
from werkzeug.middleware.proxy_fix import ProxyFix

from dre_queries import DRE_LINES, get_dre, get_dre_categorias, get_dre_previsto, _CONSOLIDADO_DATASETS, _get_cat_names
from orcamento_ia import (
    carregar_orcamento,
    chat_bigquery,
    gerar_narrativa_dre,
    gerar_orcamento_ia,
    orcamento_existe,
    salvar_orcamento,
    _valores_para_df,
    _flatten_valores,
    _categorias_ativas_por_linha,
)

# ---------------------------------------------------------------------------
# App init
# ---------------------------------------------------------------------------
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY],
    title="Dashboard DRE",
    suppress_callback_exceptions=True,
)
server = app.server
server.wsgi_app = ProxyFix(server.wsgi_app, x_proto=1, x_host=1)

# ---------------------------------------------------------------------------
# Auth — Google OAuth 2.0 + whitelist de e-mails
# ---------------------------------------------------------------------------
_ALLOWED_FILE = os.path.join(os.path.dirname(__file__), "allowed_users.json")
try:
    with open(_ALLOWED_FILE) as _f:
        _ALLOWED_EMAILS: set = set(e.lower() for e in json.load(_f))
except FileNotFoundError:
    _ALLOWED_EMAILS = set()

server.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

oauth = OAuth(server)
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

_LOGIN_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Empresa Exemplo — Login</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Inter', sans-serif;
    background: #f5f5f5;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .login-card {
    background: white;
    border-radius: 16px;
    box-shadow: 0 4px 32px rgba(0,0,0,0.12);
    padding: 2.5rem 2.5rem 2rem;
    width: 100%;
    max-width: 380px;
    text-align: center;
  }
  .login-header {
    background: linear-gradient(135deg, #8b0f0e 0%, #af1917 40%, #e52322 100%);
    margin: -2.5rem -2.5rem 2rem;
    padding: 2rem 2.5rem;
    border-radius: 16px 16px 0 0;
  }
  .login-header h1 {
    color: white;
    font-size: 1.35rem;
    font-weight: 700;
    letter-spacing: 0.02em;
  }
  .login-header p {
    color: rgba(255,255,255,0.75);
    font-size: 0.82rem;
    margin-top: 0.25rem;
  }
  .subtitle {
    color: #607d8b;
    font-size: 0.88rem;
    margin-bottom: 1.75rem;
    line-height: 1.4;
  }
  .btn-google {
    display: inline-flex;
    align-items: center;
    gap: 0.65rem;
    background: white;
    border: 1.5px solid #dadce0;
    border-radius: 8px;
    padding: 0.7rem 1.4rem;
    font-size: 0.95rem;
    font-weight: 500;
    font-family: 'Inter', sans-serif;
    color: #3c4043;
    text-decoration: none;
    cursor: pointer;
    transition: box-shadow .18s, border-color .18s;
    width: 100%;
    justify-content: center;
  }
  .btn-google:hover {
    box-shadow: 0 2px 10px rgba(0,0,0,0.12);
    border-color: #bdc1c6;
  }
  .btn-google svg { flex-shrink: 0; }
  .error {
    background: #ffebee;
    color: #c62828;
    border-radius: 8px;
    padding: 0.6rem 0.9rem;
    font-size: 0.85rem;
    margin-bottom: 1.25rem;
    text-align: left;
  }
  .footer {
    color: #90a4ae;
    font-size: 0.75rem;
    margin-top: 1.75rem;
  }
</style>
</head>
<body>
<div class="login-card">
  <div class="login-header">
    <h1>Empresa Exemplo</h1>
    <p>Dashboard DRE — Acesso Restrito</p>
  </div>
  {% if error %}
  <div class="error">{{ error }}</div>
  {% endif %}
  <p class="subtitle">Entre com sua conta Google corporativa<br>(@exemplo.com.br)</p>
  <a href="/auth/google" class="btn-google">
    <svg width="18" height="18" viewBox="0 0 18 18">
      <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"/>
      <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"/>
      <path fill="#FBBC05" d="M3.964 10.706A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.706V4.962H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.038l3.007-2.332z"/>
      <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.962L3.964 6.294C4.672 4.169 6.656 3.58 9 3.58z"/>
    </svg>
    Entrar com Google
  </a>
  <div class="footer">Empresa Exemplo &copy; {{ year }}</div>
</div>
</body>
</html>"""

_DENIED_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Acesso negado — Empresa Exemplo</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
  body { font-family: 'Inter', sans-serif; background:#f5f5f5; display:flex;
         align-items:center; justify-content:center; min-height:100vh; }
  .card { background:white; border-radius:16px; box-shadow:0 4px 32px rgba(0,0,0,.12);
          padding:2.5rem; max-width:380px; text-align:center; }
  h2 { color:#c62828; margin-bottom:.75rem; }
  p  { color:#607d8b; font-size:.9rem; line-height:1.5; }
  a  { display:inline-block; margin-top:1.5rem; color:#e52322; font-weight:600;
       text-decoration:none; }
</style>
</head>
<body>
<div class="card">
  <h2>Acesso negado</h2>
  <p>A conta <strong>{{ email }}</strong> não tem permissão para acessar este dashboard.<br>
     Solicite acesso ao administrador.</p>
  <a href="/logout">Usar outra conta</a>
</div>
</body>
</html>"""


@server.route("/login")
def login():
    if session.get("user"):
        return redirect("/")
    return render_template_string(_LOGIN_HTML, error=None, year=date.today().year)


@server.route("/auth/google")
def auth_google():
    redirect_uri = request.url_root.rstrip("/") + "/auth/callback"
    return oauth.google.authorize_redirect(redirect_uri)


@server.route("/auth/callback")
def auth_callback():
    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.google.userinfo()
    email = (userinfo.get("email") or "").lower()
    if not email:
        return render_template_string(_LOGIN_HTML, error="Não foi possível obter o e-mail da conta Google.", year=date.today().year)
    if _ALLOWED_EMAILS and email not in _ALLOWED_EMAILS:
        return render_template_string(_DENIED_HTML, email=email), 403
    session["user"] = email
    session["name"] = userinfo.get("name", email)
    return redirect(session.pop("next_url", "/"))


@server.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


_PUBLIC_PREFIXES = ("/login", "/auth/", "/assets/", "/_dash-component-suites/",
                    "/_dash-dependencies", "/_dash-layout", "/favicon.ico")


@server.before_request
def require_login():
    if any(request.path.startswith(p) for p in _PUBLIC_PREFIXES):
        return
    if not session.get("user"):
        session["next_url"] = request.path
        return redirect("/login")


cache = Cache(server, config={
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 3600,
})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
MONTH_LABELS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
CURRENT_YEAR = pd.Timestamp.now().year

COMPANIES = {
    "ca_empresa_a": "Empresa A",
    "ca_empresa_b": "Empresa B",
    "ca_empresa_c": "Empresa C",
    "consolidado": "Consolidado",
}

COLOR_BRAND    = "#e52322"   # Empresa Exemplo vermelho principal
COLOR_BRAND_DK = "#af1917"   # Empresa Exemplo vermelho escuro
COLOR_GREEN  = "#2e7d32"
COLOR_RED    = "#c62828"
COLOR_ORANGE = "#e65100"
COLOR_PREV   = "#ff8f00"   # previsto line color

# Alias para compatibilidade com helpers de gráfico
COLOR_BLUE = COLOR_BRAND

# Metadados por linha (sinal, quadro) para estilo da tabela
_LINE_META = {l["id"]: l for l in DRE_LINES}


def fmt_brl(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    return f"R$ {v:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}%"


def fmt_av(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    return f"{v:.1f}%"


def fmt_exec(real, prev) -> str:
    if not prev:
        return "-"
    pct = real / prev * 100
    return f"{pct:.0f}%"


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

_CHART_LAYOUT = dict(
    margin=dict(t=10, b=10, l=10, r=10),
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(family="Inter, -apple-system, sans-serif", size=11),
    height=290,
    hovermode="x unified",
    legend=dict(
        orientation="h", yanchor="bottom", y=1.02,
        font=dict(size=10), bgcolor="rgba(0,0,0,0)",
    ),
)

_AXIS_Y = dict(
    showgrid=True, gridcolor="#eeeeee",
    tickformat=",.0f", tickfont=dict(size=10),
    zeroline=False,
)
_AXIS_X = dict(
    showgrid=False, tickfont=dict(size=10),
    categoryorder="array", categoryarray=MONTH_LABELS,
)


def _meses_com_dados(df, year: int) -> list[str]:
    """Retorna apenas os rótulos de meses com dados reais.
    No ano corrente, corta após o mês atual; em anos passados, retorna todos os 12."""
    if year < CURRENT_YEAR:
        return MONTH_LABELS
    # Usa L1 (Receita Bruta) como indicador de atividade
    row_l1 = df[df["id"] == 1]
    if row_l1.empty:
        return MONTH_LABELS[:pd.Timestamp.now().month]
    # Inclui todos os meses até o último com receita > 0, mais o mês seguinte (previsto)
    ultimo = 0
    for i, m in enumerate(MONTH_LABELS):
        if (row_l1[m].values[0] or 0) > 0:
            ultimo = i
    # mostra até o mês atual (pode incluir mês em curso sem dados completos)
    hoje_mes = pd.Timestamp.now().month
    corte = max(ultimo + 1, hoje_mes)
    return MONTH_LABELS[:corte]


def _bar_with_previsto(df, df_prev, linha_id, year: int, color_pos=COLOR_BLUE):
    """Bar (Realizado) + dashed line (Previsto) para uma linha do DRE.
    Barras apenas nos meses com dados reais; linha prevista cobre os 12 meses."""
    row = df[df["id"] == linha_id]
    if row.empty:
        return go.Figure()

    meses_real = _meses_com_dados(df, year)
    # Barras: realizado apenas onde há dados; None nos demais para não poluir
    vals_bar = []
    for m in MONTH_LABELS:
        if m in meses_real:
            vals_bar.append(row[m].values[0])
        else:
            vals_bar.append(None)
    colors = [color_pos if (v or 0) >= 0 else COLOR_RED for v in vals_bar]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=MONTH_LABELS, y=vals_bar,
        name="Realizado",
        marker_color=colors,
        hovertemplate="R$ %{y:,.0f}<extra>Realizado</extra>",
    ))

    if df_prev is not None:
        row_prev = df_prev[df_prev["id"] == linha_id]
        if not row_prev.empty:
            vals_prev = [row_prev[m].values[0] for m in MONTH_LABELS]
            fig.add_trace(go.Scatter(
                x=MONTH_LABELS, y=vals_prev,
                name="Previsto",
                mode="lines+markers",
                line=dict(color=COLOR_PREV, width=2, dash="dot"),
                marker=dict(size=5, color=COLOR_PREV),
                hovertemplate="R$ %{y:,.0f}<extra>Previsto</extra>",
            ))

    fig.update_layout(
        **_CHART_LAYOUT,
        yaxis=_AXIS_Y,
        xaxis={**_AXIS_X, "categoryarray": MONTH_LABELS},
        showlegend=df_prev is not None,
    )
    return fig


def _saldo_chart(df, df_prev, year: int):
    """Área preenchida para o Saldo Final de Caixa.
    Realizado nos meses com dados; linha prevista cobre os 12 meses."""
    row = df[df["id"] == 19]
    if row.empty:
        return go.Figure()

    meses_real = _meses_com_dados(df, year)
    vals_real  = [row[m].values[0] for m in meses_real]
    pos_y = [v if v >= 0 else 0 for v in vals_real]
    neg_y = [v if v <  0 else 0 for v in vals_real]
    marker_colors = [COLOR_GREEN if v >= 0 else COLOR_RED for v in vals_real]

    fig = go.Figure()
    # Área positiva (verde) — só meses realizados para não quebrar eixo
    fig.add_trace(go.Scatter(
        x=meses_real, y=pos_y,
        mode="none", fill="tozeroy",
        fillcolor="rgba(46,125,50,0.12)",
        showlegend=False, hoverinfo="skip",
    ))
    # Área negativa (vermelha)
    fig.add_trace(go.Scatter(
        x=meses_real, y=neg_y,
        mode="none", fill="tozeroy",
        fillcolor="rgba(198,40,40,0.10)",
        showlegend=False, hoverinfo="skip",
    ))
    # Linha realizado
    fig.add_trace(go.Scatter(
        x=meses_real, y=vals_real,
        name="Realizado",
        mode="lines+markers",
        line=dict(color=COLOR_BRAND_DK, width=2.5),
        marker=dict(color=marker_colors, size=9,
                    line=dict(color="white", width=1.5)),
        hovertemplate="R$ %{y:,.0f}<extra>Saldo Realizado</extra>",
    ))
    # Linha previsto (todos os 12 meses)
    if df_prev is not None:
        row_prev = df_prev[df_prev["id"] == 19]
        if not row_prev.empty:
            vals_prev = [row_prev[m].values[0] for m in MONTH_LABELS]
            fig.add_trace(go.Scatter(
                x=MONTH_LABELS, y=vals_prev,
                name="Previsto",
                mode="lines+markers",
                line=dict(color=COLOR_PREV, width=2, dash="dot"),
                marker=dict(size=5, color=COLOR_PREV),
                hovertemplate="R$ %{y:,.0f}<extra>Saldo Previsto</extra>",
            ))
    fig.add_hline(y=0, line_dash="dot", line_color="#9e9e9e", line_width=1)
    fig.update_layout(
        **_CHART_LAYOUT,
        yaxis=_AXIS_Y,
        xaxis={**_AXIS_X, "categoryarray": MONTH_LABELS},
        showlegend=df_prev is not None,
    )
    return fig



def _despesas_chart(df, year: int):
    """Barras empilhadas de despesas com cores por categoria."""
    linhas = [
        (2,  "Custos Operac.", "#EF6C00"),
        (4,  "Impostos",       "#D32F2F"),
        (6,  "Desp. Operac.",  "#7B1FA2"),
        (8,  "Desp. Holding",  "#455A64"),
    ]
    meses_real = _meses_com_dados(df, year)
    fig = go.Figure()
    for lid, nome, cor in linhas:
        row = df[df["id"] == lid]
        if row.empty:
            continue
        vals = [abs(row[m].values[0] or 0) if m in meses_real else None
                for m in MONTH_LABELS]
        fig.add_trace(go.Bar(
            name=nome, x=MONTH_LABELS, y=vals,
            marker_color=cor,
            hovertemplate=f"{nome}: R$ %{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(
        **_CHART_LAYOUT,
        barmode="stack",
        yaxis=_AXIS_Y,
        xaxis={**_AXIS_X, "categoryarray": MONTH_LABELS},
        showlegend=True,
    )
    return fig


# ---------------------------------------------------------------------------
# Modal — Metodologia dos Cálculos
# ---------------------------------------------------------------------------

def _metodologia_modal():
    """Retorna o dbc.Modal completo com a explicação de todos os cálculos."""

    _S = {"fontSize": "0.84rem", "lineHeight": "1.6", "color": "#333"}
    _LABEL = {"fontWeight": "700", "color": COLOR_BRAND_DK}
    _FORMULA = {"fontFamily": "monospace", "background": "#f5f5f5",
                "padding": "2px 7px", "borderRadius": "4px",
                "fontSize": "0.82rem", "color": "#333"}
    _SEP = html.Hr(style={"margin": "10px 0", "borderColor": "#eee"})

    def item(label, formula, desc):
        return html.Div([
            html.Div([
                html.Span(label, style={**_LABEL, "marginRight": "8px"}),
                html.Code(formula, style=_FORMULA),
            ], style={"marginBottom": "3px"}),
            html.P(desc, style={**_S, "color": "#666", "marginBottom": "10px",
                                "paddingLeft": "4px"}),
        ])

    def dre_row(num, nome, formula_ou_tipo, desc, totalizador=False):
        cor = "#2e7d32" if totalizador else COLOR_BRAND_DK
        return html.Div([
            html.Div([
                html.Span(f"L{num}", style={"fontWeight": "700", "color": cor,
                                            "minWidth": "28px", "display": "inline-block"}),
                html.Span(nome, style={"fontWeight": "600" if totalizador else "400"}),
                html.Code(formula_ou_tipo,
                          style={**_FORMULA, "marginLeft": "8px", "fontSize": "0.76rem"}),
            ], style={"marginBottom": "2px"}),
            html.P(desc, style={**_S, "color": "#777", "fontSize": "0.79rem",
                                "paddingLeft": "28px", "marginBottom": "8px"}),
        ])

    # ── Seção 1: Cards KPI ──────────────────────────────────────────────────
    sec_kpi = html.Div([
        item("Receita Bruta", "soma acumulada da L1",
             "Total de tudo que a empresa recebeu no período (ano até o mês atual). "
             "Inclui eventos, corporate, comissões, reembolsos e patrocínios."),
        item("Lucro Operacional", "soma acumulada da L9",
             "Resultado após deduzir todos os custos operacionais, impostos, "
             "despesas da equipe e despesas da holding. Reflete a eficiência "
             "das operações, sem contar o resultado financeiro."),
        item("Lucro Líquido", "soma acumulada da L13",
             "Resultado final da empresa após IR e CSLL. "
             "É o número que vai para o balanço como sobra (ou deficit) do período."),
        item("Saldo Final de Caixa", "valor da L19 do último mês com dados",
             "Não é uma soma — é o saldo real do caixa no último mês fechado. "
             "Equivale ao saldo bancário consolidado de todas as contas da empresa."),
        _SEP,
        html.P("Variação YTD %", style={**_S, **_LABEL}),
        html.Code("(acumulado ano atual − mesmo período ano anterior) ÷ |mesmo período ano anterior| × 100",
                  style={**_FORMULA, "display": "block", "margin": "4px 0 6px 0"}),
        html.P("Compara o acumulado do ano atual com exatamente o mesmo número de meses do ano anterior. "
               "Exemplo: se estamos em março/2025, compara Jan–Mar 2025 com Jan–Mar 2024.",
               style={**_S, "color": "#666"}),
    ])

    # ── Seção 2: Cards de Margem ─────────────────────────────────────────────
    sec_margens = html.Div([
        item("Margem Bruta %", "L5 ÷ L1 × 100",
             "Quanto sobra da receita após pagar os custos diretos dos eventos e os impostos sobre vendas. "
             "Mostra a eficiência na precificação e execução dos projetos."),
        item("Margem Operacional %", "L9 ÷ L1 × 100",
             "Quanto sobra após pagar também toda a equipe e as despesas da holding. "
             "É a margem mais importante para avaliar a saúde operacional da empresa."),
        item("Margem Líquida %", "L13 ÷ L1 × 100",
             "Quanto sobra no final, após IR e CSLL. "
             "É o percentual de cada real de receita que vira lucro de verdade."),
        _SEP,
        html.P("Delta pp (pontos percentuais vs ano anterior)", style={**_S, **_LABEL}),
        html.Code("margem atual − margem do mesmo período do ano anterior",
                  style={**_FORMULA, "display": "block", "margin": "4px 0 6px 0"}),
        html.P("Indica se a empresa está ganhando ou perdendo eficiência em relação ao ano passado. "
               "+2pp significa que a margem melhorou 2 pontos percentuais.",
               style={**_S, "color": "#666"}),
    ])

    # ── Seção 3: Estrutura do DRE ────────────────────────────────────────────
    sec_dre = html.Div([
        html.P("As 19 linhas do DRE e como cada uma é calculada:", style=_S),
        html.Br(),
        dre_row(1, "Receita Bruta", "dados reais",
                "Tudo que entrou como receita operacional: serviços, comissões, "
                "reembolsos e patrocínios."),
        dre_row(2, "(-) Custos Operacionais", "dados reais",
                "Gastos diretamente ligados à execução dos eventos: hospedagem, "
                "passagens, transfers, produções, adiantamentos e devoluções."),
        dre_row(3, "(=) Receita Líquida", "L1 − L2",
                "O que sobra da receita depois de pagar o custo direto de cada projeto.", totalizador=True),
        dre_row(4, "(-) Impostos sobre Vendas", "dados reais",
                "ISS, PIS, COFINS e Simples Nacional — tributos sobre o faturamento."),
        dre_row(5, "(=) Resultado Bruto", "L3 − L4",
                "Resultado após custos diretos e impostos sobre vendas.", totalizador=True),
        dre_row(6, "(-) Despesas Operacionais", "dados reais",
                "Gastos com a equipe: salários, 13º, FGTS, INSS, férias, VT, VA, "
                "pró-labore operacional, freelancers e prestadores PJ."),
        dre_row(7, "(=) Resultado Operacional", "L5 − L6",
                "Resultado após pagar a equipe.", totalizador=True),
        dre_row(8, "(-) Despesas Holding", "dados reais",
                "Despesas estruturais: aluguel, softwares, consultoria, marketing, "
                "pró-labore dos sócios, distribuição de lucros para sócios, "
                "equipamentos, viagens de sócios."),
        dre_row(9, "(=) Lucro Operacional", "L7 − L8",
                "Resultado puro das operações, antes de qualquer efeito financeiro.", totalizador=True),
        dre_row(10, "Resultado Financeiro", "dados reais",
                "Rendimentos de aplicações financeiras, menos tarifas bancárias e encargos."),
        dre_row(11, "(=) Lucro antes do IR", "L9 + L10",
                "Lucro operacional mais (ou menos) o resultado financeiro.", totalizador=True),
        dre_row(12, "(-) IR / CSLL", "dados reais",
                "Imposto de Renda (IRPJ) e Contribuição Social sobre o Lucro Líquido."),
        dre_row(13, "(=) Lucro Líquido", "L11 − L12",
                "Resultado final contábil da empresa no período.", totalizador=True),
        dre_row(14, "(-) Reserva PIS/COFINS", "dados reais",
                "Provisão de caixa separada para pagamento futuro de PIS e COFINS."),
        dre_row(15, "(-) Reserva IR/CSLL", "dados reais",
                "Provisão de caixa separada para pagamento futuro de IRPJ e CSLL."),
        dre_row(16, "(=) Saldo Disponível", "L13 − L14 − L15",
                "Caixa disponível após separar as reservas de impostos.", totalizador=True),
        dre_row(17, "(+) Entradas Não Operacionais", "dados reais",
                "Recebimentos fora do operacional: distribuições recebidas de "
                "subsidiárias, empréstimos tomados, outras entradas extraordinárias."),
        dre_row(18, "(-) Saídas Não Operacionais", "dados reais",
                "Pagamentos fora do operacional: distribuição de lucros extra para sócios, "
                "amortização de empréstimos, aquisições de empresas."),
        dre_row(19, "(=) Saldo Final de Caixa", "L16 + L17 − L18 + saldo anterior",
                "Posição real do caixa no final do mês. O saldo anterior vem do "
                "Conta Azul (cadastrado manualmente para o mês de janeiro de cada ano) "
                "e se acumula mês a mês.", totalizador=True),
    ])

    # ── Seção 4: Modos de Análise ────────────────────────────────────────────
    sec_analise = html.Div([
        item("Realizado (R$)", "valores diretos",
             "Exibe os valores reais de cada mês, sem comparação. "
             "É o modo padrão para visualizar o resultado do período."),
        item("Previsto (R$)", "orçamento cadastrado",
             "Exibe os valores do orçamento (gerado pela IA ou editado manualmente na aba Orçamentos). "
             "Disponível apenas para anos que possuem orçamento cadastrado."),
        item("Prev vs Real", "realizado + previsto + % execução",
             "Mostra lado a lado: o previsto, o realizado e o percentual de execução "
             "(Realizado ÷ Previsto × 100). Essencial para acompanhar o atingimento de metas."),
        _SEP,
        item("AV — Análise Vertical (%)", "linha ÷ L1 × 100",
             "Mostra o peso de cada linha sobre a Receita Bruta. "
             "Exemplo: Despesas Operacionais AV 18% significa que 18% da receita vai para a equipe."),
        item("AH MoM — Variação Mês a Mês (%)",
             "(mês atual − mês anterior) ÷ |mês anterior| × 100",
             "Compara cada mês com o mês imediatamente anterior. "
             "Identifica tendências de curto prazo e sazonalidade dentro do ano."),
        item("AH YoY — Variação Ano a Ano (%)",
             "(mês atual − mesmo mês ano anterior) ÷ |mesmo mês ano anterior| × 100",
             "Compara cada mês com o mesmo mês do ano anterior. "
             "Elimina o efeito da sazonalidade e mostra crescimento real."),
    ])

    # ── Seção 5: Gráficos ───────────────────────────────────────────────────
    sec_graficos = html.Div([
        item("Receita Bruta Mensal", "valores mensais da L1",
             "Barras mostrando a receita bruta de cada mês. "
             "Se houver orçamento, uma linha pontilhada mostra o previsto para comparação."),
        item("Lucro Operacional Mensal", "valores mensais da L9",
             "Barras do lucro operacional por mês. Barras vermelhas indicam meses negativos. "
             "Linha pontilhada mostra o previsto quando disponível."),
        item("Composição de Despesas", "valores mensais de L2 + L4 + L6 + L8",
             "Barras empilhadas mostrando quanto cada bloco de despesa representou em cada mês: "
             "Custos Operacionais (laranja), Impostos (vermelho), "
             "Despesas Operacionais/equipe (roxo) e Despesas Holding (cinza)."),
        item("Saldo Final de Caixa", "valor mensal da L19 (não soma — posição do mês)",
             "Linha com área preenchida mostrando o saldo do caixa mês a mês. "
             "Verde quando positivo, vermelho quando negativo. "
             "Não é soma acumulada — é a fotografia do caixa no final de cada mês."),
    ])

    return dbc.Modal(
        [
            dbc.ModalHeader(
                dbc.ModalTitle([
                    html.Span("📐 ", style={"marginRight": "4px"}),
                    "Metodologia dos Cálculos",
                ]),
            ),
            dbc.ModalBody(
                [
                    html.P(
                        "Como cada número deste dashboard é calculado. "
                        "Clique em cada seção para expandir.",
                        style={**_S, "color": "#666", "marginBottom": "16px"},
                    ),
                    dbc.Accordion(
                        [
                            dbc.AccordionItem(sec_kpi,       title="🟦 Cards KPI (topo da página)"),
                            dbc.AccordionItem(sec_margens,   title="📊 Cards de Margem"),
                            dbc.AccordionItem(sec_dre,       title="📋 Estrutura do DRE — 19 linhas"),
                            dbc.AccordionItem(sec_analise,   title="🔍 Modos de Análise (AV, MoM, YoY, Prev vs Real)"),
                            dbc.AccordionItem(sec_graficos,  title="📈 Gráficos"),
                        ],
                        always_open=True,
                        start_collapsed=True,
                        active_item="item-0",
                    ),
                ],
            ),
            dbc.ModalFooter(
                dbc.Button("Fechar", id="btn-met-fechar", color="secondary", size="sm"),
            ),
        ],
        id="modal-metodologia",
        size="xl",
        scrollable=True,
        is_open=False,
    )


# ---------------------------------------------------------------------------
# Chat helpers
# ---------------------------------------------------------------------------

def _dre_para_contexto(df: pd.DataFrame, year: int, company: str) -> str:
    """Formata o DRE como texto compacto para o contexto do chat.
    Inclui sumário executivo com margens pré-calculadas no topo.
    """
    empresa_label = COMPANIES.get(company, company)

    def _t(lid):
        row = df[df["id"] == lid]
        if row.empty: return 0.0
        v = row["TOTAL"].values[0]
        try: return float(v) if str(v) != "nan" else 0.0
        except: return 0.0

    rb = _t(1)
    ll = _t(13)
    lo = _t(9)
    lb = _t(5)

    def _pct(num, den):
        return f"{num/den*100:.1f}%" if den else "n/d"

    def _brl(v):
        return f"R$ {v:,.0f}"

    # Sumário executivo com margens já calculadas — evita o modelo rodar SQL
    sumario = [
        f"=== DRE SUMÁRIO: {empresa_label} {year} ===",
        f"Receita Bruta:       {_brl(rb)}",
        f"Lucro Bruto (L5):    {_brl(lb)}  |  Margem Bruta:       {_pct(lb, rb)}",
        f"Lucro Operacional:   {_brl(lo)}  |  Margem Operacional: {_pct(lo, rb)}",
        f"Lucro Líquido (L13): {_brl(ll)}  |  Margem Líquida:     {_pct(ll, rb)}",
        "=== DETALHAMENTO MENSAL ===",
    ]

    for _, row in df.iterrows():
        lid = int(row["id"])
        label = str(row["label"])
        total = row.get("TOTAL", 0) or 0
        ytd = row.get("AH_YTD")
        ytd_str = f" | YTD {ytd:+.1f}%" if (ytd is not None and not pd.isna(ytd)) else ""
        monthly = []
        for m in MONTH_LABELS:
            v = row.get(m, 0) or 0
            if v != 0:
                monthly.append(f"{m}={v:,.0f}")
        mensal_str = "  " + " ".join(monthly) if monthly else ""
        sumario.append(f"L{lid} {label}: TOTAL={total:,.0f}{ytd_str}")
        if mensal_str:
            sumario.append(mensal_str)

    return "\n".join(sumario)


def _render_chat_bubbles(historico: list[dict]) -> list:
    """Renderiza histórico de mensagens como bubbles HTML."""
    bubbles = []
    for msg in historico:
        is_user = msg["role"] == "user"

        if is_user:
            inner_content = html.Span(
                msg["content"],
                style={"whiteSpace": "pre-wrap"},
            )
            bubble_style = {
                "background": COLOR_BRAND,
                "color": "white",
                "borderRadius": "16px 16px 4px 16px",
                "padding": "8px 13px",
                "maxWidth": "85%",
                "fontSize": "0.84rem",
                "lineHeight": "1.55",
                "boxShadow": "0 1px 3px rgba(0,0,0,0.08)",
            }
        else:
            # Markdown renderizado para mensagens do assistente
            inner_content = dcc.Markdown(
                msg["content"],
                className="chat-md",
                dangerously_allow_html=False,
            )
            bubble_style = {
                "background": "#f8f9fa",
                "borderRadius": "16px 16px 16px 4px",
                "padding": "10px 13px",
                "maxWidth": "92%",
                "boxShadow": "0 1px 3px rgba(0,0,0,0.08)",
                "border": "1px solid #e0e0e0",
            }

        bubble = html.Div(
            html.Div(inner_content, style=bubble_style),
            style={
                "display": "flex",
                "justifyContent": "flex-end" if is_user else "flex-start",
                "marginBottom": "8px",
                "paddingRight": "4px" if is_user else "0",
                "paddingLeft": "0" if is_user else "4px",
            },
        )
        bubbles.append(bubble)
    return bubbles


_CHAT_WELCOME = [{
    "role": "assistant",
    "content": (
        "Olá! Tenho acesso direto ao banco de dados financeiro do Empresa Exemplo. "
        "Pode me perguntar qualquer coisa — receitas por categoria, despesas por fornecedor, "
        "comparativos entre empresas, análise de períodos específicos, ou qualquer outra consulta nos dados."
    ),
}]


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
app.layout = dbc.Container(
    fluid=True,
    style={"padding": "0"},
    children=[
        # ── Header ──────────────────────────────────────────────────────
        html.Div(
            className="dash-header",
            children=dbc.Row([
                dbc.Col(
                    html.Div([
                        html.Img(
                            src="/assets/logo.png",
                            className="app-logo",
                        ),
                        html.Div([
                            html.H2("Dashboard Financeiro",
                                    className="mb-0 fw-bold text-white",
                                    style={"fontSize": "1.25rem", "lineHeight": "1.2"}),
                            html.Small(
                                "Conta Azul · BigQuery · Regime de Caixa",
                                className="text-white-50",
                                style={"fontSize": "0.75rem"},
                            ),
                        ]),
                    ], style={"display": "flex", "alignItems": "center"}),
                    width=4,
                ),
                dbc.Col([
                    dbc.Label("Empresa", className="text-white-50 small mb-1 d-block"),
                    dcc.Dropdown(
                        id="dd-company",
                        options=[{"label": v, "value": k} for k, v in COMPANIES.items()],
                        value="consolidado",
                        clearable=False,
                        className="header-dropdown",
                    ),
                ], width=2),
                dbc.Col([
                    dbc.Label("Ano", className="text-white-50 small mb-1 d-block"),
                    dcc.Dropdown(
                        id="dd-ano",
                        options=[{"label": str(y), "value": y}
                                 for y in range(2022, CURRENT_YEAR + 1)],
                        value=CURRENT_YEAR,
                        clearable=False,
                        className="header-dropdown",
                    ),
                ], width=2),
                dbc.Col([
                    dbc.Label("Exibir", className="text-white-50 small mb-1 d-block"),
                    dcc.Dropdown(
                        id="dd-analise",
                        options=[
                            {"label": "Realizado (R$)",    "value": "valor"},
                            {"label": "Previsto (R$)",     "value": "previsto"},
                            {"label": "Prev vs Real (R$)", "value": "prev_real"},
                            {"label": "AV (%)",            "value": "av"},
                            {"label": "AH MoM (%)",        "value": "mom"},
                            {"label": "AH YoY (%)",        "value": "yoy"},
                        ],
                        value="prev_real",
                        clearable=False,
                        className="header-dropdown",
                    ),
                ], width=3),
                dbc.Col([
                    dbc.Label("\u00a0", className="d-block mb-1",
                              style={"fontSize": "0.75rem"}),
                    dbc.Button(
                        "↻ Atualizar",
                        id="btn-refresh",
                        color="light",
                        size="sm",
                        style={
                            "background": "rgba(255,255,255,0.15)",
                            "border": "1px solid rgba(255,255,255,0.4)",
                            "color": "white",
                            "fontWeight": "600",
                            "borderRadius": "8px",
                            "width": "100%",
                        },
                    ),
                ], width=1),
            ], align="center"),
        ),

        # ── Navegação de páginas ────────────────────────────────────────
        html.Div(
            className="px-3 pt-3 pb-0",
            children=dbc.ButtonGroup([
                dbc.Button("📊 DRE",         id="nav-dre",       color="danger",
                           size="sm", outline=False, n_clicks=0,
                           style={"borderRadius": "8px 0 0 8px", "fontWeight": "600"}),
                dbc.Button("🎯 Orçamentos",  id="nav-orcamentos", color="danger",
                           size="sm", outline=True, n_clicks=0,
                           style={"borderRadius": "0 8px 8px 0", "fontWeight": "600"}),
            ]),
        ),
        dcc.Store(id="store-pagina", data="dre"),

        # ── Página DRE ──────────────────────────────────────────────────
        html.Div(id="page-dre", children=[

            # ── KPI Cards ───────────────────────────────────────────────
            dbc.Row(id="kpi-cards", className="mt-3 mb-2 g-3 px-3"),

            # ── KPI Margens ──────────────────────────────────────────────
            dbc.Row(id="kpi-margins", className="mb-3 g-3 px-3"),

            # ── Narrativa IA ─────────────────────────────────────────────
            dcc.Loading(
                type="dot",
                color=COLOR_BRAND,
                children=html.Div(id="narrativa-dre", className="px-3 mb-4"),
            ),

            # ── Tabela DRE ──────────────────────────────────────────────
            dbc.Row([
                dbc.Col(
                    dbc.Card([
                        dbc.CardHeader(
                            dbc.Row([
                                dbc.Col(
                                    html.H5("Demonstração de Resultado",
                                            className="mb-0 fw-semibold"),
                                    width="auto",
                                    className="d-flex align-items-center",
                                ),
                                dbc.Col(
                                    html.Div([
                                        html.Small(
                                            "Acumulado até:",
                                            className="text-muted me-2",
                                            style={"fontSize": "0.75rem",
                                                   "whiteSpace": "nowrap"},
                                        ),
                                        dcc.Dropdown(
                                            id="dd-acum-mes",
                                            options=[
                                                {"label": m, "value": i + 1}
                                                for i, m in enumerate(MONTH_LABELS)
                                            ],
                                            value=None,
                                            clearable=True,
                                            placeholder="Auto",
                                            style={"minWidth": "90px",
                                                   "fontSize": "0.82rem"},
                                        ),
                                        dbc.Button(
                                            "⬇ Exportar CSV",
                                            id="btn-export-dre",
                                            color="secondary",
                                            outline=True,
                                            size="sm",
                                            n_clicks=0,
                                            className="ms-2",
                                            style={"fontSize": "0.75rem",
                                                   "whiteSpace": "nowrap"},
                                        ),
                                        dcc.Download(id="download-dre-csv"),
                                    ], className="d-flex align-items-center"),
                                    width="auto",
                                    className="ms-auto",
                                ),
                            ], align="center"),
                            style={"background": "white",
                                   "borderBottom": "2px solid #e9ecef"},
                        ),
                        dbc.CardBody(
                            html.Div(id="tabela-dre",
                                     style={"overflowX": "auto"}),
                            className="p-0",
                        ),
                    ], className="section-card"),
                )
            ], className="mb-4 px-3"),

            # ── Gráficos linha 1 ────────────────────────────────────────
            dbc.Row([
                dbc.Col(
                    dbc.Card(dbc.CardBody([
                        html.P("Receita Bruta Mensal", className="chart-title"),
                        dcc.Graph(id="grafico-receita",
                                  config={"displayModeBar": False}),
                    ]), className="section-card"),
                    md=6,
                ),
                dbc.Col(
                    dbc.Card(dbc.CardBody([
                        html.P("Lucro Operacional Consolidado Mensal",
                               className="chart-title"),
                        dcc.Graph(id="grafico-lucro",
                                  config={"displayModeBar": False}),
                    ]), className="section-card"),
                    md=6,
                ),
            ], className="mb-3 g-3 px-3"),

            # ── Gráficos linha 2 ────────────────────────────────────────
            dbc.Row([
                dbc.Col(
                    dbc.Card(dbc.CardBody([
                        html.P("Composição de Despesas", className="chart-title"),
                        dcc.Graph(id="grafico-despesas",
                                  config={"displayModeBar": False}),
                    ]), className="section-card"),
                    md=6,
                ),
                dbc.Col(
                    dbc.Card(dbc.CardBody([
                        html.P("Evolução do Saldo Final de Caixa",
                               className="chart-title"),
                        dcc.Graph(id="grafico-saldo",
                                  config={"displayModeBar": False}),
                    ]), className="section-card"),
                    md=6,
                ),
            ], className="mb-3 g-3 px-3"),



        ]),

        # ── Página Orçamentos ────────────────────────────────────────────
        html.Div(id="page-orcamentos", style={"display": "none"}, children=[
            dbc.Row(className="mb-4 px-3 pt-3", children=[
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(
                            dbc.Row([
                                dbc.Col(
                                    html.H5("🎯 Orçamento",
                                            className="mb-0 fw-semibold"),
                                    width="auto",
                                ),
                                dbc.Col(
                                    dbc.Row([
                                        dbc.Col(
                                            dcc.Dropdown(
                                                id="orc-empresa",
                                                options=[{"label": v, "value": k}
                                                         for k, v in COMPANIES.items()],
                                                value="ca_empresa_a",
                                                clearable=False,
                                                style={"minWidth": "160px"},
                                            ),
                                            width="auto",
                                        ),
                                        dbc.Col(
                                            dcc.Dropdown(
                                                id="orc-ano",
                                                options=[{"label": str(y), "value": y}
                                                         for y in range(CURRENT_YEAR, CURRENT_YEAR + 3)],
                                                value=CURRENT_YEAR,
                                                clearable=False,
                                                style={"minWidth": "100px"},
                                            ),
                                            width="auto",
                                        ),
                                        dbc.Col(
                                            dbc.Button(
                                                "📝 Contexto",
                                                id="btn-toggle-contexto",
                                                color="secondary",
                                                outline=True,
                                                size="sm",
                                                n_clicks=0,
                                            ),
                                            width="auto",
                                        ),
                                        dbc.Col(
                                            dbc.Button(
                                                [dbc.Spinner(size="sm", id="orc-spinner",
                                                             spinner_style={"display": "none"}),
                                                 " 🤖 Gerar com IA"],
                                                id="btn-gerar-ia",
                                                color="primary",
                                                size="sm",
                                                n_clicks=0,
                                            ),
                                            width="auto",
                                        ),
                                        dbc.Col(
                                            dbc.Button(
                                                "💾 Salvar",
                                                id="btn-salvar-orc",
                                                color="success",
                                                size="sm",
                                                n_clicks=0,
                                            ),
                                            width="auto",
                                        ),
                                        dbc.Col(
                                            dbc.Button(
                                                "⬇ Exportar CSV",
                                                id="btn-export-orc",
                                                color="secondary",
                                                outline=True,
                                                size="sm",
                                                n_clicks=0,
                                            ),
                                            width="auto",
                                        ),
                                        dbc.Col(
                                            html.Small(
                                                id="orc-status",
                                                className="text-muted",
                                                style={"lineHeight": "2.2"},
                                            ),
                                            width="auto",
                                        ),
                                    ], align="center", className="g-2"),
                                    width=True,
                                ),
                            ], align="center"),
                            style={"background": "white",
                                   "borderBottom": "2px solid #e9ecef"},
                        ),
                        dbc.Collapse(
                            dbc.CardBody(
                                dbc.Textarea(
                                    id="orc-contexto",
                                    placeholder="Contexto para a IA (opcional): descreva premissas, eventos esperados, metas estratégicas ou qualquer observação que deva ser considerada ao gerar o orçamento...",
                                    rows=3,
                                    style={"fontSize": "0.85rem", "resize": "vertical"},
                                    className="border-0 bg-light",
                                ),
                                className="p-2 pb-0",
                                style={"borderBottom": "1px solid #e9ecef"},
                            ),
                            id="orc-contexto-collapse",
                            is_open=False,
                        ),
                        dbc.CardBody(
                            dcc.Loading(
                                id="orc-loading",
                                type="circle",
                                color="#e52322",
                                children=html.Div(id="orc-tabela-container"),
                            ),
                            className="p-2",
                        ),
                    ], className="section-card"),
                ]),
            ]),
            dbc.Toast(
                id="orc-toast",
                header="Orçamento",
                is_open=False,
                dismissable=True,
                duration=4000,
                style={"position": "fixed", "top": 80, "right": 20, "zIndex": 9999},
            ),
            dcc.Store(id="store-orcamento"),
            dcc.Store(id="store-orc-expanded", data=[]),
            dcc.Store(id="store-orc-nested",   data={}),
            dcc.Download(id="download-orc-csv"),
        ]),

        # ── Footer ──────────────────────────────────────────────────────
        html.Div(
            "Empresa Exemplo · Dashboard Financeiro · Conta Azul → BigQuery",
            className="dash-footer",
        ),

        # ── Modal Metodologia ───────────────────────────────────────────
        _metodologia_modal(),

        # ── Chat Widget (flutuante) ──────────────────────────────────────
        html.Div([
            # Botão metodologia (acima do chat)
            html.Button(
                "?",
                id="btn-met-toggle",
                n_clicks=0,
                title="Metodologia dos Cálculos",
                style={
                    "position": "fixed", "bottom": "84px", "right": "24px",
                    "width": "52px", "height": "52px", "borderRadius": "50%",
                    "background": "#455a64", "color": "white", "border": "none",
                    "fontSize": "1.25rem", "fontWeight": "700", "cursor": "pointer",
                    "zIndex": 1050, "boxShadow": "0 4px 14px rgba(0,0,0,0.20)",
                    "display": "flex", "alignItems": "center", "justifyContent": "center",
                },
            ),
            # Botão flutuante chat
            html.Button(
                "💬",
                id="btn-chat-toggle",
                n_clicks=0,
                title="Assistente Financeiro IA",
                style={
                    "position": "fixed", "bottom": "24px", "right": "24px",
                    "width": "52px", "height": "52px", "borderRadius": "50%",
                    "background": COLOR_BRAND, "color": "white", "border": "none",
                    "fontSize": "1.4rem", "cursor": "pointer", "zIndex": 1050,
                    "boxShadow": "0 4px 16px rgba(0,0,0,0.25)",
                    "display": "flex", "alignItems": "center", "justifyContent": "center",
                    "transition": "transform 0.15s",
                },
            ),
            # Painel do chat
            html.Div(
                id="chat-panel",
                style={"display": "none", "position": "fixed", "bottom": "84px",
                       "right": "24px", "width": "480px", "zIndex": 1049},
                children=dbc.Card([
                    # Header
                    dbc.CardHeader(
                        dbc.Row([
                            dbc.Col(
                                html.Div([
                                    html.Span("✦ ", style={"color": COLOR_BRAND}),
                                    html.Strong("Assistente Financeiro",
                                                style={"fontSize": "0.9rem"}),
                                ]),
                                className="d-flex align-items-center",
                            ),
                            dbc.Col(
                                html.Button(
                                    "✕", id="btn-chat-fechar", n_clicks=0,
                                    style={
                                        "background": "none", "border": "none",
                                        "color": "#888", "fontSize": "1rem",
                                        "cursor": "pointer", "padding": "0 4px",
                                    },
                                ),
                                width="auto",
                                className="d-flex align-items-center",
                            ),
                        ], align="center", justify="between"),
                        style={"padding": "10px 14px",
                               "borderBottom": "1px solid #e9ecef"},
                    ),
                    # Mensagens
                    dbc.CardBody(
                        dcc.Loading(
                            id="chat-loading",
                            type="circle",
                            color=COLOR_BRAND,
                            children=html.Div(
                                id="chat-messages",
                                style={
                                    "overflowY": "auto",
                                    "height": "420px",
                                    "padding": "8px 4px",
                                },
                            ),
                        ),
                        style={"padding": "8px 10px"},
                    ),
                    # Input — plain flex div para evitar conflito dbc.InputGroup
                    dbc.CardFooter(
                        html.Div([
                            dcc.Input(
                                id="chat-input",
                                type="text",
                                placeholder="Pergunte sobre os dados...",
                                debounce=False,
                                n_submit=0,
                                style={
                                    "flex": "1",
                                    "border": "1px solid #dee2e6",
                                    "borderRight": "none",
                                    "borderRadius": "6px 0 0 6px",
                                    "padding": "7px 10px",
                                    "fontSize": "0.85rem",
                                    "outline": "none",
                                    "minWidth": "0",
                                },
                            ),
                            html.Button(
                                "→",
                                id="btn-chat-enviar",
                                n_clicks=0,
                                style={
                                    "background": COLOR_BRAND,
                                    "color": "white",
                                    "border": "none",
                                    "borderRadius": "0 6px 6px 0",
                                    "padding": "7px 14px",
                                    "fontSize": "1rem",
                                    "fontWeight": "bold",
                                    "cursor": "pointer",
                                    "flexShrink": "0",
                                },
                            ),
                        ], style={"display": "flex", "width": "100%"}),
                        style={"padding": "8px 10px",
                               "borderTop": "1px solid #e9ecef"},
                    ),
                ], style={
                    "boxShadow": "0 8px 32px rgba(0,0,0,0.18)",
                    "borderRadius": "12px", "overflow": "hidden",
                    "border": "1px solid #e0e0e0",
                }),
            ),
        ]),

        # ── Stores ──────────────────────────────────────────────────────
        dcc.Store(id="store-dre"),
        dcc.Store(id="store-dre-prev"),
        dcc.Store(id="store-cats"),
        dcc.Store(id="store-expanded", data=[]),
        dcc.Store(id="store-refresh", data=0),
        dcc.Store(id="store-company", data="consolidado"),
        dcc.Store(id="store-chat", data=_CHAT_WELCOME),
    ],
)


# ---------------------------------------------------------------------------
# Callbacks — carregamento de dados
# ---------------------------------------------------------------------------

@callback(Output("store-refresh", "data"),
          Input("btn-refresh", "n_clicks"),
          State("store-refresh", "data"),
          prevent_initial_call=True)
def atualizar_cache(_n_clicks, current):
    cache.clear()
    return (current or 0) + 1


@callback(
    Output("store-company", "data"),
    Input("dd-company", "value"),
)
def switch_company(company):
    return company or "ca_empresa_a"


@callback(Output("store-dre", "data"),
          Input("dd-ano", "value"), Input("store-refresh", "data"),
          Input("store-company", "data"))
@cache.memoize(timeout=3600)
def carregar_dre(year: int, _refresh, company: str):
    df = get_dre(year, company)
    return df.to_json(orient="records", force_ascii=False)


@callback(Output("store-dre-prev", "data"),
          Input("dd-ano", "value"), Input("store-refresh", "data"),
          Input("store-company", "data"))
@cache.memoize(timeout=3600)
def carregar_dre_prev(year: int, _refresh, company: str):
    df = get_dre_previsto(year, company)
    return df.to_json(orient="records", force_ascii=False)


@callback(Output("store-cats", "data"),
          Input("dd-ano", "value"), Input("store-refresh", "data"),
          Input("store-company", "data"))
@cache.memoize(timeout=3600)
def carregar_cats(year: int, _refresh, company: str):
    cats = get_dre_categorias(year, company)
    return json.dumps(cats, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Callback — expand/collapse rows
# ---------------------------------------------------------------------------

@callback(
    Output("store-expanded", "data"),
    Input({"type": "btn-expand", "index": ALL}, "n_clicks"),
    State("store-expanded", "data"),
    prevent_initial_call=True,
)
def toggle_row(_, expanded):
    triggered = ctx.triggered_id
    if not triggered:
        return dash.no_update
    # Ignora disparos causados pelo reset de n_clicks (re-render da tabela)
    if not ctx.triggered[0].get("value"):
        return dash.no_update
    lid = triggered["index"]
    if lid in expanded:
        return [x for x in expanded if x != lid]
    return expanded + [lid]


# ---------------------------------------------------------------------------
# Callback — KPIs
# ---------------------------------------------------------------------------

@callback(Output("kpi-cards", "children"), Input("store-dre", "data"))
def atualizar_kpis(data):
    if not data:
        return []
    df = pd.read_json(data, orient="records")

    def get_val(lid):
        row = df[df["id"] == lid]
        return row["TOTAL"].values[0] if not row.empty else 0.0

    def get_saldo_atual():
        """Retorna o saldo do último mês com dados reais (não a soma anual)."""
        row = df[df["id"] == 19]
        if row.empty:
            return 0.0
        ultimo_val = 0.0
        for m in MONTH_LABELS:
            v = row[m].values[0] if m in row.columns else 0
            if v and v != 0:
                ultimo_val = v
        return ultimo_val

    def get_ytd(lid):
        row = df[df["id"] == lid]
        return row["AH_YTD"].values[0] if not row.empty else None

    kpis = [
        ("Receita Bruta",        get_val(1),     get_ytd(1),  COLOR_BRAND,    "📈"),
        ("Lucro Operacional",    get_val(9),     get_ytd(9),  COLOR_GREEN,  "💹"),
        ("Lucro Líquido",        get_val(13),    get_ytd(13), COLOR_BRAND_DK, "✅"),
        ("Saldo Final de Caixa", get_saldo_atual(), get_ytd(19), COLOR_ORANGE, "🏦"),
    ]

    cards = []
    for title, total, ytd, accent, _icon in kpis:
        ytd_text  = (fmt_pct(ytd) + " YTD") if ytd is not None else "—"
        ytd_color = "#2e7d32" if (ytd or 0) >= 0 else "#c62828"
        cards.append(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.Small(
                            title,
                            className="text-muted fw-semibold text-uppercase",
                            style={"fontSize": "0.7rem", "letterSpacing": "0.07em"},
                        ),
                        html.H3(
                            fmt_brl(total),
                            className="mb-1 fw-bold mt-1",
                            style={"fontSize": "1.35rem"},
                        ),
                        html.Span(
                            ytd_text,
                            className="fw-semibold",
                            style={"fontSize": "0.8rem", "color": ytd_color},
                        ),
                    ], style={"borderLeft": f"4px solid {accent}",
                              "paddingLeft": "1rem"}),
                    className="kpi-card h-100",
                ),
                md=3,
            )
        )
    return cards


@callback(Output("kpi-margins", "children"), Input("store-dre", "data"))
def atualizar_kpi_margins(data):
    """Cards de Margem Bruta %, Operacional % e Líquida % com delta vs ano anterior."""
    if not data:
        return []
    df = pd.read_json(data, orient="records")

    def get_total(lid):
        row = df[df["id"] == lid]
        return float(row["TOTAL"].values[0]) if not row.empty else 0.0

    def get_ytd(lid):
        row = df[df["id"] == lid]
        v = row["AH_YTD"].values[0] if not row.empty else None
        return None if (v is None or pd.isna(v)) else float(v)

    def prior_total(lid):
        """Deriva o total do ano anterior via AH_YTD."""
        cur = get_total(lid)
        ytd = get_ytd(lid)
        if ytd is None or (100 + ytd) == 0:
            return None
        return cur * 100 / (100 + ytd)

    l1 = get_total(1)
    if l1 == 0:
        return []

    prior_l1 = prior_total(1) or 0

    def margem(lid):
        val = get_total(lid)
        return val / l1 * 100

    def margem_prior(lid):
        if prior_l1 == 0:
            return None
        p = prior_total(lid)
        if p is None:
            return None
        return p / prior_l1 * 100

    MARGEM_CARDS = [
        ("Margem Bruta",       5,  "#2e7d32", "#a5d6a7"),
        ("Margem Operacional", 9,  "#1565c0", "#90caf9"),
        ("Margem Líquida",     13, "#e65100", "#ffcc80"),
    ]

    cards = []
    for title, lid, color, border_color in MARGEM_CARDS:
        cur_m  = margem(lid)
        prev_m = margem_prior(lid)
        if prev_m is not None:
            delta  = cur_m - prev_m
            delta_txt   = f"{'+' if delta >= 0 else ''}{delta:.1f}pp vs ano ant."
            delta_color = "#2e7d32" if delta >= 0 else "#c62828"
        else:
            delta_txt   = "—"
            delta_color = "#999"

        cards.append(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.Small(
                            title,
                            className="text-muted fw-semibold text-uppercase",
                            style={"fontSize": "0.7rem", "letterSpacing": "0.07em"},
                        ),
                        html.H3(
                            f"{cur_m:.1f}%",
                            className="mb-1 fw-bold mt-1",
                            style={"fontSize": "1.35rem", "color": color},
                        ),
                        html.Span(
                            delta_txt,
                            className="fw-semibold",
                            style={"fontSize": "0.8rem", "color": delta_color},
                        ),
                    ], style={"borderLeft": f"4px solid {border_color}",
                              "paddingLeft": "1rem"}),
                    className="kpi-card h-100",
                ),
                md=4,
            )
        )
    return cards


# ---------------------------------------------------------------------------
# Callback — Narrativa Automática do DRE (IA)
# ---------------------------------------------------------------------------

@cache.memoize(timeout=3600)
def _narrativa_cached(year: int, company: str):
    """
    Computa a narrativa IA — NÃO captura exceções.
    Assim o @cache.memoize nunca armazena None por falha;
    o try/except fica no callback wrapper.
    """
    df = get_dre(year, company)

    def _tot(lid):
        row = df[df["id"] == lid]
        v = row["TOTAL"].values[0] if not row.empty else 0.0
        return float(v) if v is not None and not pd.isna(v) else 0.0

    def _ytd(lid):
        row = df[df["id"] == lid]
        v = row["AH_YTD"].values[0] if not row.empty else None
        return None if (v is None or pd.isna(v)) else float(v)

    def _saldo_atual():
        row = df[df["id"] == 19]
        if row.empty:
            return 0.0
        ultimo = 0.0
        for m in MONTH_LABELS:
            v = row[m].values[0] if m in row.columns else 0
            if v and not pd.isna(v):
                ultimo = float(v)
        return ultimo

    rb = _tot(1)
    if rb == 0:
        return None  # sem dados — None aqui é válido e pode ser cacheado

    meses_com_dados = _meses_com_dados(df, year)
    n_meses = len(meses_com_dados)
    periodo = (f"Jan–{meses_com_dados[-1]}" if n_meses > 1
               else meses_com_dados[0] if meses_com_dados else str(year))

    metricas = {
        "rb":           rb,
        "lucro_bruto":  _tot(5),
        "lucro_op":     _tot(9),
        "lucro_liq":    _tot(13),
        "margem_bruta": _tot(5) / rb * 100,
        "margem_op":    _tot(9) / rb * 100,
        "margem_liq":   _tot(13) / rb * 100,
        "rb_ytd":       _ytd(1),
        "op_ytd":       _ytd(9),
        "liq_ytd":      _ytd(13),
        "saldo_caixa":  _saldo_atual(),
        "meses_ytd":    n_meses,
        "periodo":      periodo,
    }

    texto = gerar_narrativa_dre(year, company, metricas)  # pode lançar exceção → não cacheado

    return dbc.Card(
        dbc.CardBody([
            dbc.Row([
                dbc.Col(
                    html.Span(
                        "✦ Análise IA",
                        style={
                            "fontSize": "0.65rem",
                            "fontWeight": "700",
                            "letterSpacing": "0.08em",
                            "textTransform": "uppercase",
                            "color": COLOR_BRAND,
                            "background": "#fff0f0",
                            "border": f"1px solid {COLOR_BRAND}",
                            "borderRadius": "20px",
                            "padding": "2px 10px",
                        },
                    ),
                    width="auto",
                    className="d-flex align-items-center",
                ),
                dbc.Col(
                    html.P(
                        texto,
                        className="mb-0",
                        style={
                            "fontSize": "0.88rem",
                            "color": "#444",
                            "lineHeight": "1.6",
                            "fontStyle": "italic",
                        },
                    ),
                ),
            ], align="center", className="g-3"),
        ], style={"padding": "0.75rem 1rem"}),
        style={
            "background": "#fafafa",
            "border": "1px solid #f0e0e0",
            "borderLeft": f"4px solid {COLOR_BRAND}",
            "borderRadius": "8px",
        },
    )


@callback(
    Output("narrativa-dre", "children"),
    Input("store-dre", "data"),
    State("dd-ano", "value"),
    State("store-company", "data"),
)
def atualizar_narrativa(_dre_data, year, company):
    """Dispara após store-dre estar populado. Try/except aqui para não cachear erros."""
    if not _dre_data:
        return None
    try:
        return _narrativa_cached(year or CURRENT_YEAR, company or "ca_empresa_a")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Callback — Tabela DRE com subitens expansíveis
# ---------------------------------------------------------------------------

@callback(
    Output("tabela-dre", "children"),
    Input("store-dre", "data"),
    Input("store-dre-prev", "data"),
    Input("store-cats", "data"),
    Input("store-expanded", "data"),
    Input("dd-analise", "value"),
    Input("dd-acum-mes", "value"),
    State("dd-ano", "value"),
)
def atualizar_tabela(data, data_prev, cats_json, expanded, modo, acum_mes, year):
    if not data:
        return html.P("Carregando...", className="p-3 text-muted")

    df      = pd.read_json(data, orient="records")
    df_prev = pd.read_json(data_prev, orient="records") if data_prev else df.copy()
    cats    = json.loads(cats_json) if cats_json else {}

    # ── Acumulado: mês selecionado ou último com dados ───────────────────
    meses_real = _meses_com_dados(df, year or CURRENT_YEAR)
    default_mes = MONTH_LABELS.index(meses_real[-1]) + 1 if meses_real else 12
    mes_acum = int(acum_mes) if acum_mes else default_mes
    mes_acum_label = MONTH_LABELS[mes_acum - 1]

    def _acum_row(row, use_prev=False):
        """Calcula valor acumulado até mes_acum.
        Para L19 (Saldo Final) retorna o valor do mês selecionado — saldo é
        posição acumulada, não fluxo, então somar meses daria número errado.
        Para demais linhas: soma Jan..mes_acum.
        """
        lid_r = int(row.get("id", 0))
        m_label = MONTH_LABELS[mes_acum - 1]
        if lid_r == 19:
            # Saldo Final de Caixa — mostrar posição do mês selecionado
            if use_prev:
                src = df_prev[df_prev["id"] == lid_r]
                v = src[m_label].values[0] if not src.empty else 0.0
            else:
                v = row.get(m_label, 0) or 0
            return float(v) if v and str(v) != "nan" else 0.0
        # Demais linhas: soma de fluxos Jan..mes_acum
        total = 0.0
        src = df_prev[df_prev["id"] == lid_r] if use_prev else None
        for m in MONTH_LABELS[:mes_acum]:
            if use_prev:
                v = src[m].values[0] if (src is not None and not src.empty) else 0.0
            else:
                v = row.get(m, 0) or 0
            total += float(v) if v and str(v) != "nan" else 0.0
        return total

    # ── Helpers ────────────────────────────────────────────────────────
    def neg_color(val, is_grand=False, faint=False):
        if is_grand or val is None or (isinstance(val, float) and pd.isna(val)):
            return "inherit"
        base = "#c62828" if val < 0 else "inherit"
        if faint and base == "inherit":
            return "#888"
        return base

    def pct_color(val, is_grand=False):
        if is_grand or val is None or (isinstance(val, float) and pd.isna(val)):
            return "inherit"
        return "#2e7d32" if val >= 0 else "#c62828"

    def exec_color_fn(real, prev):
        if not prev:
            return "inherit"
        pct = real / prev
        return "#2e7d32" if pct >= 0.9 else ("#e65100" if pct >= 0.7 else "#c62828")

    # ── Estilo compartilhado de linha ───────────────────────────────────
    def row_meta(row):
        lid       = int(row["id"])
        is_tot    = bool(row["totalizador"])
        is_grand  = (lid == 19)
        meta      = _LINE_META.get(lid, {})
        sinal     = meta.get("sinal", 1)
        if is_grand:
            lborder = "none"
        elif is_tot:
            lborder = "4px solid #e52322"
        elif sinal == 1:
            lborder = "4px solid #a5d6a7"
        else:
            lborder = "4px solid #ffcc80"
        return lid, is_tot, is_grand, lborder, sinal

    def _semaforo(real_val, prev_val, sinal):
        """🟢🟡🔴 baseado em execução vs orçamento, considerando se é receita ou despesa."""
        if not prev_val or prev_val == 0:
            return "·"
        ratio = real_val / prev_val
        if sinal == 1:   # receita/resultado — mais é melhor
            if ratio >= 0.90: return "🟢"
            if ratio >= 0.70: return "🟡"
            return "🔴"
        else:            # despesa — menos é melhor (abaixo do orçado = bom)
            if ratio <= 1.00: return "🟢"
            if ratio <= 1.15: return "🟡"
            return "🔴"

    # ── MODO VALOR: Prev + Real lado a lado por mês ─────────────────────
    if modo == "prev_real":
        th_m  = {"textAlign": "center", "minWidth": "130px"}
        th_sub = {"textAlign": "right",  "minWidth": "64px",
                  "fontSize": "0.65rem", "fontWeight": "500",
                  "letterSpacing": "0.03em"}
        th_tot = {"textAlign": "center", "minWidth": "130px"}

        header_r1 = [html.Th("", rowSpan=2, style={"minWidth": "230px"})]
        header_r2 = []
        for m in MONTH_LABELS:
            header_r1.append(html.Th(m, colSpan=2, style=th_m))
            header_r2.append(html.Th("Prev",  style={**th_sub, "color": "#aad4ff"}))
            header_r2.append(html.Th("Real",  style=th_sub))
        header_r1.append(html.Th("TOTAL", colSpan=2, style=th_tot))
        header_r2.append(html.Th("Prev",  style={**th_sub, "color": "#aad4ff"}))
        header_r2.append(html.Th("Real",  style=th_sub))
        header_r1.append(html.Th("% EXEC", rowSpan=2,
                                  style={"textAlign": "right", "minWidth": "72px"}))
        header_r1.append(html.Th("YTD (%)", rowSpan=2,
                                  style={"textAlign": "right", "minWidth": "75px"}))
        tem_orcamento = data_prev is not None
        header_r1.append(html.Th("", rowSpan=2,
                                  style={"textAlign": "center", "minWidth": "36px",
                                         "fontSize": "0.7rem", "color": "#999"}))
        header_r1.append(html.Th(
            [html.Div(f"Acum. {mes_acum_label}",
                      style={"fontSize": "0.7rem", "fontWeight": "700",
                             "color": "#fff", "letterSpacing": "0.04em"})],
            rowSpan=2,
            style={"textAlign": "right", "minWidth": "100px",
                   "background": "#5c6bc0", "borderRadius": "4px 4px 0 0"},
        ))
        header = html.Thead([html.Tr(header_r1), html.Tr(header_r2)])

        rows_html = []
        prev_quadro = None
        for _, row in df.iterrows():
            lid, is_tot, is_grand, lborder, sinal = row_meta(row)
            cur_quadro  = int(row.get("quadro", 1))
            quadro_border = (prev_quadro is not None and cur_quadro != prev_quadro)
            prev_quadro = cur_quadro

            if is_grand:
                row_cls, row_style = "row-grand-total", {}
            elif is_tot:
                row_cls, row_style = "", {"background": "#fdf0f0", "fontWeight": "600"}
            else:
                row_cls, row_style = "", {}
            if quadro_border and not is_grand:
                row_style = {**row_style, "borderTop": "2px solid #b0bec5"}

            has_cats    = (not is_tot) and cats and str(lid) in cats and bool(cats[str(lid)])
            is_expanded = lid in (expanded or [])

            toggle = html.Button(
                "▼" if is_expanded else "▶",
                id={"type": "btn-expand", "index": lid},
                n_clicks=0,
                style={"background": "none", "border": "none", "cursor": "pointer",
                       "fontSize": "0.65rem", "color": "#888", "padding": "0 4px 0 0"},
            ) if has_cats else html.Span(style={"display": "inline-block", "width": "14px"})

            label_cell = html.Td(
                [toggle, row["label"]],
                style={"paddingLeft": "10px", "whiteSpace": "nowrap",
                       "fontWeight": "600" if is_tot else "normal",
                       "borderLeft": lborder},
            )

            cells = [label_cell]
            row_prev_data = df_prev[df_prev["id"] == lid]
            for m in MONTH_LABELS:
                pv = row_prev_data[m].values[0] if not row_prev_data.empty else 0.0
                rv = row[m]
                cells.append(html.Td(fmt_brl(pv),
                    style={"textAlign": "right", "fontSize": "0.77rem",
                           "color": neg_color(pv, is_grand, faint=True)}))
                cells.append(html.Td(fmt_brl(rv),
                    style={"textAlign": "right",
                           "color": neg_color(rv, is_grand)}))

            # Totais
            real_total = df[df["id"] == lid]["TOTAL"].values
            real_val   = real_total[0] if len(real_total) else 0.0
            prev_total = df_prev[df_prev["id"] == lid]["TOTAL"].values
            prev_val   = prev_total[0] if len(prev_total) else 0.0
            cells.append(html.Td(fmt_brl(prev_val),
                style={"textAlign": "right", "fontWeight": "600", "fontSize": "0.77rem",
                       "color": neg_color(prev_val, is_grand, faint=True)}))
            cells.append(html.Td(fmt_brl(real_val),
                style={"textAlign": "right", "fontWeight": "700",
                       "color": neg_color(real_val, is_grand)}))

            exec_txt = fmt_exec(real_val, prev_val)
            cells.append(html.Td(exec_txt,
                style={"textAlign": "right", "fontWeight": "600",
                       "color": exec_color_fn(real_val, prev_val)}))

            ytd_val = row.get("AH_YTD")
            cells.append(html.Td(fmt_pct(ytd_val),
                style={"textAlign": "right", "color": pct_color(ytd_val, is_grand)}))

            if tem_orcamento and not is_grand:
                semaforo = _semaforo(real_val, prev_val, sinal)
                cells.append(html.Td(semaforo,
                    style={"textAlign": "center", "fontSize": "0.85rem",
                           "paddingLeft": "4px", "paddingRight": "4px"}))
            else:
                cells.append(html.Td(""))

            # Coluna Acumulado
            acum_val = _acum_row(row)
            cells.append(html.Td(fmt_brl(acum_val),
                style={"textAlign": "right", "fontWeight": "700",
                       "fontSize": "0.8rem",
                       "color": "white" if is_grand else ("#c62828" if acum_val < 0 else "#283593"),
                       "background": "#e8eaf6" if not is_grand else "transparent",
                       "borderLeft": "2px solid #9fa8da"}))

            rows_html.append(html.Tr(cells, className=row_cls, style=row_style))

            # Sub-categorias
            if has_cats and is_expanded:
                for cat in cats[str(lid)]:
                    sc = [html.Td(
                        [html.Span("└ ", style={"color": "#bbb"}), cat["label"]],
                        style={"paddingLeft": "32px", "whiteSpace": "nowrap",
                               "color": "#555", "fontSize": "0.78rem",
                               "borderLeft": lborder},
                    )]
                    for m in MONTH_LABELS:
                        pv = cat.get(f"{m}_prev", 0.0) or 0.0
                        rv = cat.get(f"{m}_real", 0.0) or 0.0
                        sc.append(html.Td(fmt_brl(pv) if pv else "-",
                            style={"textAlign": "right", "fontSize": "0.73rem",
                                   "color": "#c62828" if pv < 0 else "#999"}))
                        sc.append(html.Td(fmt_brl(rv) if rv else "-",
                            style={"textAlign": "right", "fontSize": "0.73rem",
                                   "color": "#c62828" if rv < 0 else "#555"}))
                    tr = cat.get("total_real", 0) or 0
                    tp = cat.get("total_prev", 0) or 0
                    sc.append(html.Td(fmt_brl(tp),
                        style={"textAlign": "right", "fontSize": "0.75rem",
                               "color": "#c62828" if tp < 0 else "#999"}))
                    sc.append(html.Td(fmt_brl(tr),
                        style={"textAlign": "right", "fontWeight": "500",
                               "fontSize": "0.75rem",
                               "color": "#c62828" if tr < 0 else "#444"}))
                    sc.append(html.Td(fmt_exec(tr, tp),
                        style={"textAlign": "right", "color": "#888",
                               "fontSize": "0.75rem"}))
                    sc.append(html.Td("-", style={"textAlign": "right"}))
                    sc.append(html.Td(""))  # semáforo
                    # Acumulado sub-categoria
                    cat_acum = sum(cat.get(f"{MONTH_LABELS[i]}_real", 0) or 0
                                   for i in range(mes_acum))
                    sc.append(html.Td(fmt_brl(cat_acum) if cat_acum else "-",
                        style={"textAlign": "right", "fontSize": "0.75rem",
                               "color": "#c62828" if cat_acum < 0 else "#444",
                               "background": "#e8eaf6",
                               "borderLeft": "2px solid #9fa8da"}))
                    rows_html.append(html.Tr(sc, style={"background": "#f7f9fc"}))

    # ── OUTROS MODOS: Realizado / Previsto / AV / MoM / YoY — coluna única ──
    else:
        if modo == "previsto":
            df = df_prev   # exibe dados do previsto no lugar do realizado
        if modo == "av":
            col_fn = lambda m: f"AV_{m}"
            fmt_fn = fmt_av
        elif modo == "mom":
            col_fn = lambda m: f"AH_MoM_{m}"
            fmt_fn = fmt_pct
        elif modo == "yoy":
            col_fn = lambda m: f"AH_YoY_{m}"
            fmt_fn = fmt_pct
        else:  # valor ou previsto — exibe R$ mensais
            col_fn = lambda m: m
            fmt_fn = fmt_brl

        def cell_color(val, is_grand=False):
            if is_grand or val is None or (isinstance(val, float) and pd.isna(val)):
                return "inherit"
            if modo in ("mom", "yoy"):
                return "#2e7d32" if val >= 0 else "#c62828"
            return "#c62828" if val < 0 else "inherit"

        th_style = {"textAlign": "right", "minWidth": "82px"}
        header = html.Thead(html.Tr([
            html.Th("", style={"minWidth": "230px"}),
            *[html.Th(m, style=th_style) for m in MONTH_LABELS],
            html.Th("TOTAL",    style={**th_style, "minWidth": "100px"}),
            html.Th("% EXEC",   style={**th_style, "minWidth": "72px"}),
            html.Th("YTD (%)",  style={**th_style, "minWidth": "75px"}),
            html.Th(f"Acum. {mes_acum_label}",
                    style={**th_style, "minWidth": "100px",
                           "background": "#5c6bc0", "color": "white",
                           "borderRadius": "4px 4px 0 0",
                           "fontSize": "0.7rem", "fontWeight": "700",
                           "letterSpacing": "0.04em"}),
        ]))

        rows_html = []
        prev_quadro = None
        for _, row in df.iterrows():
            lid, is_tot, is_grand, lborder, sinal = row_meta(row)
            cur_quadro    = int(row.get("quadro", 1))
            quadro_border = (prev_quadro is not None and cur_quadro != prev_quadro)
            prev_quadro   = cur_quadro

            if is_grand:
                row_cls, row_style = "row-grand-total", {}
            elif is_tot:
                row_cls, row_style = "", {"background": "#fdf0f0", "fontWeight": "600"}
            else:
                row_cls, row_style = "", {}
            if quadro_border and not is_grand:
                row_style = {**row_style, "borderTop": "2px solid #b0bec5"}

            has_cats    = (not is_tot) and cats and str(lid) in cats and bool(cats[str(lid)])
            is_expanded = lid in (expanded or [])

            toggle = html.Button(
                "▼" if is_expanded else "▶",
                id={"type": "btn-expand", "index": lid},
                n_clicks=0,
                style={"background": "none", "border": "none", "cursor": "pointer",
                       "fontSize": "0.65rem", "color": "#888", "padding": "0 4px 0 0"},
            ) if has_cats else html.Span(style={"display": "inline-block", "width": "14px"})

            cells = [html.Td(
                [toggle, row["label"]],
                style={"paddingLeft": "10px", "whiteSpace": "nowrap",
                       "fontWeight": "600" if is_tot else "normal",
                       "borderLeft": lborder},
            )]
            for m in MONTH_LABELS:
                val = row.get(col_fn(m))
                cells.append(html.Td(fmt_fn(val),
                    style={"textAlign": "right", "color": cell_color(val, is_grand)}))

            real_val = df[df["id"] == lid]["TOTAL"].values
            real_val = real_val[0] if len(real_val) else 0.0
            prev_val = df_prev[df_prev["id"] == lid]["TOTAL"].values
            prev_val = prev_val[0] if len(prev_val) else 0.0
            cells.append(html.Td(fmt_brl(real_val),
                style={"textAlign": "right", "fontWeight": "700",
                       "color": cell_color(real_val, is_grand)}))
            cells.append(html.Td(fmt_exec(real_val, prev_val),
                style={"textAlign": "right", "fontWeight": "600",
                       "color": exec_color_fn(real_val, prev_val)}))
            ytd_val = row.get("AH_YTD")
            cells.append(html.Td(fmt_pct(ytd_val),
                style={"textAlign": "right", "color": pct_color(ytd_val, is_grand)}))

            # Coluna Acumulado — só faz sentido para modos de valor (não AV/MoM/YoY)
            if modo in ("valor", "previsto", "prev_real"):
                acum_val = _acum_row(row, use_prev=(modo == "previsto"))
                cells.append(html.Td(fmt_brl(acum_val),
                    style={"textAlign": "right", "fontWeight": "700",
                           "fontSize": "0.8rem",
                           "color": "white" if is_grand else ("#c62828" if acum_val < 0 else "#283593"),
                           "background": "#e8eaf6" if not is_grand else "transparent",
                           "borderLeft": "2px solid #9fa8da"}))
            else:
                cells.append(html.Td("—",
                    style={"textAlign": "right", "color": "#bbb",
                           "background": "#f3f4fb",
                           "borderLeft": "2px solid #9fa8da"}))

            rows_html.append(html.Tr(cells, className=row_cls, style=row_style))

            if has_cats and is_expanded:
                for cat in cats[str(lid)]:
                    sc = [html.Td(
                        [html.Span("└ ", style={"color": "#bbb"}), cat["label"]],
                        style={"paddingLeft": "32px", "whiteSpace": "nowrap",
                               "color": "#555", "fontSize": "0.78rem",
                               "borderLeft": lborder},
                    )]
                    for m in MONTH_LABELS:
                        val = cat.get(f"{m}_real", 0.0) or 0.0
                        sc.append(html.Td(fmt_brl(val) if val else "-",
                            style={"textAlign": "right", "fontSize": "0.75rem",
                                   "color": "#c62828" if val < 0 else "#555"}))
                    tr = cat.get("total_real", 0) or 0
                    tp = cat.get("total_prev", 0) or 0
                    sc.append(html.Td(fmt_brl(tr),
                        style={"textAlign": "right", "fontWeight": "500",
                               "fontSize": "0.75rem",
                               "color": "#c62828" if tr < 0 else "#444"}))
                    sc.append(html.Td(fmt_exec(tr, tp),
                        style={"textAlign": "right", "color": "#888",
                               "fontSize": "0.75rem"}))
                    sc.append(html.Td("-", style={"textAlign": "right"}))
                    # Acumulado sub-categoria
                    if modo in ("valor", "previsto", "prev_real"):
                        cat_acum = sum(cat.get(f"{MONTH_LABELS[i]}_real", 0) or 0
                                       for i in range(mes_acum))
                        sc.append(html.Td(fmt_brl(cat_acum) if cat_acum else "-",
                            style={"textAlign": "right", "fontSize": "0.75rem",
                                   "color": "#c62828" if cat_acum < 0 else "#444",
                                   "background": "#e8eaf6",
                                   "borderLeft": "2px solid #9fa8da"}))
                    else:
                        sc.append(html.Td("—",
                            style={"textAlign": "right", "color": "#bbb",
                                   "background": "#f3f4fb",
                                   "borderLeft": "2px solid #9fa8da"}))
                    rows_html.append(html.Tr(sc, style={"background": "#f7f9fc"}))

    return dbc.Table(
        [header, html.Tbody(rows_html)],
        bordered=True,
        hover=True,
        responsive=True,
        size="sm",
        className="dre-table",
    )


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------

@callback(
    Output("grafico-receita", "figure"),
    Input("store-dre", "data"),
    Input("store-dre-prev", "data"),
    Input("dd-ano", "value"),
)
def grafico_receita(data, data_prev, year):
    if not data:
        return go.Figure()
    df      = pd.read_json(data, orient="records")
    df_prev = pd.read_json(data_prev, orient="records") if data_prev else None
    return _bar_with_previsto(df, df_prev, 1, year or CURRENT_YEAR, COLOR_BLUE)


@callback(
    Output("grafico-lucro", "figure"),
    Input("store-dre", "data"),
    Input("store-dre-prev", "data"),
    Input("dd-ano", "value"),
)
def grafico_lucro(data, data_prev, year):
    if not data:
        return go.Figure()
    df      = pd.read_json(data, orient="records")
    df_prev = pd.read_json(data_prev, orient="records") if data_prev else None
    return _bar_with_previsto(df, df_prev, 9, year or CURRENT_YEAR, COLOR_GREEN)


@callback(Output("grafico-despesas", "figure"),
          Input("store-dre", "data"), Input("dd-ano", "value"))
def grafico_despesas(data, year):
    if not data:
        return go.Figure()
    return _despesas_chart(pd.read_json(data, orient="records"), year or CURRENT_YEAR)


@callback(Output("grafico-saldo", "figure"),
          Input("store-dre", "data"), Input("store-dre-prev", "data"),
          Input("dd-ano", "value"))
def grafico_saldo(data, data_prev, year):
    if not data:
        return go.Figure()
    df_prev = pd.read_json(data_prev, orient="records") if data_prev else None
    return _saldo_chart(pd.read_json(data, orient="records"), df_prev, year or CURRENT_YEAR)





# ---------------------------------------------------------------------------
# Callbacks — Navegação de páginas
# ---------------------------------------------------------------------------

@callback(
    Output("store-pagina", "data"),
    Input("nav-dre", "n_clicks"),
    Input("nav-orcamentos", "n_clicks"),
    prevent_initial_call=True,
)
def trocar_pagina(n_dre, n_orc):
    triggered = ctx.triggered_id
    return "orcamentos" if triggered == "nav-orcamentos" else "dre"


@callback(
    Output("page-dre",        "style"),
    Output("page-orcamentos", "style"),
    Output("nav-dre",         "outline"),
    Output("nav-orcamentos",  "outline"),
    Output("dd-company",      "disabled"),
    Output("dd-ano",          "disabled"),
    Output("dd-analise",      "disabled"),
    Output("btn-refresh",     "disabled"),
    Input("store-pagina",     "data"),
)
def mostrar_pagina(pagina):
    if pagina == "orcamentos":
        # Header controls são irrelevantes na tela de orçamentos — desabilitar
        return {"display": "none"}, {}, True, False, True, True, True, True
    return {}, {"display": "none"}, False, True, False, False, False, False


# ---------------------------------------------------------------------------
# Callbacks — Orçamentos
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Orçamentos — HTML table editável com expand/collapse por subitem
# ---------------------------------------------------------------------------

def _nested_from_jsonable(obj) -> dict:
    """Converte o JSON de dcc.Store para nested {lid int: {cat str: {mes int: valor float}}}."""
    if not obj:
        return {}
    out: dict = {}
    for lid_str, cats in obj.items():
        try:
            lid = int(lid_str)
        except (ValueError, TypeError):
            continue
        out[lid] = {}
        for cat_id, meses in (cats or {}).items():
            cid = str(cat_id or "")
            out[lid][cid] = {}
            for mes, v in (meses or {}).items():
                try:
                    out[lid][cid][int(mes)] = float(v or 0)
                except (ValueError, TypeError):
                    pass
    return out


def _orc_input(lid: int, cat_id: str, mes: int, value: float):
    """Célula editável para (linha, categoria, mês)."""
    return dcc.Input(
        id={"type": "orc-cell", "lid": int(lid), "cat": str(cat_id or ""), "mes": int(mes)},
        type="number",
        value=float(value or 0),
        debounce=True,
        style={
            "width": "100%", "border": "1px solid transparent",
            "padding": "3px 5px", "fontSize": "0.76rem",
            "textAlign": "right", "background": "transparent",
            "outline": "none",
            "fontFamily": "Inter, -apple-system, sans-serif",
        },
        className="orc-input-cell",
    )


_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I
)

def _cat_label(cid: str, uuid_to_nome: dict | None = None) -> str:
    """Gera label amigável para um cat_id.
    Se uuid_to_nome for fornecido, resolve UUIDs para o nome real do BQ.
    """
    if cid == "__temporario__":
        return "Temporário"
    if _UUID_RE.match(cid):
        if uuid_to_nome and cid in uuid_to_nome and uuid_to_nome[cid]:
            return uuid_to_nome[cid]
        return f"Categoria {cid[:8]}…"
    return cid  # label descritivo (ex: 'Salarios', 'Pro Labore - Operação')


def _uuid_to_nome_para_empresa(empresa: str) -> dict[str, str]:
    """Carrega mapeamento {uuid: nome} de todas as categorias da(s) empresa(s).
    Para consolidado, mescla os 3 datasets."""
    datasets = _CONSOLIDADO_DATASETS if empresa == "consolidado" else [empresa]
    merged: dict[str, str] = {}
    for ds in datasets:
        try:
            merged.update(_get_cat_names(ds))
        except Exception:
            continue
    return merged


def _categorias_para_linha(lid: int, historical: dict, nested: dict,
                            uuid_to_nome: dict | None = None) -> list[dict]:
    """Lista ordenada de categorias a mostrar para uma linha.
    Combina o histórico do ano anterior com cat_ids do orçamento salvo.
    `uuid_to_nome` resolve UUIDs para o nome real do BQ (essencial para categorias
    importadas da planilha que não têm histórico).
    """
    result: list[dict] = []
    seen: set = set()
    for c in (historical.get(lid, []) or []):
        cid = str(c.get("cat_id") or "")
        if cid == "" or cid in seen:
            continue
        seen.add(cid)
        result.append({
            "cat_id": cid,
            "label": c.get("label") or _cat_label(cid, uuid_to_nome),
        })
    # Cat_ids do orçamento ausentes do histórico (ex: UUIDs importados, __temporario__)
    extras = set((nested.get(lid) or {}).keys()) - seen - {""}
    for cid in sorted(extras):
        result.append({"cat_id": cid, "label": _cat_label(cid, uuid_to_nome)})
    return result


def _build_orc_table_html(nested: dict, df: pd.DataFrame,
                          ano: int, empresa: str, expanded: list) -> html.Div:
    """Tabela HTML com linhas DRE, expand/collapse e células editáveis por subitem."""
    try:
        historical = _categorias_ativas_por_linha(empresa, ano - 1)
    except Exception:
        historical = {}

    # Lookup UUID → nome do BQ para categorias importadas sem histórico ativo
    try:
        uuid_to_nome = _uuid_to_nome_para_empresa(empresa)
    except Exception:
        uuid_to_nome = {}

    expanded_set = set(int(x) for x in (expanded or []))

    # ── Header ─────────────────────────────────────────────────────────────
    th_style_month = {"textAlign": "right", "minWidth": "88px",
                      "padding": "8px 6px", "fontSize": "0.72rem",
                      "color": "white", "fontWeight": "600"}
    th_style_label = {"textAlign": "left", "minWidth": "260px",
                      "padding": "8px 10px", "fontSize": "0.72rem",
                      "color": "white", "fontWeight": "600"}
    th_style_total = {"textAlign": "right", "minWidth": "100px",
                      "padding": "8px 6px", "fontSize": "0.72rem",
                      "color": "white", "fontWeight": "600"}
    thead = html.Thead(
        html.Tr(
            [html.Th("Linha DRE", style=th_style_label)]
            + [html.Th(m, style=th_style_month) for m in MONTH_LABELS]
            + [html.Th("Total", style=th_style_total)],
            style={"background": COLOR_BRAND_DK},
        )
    )

    rows: list = []

    def _line_month_from_df(lid_, m_label):
        row = df[df["id"] == lid_]
        if row.empty:
            return 0.0
        v = row[m_label].values[0]
        try:
            return float(v) if v is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    for line in DRE_LINES:
        lid = int(line["id"])
        is_formula = bool(line.get("is_formula"))
        is_tot     = bool(line.get("totalizador"))
        is_grand   = (lid == 19)

        line_cats   = _categorias_para_linha(lid, historical, nested, uuid_to_nome)
        has_cats    = bool(line_cats)
        is_expanded = lid in expanded_set

        # ── Main row ──────────────────────────────────────────────────────
        if has_cats and not is_formula:
            toggle_btn = html.Button(
                "▼" if is_expanded else "▶",
                id={"type": "orc-expand", "index": lid},
                n_clicks=0,
                style={"background": "none", "border": "none", "cursor": "pointer",
                       "fontSize": "0.7rem", "color": "#777", "padding": "0 6px 0 0"},
            )
        else:
            toggle_btn = html.Span(style={"display": "inline-block", "width": "14px"})

        label_cell_children = [toggle_btn, line["label"]]

        # Background e estilo da linha
        if is_grand:
            row_style = {"background": COLOR_BRAND_DK, "color": "white", "fontWeight": "700"}
            cell_color = "white"
        elif is_tot or is_formula:
            row_style = {"background": "#fdf0f0", "fontWeight": "600"}
            cell_color = "#333"
        else:
            row_style = {}
            cell_color = "#333"

        label_td = html.Td(
            label_cell_children,
            style={"padding": "6px 10px", "fontSize": "0.79rem",
                   "fontWeight": "600" if (is_tot or is_formula) else "400",
                   "whiteSpace": "nowrap", "color": cell_color},
        )

        # Células mensais
        month_cells = []
        line_total = 0.0
        for i, m_label in enumerate(MONTH_LABELS, start=1):
            if is_formula or is_grand:
                # Linhas fórmula usam o df (valores calculados com normalização correta)
                val = _line_month_from_df(lid, m_label)
                line_total += val
                month_cells.append(html.Td(
                    fmt_brl(val) if val else ("—" if not is_grand else fmt_brl(0)),
                    style={"textAlign": "right", "fontSize": "0.78rem",
                           "padding": "6px", "color": cell_color,
                           "whiteSpace": "nowrap"},
                ))
            elif has_cats:
                # Linha com subcategorias: soma do nested
                # Despesas (sinal==-1) exibidas como NEGATIVAS para coerência visual com a fórmula
                raw = sum(
                    float((nested.get(lid) or {}).get(cid, {}).get(i, 0.0) or 0.0)
                    for cid in (nested.get(lid) or {})
                )
                if line.get("sinal") == -1:
                    raw = -abs(raw)
                line_total += raw
                txt_color = "#c62828" if raw < 0 else "#333"
                extra = {"fontStyle": "italic", "opacity": "0.65"} if is_expanded else {}
                month_cells.append(html.Td(
                    fmt_brl(raw) if raw else "—",
                    style={"textAlign": "right", "fontSize": "0.78rem",
                           "padding": "6px", "color": txt_color,
                           "whiteSpace": "nowrap", **extra},
                ))
            else:
                # Linha editável diretamente (cat="")
                # Despesas: armazenadas como abs(), exibidas como -abs() para coerência visual
                seed = float((nested.get(lid) or {}).get("", {}).get(i, 0.0) or 0.0)
                if line.get("sinal") == -1:
                    seed = -abs(seed)
                line_total += seed
                month_cells.append(html.Td(
                    _orc_input(lid, "", i, seed),
                    style={"padding": "2px 4px"},
                ))

        total_td = html.Td(
            fmt_brl(line_total),
            style={"textAlign": "right", "fontWeight": "700",
                   "fontSize": "0.8rem", "padding": "6px",
                   "color": cell_color, "whiteSpace": "nowrap"},
        )

        rows.append(html.Tr([label_td, *month_cells, total_td], style=row_style))

        # ── Sub-rows (categorias) quando expandido ────────────────────────
        if has_cats and is_expanded and not is_formula:
            # + linha "sem categoria específica" ao final, sempre
            all_cats = line_cats + [{"cat_id": "", "label": "— Sem categoria específica"}]
            for cat in all_cats:
                cid = cat["cat_id"]
                sub_label = html.Td(
                    html.Span([
                        html.Span("↳  ", style={"color": "#999"}),
                        cat["label"],
                    ]),
                    style={"paddingLeft": "36px", "padding": "4px 10px 4px 36px",
                           "fontSize": "0.76rem", "color": "#555",
                           "whiteSpace": "nowrap", "maxWidth": "300px",
                           "overflow": "hidden", "textOverflow": "ellipsis",
                           "fontStyle": "italic" if cid == "" else "normal"},
                )
                sub_cells = []
                sub_total = 0.0
                is_despesa_line = line.get("sinal") == -1
                for i, m_label in enumerate(MONTH_LABELS, start=1):
                    val = float((nested.get(lid) or {}).get(cid, {}).get(i, 0.0) or 0.0)
                    if is_despesa_line:
                        val = -abs(val)
                    sub_total += val
                    sub_cells.append(html.Td(
                        _orc_input(lid, cid, i, val),
                        style={"padding": "2px 4px"},
                    ))
                sub_total_td = html.Td(
                    fmt_brl(sub_total) if sub_total else "—",
                    style={"textAlign": "right", "fontSize": "0.76rem",
                           "padding": "4px 6px", "color": "#666",
                           "whiteSpace": "nowrap"},
                )
                rows.append(html.Tr(
                    [sub_label, *sub_cells, sub_total_td],
                    style={"background": "#fafafa"},
                ))

    tbody = html.Tbody(rows)
    tbl = html.Table(
        [thead, tbody],
        style={"width": "100%", "borderCollapse": "collapse"},
        className="orc-table",
    )
    return html.Div(tbl, style={"overflowX": "auto"})


_DESPESA_LIDS = {2, 4, 6, 8, 12, 14, 15, 18}


def _coletar_inputs_para_nested(cell_values, cell_ids, base_nested: dict) -> dict:
    """Faz merge dos valores vindos dos inputs pattern-matched no nested base.
    Despesas são guardadas como abs() — o display em _build_orc_table_html mostra
    com sinal negativo para coerência visual com a fórmula da DRE.
    """
    nested = {lid: {c: dict(m) for c, m in cats.items()} for lid, cats in (base_nested or {}).items()}
    for val, id_dict in zip(cell_values or [], cell_ids or []):
        try:
            lid = int(id_dict["lid"])
            cat = str(id_dict["cat"] or "")
            mes = int(id_dict["mes"])
            v   = float(val or 0)
        except (KeyError, ValueError, TypeError):
            continue
        if lid in _DESPESA_LIDS:
            v = abs(v)
        nested.setdefault(lid, {}).setdefault(cat, {})[mes] = v
    return nested


@callback(
    Output("orc-contexto-collapse", "is_open"),
    Input("btn-toggle-contexto",    "n_clicks"),
    State("orc-contexto-collapse",  "is_open"),
    prevent_initial_call=True,
)
def toggle_contexto(_, is_open):
    return not is_open


@callback(
    Output("store-orc-expanded", "data"),
    Input({"type": "orc-expand", "index": ALL}, "n_clicks"),
    State("store-orc-expanded", "data"),
    prevent_initial_call=True,
)
def toggle_orc_row(_clicks, expanded):
    triggered = ctx.triggered_id
    if not triggered:
        return dash.no_update
    if not ctx.triggered[0].get("value"):
        return dash.no_update
    lid = int(triggered["index"])
    current = list(expanded or [])
    if lid in current:
        return [x for x in current if x != lid]
    return current + [lid]


@callback(
    Output("orc-tabela-container", "children"),
    Output("orc-status",           "children"),
    Output("store-orc-nested",     "data"),
    Input("orc-empresa",           "value"),
    Input("orc-ano",               "value"),
    Input("store-orc-expanded",    "data"),
    Input({"type": "orc-cell", "lid": ALL, "cat": ALL, "mes": ALL}, "value"),
    State({"type": "orc-cell", "lid": ALL, "cat": ALL, "mes": ALL}, "id"),
    State("store-orc-nested",      "data"),
)
def atualizar_tabela_orcamento(empresa, ano, expanded, cell_values, cell_ids, stored_nested):
    """Rebuild da tabela em 3 cenários:
    - empresa/ano mudou → recarrega do BQ
    - expand/collapse → snapshot dos inputs atuais + novo estado de expansão
    - load inicial → usa store (pode estar vazio)
    """
    if not empresa or not ano:
        return (html.P("Selecione empresa e ano.", className="text-muted p-3"),
                "", {})

    trigger = ctx.triggered_id
    stored = _nested_from_jsonable(stored_nested)

    if trigger in ("orc-empresa", "orc-ano") or not stored:
        # recarrega do BQ
        try:
            nested_loaded, _df = carregar_orcamento(int(ano), empresa)
        except Exception as e:
            return (html.P(f"Erro ao carregar: {str(e)[:160]}", className="text-danger p-3"),
                    "Erro ao carregar", {})
        nested = nested_loaded or {}
        status = "✅ Orçamento carregado do banco" if nested_loaded else \
                 "Sem orçamento salvo — edite ou gere com IA"
    else:
        # expand/collapse — preserva valores digitados
        nested = _coletar_inputs_para_nested(cell_values, cell_ids, stored)
        status = dash.no_update

    flat = _flatten_valores(nested)
    df   = _valores_para_df(flat, empresa, int(ano))
    tbl  = _build_orc_table_html(nested, df, int(ano), empresa, expanded or [])
    return tbl, status, nested


@callback(
    Output("orc-tabela-container", "children", allow_duplicate=True),
    Output("orc-status",           "children", allow_duplicate=True),
    Output("store-orc-nested",     "data",     allow_duplicate=True),
    Output("orc-toast",            "children", allow_duplicate=True),
    Output("orc-toast",            "is_open",  allow_duplicate=True),
    Output("orc-toast",            "icon",     allow_duplicate=True),
    Input("btn-gerar-ia",          "n_clicks"),
    State("orc-empresa",           "value"),
    State("orc-ano",               "value"),
    State("orc-contexto",          "value"),
    State("store-orc-expanded",    "data"),
    prevent_initial_call=True,
)
def gerar_ia(n_clicks, empresa, ano, contexto, expanded):
    if not n_clicks or not empresa or not ano:
        return (dash.no_update,) * 3 + (dash.no_update, False, dash.no_update)
    try:
        nested = gerar_orcamento_ia(int(ano), empresa, contexto_usuario=contexto or "")
        salvar_orcamento(int(ano), empresa, nested, fonte="ia")
        cache.clear()
        get_dre_previsto.cache_clear()
        flat = _flatten_valores(nested)
        df   = _valores_para_df(flat, empresa, int(ano))
        tbl  = _build_orc_table_html(nested, df, int(ano), empresa, expanded or [])
        return (tbl, "🤖 Gerado por IA e salvo", nested,
                "Orçamento gerado com sucesso pela IA!", True, "success")
    except Exception as e:
        msg = str(e)[:200]
        return (dash.no_update, dash.no_update, dash.no_update,
                f"Erro: {msg}", True, "danger")


@callback(
    Output("orc-toast",            "children",  allow_duplicate=True),
    Output("orc-toast",            "is_open",   allow_duplicate=True),
    Output("orc-toast",            "icon",      allow_duplicate=True),
    Output("orc-status",           "children",  allow_duplicate=True),
    Output("orc-tabela-container", "children",  allow_duplicate=True),
    Output("store-orc-nested",     "data",      allow_duplicate=True),
    Output("store-refresh",        "data",      allow_duplicate=True),
    Input("btn-salvar-orc", "n_clicks"),
    State({"type": "orc-cell", "lid": ALL, "cat": ALL, "mes": ALL}, "value"),
    State({"type": "orc-cell", "lid": ALL, "cat": ALL, "mes": ALL}, "id"),
    State("store-orc-nested",   "data"),
    State("orc-empresa",        "value"),
    State("orc-ano",            "value"),
    State("store-orc-expanded", "data"),
    State("store-refresh",      "data"),
    prevent_initial_call=True,
)
def salvar_orcamento_callback(n_clicks, cell_values, cell_ids, stored_nested,
                               empresa, ano, expanded, refresh_val):
    if not n_clicks or not empresa or not ano:
        return dash.no_update, False, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
    try:
        base   = _nested_from_jsonable(stored_nested)
        nested = _coletar_inputs_para_nested(cell_values, cell_ids, base)
        salvar_orcamento(int(ano), empresa, nested, fonte="manual")
        cache.clear()
        get_dre_previsto.cache_clear()
        flat = _flatten_valores(nested)
        df   = _valores_para_df(flat, empresa, int(ano))
        tbl  = _build_orc_table_html(nested, df, int(ano), empresa, expanded or [])
        new_refresh = (refresh_val or 0) + 1
        return ("Orçamento salvo com sucesso!", True, "success",
                "💾 Salvo manualmente", tbl, nested, new_refresh)
    except Exception as e:
        return (f"Erro ao salvar: {str(e)[:150]}", True, "danger",
                dash.no_update, dash.no_update, dash.no_update, dash.no_update)


# ---------------------------------------------------------------------------
# Callback — Modal Metodologia
# ---------------------------------------------------------------------------

@callback(
    Output("modal-metodologia", "is_open"),
    Input("btn-met-toggle", "n_clicks"),
    Input("btn-met-fechar", "n_clicks"),
    State("modal-metodologia", "is_open"),
    prevent_initial_call=True,
)
def toggle_metodologia(_n1, _n2, is_open):
    return not is_open


# ---------------------------------------------------------------------------
# Callbacks — Chat com os Dados
# ---------------------------------------------------------------------------

@callback(
    Output("chat-panel", "style"),
    Input("btn-chat-toggle", "n_clicks"),
    Input("btn-chat-fechar", "n_clicks"),
    State("chat-panel", "style"),
    prevent_initial_call=True,
)
def toggle_chat_panel(_n_toggle, _n_fechar, style):
    triggered = ctx.triggered_id
    hidden = {"display": "none", "position": "fixed", "bottom": "148px",
              "right": "24px", "width": "480px", "zIndex": 1049}
    visible = {**hidden, "display": "block"}
    if triggered == "btn-chat-fechar":
        return hidden
    return visible if (style or {}).get("display") == "none" else hidden


_TYPING_SENTINEL = "__typing__"


@callback(
    Output("store-chat", "data"),
    Output("chat-input", "value"),
    Input("btn-chat-enviar", "n_clicks"),
    Input("chat-input", "n_submit"),
    State("chat-input", "value"),
    State("store-chat", "data"),
    prevent_initial_call=True,
)
def adicionar_mensagem_usuario(_n_btn, _n_submit, texto, historico):
    """Passo 1: adiciona mensagem do usuário imediatamente + indicador de digitação."""
    if not texto or not texto.strip():
        return dash.no_update, dash.no_update
    texto     = texto.strip()
    historico = list(historico or _CHAT_WELCOME)
    historico.append({"role": "user", "content": texto})
    historico.append({"role": "assistant", "content": _TYPING_SENTINEL})
    return historico, ""


@callback(
    Output("store-chat", "data", allow_duplicate=True),
    Input("store-chat", "data"),
    State("dd-ano", "value"),
    State("store-company", "data"),
    prevent_initial_call=True,
)
def gerar_resposta_ia(historico, year, company):
    """Passo 2: chama a IA quando o sentinel estiver no store."""
    if not historico or historico[-1].get("content") != _TYPING_SENTINEL:
        return dash.no_update

    year    = year    or CURRENT_YEAR
    company = company or "ca_empresa_a"

    historico_clean = [m for m in historico if m.get("content") != _TYPING_SENTINEL]

    try:
        resposta = chat_bigquery(
            [{"role": m["role"], "content": m["content"]} for m in historico_clean],
            company,
            year,
        )
    except Exception as e:
        resposta = f"Erro ao processar: {str(e)[:120]}"

    historico_clean.append({"role": "assistant", "content": resposta})
    return historico_clean


@callback(
    Output("chat-messages", "children"),
    Input("store-chat", "data"),
)
def renderizar_chat(historico):
    if not historico:
        return _render_chat_bubbles(_CHAT_WELCOME)
    # Substitui sentinel por indicador visual de "digitando..."
    display = []
    for msg in historico:
        if msg.get("content") == _TYPING_SENTINEL:
            display.append({"role": "assistant", "content": "_Gerando resposta…_"})
        else:
            display.append(msg)
    return _render_chat_bubbles(display)


# ---------------------------------------------------------------------------
# Callbacks — Exportar CSV
# ---------------------------------------------------------------------------

@callback(
    Output("download-dre-csv", "data"),
    Input("btn-export-dre", "n_clicks"),
    State("store-dre", "data"),
    State("dd-ano", "value"),
    State("store-company", "data"),
    prevent_initial_call=True,
)
def exportar_dre_csv(n_clicks, dre_data, ano, empresa):
    if not n_clicks or not dre_data:
        return dash.no_update
    df = pd.read_json(dre_data, orient="records")
    cols = ["id", "label"] + MONTH_LABELS + ["TOTAL", "AH_YTD"]
    cols_present = [c for c in cols if c in df.columns]
    out = df[cols_present].rename(columns={"label": "Linha DRE", "TOTAL": "Total", "AH_YTD": "AH YTD (%)"})
    empresa_lbl = (empresa or "consolidado").replace(" ", "_")
    fname = f"dre_{empresa_lbl}_{ano or CURRENT_YEAR}.csv"
    return dcc.send_data_frame(out.to_csv, fname, index=False, sep=";", decimal=",", encoding="utf-8-sig")


@callback(
    Output("download-orc-csv", "data"),
    Input("btn-export-orc", "n_clicks"),
    State({"type": "orc-cell", "lid": ALL, "cat": ALL, "mes": ALL}, "value"),
    State({"type": "orc-cell", "lid": ALL, "cat": ALL, "mes": ALL}, "id"),
    State("store-orc-nested", "data"),
    State("orc-empresa", "value"),
    State("orc-ano", "value"),
    prevent_initial_call=True,
)
def exportar_orc_csv(n_clicks, cell_values, cell_ids, stored_nested, empresa, ano):
    if not n_clicks or not empresa or not ano:
        return dash.no_update

    base = _nested_from_jsonable(stored_nested)
    nested = _coletar_inputs_para_nested(cell_values, cell_ids, base)

    try:
        uuid_to_nome = _uuid_to_nome_para_empresa(empresa)
    except Exception:
        uuid_to_nome = {}

    line_label = {int(l["id"]): l["label"] for l in DRE_LINES}
    line_sinal = {int(l["id"]): l.get("sinal", 1) for l in DRE_LINES}

    rows: list[dict] = []
    for lid in sorted(nested.keys()):
        for cid, meses in (nested[lid] or {}).items():
            cat_label = _cat_label(cid, uuid_to_nome) if cid else "(linha)"
            row = {
                "linha_id": lid,
                "linha": line_label.get(lid, f"Linha {lid}"),
                "categoria": cat_label,
            }
            total = 0.0
            sinal_despesa = (line_sinal.get(lid, 1) == -1)
            for i, m_label in enumerate(MONTH_LABELS, start=1):
                v = float((meses or {}).get(i, 0.0) or 0.0)
                if sinal_despesa:
                    v = -abs(v)
                row[m_label] = v
                total += v
            row["Total"] = total
            rows.append(row)

    if not rows:
        rows = [{"linha_id": "", "linha": "(orçamento vazio)", "categoria": "",
                 **{m: 0 for m in MONTH_LABELS}, "Total": 0}]

    out = pd.DataFrame(rows, columns=["linha_id", "linha", "categoria", *MONTH_LABELS, "Total"])
    empresa_lbl = (empresa or "consolidado").replace(" ", "_")
    fname = f"orcamento_{empresa_lbl}_{ano}.csv"
    return dcc.send_data_frame(out.to_csv, fname, index=False, sep=";", decimal=",", encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# Run local
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=False)
