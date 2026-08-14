from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_PSEUDO = ("VENCIMENTOS", "DIARIAS", "13", "1/3")


class MsEstadoConnector(PortalConnector):
    """Conector do Estado de Mato Grosso do Sul (dados.ms.gov.br).

    Dataset "Despesas por Credor - Mensal": um CSV por mês (2012-01 a 2026-06),
    com Órgão, Credor, Cpf/Cnpj, Documento (número do empenho) e valores
    empenhado/liquidado/pago. Não há coluna de data.

    Os arquivos recentes (2017+) não têm datastore ativo — download direto do
    CSV (~13 MB/mês, latin-1, delimitador ";"). Vários lançamentos de um mesmo
    empenho no mês são agregados por documento para evitar duplicidade na base.
    Sincronização em lote (sem busca ao vivo).
    """

    _PACKAGE = "despesas-por-credor-mensal"

    def _resources(self) -> dict[tuple[int, int], str]:
        try:
            r = self.client.get(
                f"https://www.dados.ms.gov.br/api/3/action/package_show?id={self._PACKAGE}",
                headers={"User-Agent": UA},
                timeout=120,
            )
            r.raise_for_status()
            dados = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PortalConnectorError(f"Erro ao listar recursos do MS: {e}") from e
        mapa: dict[tuple[int, int], str] = {}
        for res in dados.get("result", {}).get("resources", []) or []:
            nome = str(res.get("name") or "")
            if " - " not in nome:
                continue
            parte = nome.rsplit(" - ", 1)[-1].strip()
            try:
                mes, ano = parte.split("/")
                mapa[(int(ano), int(mes))] = str(res["url"])
            except (ValueError, KeyError):
                continue
        return mapa

    def _baixar_mes(self, ano: int, mes: int) -> Iterator[Empenho]:
        url = self._resources().get((ano, mes))
        if not url:
            return
        try:
            r = self.client.get(url, headers={"User-Agent": UA}, timeout=600)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao baixar CSV do MS ({mes:02d}/{ano}): {e}") from e
        texto = r.content.decode("latin-1", errors="replace")
        for emp in self._parse_mes(texto, ano, mes):
            yield emp

    def _parse_mes(self, texto: str, ano: int, mes: int) -> Iterator[Empenho]:
        leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
        agregado: dict[str, dict[str, Any]] = {}
        for linha in leitor:
            doc = (linha.get("Documento") or "").strip()
            if not doc:
                continue
            chave = f"{doc}-{mes:02d}/{ano}"
            ag = agregado.setdefault(chave, {
                "credor": "", "cpf": "", "orgao": "",
                "empenhado": 0.0, "liquidado": 0.0, "pago": 0.0,
            })
            credor = (linha.get("Credor") or "").strip()
            if credor and not ag["credor"] and credor.upper() not in _PSEUDO:
                ag["credor"] = credor
                ag["cpf"] = (linha.get("Cpf/Cnpj") or "").strip()
            if not ag["orgao"]:
                ag["orgao"] = (linha.get("\xd3rg\xe3o") or "").strip()
            ag["empenhado"] += self._num(linha.get("Empenhado", 0))
            ag["liquidado"] += self._num(linha.get("Liquidado", 0))
            ag["pago"] += self._num(linha.get("Pago", 0))

        for chave, ag in agregado.items():
            yield Empenho(
                portal=self.portal.nome,
                portal_id=self.portal.id,
                numeroAno=chave,
                dataEmpenho="",
                favorecido=ag["credor"] or "NÃO INFORMADO",
                cpfCnpj=ag["cpf"],
                unidadeGestora=ag["orgao"],
                unidadeOrcamentaria="",
                orgao=ag["orgao"],
                elementoDespesa="",
                naturezaDespesa="",
                fonteRecurso="",
                empenhado=ag["empenhado"],
                liquidado=ag["liquidado"],
                pago=ag["pago"],
                historico="",
                url=self.portal.url,
                extra={"mes": f"{mes:02d}/{ano}"},
            )

    def sync_todos(self, ano: int = 2026, data_ini: str = "", data_fim: str = "",
                   **_kwargs) -> Iterator[Empenho]:
        agora = datetime.now()
        mes_fim = agora.month if ano == agora.year else 12
        for mes in range(1, mes_fim + 1):
            yield from self._baixar_mes(ano, mes)

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
