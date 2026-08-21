from __future__ import annotations

import csv
import io
import re
import time
import unicodedata
import zipfile
from datetime import datetime
from typing import Any, Iterator

import httpx

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_SLUG_PADRAO = (
    "portal-da-transparencia-despesas-da-"
    "administracao-publica-do-distrito-federal"
)


def _norm(texto: str) -> str:
    sem_acento = "".join(
        ch for ch in unicodedata.normalize("NFD", texto)
        if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"\s+", " ", sem_acento.strip()).upper()


class DfEstadoConnector(PortalConnector):
    """Conector do Distrito Federal (dados.df.gov.br).

    API Liferay de dados abertos: metadados do dataset expoe ZIP anual
    (~28 MB) com ``Despesa_Empenho_{ano}.csv`` (separador ``¨``, cp1252),
    contendo nota de empenho, credor, CNPJ/CPF, datas e valores. O downloadUrl
    vem relativo — prefixar o host. Sincronizacao em lote.
    """

    def _slug(self) -> str:
        return self.portal.config.get("slug") or _SLUG_PADRAO

    def _host(self) -> str:
        return (self.portal.config.get("base") or "https://www.dados.df.gov.br").rstrip("/")

    def _baixar_zip(self, ano: int) -> bytes:
        try:
            r = self.client.get(
                f"{self._host()}/o/dados-abertos/v1.0/datasets/{self._slug()}",
                timeout=60,
            )
            r.raise_for_status()
            detalhes = r.json().get("resourceDetails", []) or []
            alvo = None
            for d in detalhes:
                if str(ano) in str(d.get("name", "")):
                    alvo = d
                    break
            if alvo is None:
                raise PortalConnectorError(f"DF: sem arquivo para {ano}")
            url = str(alvo["downloadUrl"])
            if url.startswith("/"):
                url = self._host() + url
        except (httpx.HTTPError, ValueError) as e:
            raise PortalConnectorError(f"Erro ao obter metadados do DF ({ano}): {e}") from e

        ultimo: Exception | None = None
        for tentativa in range(3):
            try:
                r2 = self.client.get(url, timeout=240)
                r2.raise_for_status()
                return r2.content
            except httpx.HTTPError as e:
                ultimo = e
                time.sleep(5)
        raise PortalConnectorError(f"Erro ao baixar ZIP do DF ({ano}): {ultimo}")

    def sync_todos(self, ano: int = 2026, data_ini: str = "", data_fim: str = "",
                   **_kwargs) -> Iterator[Empenho]:
        conteudo = self._baixar_zip(ano)
        z = zipfile.ZipFile(io.BytesIO(conteudo))
        membros = [n for n in z.namelist() if f"Despesa_Empenho_{ano}" in n]
        if not membros:
            raise PortalConnectorError(f"DF: Despesa_Empenho_{ano}.csv ausente no ZIP")
        texto = z.read(membros[0]).decode("cp1252", errors="replace")
        leitor = csv.reader(texto.splitlines(), delimiter="\xa8", quotechar='"')
        try:
            cabecalho = next(leitor)
        except StopIteration:
            return
        cols = [_norm(c) for c in cabecalho]

        def idx(nome: str) -> int:
            alvo = _norm(nome)
            for i, c in enumerate(cols):
                if c == alvo:
                    return i
            return -1

        i_nota = idx("NOTA EMPENHO")
        i_exer = idx("EXERCICIO")
        i_emis = idx("EMISSAO")
        i_proc = idx("N DO PROCESSO")
        i_doc = idx("CNPJ CPF CREDOR")
        i_cred = idx("CREDOR")
        i_ugcod = idx("CODIGO UG")
        i_ug = idx("UG")
        i_uo = idx("UNIDADE UO")
        i_fonte = idx("FONTE RECURSOS")
        i_elem = idx("ELEMENTO DESPESA")
        i_vini = idx("VALOR INICIAL")
        i_vfin = idx("VALOR FINAL")

        def pega(linha: list[str], i: int) -> str:
            if 0 <= i < len(linha):
                return linha[i].strip()
            return ""

        for linha in leitor:
            nota = pega(linha, i_nota)
            credor = pega(linha, i_cred)
            if not nota or not credor:
                continue
            data = pega(linha, i_emis)[:10]
            if data:
                try:
                    data = datetime.strptime(data, "%d/%m/%Y").strftime("%Y-%m-%d")
                except ValueError:
                    pass
            ug_cod = pega(linha, i_ugcod)
            yield Empenho(
                portal=self.portal.nome,
                portal_id=self.portal.id,
                numeroAno=f"{nota}-{ug_cod}/{pega(linha, i_exer)}",
                dataEmpenho=data,
                favorecido=credor,
                cpfCnpj=pega(linha, i_doc),
                unidadeGestora=pega(linha, i_ug),
                unidadeOrcamentaria=pega(linha, i_uo),
                orgao="",
                elementoDespesa=pega(linha, i_elem),
                naturezaDespesa="",
                fonteRecurso=pega(linha, i_fonte),
                empenhado=self._num(pega(linha, i_vini)),
                liquidado=0.0,
                pago=0.0,
                historico="",
                url=self.portal.url,
                extra={
                    "valor_final": self._num(pega(linha, i_vfin)),
                    "processo": pega(linha, i_proc),
                },
            )

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
