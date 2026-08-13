from __future__ import annotations

import re
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from app.connectors.base import PortalConnector, PortalConnectorError
from app.models import Empenho


class MtEstadoConnector(PortalConnector):
    """Conector do portal de transparência do Estado de Mato Grosso.

    Fluxo:
      1. resultado_01.php (busca por nome/CNPJ) → página agregada com totais
         e o código interno do credor (credor=...).
      2. cards.php?credor=...&estagio=emp → cards individuais de empenho
         com histórico já preenchido.
    """

    def _session_base(self) -> str:
        base = self.portal.config.get("base")
        if base:
            return base.rstrip("/") + "/"
        return "https://consultas.transparencia.mt.gov.br/despesa/por_favorecido/"

    def _get(self, url: str) -> str:
        try:
            r = self.client.get(url, headers={"Referer": self._session_base()})
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise PortalConnectorError(f"Erro ao consultar portal MT: {e}") from e
        return r.text

    def buscar_empenhos(self, termo: str = "", favorecido: str = "",
                        cpf_cnpj: str = "", unidade: str = "",
                        data_ini: str = "", data_fim: str = "",
                        ano: int = 2026) -> list[Empenho]:
        nome = favorecido or termo
        params = {
            "fonte": "",
            "cpf_cnpj": re.sub(r"[^0-9A-Za-z]", "", cpf_cnpj or ""),
            "nome": nome,
            "ano": str(ano),
            "mes_ini": "1",
            "mes_fim": "12",
        }
        agregado = self._get(self._session_base() + "resultado_01.php?" + urlencode(params))
        empenhos: list[Empenho] = []
        for credor, nome_credor, cnpj in self._parse_credores(agregado):
            cards = self._get_cards(credor, nome_credor, cnpj, ano)
            empenhos.extend(cards)
        return empenhos

    def _parse_credores(self, html: str) -> list[tuple[str, str, str]]:
        """Extrai (credor_id, nome, cnpj) dos links cards.php da página agregada."""
        out: list[tuple[str, str, str]] = []
        for m in re.finditer(
            r"cards\.php\?[^\"']*credor=(\d+)[^\"']*estagio=emp[^\"']*"
            r"[\"'](?![^\"']*href)",
            html,
        ):
            credor = m.group(1)
            bloco = html[max(0, m.start() - 600): m.end()]
            nome = ""
            nm = re.search(r">\s*([A-ZÀ-Ú][A-Z0-9À-Ú /.\-]{5,}?)\s*</a>", bloco)
            if nm:
                nome = nm.group(1).strip()
            cnpj = ""
            cm = re.search(r"([\d]{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", bloco)
            if cm:
                cnpj = cm.group(1)
            if credor and (credor, nome, cnpj) not in out:
                out.append((credor, nome, cnpj))
        # fallback: qualquer credor presente
        if not out:
            for m in re.finditer(r"credor=(\d+)", html):
                credor = m.group(1)
                if (credor, "", "") not in out:
                    out.append((credor, "", ""))
        return out

    def _get_cards(self, credor: str, nome: str, cnpj: str, ano: int) -> list[Empenho]:
        params = {
            "ano": str(ano), "mes_ini": "1", "mes_fim": "12",
            "nome": nome, "credor": credor, "estagio": "emp",
        }
        url = self._session_base() + "cards.php?" + urlencode(params)
        html = self._get(url)
        return self._parse_cards(html, credor, nome, cnpj)

    def _parse_cards(self, html: str, credor: str, nome: str, cnpj: str) -> list[Empenho]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[Empenho] = []
        for card in soup.select(".conteudo-documento"):
            cab = card.select_one(".conteudo-documento-cabecalho-texto")
            numero = cab.get_text(strip=True) if cab else ""
            valor_el = card.select_one(
                ".conteudo-documento-cabecalho-valores .conteudo-documento-cabecalho-texto"
            )
            valor = self._num(valor_el.get_text(strip=True) if valor_el else "")
            hist_el = card.find("b", string=lambda t: t and "Histórico" in t)
            historico = ""
            if hist_el and hist_el.next_sibling:
                historico = str(hist_el.next_sibling).strip()
            data = ""
            data_el = card.find("b", string=lambda t: t and t.strip() == "Data:")
            if data_el and data_el.next_sibling:
                data = str(data_el.next_sibling).strip()
            orgao = ""
            org_span = card.select_one(".conteudo-documento-linha span")
            if org_span:
                orgao = org_span.get_text(strip=True)
            if not numero:
                continue
            out.append(
                Empenho(
                    portal=self.portal.nome,
                    portal_id=self.portal.id,
                    numeroAno=numero,
                    dataEmpenho=data,
                    favorecido=nome or credor,
                    cpfCnpj=cnpj,
                    unidadeGestora="",
                    unidadeOrcamentaria="",
                    orgao=orgao,
                    elementoDespesa="",
                    naturezaDespesa="",
                    fonteRecurso="",
                    empenhado=valor,
                    liquidado=valor,
                    pago=valor,
                    historico=historico,
                )
            )
        return out

    def detalhe_empenho(self, empenho: Empenho) -> Empenho:
        return empenho
