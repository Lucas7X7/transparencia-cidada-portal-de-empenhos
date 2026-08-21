from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class RrEstadoConnector(PortalConnector):
    """Conector do Estado de Roraima (api.transparencia.rr.gov.br).

    1. GET unidades-orcamentarias -> lista de UOs (~106);
    2. GET visualizar-despesa-detalhada?codExercicioInicial={ano}&codUnidadeOrcamentaria={cod}
       por UO — cada resposta traz todos os empenhos da UO com credor
       (razaoSocial + cpfCnpj), valores e classificacao.
    O host e instavel — retries com pausa. Sincronizacao em lote (sem filtro
    de exercicio no servidor; filtramos localmente).
    """

    def __init__(self, portal):
        super().__init__(portal)
        self.client.close()
        self.client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True,
                                   timeout=httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=60.0),
                                   verify=False)

    def _base(self) -> str:
        return (self.portal.config.get("base")
                or "https://api.transparencia.rr.gov.br/api/v1/portal/transparencia").rstrip("/")

    def _get(self, rota: str, params: dict[str, Any], tentativas: int = 3) -> dict[str, Any]:
        ultimo: Exception | None = None
        for i in range(tentativas):
            try:
                r = self.client.get(f"{self._base()}/{rota}", params=params)
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, ValueError) as e:
                ultimo = e
                time.sleep(3 * (i + 1))
        raise PortalConnectorError(f"Erro ao consultar portal RR ({rota}): {ultimo}")

    def _unidades(self) -> list[dict[str, Any]]:
        dados = self._get("unidades-orcamentarias", {})
        if not isinstance(dados, list):
            raise PortalConnectorError("RR: lista de unidades inesperada")
        return dados

    @staticmethod
    def _data(v: Any) -> str:
        s = "" if v is None else str(v).strip()[:10]
        if not s:
            return ""
        try:
            return datetime.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return s

    def sync_todos(self, ano: int = 2026, data_ini: str = "", data_fim: str = "",
                   **_kwargs) -> Iterator[Empenho]:
        for uo in self._unidades():
            cod = str(uo.get("codigoUnidadeorcamentaria") or "").strip()
            if not cod:
                continue
            try:
                detalhe = self._get(
                    "visualizar-despesa-detalhada",
                    {"codExercicioInicial": ano, "codUnidadeOrcamentaria": cod},
                    tentativas=2,
                )
            except PortalConnectorError:
                continue
            blocos = ((detalhe.get("data") or {}).get("data")) or []
            for bloco in blocos:
                indice = str(bloco.get("indice") or "")
                for item in bloco.get("dados") or []:
                    if str(item.get("exercicio") or "").strip() != str(ano):
                        continue
                    emp = self._normalizar(item, indice)
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

    def _normalizar(self, r: dict[str, Any], indice: str) -> Empenho:
        def s(campo: str) -> str:
            v = r.get(campo)
            return "" if v is None else str(v).strip()

        ug = s("descricaoUnidadeOrcamentaria") or indice
        return Empenho(
            portal=self.portal.nome,
            portal_id=self.portal.id,
            numeroAno=s("numeroEmpenho"),
            dataEmpenho=self._data(r.get("dataEmpenho")),
            favorecido=s("razaoSocial") or "NÃO INFORMADO",
            cpfCnpj=s("cpfCnpj"),
            unidadeGestora=ug,
            unidadeOrcamentaria=ug,
            orgao=indice,
            elementoDespesa=s("naturezaDespesa"),
            naturezaDespesa="",
            fonteRecurso=s("fonteRecurso"),
            empenhado=self._num_us(r.get("valorEmpenho", 0)),
            liquidado=self._num_us(r.get("totalLiquidado", 0)),
            pago=self._num_us(r.get("totalPago", 0)),
            historico=s("historicoPed"),
            url=self.portal.url,
            extra={
                "processo": s("numeroProcessoFormatado"),
                "funcao": s("descricaoFuncao"),
                "programa": s("paoe"),
                "estornado": self._num_us(r.get("totalEstornado", 0)),
            },
        )

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        return empenho
