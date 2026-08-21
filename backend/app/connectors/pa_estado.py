from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho


class PaEstadoConnector(PortalConnector):
    """Conector do Estado do Para (api-notas-empenho.sistemas.pa.gov.br).

    GET /notas-empenho com ``ano``, ``textoBusca`` (credor/CNPJ), ``pagina`` e
    ``qtdRegistros`` (ate 1000). Consultado ao vivo.
    """

    _MAX = 3000
    _PAG = 1000

    def _base(self) -> str:
        return (self.portal.config.get("base") or "https://api-notas-empenho.sistemas.pa.gov.br").rstrip("/")

    def _paginar(self, ano: int, busca: str, pagina: int) -> dict[str, Any]:
        try:
            r = self.client.get(
                f"{self._base()}/notas-empenho",
                params={"ano": ano, "textoBusca": busca, "pagina": pagina,
                        "qtdRegistros": self._PAG},
            )
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PortalConnectorError(f"Erro ao consultar portal PA: {e}") from e

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
        busca = cpf_cnpj.strip() or (favorecido or termo).strip()
        if not busca:
            return []
        saida: list[Empenho] = []
        pagina = 1
        while len(saida) < self._MAX:
            dados = self._paginar(ano, busca, pagina)
            linhas = dados.get("data") or []
            if not linhas:
                break
            for linha in linhas:
                emp = self._normalizar(linha)
                if data_ini and emp.dataEmpenho and emp.dataEmpenho < data_ini:
                    continue
                if data_fim and emp.dataEmpenho and emp.dataEmpenho > data_fim:
                    continue
                saida.append(emp)
            if len(linhas) < self._PAG:
                break
            pagina += 1
        return saida[: self._MAX]

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        return empenho

    def _normalizar(self, r: dict[str, Any]) -> Empenho:
        def s(campo: str) -> str:
            v = r.get(campo)
            return "" if v is None else str(v).strip()

        data = s("dt_despesa")
        if data:
            try:
                data = datetime.strptime(data[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=s("numero"),
            dataEmpenho=data,
            favorecido=s("credor"),
            cpfCnpj=s("credor_cpf_cnpj"),
            unidadeGestora=s("unidade_gestora"),
            unidadeOrcamentaria="",
            orgao=s("orgao"),
            elementoDespesa=s("elemento_despesa"),
            naturezaDespesa="",
            fonteRecurso="",
            empenhado=self._num_us(r.get("valor_empenhado", 0)),
            liquidado=self._num_us(r.get("valor_liquidado", 0)),
            pago=self._num_us(r.get("valor_pago", 0)),
            historico=s("historico") or s("descricao"),
            url=f"{self.portal.url}",
            extra={"id_ne": s("id_ne")},
        )
