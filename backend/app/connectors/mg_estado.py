from __future__ import annotations

import csv
import io
from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class MgEstadoConnector(PortalConnector):
    """Conector do Estado de Minas Gerais (dados.mg.gov.br).

    Dataset "Despesa por Empenho" — arquivos CSV anuais por exercício
    (2022 a 2026), com favorecido, CNPJ/CPF, valores empenhado/liquidado/pago,
    data e número do empenho. O download exige User-Agent de navegador.

    Não há API de consulta filtrável (o datastore CKAN está vazio para os
    exercícios recentes); a busca é feita no cache local após a sincronização
    em lote.
    """

    _RESOURCES: dict[str, str] = {
        "2022": "c8757609-bd2e-4864-a75e-f39c72d025f4",
        "2023": "ab2a08af-7db8-407a-a4b4-a91e942eef55",
        "2024": "38eafdd6-bc1e-4bf9-bc39-bf5842380d6c",
        "2025": "2ef02d2b-655e-44a0-aaeb-bdac5c222871",
        "2026": "c5edcee8-e67f-4352-b499-d578625669b4",
    }

    def _resource_para(self, ano: int) -> str | None:
        return self.portal.config.get("resources", {}).get(str(ano)) or self._RESOURCES.get(str(ano))

    def _baixar_csv(self, ano: int) -> str:
        resource = self._resource_para(ano)
        if not resource:
            raise PortalConnectorError(f"MG: sem arquivo configurado para {ano}")
        url = (
            f"https://dados.mg.gov.br/dataset/portal_despesa_empenho/"
            f"resource/{resource}/download/empenho{ano}.csv"
        )
        try:
            r = self.client.get(url, headers={"User-Agent": UA}, timeout=600)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao baixar CSV de MG: {e}") from e
        return r.content.decode("utf-8-sig", errors="replace")

    def sync_todos(self, ano: int = 2026, data_ini: str = "", data_fim: str = "",
                   **_kwargs) -> Iterator[Empenho]:
        texto = self._baixar_csv(ano)
        leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
        for linha in leitor:
            emp = self._normalizar(linha)
            if data_ini and emp.dataEmpenho and emp.dataEmpenho < data_ini:
                continue
            if data_fim and emp.dataEmpenho and emp.dataEmpenho > data_fim:
                continue
            yield emp

    def buscar_empenhos(
        self,
        termo: str = "",
        favorecido: str = "",
        cpf_cnpj: str = "",
        unidade: str = "",
        data_ini: str = "",
        data_fim: str = "",
        ano: int = 2026,
    ) -> list[Empenho]:
        return []

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        return empenho

    def _normalizar(self, linha: dict[str, Any]) -> Empenho:
        def s(campo: str) -> str:
            v = linha.get(campo)
            return "" if v is None else str(v).strip()

        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=f"{s('numero_empenho')}/{s('unidade_orcamentaria_codigo')}/{s('ano_de_exercicio')}",
            dataEmpenho=s("data_registro_doc_empenho")[:10],
            favorecido=s("razao_social_credor"),
            cpfCnpj=s("cnpj_cpf_credor_formatado"),
            unidadeGestora=s("unidade_orcamentaria_nome"),
            unidadeOrcamentaria=s("unidade_orcamentaria_nome"),
            orgao=s("unidade_orcamentaria_sigla"),
            elementoDespesa=s("elemento_despesa_descricao"),
            naturezaDespesa="",
            fonteRecurso=s("fonte_recurso_descricao"),
            empenhado=self._num(linha.get("valor_despesa_empenhada", 0)),
            liquidado=self._num(linha.get("valor_despesa_liquidada", 0)),
            pago=self._num(linha.get("valor_pago_financeiro", 0)),
            historico=s("item_despesa_descricao"),
            url=self.portal.url,
            extra={
                "ano": s("ano_de_exercicio"),
                "processo": s("numero_processo_compra_siad"),
                "licitacao": s("licitacao_descricao_da_modalidade"),
                "cod_item": s("item_despesa_codigo"),
                "cod_elemento": s("elemento_despesa_codigo"),
                "cod_fonte": s("fonte_recurso_codigo"),
                "valor_liquidado_rp": self._num(linha.get("valor_liquidado_rp", 0)),
                "valor_pago_rp": self._num(linha.get("valor_pago_rp", 0)),
            },
        )
