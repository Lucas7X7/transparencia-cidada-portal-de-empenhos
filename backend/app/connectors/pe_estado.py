from __future__ import annotations

import json
from typing import Any

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho


class PeEstadoConnector(PortalConnector):
    """Conector do Estado de Pernambuco (API de Dados Abertos do TCE/PE).

      GET {base}/DespesasEstaduais!json?CPF_CNPJ=&FORNECEDOR=&ANOREFERENCIA=&...

    A resposta vem em ISO-8859-1 e pode retornar até 100 mil registros por
    chamada. Filtros: FORNECEDOR (nome), CPF_CNPJ, NUMEROEMPENHO, ANOREFERENCIA,
    UNIDADEORCAMENTARIA, etc. Não há paginação publicada — para nomes genéricos
    a resposta pode ser grande, então limitamos aos maiores valores.

    O exercício de PE tem centenas de milhares de empenhos; a sincronização em
    lote exigiria baixar blocos de 100 mil registros (~200 MB) por chamada —
    inviável no ciclo de background. O portal é consultado ao vivo.
    """

    _MAX = 3000

    def _api_base(self) -> str:
        return (self.portal.config.get("base") or "https://sistemas.tce.pe.gov.br/DadosAbertos").rstrip("/")

    def _get(self, params: dict[str, Any]) -> dict:
        try:
            r = self.client.get(
                f"{self._api_base()}/DespesasEstaduais!json",
                params=params,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                timeout=240,
            )
            r.raise_for_status()
            return json.loads(r.content.decode("latin-1"))
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao consultar portal PE: {e}") from e

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
        params: dict[str, Any] = {}
        if cpf_cnpj:
            params["CPF_CNPJ"] = cpf_cnpj.strip()
        elif favorecido or termo:
            params["FORNECEDOR"] = (favorecido or termo).strip()
        elif unidade:
            params["UNIDADEORCAMENTARIA"] = unidade.strip()
        else:
            return []
        params["ANOREFERENCIA"] = ano

        dados = self._get(params)
        conteudo = ((dados.get("resposta") or {}).get("conteudo") or [])
        conteudo.sort(key=lambda x: self._num(x.get("VALOREMPENHADO", 0)), reverse=True)
        conteudo = conteudo[: self._MAX]
        empenhos = [self._normalizar(r) for r in conteudo]

        if data_ini:
            empenhos = [e for e in empenhos if not e.dataEmpenho or e.dataEmpenho >= data_ini]
        if data_fim:
            empenhos = [e for e in empenhos if not e.dataEmpenho or e.dataEmpenho <= data_fim]
        if termo:
            t = self._norm(termo)
            empenhos = [e for e in empenhos if t in self._norm(e.favorecido) or t in self._norm(e.historico)]
        return empenhos

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        return empenho

    def _normalizar(self, r: dict[str, Any]) -> Empenho:
        def s(campo: str) -> str:
            v = r.get(campo)
            return "" if v is None else str(v).strip()

        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=f"{s('NUMEROEMPENHO')}/{s('ANOREFERENCIA')}",
            dataEmpenho=s("DATAEMPENHO")[:10],
            favorecido=s("NOME_FORNECEDOR"),
            cpfCnpj=s("CPF_CNPJ"),
            unidadeGestora=s("NOMEUNIDADEGESTORA"),
            unidadeOrcamentaria=s("UNIDADEORCAMENTARIA"),
            orgao=s("NOMEUNIDADEGESTORA"),
            elementoDespesa=s("ELEMENTODESPESA"),
            naturezaDespesa=s("NATUREZA"),
            fonteRecurso=s("FONTERECURSO"),
            empenhado=self._num_us(r.get("VALOREMPENHADO", 0)),
            liquidado=self._num_us(r.get("VALORLIQUIDADO", 0)),
            pago=self._num_us(r.get("VALORPAGO", 0)),
            historico=s("HISTORICO"),
            url=self.portal.url,
            extra={
                "modo": s("MODALIDADE"),
                "funcao": s("FUNCAO"),
                "subfuncao": s("SUBFUNCAO"),
                "acao": s("ACAO"),
                "categoria": s("CATEGORIA"),
                "tipo_credor": s("TIPOCREDOR"),
                "id_ug": s("ID_UNIDADE_GESTORA"),
            },
        )
