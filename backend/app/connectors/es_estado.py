from __future__ import annotations

import csv
import tempfile
from datetime import datetime
from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class EsEstadoConnector(PortalConnector):
    """Conector do Estado do Espirito Santo (dados.es.gov.br).

    Dataset CKAN com CSV anual de despesas por documento (empenho/liquidacao/
    pagamento) contendo favorecido, CPF/CNPJ, datas e valores:
      GET {dataset}/resource/{uuid}/download/despesas-{ano}.csv (~100+ MB/ano)
    O download e feito em streaming para nao carregar o arquivo inteiro na
    memoria. Sincronizacao em lote.
    """

    _DATASET_PADRAO = "99e16b13-0e6f-4504-8544-00de842ab1fd"

    def _dataset(self) -> str:
        return self.portal.config.get("dataset_id") or self._DATASET_PADRAO

    def _url_csv(self, ano: int) -> str:
        try:
            r = self.client.get(
                "https://dados.es.gov.br/api/3/action/package_show",
                params={"id": self._dataset()},
                timeout=120,
            )
            r.raise_for_status()
            recursos = r.json().get("result", {}).get("resources", []) or []
        except (httpx.HTTPError, ValueError) as e:
            raise PortalConnectorError(f"Erro ao listar recursos do ES: {e}") from e
        nome_alvo = f"Despesas-{ano}.csv"
        for res in recursos:
            if str(res.get("name") or "").strip().lower() == nome_alvo.lower():
                return str(res["url"])
        raise PortalConnectorError(f"ES: sem arquivo para {ano}")

    def sync_todos(self, ano: int = 2026, data_ini: str = "", data_fim: str = "",
                   **_kwargs) -> Iterator[Empenho]:
        url = self._url_csv(ano)
        try:
            with self.client.stream("GET", url, timeout=1800) as resposta:
                resposta.raise_for_status()
                with tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024) as tmp:
                    for chunk in resposta.iter_bytes():
                        tmp.write(chunk)
                    tmp.seek(0)
                    yield from self._parse(tmp.read().decode("utf-8-sig", errors="replace"),
                                           data_ini, data_fim)
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao baixar CSV do ES ({ano}): {e}") from e

    def _parse(self, texto: str, data_ini: str, data_fim: str) -> Iterator[Empenho]:
        leitor = csv.DictReader(texto.splitlines(), delimiter=";")
        for linha in leitor:
            def s(nome: str) -> str:
                v = linha.get(nome)
                return "" if v is None else str(v).strip()

            documento = s("Documento")
            if not documento:
                continue
            data = s("Data")[:10]
            if data:
                try:
                    data = datetime.strptime(data, "%d/%m/%Y").strftime("%Y-%m-%d")
                except ValueError:
                    pass
            emp = Empenho(
                portal=self.portal.nome,
                portal_id=self.portal.id,
                numeroAno=documento,
                dataEmpenho=data,
                favorecido=s("Favorecido") or "NÃO INFORMADO",
                cpfCnpj=s("CpfCnpjNis"),
                unidadeGestora=s("UnidadeGestora"),
                unidadeOrcamentaria=s("UnidadeGestora"),
                orgao="",
                elementoDespesa=s("ElementoDespesa"),
                naturezaDespesa="",
                fonteRecurso=s("Fonte"),
                empenhado=self._num(linha.get("ValorEmpenho", 0)),
                liquidado=self._num(linha.get("ValorLiquidado", 0)),
                pago=self._num(linha.get("ValorPago", 0)),
                historico=s("HistoricoDocumento"),
                url=self.portal.url,
                extra={
                    "empenho": s("DocumentoEmpenho"),
                    "processo": s("Processo"),
                    "rap": self._num(linha.get("ValorRap", 0)),
                    "tipo_licitacao": s("TipoLicitacao"),
                },
            )
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
