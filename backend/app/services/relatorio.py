from __future__ import annotations

import csv
import io
from datetime import datetime

from app.models import Empenho, PortalInfo


def _fmt_br(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_markdown(portal: PortalInfo, empenhos: list[Empenho], termo: str,
                   data_ini: str, data_fim: str, titulo: str = "") -> str:
    total_emp = sum(e.empenhado for e in empenhos)
    total_liq = sum(e.liquidado for e in empenhos)
    total_pag = sum(e.pago for e in empenhos)
    linhas: list[str] = []
    linhas.append(f"# {titulo or f'Relatório de Despesas — {portal.nome}'}")
    linhas.append("")
    linhas.append(f"**Portal:** {portal.nome} ({portal.esfera}, {portal.uf})")
    linhas.append(f"**Gerado em:** {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    if termo:
        linhas.append(f"**Busca por:** “{termo}”")
    if data_ini or data_fim:
        linhas.append(f"**Período:** {data_ini or 'início'} a {data_fim or 'hoje'}")
    linhas.append("")
    linhas.append("## Resumo")
    linhas.append("")
    linhas.append(f"- **Empenhos encontrados:** {len(empenhos)}")
    linhas.append(f"- **Total empenhado:** {_fmt_br(total_emp)}")
    linhas.append(f"- **Total liquidado:** {_fmt_br(total_liq)}")
    linhas.append(f"- **Total pago:** {_fmt_br(total_pag)}")
    linhas.append("")
    linhas.append("## Empenhos")
    linhas.append("")
    linhas.append("| Empenho | Data | Favorecido | CNPJ/CPF | Unidade | Elemento | Empenhado | Liquidado | Pago |")
    linhas.append("|---|---|---|---|---|---|---|---|---|")
    for e in sorted(empenhos, key=lambda x: x.dataEmpenho):
        hist = (e.historico or "").replace("|", "\\|").replace("\n", " ")[:200]
        unid = e.unidadeOrcamentaria or e.orgao or ""
        linhas.append(
            f"| {e.numeroAno} | {e.dataEmpenho} | {e.favorecido} | {e.cpfCnpj} "
            f"| {unid} | {e.elementoDespesa} | {_fmt_br(e.empenhado)} "
            f"| {_fmt_br(e.liquidado)} | {_fmt_br(e.pago)} |"
        )
        if hist:
            linhas.append(f"  > {hist}")
    linhas.append("")
    return "\n".join(linhas)


def gerar_csv(empenhos: list[Empenho]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow([
        "NumeroAno", "Data", "Favorecido", "CPF/CNPJ", "Unidade Gestora",
        "Unidade Orcamentaria", "Orgao", "Elemento", "Natureza", "Fonte",
        "Empenhado", "Liquidado", "Pago", "Historico",
    ])
    for e in empenhos:
        writer.writerow([
            e.numeroAno, e.dataEmpenho, e.favorecido, e.cpfCnpj,
            e.unidadeGestora, e.unidadeOrcamentaria, e.orgao,
            e.elementoDespesa, e.naturezaDespesa, e.fonteRecurso,
            e.empenhado, e.liquidado, e.pago, e.historico,
        ])
    return buf.getvalue()
