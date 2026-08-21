from __future__ import annotations

import time
from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _texto(item: dict[str, Any], *nomes: str) -> str:
    baixo = {str(k).strip().lower(): v for k, v in item.items()}
    for nome in nomes:
        v = baixo.get(nome.lower())
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


class ApEstadoConnector(PortalConnector):
    """Conector do Estado do Amapa (api.transparencia.ap.gov.br).

    GET /siafe-despesas/?ano=&mes=&limite= com paginacao por cursor: a resposta
    traz ``proximo_id`` que deve ser repassado como ``ultimo_id``. Meses antigos
    podem responder 504 — retries com pausa. Sincronizacao em lote.
    O certificado do host tem nome invalido — verificacao desativada.
    """

    def __init__(self, portal):
        super().__init__(portal)
        self.client.close()
        self.client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True,
                                   timeout=httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=60.0),
                                   verify=False)

    def _base(self) -> str:
        return (self.portal.config.get("base") or "https://api.transparencia.ap.gov.br").rstrip("/")

    def _get(self, params: dict[str, Any], tentativas: int = 3) -> Any:
        ultimo: Exception | None = None
        for i in range(tentativas):
            try:
                r = self.client.get(f"{self._base()}/siafe-despesas/", params=params)
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, ValueError) as e:
                ultimo = e
                time.sleep(5 * (i + 1))
        raise PortalConnectorError(f"Erro ao consultar portal AP: {ultimo}")

    @staticmethod
    def _itens(j: Any) -> tuple[list[Any], Any]:
        if isinstance(j, list):
            return j, None
        if isinstance(j, dict):
            for chave in ("data", "items", "resultados", "dados", "results"):
                if isinstance(j.get(chave), list):
                    cursor = None
                    for c in ("proximo_id", "proximoId", "next_id"):
                        if j.get(c):
                            cursor = j[c]
                            break
                    return j[chave], cursor
        return [], None

    def _mes(self, ano: int, mes: int) -> Iterator[Empenho]:
        cursor: Any = None
        while True:
            params: dict[str, Any] = {"ano": ano, "mes": mes, "limite": 500}
            if cursor is not None:
                params["ultimo_id"] = cursor
            j = self._get(params)
            itens, proximo = self._itens(j)
            if not itens:
                break
            for item in itens:
                if isinstance(item, dict):
                    yield self._normalizar(item)
            if proximo is None or len(itens) < 2:
                break
            cursor = proximo

    def sync_todos(self, ano: int = 2026, data_ini: str = "", data_fim: str = "",
                   **_kwargs) -> Iterator[Empenho]:
        from datetime import datetime
        agora = datetime.now()
        mes_fim = agora.month if ano == agora.year else 12
        for mes in range(1, mes_fim + 1):
            yield from self._mes(ano, mes)

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

    def _normalizar(self, r: dict[str, Any]) -> Empenho:
        numero = _texto(r, "NOTA_EMPENHO", "nota_empenho", "NE")
        data = _texto(r, "DATA_EMISSAO", "data_emissao")[:10]
        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=numero,
            dataEmpenho=data,
            favorecido=_texto(r, "NOME_CREDOR", "nome_credor", "CREDOR") or "NÃO INFORMADO",
            cpfCnpj=_texto(r, "CPF_CNPJ", "cpf_cnpj"),
            unidadeGestora=_texto(r, "UNIDADE_GESTORA", "UG", "ORGAO"),
            unidadeOrcamentaria="",
            orgao=_texto(r, "ORGAO", "UO"),
            elementoDespesa=_texto(r, "ELEMENTO_DESPESA", "ITEM_DESPESA"),
            naturezaDespesa="",
            fonteRecurso="",
            empenhado=self._num_us(_texto(r, "VAL_EMPENHADO", "VALOREMPENHADO")),
            liquidado=self._num_us(_texto(r, "VAL_LIQUIDADO", "VALORLIQUIDADO")),
            pago=self._num_us(_texto(r, "VAL_PAGO", "VALORPAGO")),
            historico=_texto(r, "HISTORICO", "OBSERVACAO"),
            url=self.portal.url,
            extra={"saldo": self._num_us(_texto(r, "VAL_SALDO", "SALDO"))},
        )

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        return empenho
