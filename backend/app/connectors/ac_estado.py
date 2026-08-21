from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import unquote

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho


class AcEstadoConnector(PortalConnector):
    """Conector do Estado do Acre (transparencia.ac.gov.br).

    DataTables server-side em POST /despesas/listar com protecao CSRF Laravel
    (cookie XSRF-TOKEN -> header X-XSRF-TOKEN). O parametro ``busca`` filtra por
    credor/CNPJ. Consultado ao vivo (sem sincronizacao em lote).
    """

    _MAX = 3000
    _PAG = 200

    def _listar(self, ano: int, busca: str, start: int) -> dict[str, Any]:
        try:
            self.client.get(f"{self._base()}/despesas")
            xsrf = unquote(self.client.cookies.get("XSRF-TOKEN", ""))
            r = self.client.post(
                f"{self._base()}/despesas/listar",
                headers={"X-XSRF-TOKEN": xsrf, "X-Requested-With": "XMLHttpRequest"},
                data={
                    "draw": "1", "start": str(start), "length": str(self._PAG),
                    "ano": str(ano), "orgao": "", "busca": busca, "filtro": "",
                    "fonte": "", "despesa": "", "categoria_economica": "",
                    "grupo_natureza": "", "elemento_despesa": "", "periodo": "0",
                },
            )
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PortalConnectorError(f"Erro ao consultar portal AC: {e}") from e

    def _base(self) -> str:
        return (self.portal.config.get("base") or "https://transparencia.ac.gov.br").rstrip("/")

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
        start = 0
        while len(saida) < self._MAX:
            dados = self._listar(ano, busca, start)
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
            total = int(dados.get("recordsFiltered") or 0)
            start += self._PAG
            if start >= total:
                break
        return saida[: self._MAX]

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        return empenho

    def _normalizar(self, r: dict[str, Any]) -> Empenho:
        def s(campo: str) -> str:
            v = r.get(campo)
            return "" if v is None else str(v).strip()

        data = s("dataempenho")
        if data:
            try:
                data = datetime.strptime(data[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=f"{s('numeroempenho')}/{s('anoempenho')}",
            dataEmpenho=data,
            favorecido=s("razaosocial"),
            cpfCnpj=s("cpfcnpjcredor"),
            unidadeGestora=s("entidade"),
            unidadeOrcamentaria="",
            orgao=s("entidade"),
            elementoDespesa=s("elemento_despesa"),
            naturezaDespesa=s("natureza"),
            fonteRecurso=s("fonte"),
            empenhado=self._num(r.get("totalempenho", 0)),
            liquidado=self._num(r.get("totalliquidacao", 0)),
            pago=self._num(r.get("totalpago", 0)),
            historico=s("motivoempenho"),
            url=f"{self._base()}/despesas",
            extra={
                "processo": s("numeroprocesso"),
                "classe_credor": s("classecredor"),
                "modalidade": s("modalidade"),
                "anulado": self._num(r.get("totalanulado", 0)),
            },
        )
