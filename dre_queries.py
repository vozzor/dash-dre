"""
Módulo de consultas BigQuery para o DRE.
Agrega receitas e despesas por mês e linha do DRE, usando os campos entrada_dre
e IDs específicos de categorias para os itens sem mapeamento direto.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

import pandas as pd
from google.cloud import bigquery

PROJECT = os.environ.get("BQ_PROJECT", "meu-projeto-gcp")

# ---------------------------------------------------------------------------
# IDs de categorias mapeados explicitamente por linha do DRE
# ---------------------------------------------------------------------------

# Linha 1 — Receita Bruta
CAT_CORPORATE_REC      = "422a11cd-dab6-40d2-853d-f742c1fecb10"  # Segmento A - Receitas
CAT_DIVISAO_D_REC     = "20dd7e63-51de-4b63-87f5-4fb7532b9e55"  # Segmento B - Receitas
CAT_DIVERSOS_REC       = "35dca58e-611f-4189-9fe7-bc91cc5ce7ae"  # Diversos (receita) → vai para L17

# Linha 2 — Custos Operacionais
CAT_CORPORATE_CUSTO    = "7c7733be-a5a4-4fba-87c9-d0a2580d7421"  # Segmento A - Custos
CAT_DIVISAO_D_CUSTO   = "c89b100c-eb67-4b98-8c7f-3c6deb1fa304"  # Segmento B - Custos
CAT_TAXAS_CUSTOS       = "ebd49813-d8dd-4862-afa3-d2c4c8962af1"  # TAXAS - Custos
CAT_ADIANTAMENTO_EVENTOS = "0a316e23-ab61-4d6d-9e1f-ff3b3a7c5132"  # Adiantamento para eventos
CAT_DEVOLUCOES_EVENTOS = "bd77f885-a8ba-4452-ab1a-e316eaf1cbf4"  # Devoluções para eventos
CAT_PLATAFORMA_CUSTO       = "982f726b-295c-4207-ab07-e1aee41cfedf"  # Plataforma de gestão

# Linha 4 — Impostos sobre vendas (IRPJ/CSLL ficam na linha 12)
CAT_IRPJ               = "3ced0ed8-9e23-4961-8f8d-2a4f6d34e10d"  # Imposto IRPJ
CAT_CSLL               = "e445b13a-871f-4b7a-922c-231590d210c5"  # Imposto Contr Social (CSLL)

# Linha 6 — Despesas Operacionais (equipe operacional / funcionários)
CAT_DESP_VIAGEM        = "0b55582a-258e-4fa1-a6c6-afff9228a285"  # Despesas viagem
CAT_ENCARGOS_13        = "f5daec9b-dd35-4a5e-b1da-c2fe61560b76"  # Encargos - 13o salário
CAT_ENCARGOS_AMS       = "50aea380-bb02-4647-9bc2-767840db01c5"  # Encargos - Assistência Médica
CAT_ENCARGOS_EXAMES    = "66d38694-3d05-4cce-a19e-505e7d9c3b9e"  # Encargos - Exames
CAT_ENCARGOS_FERIAS    = "16bcad37-63a8-48b5-946b-84f21e603c72"  # Encargos - Férias
CAT_ENCARGOS_FGTS      = "ce119b9f-0f7b-45ad-bb8d-418c2455c332"  # Encargos - FGTS
CAT_ENCARGOS_INSS      = "75094876-8a05-41ef-9691-6c6ba5338172"  # Encargos - INSS
CAT_ENCARGOS_IRPF      = "ccc8d99e-375e-4b97-b1d6-d61c13cf7145"  # Encargos - IRPF
CAT_ENCARGOS_RESCISAO  = "de9718f2-19e8-4577-9b20-bbb7f3431d3e"  # Encargos - Rescisões
CAT_ENCARGOS_VA        = "7868dc9c-fe12-454b-8559-02cdee9d30cf"  # Encargos - Vale Alimentação
CAT_VALE_TRANSPORTE    = "221c5eb5-5af8-44a8-889b-1c03eba01c90"  # Encargos - Vale Transporte
CAT_FREELANCER         = "1fb47d2d-24c3-4744-84d8-fd95b48b312f"  # Freelancer
CAT_NAO_UTILIZAR_ENC   = "0ba35515-15f8-4126-bf31-f23109c101cd"  # NÃO UTILIZAR - Encargos
CAT_PPR                = "4e822ed4-85e5-40a2-817b-1388448f3605"  # PPR
CAT_PRO_LABORE_OP      = "15728ee9-567e-4306-b3fd-c95624f71408"  # Pro labore Operação
CAT_REMUNERACAO        = "901bd807-0750-4c8c-84c4-d8f219b980c3"  # Remuneração Funcionários
CAT_SEGURO_VIDA        = "b4c8f880-cf90-4292-b204-fb80d7c97887"  # Seguro de vida
CAT_TERCEIROS_PJ       = "b60aa8ca-b7e2-40b0-a1f5-425c2f9cdc7b"  # Terceiros PJ

# Linha 8 — Despesas Operacionais Holding
CAT_ALUGUEL_IPTU       = "c7e34c15-19ed-4e14-b093-f6c2a0181773"  # Aluguel e IPTU
CAT_AQUISICAO_EQUIP    = "0379326e-7810-48d0-9844-365f04547db3"  # Aquisição de Equipamentos
CAT_ASSESSORIAS        = "4f17e068-8816-4f8b-800a-6c0a1f31f638"  # Assessorias e Associações
CAT_CONFRATERNIZACOES  = "d2014a5b-b990-44ec-b896-caa214b19eb7"  # Confraternizações
CAT_CONSULTORIA        = "4c20d250-f42a-4f06-aaec-a705cd1b0f60"  # Consultoria
CAT_CONTABILIDADE      = "3b3d76dd-b3cd-4292-8e5f-aa254cc95617"  # Contabilidade
CAT_CORREIOS           = "80d2bac6-0674-424d-8b9e-2b49ec4e66c4"  # Correios
CAT_CURSOS             = "adbee378-38e0-4c94-886e-ca9d8d02c069"  # Cursos e Treinamentos
CAT_CAPTACAO           = "22381866-f57d-456b-8c15-3cd872621d79"  # Despesas de captação/prospecção
CAT_DESP_VIAGEM_SOCIOS = "4b8b9d6c-74f8-4982-9f80-aaf600eb25c6"  # Despesas viagens sócios
CAT_DIVERSOS_DESP      = "9d1ba8bd-a734-498a-8336-a750b8c8768d"  # Diversos (despesa)
CAT_ENERGIA_AGUA       = "a47ba8bb-845c-4999-a8e3-a81c66cad576"  # Energia Elétrica + Água
CAT_LIMPEZA            = "70425bfb-0e71-4d97-abe3-5734c1681bcf"  # Limpeza
CAT_MANUT_EQUIP        = "d22170d0-62f1-407e-86d5-fb36b8162748"  # Manutenção Equipamentos
CAT_MARKETING          = "4d86abd2-5ba3-4a1a-b1bd-668c39db377b"  # Marketing e Publicidade
CAT_MATERIAL_ESCRITORIO = "dd440cdf-45a2-4d67-9d47-87a40253ebc8"  # Material de Escritório
CAT_OBRAS              = "a3641daa-48cc-4a04-8c9f-b4bc246f09f2"  # Obras e benfeitorias
CAT_PREV_PRIVADA       = "16e9c03e-c037-4f18-a02a-e5c9d5f87521"  # Previdência Privada sócios
CAT_PRO_LABORE         = "07bbc602-b857-4c39-b688-c2689f61d655"  # Pro Labore (sócios)
CAT_SEGUROS            = "c4d836a8-a4d4-47e6-a01e-1a07aeb3af1a"  # Seguros
CAT_SERVICOS_TERCEIROS = "870baa51-02ca-488f-8f24-5b22c99f3f62"  # Serviços de Terceiros
CAT_SOFTWARES          = "9d68875a-5411-424f-8895-55d20697130c"  # Softwares
CAT_TAXAS_LICENCAS     = "641d4fba-5887-489f-bdd4-341a15aad9a9"  # Taxas e Licenças
CAT_TELEFONIA          = "2ff0629e-68e1-4e37-9c36-82b51e7e4ca8"  # Telefonia e Internet
CAT_TERCEIRIZADOS      = "2d5c1ef4-efe8-4e43-955f-aad211082d58"  # Terceirizados

# Linha 10 — Resultado Financeiro
CAT_RENDIMENTO_APLIC   = "36dad089-9c02-4d1e-ac52-d0b9b94a2c03"  # Rendimento aplicação
CAT_IMP_APLIC_FIN      = "11571139-5dfc-4500-834e-4f86f26ddd39"  # Impostos S/ Aplicações Financeiras

# Linha 14 — Reserva de Impostos
CAT_RESERVA_PIS_COFINS = "e48076a8-6bac-4dca-987f-45d19c255748"  # Reserva de Impostos - PIS e COFINS

# Linha 15 — Reserva de Impostos LL
CAT_RESERVA_LL         = "70fd7db1-cd6f-45ec-a11a-afd2d7fa7a3b"  # Reserva de Impostos LL - IRPJ e CSLL

# Linha 17 — Entradas não operacionais
CAT_DISTRIB_INI        = "9745581d-43c8-40ef-86ac-b69e890f3cd1"  # Distribuição Empresa B
CAT_OUTRAS_REC_EXTRA   = "08a0e3ec-21e0-44d7-aa33-7c1cb51eee60"  # Outras receitas - extra fluxo

# Linha 17 — Entradas não operacionais
CAT_REEMBOLSO          = "88f167f2-6dd3-46f8-bcb8-a33847f5d092"  # Reembolso → vai para L1

# Linha 10 — Resultado Financeiro (despesas adicionais)
CAT_TARIFAS_BANCARIAS  = "b1238040-15b2-4095-8c01-9606927fb156"  # Tarifas Bancárias (OUTRAS_DESPESAS mas é financeiro)

# Linha 18 — Saídas Não Operacionais
CAT_OUTRAS_DESP_EXTRA  = "f1c5e9b0-bbbb-46f1-bb88-c24b720536a0"  # Outras Despesas - extra fluxo
CAT_DISTR_LUCROS_EXTRA = "1b437dd3-9ec5-43ed-9001-611c2a068a35"  # Distr Lucros - EXTRA


# ---------------------------------------------------------------------------
# Saldos iniciais de caixa por ano (Saldo do Mês Anterior em Jan, do CA)
# Atualizar anualmente com o valor real do relatório Conta Azul
# ---------------------------------------------------------------------------
SALDOS_INICIAIS: dict[str, dict[int, float]] = {
    "ca_empresa_a": {
        2022: 0.0,
        2023: 0.0,
        2024: 0.0,
        2025: 0.0,
        2026: 0.0,
    },
    "ca_empresa_b": {
        2022: 0.0,
        2023: 0.0,
        2024: 0.0,
        2025: 0.0,
        2026: 0.0,
    },
    "ca_empresa_c": {
        2022: 0.0,
        2023: 0.0,
        2024: 0.0,
        2025: 0.0,
        2026: 0.0,
    },
}

# Datasets que compõem o consolidado
_CONSOLIDADO_DATASETS = ["ca_empresa_a", "ca_empresa_b", "ca_empresa_c"]

# Linha 8 — Distr Lucros Socios (Conta Azul coloca em Despesas Holding)
CAT_DISTR_LUCROS_SOCIOS = "ea998c79-4628-41b2-a893-e5c2daa00082"  # Distr Lucros Socios

# ---------------------------------------------------------------------------
# ca_empresa_a — categorias sem entrada_dre não cobertas anteriormente
# ---------------------------------------------------------------------------
CAT_PATROCINIOS         = "45609487-234e-40fd-a1ce-b059b155d7f5"  # PATROCÍNIOS → L1
CAT_EMPRESTIMOS         = "0ec1eb45-99d0-41a7-8599-2a087877b1da"  # Empréstimos → L17
CAT_AMORTIZACAO         = "be24ff45-1029-4e44-aaae-00b728394a4c"  # Amortização Empréstimos → L18
CAT_AQUISICAO_EMP       = "919402cf-a3e3-4cdc-be71-5fb008388d42"  # Aquisição de Empresa → L18

# ---------------------------------------------------------------------------
# ca_empresa_b — categorias sem entrada_dre (UUIDs distintos de ca_empresa_a)
# ---------------------------------------------------------------------------

# Linha 2 — Custos Operacionais (ca_empresa_b)
CAT_CUSTOS_EVENTOS_INI   = "28b8f97b-a88a-4dc2-8ddc-f719e7d8fa3a"  # Custos com Eventos
CAT_REEMB_INSCRICAO_INI  = "014c1f94-6f75-4739-a2a3-44457cb0e3b3"  # Reembolso de Inscrição
CAT_REEMB_PATROC_INI     = "5b028e18-d14c-4cbd-bc48-ab1746162ed1"  # Reembolso Patrocínio
CAT_CORPORATE_CUSTO_INI  = "d0b7e0e2-29d9-412a-a906-048a91f4e754"  # Segmento A - Custo

# Linha 4 / 12 — Impostos ca_empresa_b (UUIDs distintos; têm entrada_dre=IMPOSTOS_SOBRE_VENDAS
#                mas precisam ser excluídos de L4 e redirecionados para L12)
CAT_IRPJ_INI             = "f1efe48c-5dfa-46a2-a70c-fdef71c8a2b7"  # Imposto IRPJ (Empresa B)
CAT_CSLL_INI             = "f7cd6cd7-0800-47f6-a8dc-0a7befdfb64d"  # Imposto Contr Social (Empresa B)
CAT_ISS_INI              = "63b97e82-e4d9-4b35-94b9-cdf0aa4fcee2"  # Imposto ISS (Empresa B) → L4

# Linha 2 — Custos Operacionais adicionais (ca_empresa_b) — têm entrada_dre=DESPESAS_OPERACIONAIS_NIVEL_2
#            mas pertencem ao custo direto, não às despesas de equipe (L6)
CAT_PLATAFORMA_EAD_DESP_INI = "cc6fe194-0d7a-4f5c-b93e-61eaa04ae407"  # Plataforma EAD (despesa)
CAT_HONORARIOS_INI        = "142ffda8-8e59-4c53-a467-99024878786a"  # Honorários Consultoria → L2
CAT_TAXAS_CARTAO_INI      = "0dd62b0e-31a1-4084-beda-a1d801528711"  # Taxas cartão de crédito → L2

# Linha 6 — Despesas Operacionais (ca_empresa_b)
CAT_PPR_INI              = "3ab8dcd8-0257-4c78-b214-4b638d6beca1"  # PPR
CAT_TERCEIROS_PJ_INI     = "2cf2a107-c4ff-41df-8e97-4fcc345cb07d"  # Terceiros PJ

# Linha 4 — Impostos (ca_empresa_b)
CAT_COFINS_INI           = "1c18b6a1-1ac3-4e85-8330-a2903f630164"  # Imposto COFINS
CAT_PIS_INI              = "c86f3ad9-efdd-4cff-97eb-b12b86bfbb7f"  # Imposto PIS

# Linha 8 — Despesas Operacionais Holding (ca_empresa_b)
CAT_SOFTWARE_INI         = "a5edcc34-13bf-4b0d-8222-b4c2b7a47932"  # Software
CAT_AQUISICAO_EQUIP_INI  = "e6b0c653-4e5c-498f-bdcf-7ac4cb5e3e78"  # Aquisição de equipamentos
CAT_CONSULTORIA_INI      = "ce4dec85-2426-45bd-b6dd-3fd4e8377843"  # Consultoria
CAT_CONFRATERNIZACOES_INI = "dec4b42b-a745-4182-841b-4e0fc305ba7a"  # Confraternizacoes
CAT_HONORARIOS_JUR_INI   = "7f2defc2-53b1-47f4-9432-5300e4233848"  # Honorários Jurídicos
CAT_SEGUROS_INI          = "5af91fa3-c3ae-4aa3-9776-822d5534d569"  # seguros → L8 (tem OUTRAS_DESPESAS_NAO_OPERACIONAIS mas é Holding)

# Linha 18 — Saídas Não Operacionais adicionais (ca_empresa_b)
CAT_DESP_DIVERSA_INI     = "fad6037e-98ab-46de-9099-a318dcbb0027"  # Despesa Diversa → L18

# Linha 14 / 15 — Reservas de Impostos (ca_empresa_b)
CAT_RESERVA_PIS_COFINS_INI = "1c8e3d41-6e60-4c7c-8616-2c4a2d79f732"  # Reserva PIS e COFINS
CAT_RESERVA_LL_INI         = "481ced6d-323b-45ed-bbcc-a531125bada7"  # Reserva IRPJ e CSLL

# Linha 1 — Receita Bruta (ca_empresa_b)
CAT_CORPORATE_REC_INI    = "9bb7b8eb-e661-4068-8968-6116de7914a9"  # Segmento A Receita → L1

# Linha 17 — Entradas não operacionais (ca_empresa_b)
CAT_REC_DIVERSA_INI      = "1f2cc03d-4812-401d-b28b-2ac1708a2c7e"  # Receita Diversa

# Linha 2 — Custo Operacional adicional (ca_empresa_b)
CAT_ESTORNO_PLATAFORMA_EAD       = "a957acf1-7a60-435c-8967-73c71c4effef"  # Estorno venda plataforma EAD → L2 (sem entrada_dre)

# Linha 18 — Saídas Não Operacionais (ca_empresa_b)
CAT_DISTR_LUCROS_EXTRA_INI = "06c88a5d-ab96-4499-8279-256270a2e6ba"  # Distr lucros - EXTRA


# ---------------------------------------------------------------------------
# ca_empresa_c — categorias específicas (dataset ca_empresa_c)
# ---------------------------------------------------------------------------

# Linha 1 — Receita Bruta (ca_empresa_c) — têm entrada_dre=OUTRAS_RECEITAS_NAO_OPERACIONAIS
CAT_HOSPEDAGEM_REC_MADE     = "6723af39-82c4-40b2-887b-16e686f899fe"  # Hospedagem (receita)
CAT_PASSAGENS_REC_MADE      = "45e10f81-e8a3-4abb-98e5-c86dc730adac"  # Passagens Aereas (receita)
CAT_COMISSOES_MADE          = "3c8b4166-6cc4-4d63-a319-92a94c087227"  # Comissões
CAT_TRANSFER_MADE           = "1e0d36c9-4e4c-4103-9430-6bf3e26e1fc7"  # Transfer e Transportes
CAT_SEGURO_REC_MADE         = "c8ca4a24-be32-4fa3-8144-b6648a34c6e5"  # Seguro (receita)
CAT_EVENTO_PROPRIO_MADE     = "4c45c7cb-be84-4b40-b9f3-d8618123ec8f"  # Evento Próprio

# Linha 2 — Custos Operacionais (ca_empresa_c) — têm entrada_dre=DESPESAS_OPERACIONAIS_NIVEL_2
CAT_HOSPEDAGEM_DESP_MADE    = "2f065425-f4d6-4695-b837-b3c717cd9aae"  # Hospedagem (despesa)
CAT_PASSAGENS_DESP_MADE     = "6c40f8cd-5135-422f-a54f-92b606d16c1d"  # Passagens Aéreas (despesa)
CAT_SEGURO_DESP_MADE        = "f72ee248-9e01-4bb6-ad3e-56db57b3b612"  # Seguro (despesa)
CAT_CUSTOS_EVENTOS_MADE     = "3b1ec949-767b-4b12-adac-f8a5c0a6086f"  # Custos Eventos
CAT_CUSTOS_CORPORATE_MADE   = "f50b78bb-a936-4468-bec3-b3af317fd3aa"  # Custos Corporate
CAT_TRANSFER_DESP_MADE      = "83d8af4c-dab0-4ae5-bcf9-d4b3c1718ee4"  # Transfer e Transportes (despesa)

# Linha 4 — Impostos (ca_empresa_c) — sem entrada_dre
CAT_ISS_MADE                = "e68f13ad-dffb-430d-a1d5-10d2b12c2678"  # ISS
CAT_COFINS_MADE             = "941c3be0-d3a3-464c-baa9-a038291136d4"  # COFINS
CAT_PIS_MADE                = "12a31bb5-13b8-4403-b6b2-4297856852b9"  # PIS
CAT_SIMPLES_MADE            = "a105ce12-1fed-459c-97ea-dcd111fdb8c1"  # Simples Nacional

# Linha 6 — Despesas Operacionais (ca_empresa_c)
CAT_PPR_MADE                = "9de8dee2-0eb0-4256-8638-92aba5758f98"  # PPR

# Linha 8 — Despesas Operacionais Holding (ca_empresa_c)
CAT_DISTR_LUCROS_SOCIOS_MADE = "f3a4ca91-7071-4638-913f-751b2f38402f"  # Distr Lucros Socios
CAT_TAXAS_CARTAO_MADE        = "36ed2bbc-d110-41e1-829d-b0035b3dcdc9"  # Taxas cartão de crédito
CAT_SEGURO_VIDA_MADE         = "13d90a8f-ba97-4167-ad33-e4df48a200df"  # Seguro de vida
CAT_TERCEIRIZADOS_MADE       = "94e7290b-15a7-4614-9d92-2b9f53d7c56b"  # Terceirizados
CAT_ENC_FERIAS_MADE          = "de4c8f91-d631-413b-8e03-31f46ff75215"  # Encargos Férias
CAT_ENC_RESCISOES_MADE       = "221d4a1d-4a43-4a6b-8f2b-19b934864e83"  # Encargos Rescisões
CAT_ENC_IRPF_MADE            = "b4d3a75b-601d-45c8-a48e-21fe84f3fadd"  # Encargos IRPF
CAT_CONTRIB_SINDICAL_MADE    = "9b313328-5bc1-4f67-abbb-34217a8c8bce"  # Contrib Sindical
CAT_ADIANT_VIAGENS_MADE      = "ba8416b2-d43f-4822-81bd-b7ea5a68d8b6"  # Adiantamento Viagens
CAT_ALIMENTACAO_MADE         = "6ae3f500-bb6a-4606-a2c2-9dd3ad03ee19"  # Alimentação

# Linha 10 — Resultado Financeiro (ca_empresa_c)
CAT_RENDIMENTO_APLIC_MADE   = "a90bcc89-9a2d-47a5-8a15-8b4474f102b7"  # Rendimento Aplicação
CAT_APLIC_FIN_MADE          = "cb6fae84-be84-402c-95c1-f014fc391e37"  # Aplicações Financeiras
CAT_TARIFAS_BANC_DESP_MADE  = "92c5d1c7-9255-4e22-8c8d-bbad5afa2e7a"  # Tarifas Bancárias (desp)
CAT_DESP_BANC_MADE          = "e8a78af2-c012-408b-a5d3-db6b0ddd86dd"  # Despesas Bancárias
CAT_TARIFAS_BANC_REC_MADE   = "ee278203-5a67-499f-8a2a-0d74fa78a627"  # Tarifas Bancárias (rec)

# Linha 12 — Impostos Lucro Líquido (ca_empresa_c)
CAT_IRPJ_MADE               = "b53081a2-f4f0-417b-ae4f-c860ac4b9e8b"  # IRPJ
CAT_CSLL_MADE               = "b6f171cd-987c-4758-aba5-c5c8e1e6362c"  # CSLL

# Linha 14 — Reserva de Impostos (ca_empresa_c)
CAT_RESERVA_PIS_COFINS_MADE = "2d7269b5-a79a-4f5b-9b01-f5ca40b6fb74"  # Reserva PIS e COFINS

# Linha 15 — Reserva de Impostos LL (ca_empresa_c)
CAT_RESERVA_LL_MADE         = "2e7ee84a-6955-49cb-99f2-5c4fce4f430f"  # Reserva IRPJ e CSLL

# Linha 18 — Saídas Não Operacionais (ca_empresa_c)
CAT_DISTR_LUCROS_EXTRA_MADE = "a3d28666-b954-46ac-b1ee-1b93e89181cc"  # Distribuição de lucros EXTRA


# ---------------------------------------------------------------------------
# Mapeamento das linhas do DRE
# ---------------------------------------------------------------------------

DRE_LINES: list[dict] = [
    {
        "id": 1, "label": "Receita Bruta",
        "tipo_dados": "RECEITA",
        "entradas_dre": ["RECEITA_VENDA_PRODUTOS_SERVICOS", "RECEITA_FRETES_ENTREGAS",
                         "DESCONTOS_INCONDICIONAIS"],
        "cat_ids_incluir": [
            CAT_CORPORATE_REC, CAT_DIVISAO_D_REC, CAT_REEMBOLSO, CAT_PATROCINIOS,
            # ca_empresa_b
            CAT_CORPORATE_REC_INI,
            # ca_empresa_c — receitas com entrada_dre=OUTRAS_RECEITAS_NAO_OPERACIONAIS
            CAT_HOSPEDAGEM_REC_MADE, CAT_PASSAGENS_REC_MADE, CAT_COMISSOES_MADE,
            CAT_TRANSFER_MADE, CAT_SEGURO_REC_MADE, CAT_EVENTO_PROPRIO_MADE,
        ],
        "cat_ids_excluir": [],
        "is_formula": False, "sinal": 1, "quadro": 1, "totalizador": False,
    },
    {
        "id": 2, "label": "(-) Custos Operacionais",
        "tipo_dados": "DESPESA",
        "entradas_dre": ["CUSTO_VENDAS_PRODUTOS", "CUSTO_SERVICOS_PRESTADOS"],
        "cat_ids_incluir": [
            CAT_CORPORATE_CUSTO, CAT_DIVISAO_D_CUSTO, CAT_TAXAS_CUSTOS,
            CAT_ADIANTAMENTO_EVENTOS, CAT_DEVOLUCOES_EVENTOS, CAT_PLATAFORMA_CUSTO,
            # ca_empresa_b
            CAT_CUSTOS_EVENTOS_INI, CAT_REEMB_INSCRICAO_INI,
            CAT_REEMB_PATROC_INI, CAT_CORPORATE_CUSTO_INI,
            CAT_PLATAFORMA_EAD_DESP_INI, CAT_HONORARIOS_INI, CAT_TAXAS_CARTAO_INI,
            CAT_ESTORNO_PLATAFORMA_EAD,
            # ca_empresa_c — custos diretos com entrada_dre=DESPESAS_OPERACIONAIS_NIVEL_2
            CAT_HOSPEDAGEM_DESP_MADE, CAT_PASSAGENS_DESP_MADE, CAT_SEGURO_DESP_MADE,
            CAT_CUSTOS_EVENTOS_MADE, CAT_CUSTOS_CORPORATE_MADE, CAT_TRANSFER_DESP_MADE,
        ],
        "cat_ids_excluir": [],
        "is_formula": False, "sinal": -1, "quadro": 1, "totalizador": False,
    },
    {
        "id": 3, "label": "(=) Receita Líquida",
        "formula": "1 - 2",
        "is_formula": True, "sinal": 1, "quadro": 1, "totalizador": True,
    },
    {
        "id": 4, "label": "(-) Impostos",
        "tipo_dados": "DESPESA",
        "entradas_dre": ["IMPOSTOS_SOBRE_VENDAS"],
        "cat_ids_incluir": [
            CAT_ISS_INI, CAT_COFINS_INI, CAT_PIS_INI,
            # ca_empresa_c — sem entrada_dre
            CAT_ISS_MADE, CAT_COFINS_MADE, CAT_PIS_MADE, CAT_SIMPLES_MADE,
        ],
        "cat_ids_excluir": [
            CAT_IRPJ, CAT_CSLL, CAT_IRPJ_INI, CAT_CSLL_INI,
            CAT_IRPJ_MADE, CAT_CSLL_MADE,  # IRPJ/CSLL → L12
        ],
        "is_formula": False, "sinal": -1, "quadro": 1, "totalizador": False,
    },
    {
        "id": 5, "label": "(=) Resultado Bruto",
        "formula": "3 - 4",
        "is_formula": True, "sinal": 1, "quadro": 1, "totalizador": True,
    },
    {
        "id": 6, "label": "(-) Despesas Operacionais",
        "tipo_dados": "DESPESA",
        "entradas_dre": ["DESPESAS_OPERACIONAIS_NIVEL_2"],
        "cat_ids_incluir": [
            CAT_DESP_VIAGEM,
            CAT_ENCARGOS_13, CAT_ENCARGOS_AMS, CAT_ENCARGOS_EXAMES,
            CAT_ENCARGOS_FERIAS, CAT_ENCARGOS_FGTS, CAT_ENCARGOS_INSS,
            CAT_ENCARGOS_IRPF, CAT_ENCARGOS_RESCISAO, CAT_ENCARGOS_VA,
            CAT_VALE_TRANSPORTE,
            CAT_FREELANCER, CAT_NAO_UTILIZAR_ENC,
            CAT_PPR, CAT_PRO_LABORE_OP, CAT_REMUNERACAO,
            CAT_SEGURO_VIDA, CAT_TERCEIROS_PJ,
            # ca_empresa_b
            CAT_PPR_INI, CAT_TERCEIROS_PJ_INI,
            # ca_empresa_c
            CAT_PPR_MADE,
        ],
        # Prev Privada tem entrada_dre=DESPESAS_OPERACIONAIS_NIVEL_2 mas vai para L8
        # Adiantamento tem entrada_dre=DESPESAS_OPERACIONAIS_NIVEL_2 mas vai para L2 (Custos)
        # ca_empresa_c: custos diretos de viagem/hospedagem/seguro têm DESPESAS_OPERACIONAIS_NIVEL_2 mas vão para L2
        "cat_ids_excluir": [
            CAT_PREV_PRIVADA, CAT_ADIANTAMENTO_EVENTOS,
            # ca_empresa_b: plataforma EAD tem DESPESAS_OPERACIONAIS_NIVEL_2 mas vai para L2
            CAT_PLATAFORMA_EAD_DESP_INI, CAT_HONORARIOS_INI, CAT_TAXAS_CARTAO_INI,
            # ca_empresa_c: custos diretos de viagem/hospedagem/seguro têm DESPESAS_OPERACIONAIS_NIVEL_2 mas vão para L2
            CAT_HOSPEDAGEM_DESP_MADE, CAT_PASSAGENS_DESP_MADE, CAT_SEGURO_DESP_MADE,
            CAT_CUSTOS_EVENTOS_MADE, CAT_CUSTOS_CORPORATE_MADE, CAT_TRANSFER_DESP_MADE,
        ],
        "is_formula": False, "sinal": -1, "quadro": 1, "totalizador": False,
    },
    {
        "id": 7, "label": "(=) Lucro Operacional",
        "formula": "5 - 6",
        "is_formula": True, "sinal": 1, "quadro": 2, "totalizador": True,
    },
    {
        "id": 8, "label": "(-) Despesas Operacionais Holding",
        "tipo_dados": "DESPESA",
        "entradas_dre": ["DESPESAS_ADMINISTRATIVAS"],
        "cat_ids_incluir": [
            CAT_ALUGUEL_IPTU, CAT_AQUISICAO_EQUIP, CAT_ASSESSORIAS,
            CAT_CONFRATERNIZACOES, CAT_CONSULTORIA, CAT_CONTABILIDADE,
            CAT_CORREIOS, CAT_CURSOS, CAT_CAPTACAO,
            CAT_DESP_VIAGEM_SOCIOS, CAT_DIVERSOS_DESP,
            CAT_ENERGIA_AGUA, CAT_LIMPEZA, CAT_MANUT_EQUIP,
            CAT_MARKETING, CAT_MATERIAL_ESCRITORIO, CAT_OBRAS,
            CAT_PREV_PRIVADA, CAT_PRO_LABORE,
            CAT_SEGUROS, CAT_SERVICOS_TERCEIROS, CAT_SOFTWARES,
            CAT_TAXAS_LICENCAS, CAT_TELEFONIA, CAT_TERCEIRIZADOS,
            CAT_DISTR_LUCROS_SOCIOS,
            # ca_empresa_b
            CAT_SOFTWARE_INI, CAT_AQUISICAO_EQUIP_INI,
            CAT_CONSULTORIA_INI, CAT_CONFRATERNIZACOES_INI, CAT_HONORARIOS_JUR_INI,
            CAT_SEGUROS_INI,
            # ca_empresa_c — itens com OUTRAS_DESPESAS_NAO_OPERACIONAIS ou sem entrada_dre
            CAT_DISTR_LUCROS_SOCIOS_MADE, CAT_TAXAS_CARTAO_MADE, CAT_SEGURO_VIDA_MADE,
            CAT_TERCEIRIZADOS_MADE, CAT_ENC_FERIAS_MADE, CAT_ENC_RESCISOES_MADE,
            CAT_ENC_IRPF_MADE, CAT_CONTRIB_SINDICAL_MADE,
            CAT_ADIANT_VIAGENS_MADE, CAT_ALIMENTACAO_MADE,
        ],
        # PPR tem entrada_dre=DESPESAS_ADMINISTRATIVAS mas vai para L6 (Desp Operacionais)
        # NÃO UTILIZAR Encargos idem — vai para L6
        # ca_empresa_c: Distr Lucros EXTRA tem DESPESAS_ADMINISTRATIVAS mas vai para L18
        "cat_ids_excluir": [CAT_PPR, CAT_NAO_UTILIZAR_ENC, CAT_DISTR_LUCROS_EXTRA_MADE],
        "is_formula": False, "sinal": -1, "quadro": 2, "totalizador": False,
    },
    {
        "id": 9, "label": "(=) Lucro Operacional Consolidado",
        "formula": "7 - 8",
        "is_formula": True, "sinal": 1, "quadro": 2, "totalizador": True,
    },
    {
        "id": 10, "label": "(+) Resultado Financeiro",
        "tipo_dados": "RESULTADO_FINANCEIRO",
        "entradas_dre_rec": ["RECEITAS_RENDIMENTOS_FINANCEIROS"],
        "cat_ids_rec": [
            CAT_RENDIMENTO_APLIC,
            # ca_empresa_c — têm entrada_dre=OUTRAS_RECEITAS_NAO_OPERACIONAIS
            CAT_RENDIMENTO_APLIC_MADE, CAT_APLIC_FIN_MADE, CAT_TARIFAS_BANC_REC_MADE,
        ],
        "entradas_dre_desp": ["DESPESSAS_FINANCEIRAS"],
        "cat_ids_desp": [
            CAT_IMP_APLIC_FIN, CAT_TARIFAS_BANCARIAS,
            # ca_empresa_c — têm entrada_dre=OUTRAS_DESPESAS_NAO_OPERACIONAIS
            CAT_TARIFAS_BANC_DESP_MADE, CAT_DESP_BANC_MADE,
        ],
        "is_formula": False, "sinal": 1, "quadro": 2, "totalizador": False,
    },
    {
        "id": 11, "label": "(=) LAIR",
        "formula": "9 + 10",
        "is_formula": True, "sinal": 1, "quadro": 2, "totalizador": True,
    },
    {
        "id": 12, "label": "(-) Impostos Lucro Líquido",
        "tipo_dados": "DESPESA",
        "entradas_dre": [],
        "cat_ids_incluir": [
            CAT_IRPJ, CAT_CSLL, CAT_IRPJ_INI, CAT_CSLL_INI,
            CAT_IRPJ_MADE, CAT_CSLL_MADE,
        ],
        "cat_ids_excluir": [],
        "is_formula": False, "sinal": -1, "quadro": 3, "totalizador": False,
    },
    {
        "id": 13, "label": "(=) Lucro Líquido (Geração de Caixa)",
        "formula": "11 - 12",
        "is_formula": True, "sinal": 1, "quadro": 3, "totalizador": True,
    },
    {
        "id": 14, "label": "(-) Reserva de Impostos",
        "tipo_dados": "DESPESA",
        "entradas_dre": [],
        "cat_ids_incluir": [
            CAT_RESERVA_PIS_COFINS, CAT_RESERVA_PIS_COFINS_INI,
            CAT_RESERVA_PIS_COFINS_MADE,
        ],
        "cat_ids_excluir": [],
        "is_formula": False, "sinal": -1, "quadro": 3, "totalizador": False,
    },
    {
        "id": 15, "label": "(-) Reserva de Impostos LL",
        "tipo_dados": "DESPESA",
        "entradas_dre": [],
        "cat_ids_incluir": [CAT_RESERVA_LL, CAT_RESERVA_LL_INI, CAT_RESERVA_LL_MADE],
        "cat_ids_excluir": [],
        "is_formula": False, "sinal": -1, "quadro": 3, "totalizador": False,
    },
    {
        "id": 16, "label": "(=) Lucro Líquido após Reservas",
        "formula": "13 - 14 - 15",
        "is_formula": True, "sinal": 1, "quadro": 3, "totalizador": True,
    },
    {
        "id": 17, "label": "(+) Entradas não operacionais",
        "tipo_dados": "RECEITA",
        "entradas_dre": ["OUTRAS_RECEITAS_NAO_OPERACIONAIS"],
        "cat_ids_incluir": [
            CAT_DISTRIB_INI, CAT_OUTRAS_REC_EXTRA,
            # ca_empresa_a
            CAT_EMPRESTIMOS,
            # ca_empresa_b
            CAT_REC_DIVERSA_INI,
        ],
        # Reembolso tem entrada_dre=OUTRAS_RECEITAS_NAO_OPERACIONAIS mas vai para L1 (Conta Azul)
        # ca_empresa_c: receitas de viagem/seguro/comissão vão para L1; financeiras vão para L10
        "cat_ids_excluir": [
            CAT_REEMBOLSO,
            # ca_empresa_b: CORPORATE Receita tem OUTRAS_RECEITAS_NAO_OPERACIONAIS mas vai para L1
            CAT_CORPORATE_REC_INI,
            CAT_HOSPEDAGEM_REC_MADE, CAT_PASSAGENS_REC_MADE, CAT_COMISSOES_MADE,
            CAT_TRANSFER_MADE, CAT_SEGURO_REC_MADE, CAT_EVENTO_PROPRIO_MADE,
            CAT_RENDIMENTO_APLIC_MADE, CAT_APLIC_FIN_MADE, CAT_TARIFAS_BANC_REC_MADE,
        ],
        "is_formula": False, "sinal": 1, "quadro": 3, "totalizador": False,
    },
    {
        "id": 18, "label": "(-) Saídas Não Operacionais",
        "tipo_dados": "DESPESA",
        "entradas_dre": ["OUTRAS_DESPESAS_NAO_OPERACIONAIS"],
        "cat_ids_incluir": [
            CAT_OUTRAS_DESP_EXTRA, CAT_DISTR_LUCROS_EXTRA,
            # ca_empresa_b
            CAT_DISTR_LUCROS_EXTRA_INI, CAT_DESP_DIVERSA_INI,
            # ca_empresa_a
            CAT_AMORTIZACAO, CAT_AQUISICAO_EMP,
            # ca_empresa_c — Distr Lucros EXTRA tem DESPESAS_ADMINISTRATIVAS, redirecionado aqui
            CAT_DISTR_LUCROS_EXTRA_MADE,
        ],
        # CAT_TARIFAS_BANCARIAS → L10. CAT_SERVICOS_TERCEIROS → L8 (entrada_dre erroneamente OUTRAS_DESPESAS)
        # ca_empresa_b: seguros tem OUTRAS_DESPESAS_NAO_OPERACIONAIS mas vai para L8; estorno EAD vai para L2
        # ca_empresa_c: vários itens com OUTRAS_DESPESAS_NAO_OPERACIONAIS redirecionados para L8 e L10
        "cat_ids_excluir": [
            CAT_TARIFAS_BANCARIAS, CAT_SERVICOS_TERCEIROS,
            CAT_SEGUROS_INI, CAT_ESTORNO_PLATAFORMA_EAD,                  # ca_empresa_b → L8, L2
            CAT_TARIFAS_BANC_DESP_MADE, CAT_DESP_BANC_MADE,        # → L10
            CAT_DISTR_LUCROS_SOCIOS_MADE, CAT_PPR_MADE,             # → L8, L6
            CAT_ENC_FERIAS_MADE, CAT_ENC_RESCISOES_MADE,            # → L8
            CAT_ENC_IRPF_MADE, CAT_CONTRIB_SINDICAL_MADE,           # → L8
            CAT_ADIANT_VIAGENS_MADE, CAT_ALIMENTACAO_MADE,          # → L8
        ],
        "is_formula": False, "sinal": -1, "quadro": 3, "totalizador": False,
    },
    {
        "id": 19, "label": "Saldo Final de Caixa",
        "formula": "16 + 17 - 18",
        "is_formula": True, "sinal": 1, "quadro": 3, "totalizador": True,
    },
]


# ---------------------------------------------------------------------------
# Cliente BigQuery
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT)


# ---------------------------------------------------------------------------
# Query principal: agrega valores por mês, tipo e categoria
# ---------------------------------------------------------------------------

def _fetch_raw(year: int, dataset: str = "ca_empresa_a") -> pd.DataFrame:
    """
    Retorna DataFrame com colunas:
      mes, tipo_transacao, id_categoria, entrada_dre, valor

    Usa regime de CAIXA: cada lançamento é atribuído ao mês em que foi
    efetivamente pago/recebido (data_pagamento das baixas).
    Cobre o ano solicitado + ano anterior (para YoY/YTD).
    """
    ano_ant = year - 1

    sql = f"""
    -- Receitas: cada baixa individual é atribuída ao seu mês correto.
    -- O valor de cada categoria do rateio é escalado pela proporção:
    --   valor_cat * (valor_baixa_individual / total_rateio)
    -- Isso resolve: parcelas parcialmente pagas, multi-baixas em meses diferentes.
    WITH rec_baixas AS (
      SELECT p._pk,
             JSON_VALUE(b, '$.data_pagamento') AS data_pagamento,
             CAST(JSON_VALUE(b, '$.valor_composicao.valor_liquido') AS FLOAT64) AS valor_baixa
      FROM `{PROJECT}.{dataset}.financeiro_parcelas_receitas` p,
           UNNEST(JSON_QUERY_ARRAY(p.baixas)) AS b
      WHERE p._erathos_deleted_at IS NULL
        AND JSON_VALUE(b, '$.data_pagamento') >= '{ano_ant}-01-01'
        AND JSON_VALUE(b, '$.data_pagamento') <= '{year}-12-31'
    ),
    rec_rat AS (
      SELECT p._pk,
             JSON_VALUE(r, '$.id_categoria') AS id_categoria,
             CAST(JSON_VALUE(r, '$.valor') AS FLOAT64) AS valor_cat,
             SUM(CAST(JSON_VALUE(r, '$.valor') AS FLOAT64)) OVER (PARTITION BY p._pk) AS total_rateio
      FROM `{PROJECT}.{dataset}.financeiro_parcelas_receitas` p,
           UNNEST(JSON_QUERY_ARRAY(p.evento__rateio)) AS r
      WHERE p._erathos_deleted_at IS NULL AND JSON_VALUE(r, '$.valor') IS NOT NULL
    ),
    base_rec AS (
      SELECT FORMAT_DATE('%Y-%m', DATE(b.data_pagamento)) AS mes,
             'RECEITA' AS tipo_transacao,
             rat.id_categoria,
             CASE WHEN rat.total_rateio = 0 THEN 0
                  ELSE rat.valor_cat * (b.valor_baixa / rat.total_rateio)
             END AS valor
      FROM rec_baixas b
      JOIN rec_rat rat ON rat._pk = b._pk
    ),
    -- Despesas: mesma lógica
    desp_baixas AS (
      SELECT p._pk,
             JSON_VALUE(b, '$.data_pagamento') AS data_pagamento,
             CAST(JSON_VALUE(b, '$.valor_composicao.valor_liquido') AS FLOAT64) AS valor_baixa
      FROM `{PROJECT}.{dataset}.financeiro_parcelas_despesas` p,
           UNNEST(JSON_QUERY_ARRAY(p.baixas)) AS b
      WHERE p._erathos_deleted_at IS NULL
        AND JSON_VALUE(b, '$.data_pagamento') >= '{ano_ant}-01-01'
        AND JSON_VALUE(b, '$.data_pagamento') <= '{year}-12-31'
    ),
    desp_rat AS (
      SELECT p._pk,
             JSON_VALUE(r, '$.id_categoria') AS id_categoria,
             CAST(JSON_VALUE(r, '$.valor') AS FLOAT64) AS valor_cat,
             SUM(CAST(JSON_VALUE(r, '$.valor') AS FLOAT64)) OVER (PARTITION BY p._pk) AS total_rateio
      FROM `{PROJECT}.{dataset}.financeiro_parcelas_despesas` p,
           UNNEST(JSON_QUERY_ARRAY(p.evento__rateio)) AS r
      WHERE p._erathos_deleted_at IS NULL AND JSON_VALUE(r, '$.valor') IS NOT NULL
    ),
    base_desp AS (
      SELECT FORMAT_DATE('%Y-%m', DATE(b.data_pagamento)) AS mes,
             'DESPESA' AS tipo_transacao,
             rat.id_categoria,
             CASE WHEN rat.total_rateio = 0 THEN 0
                  ELSE rat.valor_cat * (b.valor_baixa / rat.total_rateio)
             END AS valor
      FROM desp_baixas b
      JOIN desp_rat rat ON rat._pk = b._pk
    ),
    uniao AS (
      SELECT * FROM base_rec
      UNION ALL
      SELECT * FROM base_desp
    )
    SELECT
      u.mes,
      u.tipo_transacao,
      u.id_categoria,
      COALESCE(c.entrada_dre, '') AS entrada_dre,
      SUM(u.valor) AS valor
    FROM uniao u
    LEFT JOIN `{PROJECT}.{dataset}.categorias` c ON c.id = u.id_categoria
    GROUP BY mes, tipo_transacao, id_categoria, entrada_dre
    ORDER BY mes
    """

    rows = list(get_client().query(sql).result())
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        df = pd.DataFrame(columns=["mes", "tipo_transacao", "id_categoria", "entrada_dre", "valor"])
    return df


@lru_cache(maxsize=16)
def _fetch_raw_previsto(year: int, dataset: str = "ca_empresa_a") -> pd.DataFrame:
    """
    Previsto: usa data_vencimento, sem filtro de baixas.
    Inclui transações pagas e pendentes.
    """
    ano_ant = year - 1
    sql = f"""
    WITH base_rec AS (
      SELECT
        FORMAT_DATE('%Y-%m', DATE(p.data_vencimento)) AS mes,
        'RECEITA' AS tipo_transacao,
        JSON_VALUE(r, '$.id_categoria') AS id_categoria,
        CAST(JSON_VALUE(r, '$.valor') AS FLOAT64) AS valor
      FROM `{PROJECT}.{dataset}.financeiro_parcelas_receitas` p,
           UNNEST(JSON_QUERY_ARRAY(p.evento__rateio)) AS r
      WHERE p._erathos_deleted_at IS NULL
        AND p.data_vencimento >= '{ano_ant}-01-01'
        AND p.data_vencimento <= '{year}-12-31'
        AND JSON_VALUE(r, '$.valor') IS NOT NULL
    ),
    base_desp AS (
      SELECT
        FORMAT_DATE('%Y-%m', DATE(p.data_vencimento)) AS mes,
        'DESPESA' AS tipo_transacao,
        JSON_VALUE(r, '$.id_categoria') AS id_categoria,
        CAST(JSON_VALUE(r, '$.valor') AS FLOAT64) AS valor
      FROM `{PROJECT}.{dataset}.financeiro_parcelas_despesas` p,
           UNNEST(JSON_QUERY_ARRAY(p.evento__rateio)) AS r
      WHERE p._erathos_deleted_at IS NULL
        AND p.data_vencimento >= '{ano_ant}-01-01'
        AND p.data_vencimento <= '{year}-12-31'
        AND JSON_VALUE(r, '$.valor') IS NOT NULL
    ),
    uniao AS (SELECT * FROM base_rec UNION ALL SELECT * FROM base_desp)
    SELECT
      u.mes,
      u.tipo_transacao,
      u.id_categoria,
      COALESCE(c.entrada_dre, '') AS entrada_dre,
      SUM(u.valor) AS valor
    FROM uniao u
    LEFT JOIN `{PROJECT}.{dataset}.categorias` c ON c.id = u.id_categoria
    GROUP BY mes, tipo_transacao, id_categoria, entrada_dre
    ORDER BY mes
    """
    rows = list(get_client().query(sql).result())
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        df = pd.DataFrame(columns=["mes", "tipo_transacao", "id_categoria", "entrada_dre", "valor"])
    return df


# ---------------------------------------------------------------------------
# Cálculo por linha
# ---------------------------------------------------------------------------

def _calc_linha(line: dict, raw: pd.DataFrame, mes: str) -> float:
    """Calcula o valor de uma linha de dados (não fórmula) para um mês."""
    td = line.get("tipo_dados", "")
    subset = raw[raw["mes"] == mes]

    if td == "RESULTADO_FINANCEIRO":
        # Receitas financeiras (por entrada_dre OU por id de categoria)
        mask_rec = subset["tipo_transacao"] == "RECEITA"
        content_rec = (
            subset["entrada_dre"].isin(line.get("entradas_dre_rec", []))
            | subset["id_categoria"].isin(line.get("cat_ids_rec", []))
        )
        rec = subset[mask_rec & content_rec]["valor"].sum()

        # Despesas financeiras (por entrada_dre OU por id de categoria)
        mask_desp = subset["tipo_transacao"] == "DESPESA"
        content_desp = (
            subset["entrada_dre"].isin(line.get("entradas_dre_desp", []))
            | subset["id_categoria"].isin(line.get("cat_ids_desp", []))
        )
        desp = subset[mask_desp & content_desp]["valor"].sum()
        return rec - desp

    tipo_trans = "RECEITA" if td == "RECEITA" else "DESPESA"
    entradas   = line.get("entradas_dre", [])
    cat_inc    = line.get("cat_ids_incluir", [])
    cat_exc    = line.get("cat_ids_excluir", [])

    # Máscara de tipo
    type_mask = subset["tipo_transacao"] == tipo_trans

    # Conteúdo: entrada_dre OU categoria explícita (OR, não override)
    content_mask = pd.Series(False, index=subset.index)
    if entradas:
        content_mask = content_mask | subset["entrada_dre"].isin(entradas)
    if cat_inc:
        content_mask = content_mask | subset["id_categoria"].isin(cat_inc)

    combined = type_mask & content_mask

    # Excluir categorias específicas
    if cat_exc:
        combined = combined & ~subset["id_categoria"].isin(cat_exc)

    return subset[combined]["valor"].sum()


def _apply_formulas(values: dict[int, float]) -> dict[int, float]:
    """Avalia as fórmulas do DRE em ordem de dependência."""
    formula_lines = sorted(
        [l for l in DRE_LINES if l.get("is_formula")], key=lambda x: x["id"]
    )
    for line in formula_lines:
        expr = line["formula"]
        tokens = re.split(r"(\s*[+\-]\s*)", expr)
        parts = []
        for tok in tokens:
            tok_s = tok.strip()
            if tok_s in ("+", "-"):
                parts.append(f" {tok_s} ")
            elif re.match(r"^\d+$", tok_s):
                parts.append(str(values.get(int(tok_s), 0.0)))
            else:
                parts.append(tok)
        values[line["id"]] = float(eval("".join(parts)))  # safe: gerado internamente
    return values


def _build_month_values(raw: pd.DataFrame, mes: str) -> dict[int, float]:
    values: dict[int, float] = {}
    for line in DRE_LINES:
        if not line.get("is_formula"):
            values[line["id"]] = _calc_linha(line, raw, mes)
    return _apply_formulas(values)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def _build_dre_dataframe(raw: pd.DataFrame, year: int, dataset: str = "ca_empresa_a") -> pd.DataFrame:
    """Builds DRE DataFrame from a raw aggregate (realizado or previsto)."""
    meses_ano = [f"{year}-{m:02d}"     for m in range(1, 13)]
    meses_ant = [f"{year - 1}-{m:02d}" for m in range(1, 13)]

    month_vals: dict[str, dict[int, float]] = {}
    for mes in meses_ano + meses_ant:
        month_vals[mes] = _build_month_values(raw, mes)

    # ── L19 cumulativo: Saldo Final = Saldo Anterior + Geração do Período ───
    def _resolve_saldo_ini(yr: int) -> float:
        """Retorna saldo inicial do ano yr.
        Se não estiver em SALDOS_INICIAIS mas yr+1 estiver,
        deriva por: saldo_ini[yr] = saldo_ini[yr+1] − geração_total[yr]."""
        if dataset == "consolidado":
            saldos = {
                y: sum(SALDOS_INICIAIS.get(d, {}).get(y, 0.0) for d in _CONSOLIDADO_DATASETS)
                for y in range(2020, 2030)
            }
        else:
            saldos = SALDOS_INICIAIS.get(dataset, {})
        if yr in saldos:
            return saldos[yr]
        if (yr + 1) in saldos:
            meses_yr = [f"{yr}-{m:02d}" for m in range(1, 13)]
            gen_total = sum(
                month_vals[m].get(16, 0.0) + month_vals[m].get(17, 0.0)
                - month_vals[m].get(18, 0.0)
                for m in meses_yr if m in month_vals
            )
            return saldos[yr + 1] - gen_total
        return 0.0

    saldo_ini = _resolve_saldo_ini(year)
    acum = saldo_ini
    for mes in meses_ano:
        mv = month_vals[mes]
        geracao = mv.get(16, 0.0) + mv.get(17, 0.0) - mv.get(18, 0.0)
        acum += geracao
        # Só registra saldo em meses com dados reais (L1 > 0); meses futuros ficam 0
        mv[19] = acum if mv.get(1, 0.0) != 0 else 0.0

    saldo_ini_ant = _resolve_saldo_ini(year - 1)
    acum_ant = saldo_ini_ant
    for mes in meses_ant:
        mv = month_vals[mes]
        geracao = mv.get(16, 0.0) + mv.get(17, 0.0) - mv.get(18, 0.0)
        acum_ant += geracao
        mv[19] = acum_ant

    MONTH_LABELS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                    "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

    records = []
    for line in DRE_LINES:
        lid = line["id"]
        row: dict = {
            "id": lid,
            "label": line["label"],
            "quadro": line["quadro"],
            "totalizador": line.get("totalizador", False),
        }

        vals_ano = [month_vals[m].get(lid, 0.0) for m in meses_ano]
        vals_ant = [month_vals[m].get(lid, 0.0) for m in meses_ant]

        for i, label in enumerate(MONTH_LABELS):
            row[label] = vals_ano[i]

        if lid == 19:
            # Saldo Final de Caixa é posição acumulada, não fluxo.
            # TOTAL = último mês com dado real (posição atual do caixa).
            ultimo = next((v for v in reversed(vals_ano) if v != 0.0), 0.0)
            row["TOTAL"] = ultimo
        else:
            row["TOTAL"] = sum(vals_ano)

        rb_mensal = [month_vals[m].get(1, 0.0) for m in meses_ano]
        rb_total  = sum(rb_mensal)
        for i, label in enumerate(MONTH_LABELS):
            rb = rb_mensal[i]
            row[f"AV_{label}"] = (vals_ano[i] / rb * 100) if rb else None
        row["AV_TOTAL"] = (row["TOTAL"] / rb_total * 100) if rb_total else None

        for i, label in enumerate(MONTH_LABELS):
            prev = month_vals[meses_ant[11]].get(lid, 0.0) if i == 0 else vals_ano[i - 1]
            row[f"AH_MoM_{label}"] = ((vals_ano[i] - prev) / abs(prev) * 100) if prev else None

        for i, label in enumerate(MONTH_LABELS):
            prev_y = vals_ant[i]
            row[f"AH_YoY_{label}"] = ((vals_ano[i] - prev_y) / abs(prev_y) * 100) if prev_y else None

        ano_corrente = pd.Timestamp.now().year
        hoje_mes = pd.Timestamp.now().month if year >= ano_corrente else 12
        ytd_atual = sum(vals_ano[:hoje_mes])
        ytd_ant   = sum(vals_ant[:hoje_mes])
        row["AH_YTD"] = ((ytd_atual - ytd_ant) / abs(ytd_ant) * 100) if ytd_ant else None

        records.append(row)

    return pd.DataFrame(records)


@lru_cache(maxsize=16)
def get_dre(year: int, dataset: str = "ca_empresa_a") -> pd.DataFrame:
    """DRE realizado (regime de caixa: data_pagamento das baixas)."""
    if dataset == "consolidado":
        raw = pd.concat([_fetch_raw(year, d) for d in _CONSOLIDADO_DATASETS], ignore_index=True)
        return _build_dre_dataframe(raw, year, "consolidado")
    return _build_dre_dataframe(_fetch_raw(year, dataset), year, dataset)


@lru_cache(maxsize=16)
def get_dre_previsto(year: int, dataset: str = "ca_empresa_a") -> pd.DataFrame:
    """DRE previsto.
    Prioridade: orçamento salvo em ca_orcamentos.budget_lines.
    Fallback: parcelas a vencer no Conta Azul (data_vencimento).
    """
    # Tenta carregar orçamento definido pelo usuário (IA ou manual)
    try:
        from orcamento_ia import carregar_orcamento
        _nested, df_orc = carregar_orcamento(year, dataset)  # retorna (nested, df)
        if df_orc is not None:
            return df_orc
    except Exception:
        pass

    # Fallback: método original do Conta Azul
    if dataset == "consolidado":
        raw = pd.concat([_fetch_raw_previsto(year, d) for d in _CONSOLIDADO_DATASETS], ignore_index=True)
        return _build_dre_dataframe(raw, year, "consolidado")
    return _build_dre_dataframe(_fetch_raw_previsto(year, dataset), year, dataset)


@lru_cache(maxsize=4)
def _get_cat_names(dataset: str = "ca_empresa_a") -> dict[str, str]:
    """Returns {cat_id: nome} for all categories."""
    sql = f"SELECT id, nome FROM `{PROJECT}.{dataset}.categorias`"
    rows = list(get_client().query(sql).result())
    return {r["id"]: (r["nome"] or "") for r in rows}


def _calc_linha_breakdown(line: dict, raw: pd.DataFrame, mes: str) -> dict[str, float]:
    """Returns {cat_id: valor} breakdown for a non-formula DRE line."""
    td = line.get("tipo_dados", "")
    subset = raw[raw["mes"] == mes]

    if td == "RESULTADO_FINANCEIRO":
        mask_rec = subset["tipo_transacao"] == "RECEITA"
        content_rec = (
            subset["entrada_dre"].isin(line.get("entradas_dre_rec", []))
            | subset["id_categoria"].isin(line.get("cat_ids_rec", []))
        )
        rec_df = subset[mask_rec & content_rec]
        mask_desp = subset["tipo_transacao"] == "DESPESA"
        content_desp = (
            subset["entrada_dre"].isin(line.get("entradas_dre_desp", []))
            | subset["id_categoria"].isin(line.get("cat_ids_desp", []))
        )
        desp_df = subset[mask_desp & content_desp]
        result: dict[str, float] = {}
        for cat_id, val in rec_df.groupby("id_categoria")["valor"].sum().items():
            result[str(cat_id)] = float(val)
        for cat_id, val in desp_df.groupby("id_categoria")["valor"].sum().items():
            result[str(cat_id)] = result.get(str(cat_id), 0.0) - float(val)
        return result

    tipo_trans = "RECEITA" if td == "RECEITA" else "DESPESA"
    entradas = line.get("entradas_dre", [])
    cat_inc  = line.get("cat_ids_incluir", [])
    cat_exc  = line.get("cat_ids_excluir", [])

    type_mask    = subset["tipo_transacao"] == tipo_trans
    content_mask = pd.Series(False, index=subset.index)
    if entradas:
        content_mask = content_mask | subset["entrada_dre"].isin(entradas)
    if cat_inc:
        content_mask = content_mask | subset["id_categoria"].isin(cat_inc)
    combined = type_mask & content_mask
    if cat_exc:
        combined = combined & ~subset["id_categoria"].isin(cat_exc)

    filtered = subset[combined]
    if filtered.empty:
        return {}
    return {str(k): float(v) for k, v in filtered.groupby("id_categoria")["valor"].sum().items()}


def get_dre_categorias(year: int, dataset: str = "ca_empresa_a") -> dict:
    """
    Returns per-category breakdown for expandable sub-rows.
    Structure: {str(line_id): [{"cat_id", "label", "Jan_real", "Jan_prev", ..., "total_real", "total_prev"}]}
    """
    MONTH_LABELS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                    "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    meses = [f"{year}-{m:02d}" for m in range(1, 13)]
    datasets = _CONSOLIDADO_DATASETS if dataset == "consolidado" else [dataset]
    raw_real = pd.concat([_fetch_raw(year, d) for d in datasets], ignore_index=True)
    raw_prev = pd.concat([_fetch_raw_previsto(year, d) for d in datasets], ignore_index=True)
    cat_names: dict[str, str] = {}
    for d in datasets:
        cat_names.update(_get_cat_names(d))

    result: dict[str, list] = {}
    for line in DRE_LINES:
        if line.get("is_formula"):
            continue
        lid = str(line["id"])
        all_cats: dict[str, dict] = {}

        for i, mes in enumerate(meses):
            m_label = MONTH_LABELS[i]
            real_bd = _calc_linha_breakdown(line, raw_real, mes)
            prev_bd = _calc_linha_breakdown(line, raw_prev, mes)
            for cat_id, val in real_bd.items():
                if cat_id not in all_cats:
                    all_cats[cat_id] = {"cat_id": cat_id, "label": cat_names.get(cat_id, cat_id)}
                all_cats[cat_id][f"{m_label}_real"] = val
            for cat_id, val in prev_bd.items():
                if cat_id not in all_cats:
                    all_cats[cat_id] = {"cat_id": cat_id, "label": cat_names.get(cat_id, cat_id)}
                all_cats[cat_id][f"{m_label}_prev"] = val

        for cd in all_cats.values():
            for m in MONTH_LABELS:
                cd.setdefault(f"{m}_real", 0.0)
                cd.setdefault(f"{m}_prev", 0.0)
            cd["total_real"] = sum(cd[f"{m}_real"] for m in MONTH_LABELS)
            cd["total_prev"] = sum(cd[f"{m}_prev"] for m in MONTH_LABELS)

        result[lid] = sorted(all_cats.values(), key=lambda x: -abs(x.get("total_real", 0)))

    return result
