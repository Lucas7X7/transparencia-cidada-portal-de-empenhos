from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class RnEstadoConnector(PortalConnector):
    """Conector do Estado do Rio Grande do Norte (transparencia.rn.gov.br).

    Fluxo com sessao e token CSRF:
      1. GET /despesas -> extrai ``_token``;
      2. POST /gastos-diretos (posicao="No mes", mes, ano, classificacao=favorecido);
      3. POST /gastos-diretos/exportcsv com os campos hidden da resposta.
    O CSV traz favorecido + CPF/CNPJ + valores empenhado/liquidado/pago/RP por
    mes (sem numero de empenho). Periodos anuais estouram o timeout do servidor
    — sincronizar mes a mes. O certificado SSL do host nao confere com o
    dominio — verificacao desativada.
    """

    def __init__(self, portal):
        super().__init__(portal)
        self.client.close()
        self.client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True,
                                   timeout=httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=60.0),
                                   verify=False)

    def _base(self) -> str:
        return (self.portal.config.get("base") or "https://transparencia.rn.gov.br").rstrip("/")

    def _baixar_mes(self, ano: int, mes: int) -> str | None:
        try:
            r0 = self.client.get(f"{self._base()}/despesas")
            r0.raise_for_status()
            m = re.search(r'name="_token"\s+value="([^"]+)"', r0.text)
            if not m:
                raise PortalConnectorError("RN: token CSRF nao encontrado")
            token = m.group(1)
            r1 = self.client.post(
                f"{self._base()}/gastos-diretos",
                data={"_token": token, "posicao": "No mes", "mes": str(mes),
                      "ano": str(ano), "classificacao": "favorecido"},
            )
            r1.raise_for_status()
            campos = dict(re.findall(
                r'<input\s+type="hidden"\s+name="([^"]+)"\s+(?:value="([^"]*)")?', r1.text))
            campos["_token"] = token
            r2 = self.client.post(f"{self._base()}/gastos-diretos/exportcsv", data=campos)
            r2.raise_for_status()
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao exportar CSV do RN ({mes:02d}/{ano}): {e}") from e
        if len(r2.content) < 200:
            return None
        return r2.content.decode("utf-8", errors="replace")

    def _parse_mes(self, texto: str, ano: int, mes: int) -> Iterator[Empenho]:
        leitor = csv.DictReader(io.StringIO(texto))
        for linha in leitor:
            def s(nome: str) -> str:
                v = linha.get(nome)
                return "" if v is None else str(v).strip()

            cnpj = s("CPF/CNPJ/IG")
            favorecido = s("Favorecido")
            grupo = s("Grupo de Despesa")
            elemento = s("Elemento de Despesa")
            if not favorecido and not cnpj:
                continue
            chave = f"{cnpj or 'SEM-DOC'}|{grupo[:20]}|{elemento[:25]}/{mes:02d}/{ano}"
            yield Empenho(
                portal=self.portal.nome,
                portal_id=self.portal.id,
                numeroAno=chave,
                dataEmpenho="",
                favorecido=favorecido or "NÃO INFORMADO",
                cpfCnpj=cnpj,
                unidadeGestora="",
                unidadeOrcamentaria="",
                orgao="",
                elementoDespesa=elemento,
                naturezaDespesa=grupo,
                fonteRecurso="",
                empenhado=self._num(linha.get("Valor Empenhado", 0)),
                liquidado=self._num(linha.get("Valor Liquidação", 0)),
                pago=self._num(linha.get("Valor Pagamento", 0)),
                historico="",
                url=f"{self._base()}/despesas",
                extra={"mes": f"{mes:02d}/{ano}",
                       "restos_pagar": self._num(linha.get("Restos a Pagar", 0))},
            )

    def sync_todos(self, ano: int = 2026, data_ini: str = "", data_fim: str = "",
                   **_kwargs) -> Iterator[Empenho]:
        agora = datetime.now()
        mes_fim = agora.month if ano == agora.year else 12
        for mes in range(1, mes_fim + 1):
            texto = self._baixar_mes(ano, mes)
            if texto:
                yield from self._parse_mes(texto, ano, mes)

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
