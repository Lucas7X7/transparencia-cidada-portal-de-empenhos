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


class ScEstadoConnector(PortalConnector):
    """Conector do Estado de Santa Catarina (API CIASC).

    Export CSV mensal das notas de empenho:
      GET {base}/api/documentos/exportcsv?visao=empenho&anomesinifiltro=AAAAMM&anomesfimfiltro=AAAAMM
    (~14 MB/mes, ~25 mil linhas). O certificado SSL do host e invalido — a
    verificacao e desativada. Sincronizacao em lote, agregando lancamentos da
    mesma nota de empenho.
    """

    def __init__(self, portal):
        super().__init__(portal)
        self.client.close()
        self.client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True,
                                   timeout=httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=60.0),
                                   verify=False)

    def _base(self) -> str:
        return (self.portal.config.get("base")
                or "https://api-portal-transparencia.apps.sm.okd4.ciasc.sc.gov.br").rstrip("/")

    def _baixar_mes(self, ano: int, mes: int) -> str | None:
        periodo = f"{ano}{mes:02d}"
        try:
            r = self.client.get(
                f"{self._base()}/api/documentos/exportcsv",
                params={"visao": "empenho", "anomesinifiltro": periodo,
                        "anomesfimfiltro": periodo},
                timeout=600,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao baixar CSV de SC ({periodo}): {e}") from e
        if r.status_code == 200 and len(r.content) < 200:
            return None
        return r.content.decode("utf-8", errors="replace")

    def _parse_mes(self, texto: str) -> Iterator[Empenho]:
        leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
        agregado: dict[str, dict[str, Any]] = {}
        for linha in leitor:
            nota = (linha.get("nunotaempenho") or "").strip()
            if not nota:
                continue
            ag = agregado.setdefault(nota, {
                "credor": "", "cpf": "", "orgao": "", "ug": "", "data": "",
                "historico": "", "elemento": "", "fonte": "", "valor": 0.0,
            })
            credor = (linha.get("nmcredor") or "").strip()
            if credor and not ag["credor"]:
                ag["credor"] = credor
                ag["cpf"] = (linha.get("nuidentificacao") or "").strip()
            if not ag["orgao"]:
                ag["orgao"] = (linha.get("nmunidadegestora") or linha.get("nmorgao") or "").strip()
                ag["data"] = (linha.get("dtlancamento") or "").strip()[:10]
                ag["historico"] = (linha.get("dehistoricoempenho") or "").strip()
                ag["elemento"] = (linha.get("nmsubelemento") or "").strip()
                ag["fonte"] = (linha.get("nmfonterecurso") or "").strip()
            ag["valor"] += self._num(linha.get("vlempenho", 0))
        for nota, ag in agregado.items():
            yield Empenho(
                portal=self.portal.nome,
                portal_id=self.portal.id,
                numeroAno=nota,
                dataEmpenho=ag["data"],
                favorecido=ag["credor"] or "NÃO INFORMADO",
                cpfCnpj=ag["cpf"],
                unidadeGestora=ag["orgao"],
                unidadeOrcamentaria="",
                orgao=ag["orgao"],
                elementoDespesa=ag["elemento"],
                naturezaDespesa="",
                fonteRecurso=ag["fonte"],
                empenhado=ag["valor"],
                liquidado=0.0,
                pago=0.0,
                historico=ag["historico"],
                url=self.portal.url,
                extra={},
            )

    def sync_todos(self, ano: int = 2026, data_ini: str = "", data_fim: str = "",
                   **_kwargs) -> Iterator[Empenho]:
        agora = datetime.now()
        mes_fim = agora.month if ano == agora.year else 12
        for mes in range(1, mes_fim + 1):
            texto = self._baixar_mes(ano, mes)
            if texto:
                yield from self._parse_mes(texto)

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
