# Portal de Transparência Cidadã

Site que agrega e organiza **empenhos públicos** direto dos portais de transparência,
com busca por palavra-chave, favorecido, CPF/CNPJ, unidade e período — e geração de
relatórios (Markdown e CSV).

Feito para ajudar cidadãos e pesquisadores a encontrar gastos públicos de forma rápida
e centralizada, sem precisar conhecer cada portal.

## Como rodar

Pré-requisito: Python 3.11+.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Abra `http://127.0.0.1:8010`.

Ou rode o atalho `iniciar.ps1` na raiz do projeto.

## Como usar

1. **Escolha o portal** (109 cadastrados: 107 portais AgiliCloud, Prefeitura de
   Rondonópolis e Governo de MT).
2. **Busque** por palavra-chave (ex.: "exposul"), favorecido, CPF/CNPJ, unidade,
   período e faixa de valor.
3. Veja o resumo (total empenhado/liquidado/pago, nº de favorecidos), a tabela com
   o histórico de cada empenho e o gráfico mensal.
4. **Sincronize** o portal (quando disponível) para baixar os empenhos para o cache
   local — assim buscas por palavra-chave ficam instantâneas.
5. **Baixe o relatório** em Markdown ou CSV.

## Como funcionam os portais

Cada portal é um "conector" (`backend/app/connectors/`):

| Portal | Tipo | Busca | Sincronização |
|---|---|---|---|
| 107 portais AgiliCloud (prefeituras, câmaras, consórcios, previdências de MT/PR/AL/RN) | `ipm` | por palavra-chave/histórico (via cache), favorecido, CNPJ | Sim (em lote) |
| Prefeitura de Rondonópolis | `ipm` | por palavra-chave/histórico (via cache), favorecido, CNPJ | Sim (em lote) |
| Governo do Estado de MT | `mt_estado` | por favorecido/CNPJ (portal só busca por nome) | Não (consulta ao vivo, lenta ~30s–3min) |

Observações:

- **Portais AgiliCloud** (nova geração IPM Sistemas) usam a mesma API dos portais IPM
  clássicos, apenas com URL base `https://transparencia.agilicloud.com.br` e o
  cabeçalho `uc` (shortname do cliente) — o conector `ipm` atende os dois sem alteração.
- **Portais IPM** (usados por centenas de municípios brasileiros) expõem API de grid;
  a palavra-chave é buscada no **histórico** de cada empenho.
- **Portal estadual MT** só pesquisa por nome/CNPJ do favorecido; não suporta busca
  no histórico. Cada busca consulta o portal em tempo real e pode demorar bastante.
- O cache fica em `backend/data/cache.db` (SQLite) no uso local, ou no PostgreSQL
  quando a variável de ambiente `DATABASE_URL` estiver definida.

## Colocar no ar (ex.: Render)

O backend usa **SQLite automaticamente** quando não há configuração, e
**PostgreSQL** quando a variável de ambiente `DATABASE_URL` existe — sem mudar código.

1. Crie um banco PostgreSQL no Render (free tier: 1 GB) e copie a `Internal Database URL`.
2. No Web Service, defina a variável de ambiente `DATABASE_URL` com essa URL.
3. Deploy: `pip install -r requirements.txt` e iniciar com
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. As tabelas são criadas automaticamente na primeira execução (`init_db`).

Observação: o Render não mantém o diretório `backend/data` entre deploys, então use
sempre o PostgreSQL em produção. Para sincronizar os portais em background no servidor,
agende chamadas a `POST /api/sincronizar` (ex.: cron diário) ou rode um job separado.

## Adicionar um novo portal

1. Crie uma entrada em `backend/app/connectors/config/portals.json` (o arquivo é
   criado automaticamente com os portais padrão na primeira execução).
2. Escolha um tipo existente (`ipm`, `mt_estado`) ou crie um conector novo em
   `backend/app/connectors/` e registre-o em `__init__.py`.

Para regenerar automaticamente a lista de portais AgiliCloud (valida cada cliente e
descarta os sem dados), rode:

```powershell
cd backend
.venv\Scripts\python ..\scripts\gerar_portais.py            # grava portals.json
.venv\Scripts\python ..\scripts\gerar_portais.py --dry-run  # só mostra
```

Exemplo de entrada:

```json
{
  "id": "minha-cidade",
  "nome": "Prefeitura de Minha Cidade",
  "uf": "MT",
  "esfera": "municipal",
  "tipo": "ipm",
  "url": "https://transparencia.minhacidade.mt.gov.br",
  "config": { "uc": "minhacidade" }
}
```

## API

- `GET /api/portais` — lista portais cadastrados
- `POST /api/sincronizar?portal_id=...&ano=2026&data_ini=...&data_fim=...` — baixa empenhos para o cache
- `GET /api/empenhos?portal_id=...&termo=...&favorecido=...&cpf_cnpj=...&unidade=...&data_ini=...&data_fim=...&min_valor=...&max_valor=...&pagina=...&por_pagina=...` — busca
- `GET /api/relatorio/markdown?portal_id=...&...` — relatório Markdown
- `GET /api/relatorio/csv?portal_id=...&...` — CSV dos resultados

## Aviso

Ferramenta acadêmica de agregação. Os dados vêm dos portais oficiais de transparência;
consulte sempre o portal de origem para conferência e para documentos oficiais.
