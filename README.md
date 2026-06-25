# Dashboard DRE — Plotly Dash + BigQuery + IA

Dashboard financeiro de **DRE (Demonstrativo de Resultado do Exercício)** multiempresa, com dados do ERP **Conta Azul** sincronizados no Google BigQuery, autenticação Google OAuth e recursos de IA generativa.

O DRE é calculado em **regime de caixa** (cada lançamento é atribuído ao mês em que foi efetivamente pago/recebido) e o projeto foi construído para o **setor de eventos**, cuja receita é fortemente sazonal — o que se reflete nas análises, na narrativa automática e nos prompts da IA.

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

## Pré-requisitos

- **Python 3.12** (ou compatível; ver `Dockerfile`)
- **Projeto Google Cloud com BigQuery** contendo os datasets do Conta Azul, e uma *service account* com acesso de leitura (e escrita no dataset de orçamentos). Aponte `GOOGLE_APPLICATION_CREDENTIALS` para o JSON da credencial.
- **Credenciais OAuth 2.0 do Google** (Client ID e Client Secret) para o login — crie em `console.cloud.google.com/apis/credentials`.
- **Chave da API Anthropic** (`ANTHROPIC_API_KEY`) para as funcionalidades de IA.

> Sem dados reais no BigQuery o app sobe normalmente, mas as telas ficam vazias.

## Como rodar

```bash
pip install -r requirements.txt
cp .env.example .env          # preencha as variáveis
cp allowed_users.json.example allowed_users.json   # e-mails autorizados
python app.py                 # http://localhost:8050
```

## Deploy

`cloudbuild.yaml` faz build da imagem, push para o Container Registry e deploy no Cloud Run automaticamente.

## Licença

Distribuído sob a licença MIT — veja o arquivo [LICENSE](LICENSE).

> Projeto em produção em ambiente corporativo; credenciais, e-mails e identificadores da empresa foram removidos desta versão pública.
