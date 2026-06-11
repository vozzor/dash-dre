# Dashboard DRE — Plotly Dash + BigQuery + IA

Dashboard financeiro de **DRE (Demonstrativo de Resultado do Exercício)** multiempresa, com dados do ERP **Conta Azul** sincronizados no Google BigQuery, autenticação Google OAuth e recursos de IA generativa.

## Funcionalidades

- DRE mensal/anual por empresa ou consolidado (3 empresas + visão consolidada)
- Realizado × Previsto, com drill-down por categoria em cada linha do DRE
- **Orçamento gerado por IA**: Claude analisa o histórico e propõe orçamento anual completo, editável e persistido no BigQuery
- **Narrativa automática**: resumo executivo do resultado do mês escrito por IA
- **Chat com os dados**: perguntas em linguagem natural viram consultas SQL no BigQuery
- Autenticação Google OAuth 2.0 com whitelist de e-mails
- Cache de consultas para performance

## Stack

| Camada | Tecnologia |
|---|---|
| Dashboard | Plotly Dash, Dash Bootstrap Components |
| Dados | Google BigQuery (dados do Conta Azul) |
| IA | Anthropic Claude (orçamento, narrativa, chat SQL) |
| Auth | Google OAuth 2.0 (Authlib) + whitelist |
| Infra | Docker, Google Cloud Run, Cloud Build (CI/CD) |

## Como rodar

```bash
pip install -r requirements.txt
cp .env.example .env          # preencha as variáveis
cp allowed_users.json.example allowed_users.json   # e-mails autorizados
python app.py                 # http://localhost:8050
```

## Deploy

`cloudbuild.yaml` faz build da imagem, push para o Container Registry e deploy no Cloud Run automaticamente.

> Projeto em produção em ambiente corporativo; credenciais, e-mails e identificadores da empresa foram removidos desta versão pública.
