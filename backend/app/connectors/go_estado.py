from __future__ import annotations

from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho


class GoEstadoConnector(PortalConnector):
    """Conector do Estado de Goiás (dadosabertos.go.gov.br — CKAN).

    API CKAN:
      GET {base}/api/3/action/datastore_search?resource_id=&limit=&offset=
      GET {base}/api/3/action/datastore_search_sql?sql=...

    Dataset "empenhos" (Secretaria da Economia). Campos principais:
      NUMR_EMPENHO, RAZAO_SOCIAL_CREDOR, CPF_CNPJ, DATA_EMPENHO, NUMR_ANO,
      NUM_MES, NOME_ORGAO, CODG_ORGAO, SALDO_EMPENHADO, DESCRICAO_EMPENHO,
      NUMR_PROCESSO_EMPENHO, DOTACAO.
    CPF de pessoa física vem mascarado por LGPD (ex.: ***.338.866-**).

    A base de busca por texto usa datastore_search_sql com LIKE (o parâmetro
    `q` do CKAN não encontra textos). Empenhos: valores de liquidação/pagamento
    ficam em outros datasets; aqui preenchemos a fase de empenho.
    """

    _RESOURCE = "3048c428-83cc-45f9-af01-4d0ecb44d078"

    def _api_base(self) -> str:
        return (self.portal.config.get("base") or "https://dadosabertos.go.gov.br").rstrip("/")

    def _resource(self) -> str:
        return self.portal.config.get("resource_id", self._RESOURCE)

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict:
        try:
            r = self.client.get(f"{self._api_base()}/api/3/action/{endpoint}", params=params, timeout=180)
            r.raise_for_status()
            dados = r.json()
            if not dados.get("success"):
                raise PortalConnectorError(f"Erro na API CKAN de GO: {dados.get('error')}")
            return dados
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao consultar portal GO: {e}") from e

    def buscar_empenhos(
        self,
        termo: str = "",
        favorecido: str = "",
        cpf_cnpj: str = "",
        unidade: str = "",
        data_ini: str = "",
        data_fim: str = "",
        ano: int = 2026,
        limite: int = 2000,
    ) -> list[Empenho]:
        nome = (favorecido or termo or "").strip()
        clausulas: list[str] = []
        if nome:
            esc = nome.replace("'", "''")
            clausulas.append(f'"RAZAO_SOCIAL_CREDOR" LIKE \'%{esc}%\'')
        if cpf_cnpj:
            esc = cpf_cnpj.strip().replace("'", "''")
            clausulas.append(f'"CPF_CNPJ" LIKE \'%{esc}%\'')
        if data_ini:
            clausulas.append(f'"DATA_EMPENHO" >= \'{data_ini}\'')
        if data_fim:
            clausulas.append(f'"DATA_EMPENHO" <= \'{data_fim}\'')
        if not clausulas:
            return []
        sql = (
            f'SELECT * FROM "{self._resource()}" WHERE ' + " AND ".join(clausulas)
            + f' ORDER BY "SALDO_EMPENHADO" DESC LIMIT {int(limite)}'
        )
        dados = self._get("datastore_search_sql", {"sql": sql})
        registros = (dados.get("result") or {}).get("records") or []
        empenhos = [self._normalizar(r) for r in registros]
        if termo:
            t = self._norm(termo)
            empenhos = [e for e in empenhos if t in self._norm(e.favorecido) or t in self._norm(e.historico)]
        return empenhos

    def sync_todos(self, ano: int = 2026, data_ini: str = "", data_fim: str = "",
                   page_size: int = 10000, **_kwargs) -> Iterator[Empenho]:
        import json as _json

        offset = 0
        while True:
            params: dict[str, Any] = {
                "resource_id": self._resource(),
                "limit": page_size,
                "offset": offset,
                "filters": _json.dumps({"NUMR_ANO": str(ano)}),
            }
            dados = self._get("datastore_search", params)
            res = dados.get("result") or {}
            registros = res.get("records") or []
            yield from (self._normalizar(r) for r in registros)
            total = int(res.get("total", 0) or 0)
            offset += page_size
            if offset >= total or not registros:
                break

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        return empenho

    def _normalizar(self, r: dict[str, Any]) -> Empenho:
        def s(campo: str) -> str:
            v = r.get(campo)
            return "" if v is None else str(v)

        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=s("NUMR_EMPENHO"),
            dataEmpenho=s("DATA_EMPENHO")[:10],
            favorecido=s("RAZAO_SOCIAL_CREDOR"),
            cpfCnpj=s("CPF_CNPJ"),
            unidadeGestora="",
            unidadeOrcamentaria="",
            orgao=s("NOME_ORGAO"),
            elementoDespesa="",
            naturezaDespesa="",
            fonteRecurso="",
            empenhado=self._num_us(r.get("SALDO_EMPENHADO", 0)),
            liquidado=0.0,
            pago=0.0,
            historico=s("DESCRICAO_EMPENHO"),
            url=self.portal.url,
            extra={
                "ano": s("NUMR_ANO"),
                "mes": s("NUM_MES"),
                "processo": s("NUMR_PROCESSO_EMPENHO"),
                "cod_orgao": s("CODG_ORGAO"),
                "dotacao": s("DOTACAO"),
            },
        )
