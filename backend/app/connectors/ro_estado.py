from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho


class RoEstadoConnector(PortalConnector):
    """Conector do Estado de Rondonia (transparencia.ro.gov.br).

    DataTables server-side em POST /fornecedor/getempenhofornecedores com
    periodo obrigatorio (DataInicial/DataFinal ISO) e filtros Credor/DocCredor.
    Retorna pagamentos por empenho/ordem bancaria com nome e documento do
    credor. Consultado ao vivo.
    """

    _MAX = 3000
    _PAG = 200

    def _base(self) -> str:
        return (self.portal.config.get("base") or "https://transparencia.ro.gov.br").rstrip("/")

    def _listar(self, ini: str, fim: str, busca_nome: str, busca_doc: str,
                start: int) -> dict[str, Any]:
        try:
            r = self.client.post(
                f"{self._base()}/fornecedor/getempenhofornecedores",
                data={
                    "draw": "1", "start": str(start), "length": str(self._PAG),
                    "DataInicial": ini, "DataFinal": fim,
                    "Credor": busca_nome, "DocCredor": busca_doc, "UnidadeGestora": "",
                },
            )
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PortalConnectorError(f"Erro ao consultar portal RO: {e}") from e

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
        ini = data_ini or f"{ano}-01-01"
        fim = data_fim or f"{ano}-12-31"
        busca_nome = (favorecido or termo).strip() if not cpf_cnpj else ""
        busca_doc = cpf_cnpj.strip()
        if not busca_nome and not busca_doc:
            return []
        saida: list[Empenho] = []
        start = 0
        while len(saida) < self._MAX:
            dados = self._listar(ini, fim, busca_nome, busca_doc, start)
            linhas = dados.get("data") or []
            if not linhas:
                break
            for linha in linhas:
                saida.append(self._normalizar(linha))
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

        chave = s("documentoNE_DocumentoOB") or s("pagamentoFornecedorId") or s("numeroDocumento")
        data = s("dataDocumento")
        if data:
            try:
                data = datetime.strptime(data[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
        valor_paga = self._num(s("valorPaga").replace("R$", "").replace("$", ""))
        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=chave,
            dataEmpenho=data,
            favorecido=s("credor"),
            cpfCnpj=s("docCredor"),
            unidadeGestora=s("unidadeGestora"),
            unidadeOrcamentaria="",
            orgao=s("unidadeGestora"),
            elementoDespesa=s("codDescElementoDespesa"),
            naturezaDespesa=s("codDescNaturezaDespesa"),
            fonteRecurso=s("fonteDeRecursos"),
            empenhado=0.0,
            liquidado=0.0,
            pago=valor_paga,
            historico=s("objetivoDocumentoLiquidacao"),
            url=f"{self._base()}/fornecedor",
            extra={
                "processo": s("processo"),
                "empenho": s("numeroDocumento"),
                "evento": s("evento"),
                "funcao": s("funcao"),
                "subfuncao": s("subFuncao"),
                "programa": s("programa"),
                "acao": s("acao"),
                "modalidade_licitacao": s("modalidadeLicitacao"),
            },
        )
