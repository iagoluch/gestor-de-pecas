import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AssistantMarkdown } from "../components/AssistantMarkdown";
import { EmptyState } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { artifactStatusLabel, humanizeAssistantText, reportTypeLabel } from "../utils/assistantText";
import { humanize } from "../utils/format";
import { availabilityLabel, humanizeSystemState, systemStateSentence } from "../utils/systemState";

/** Nenhum identificador técnico pode sobrar em texto visível. */
const TECNICOS = /sem_registros|dados_insuficientes|insufficient_data|no_records|not_configured|nao_configurado|partial_data|management_insights|ai_messages|ai_conversations|eventos_quantidade_producao|SELECT |Traceback/;

describe("camada central de humanização de estados", () => {
  it("traduz os estados técnicos para frase humana", () => {
    expect(systemStateSentence("sem_registros")).toBe("Nenhum registro encontrado para o período.");
    expect(systemStateSentence("dados_insuficientes")).toBe("Ainda não há dados suficientes para este indicador.");
    expect(systemStateSentence("not_configured")).toBe("Este indicador ainda não foi configurado.");
    expect(systemStateSentence("partial")).toBe("Dados parciais disponíveis para o período.");
  });

  it("aceita as grafias equivalentes vindas do backend e de exportações", () => {
    expect(humanizeSystemState("NO_RECORDS")).toBe("Sem registros");
    expect(humanizeSystemState("insufficient_data")).toBe("Dados insuficientes");
    expect(humanizeSystemState("NOT_CONFIGURED")).toBe("Não configurado");
    expect(humanizeSystemState("PARTIAL")).toBe("Parcial");
    expect(humanizeSystemState("parcial")).toBe("Parcial");
  });

  it("devolve o fallback em vez de inventar significado para valor desconhecido", () => {
    expect(humanizeSystemState("kpi_customizado_da_planta")).toBe("Não disponível");
    expect(humanizeSystemState("", { fallback: "Sem leitura" })).toBe("Sem leitura");
  });

  it("é a única fonte dos rótulos consumidos pelas telas", () => {
    expect(availabilityLabel.sem_registros).toBe("Sem registros");
    expect(availabilityLabel.dados_insuficientes).toBe("Dados insuficientes");
    expect(humanize("sem_registros")).toBe("Sem registros");
    expect(humanize("timeline_op")).toBe("Linha do tempo da OP");
    expect(humanize("parada_por_falta_de_material")).toBe("Parada Por Falta De Material");
  });

  it("mostra estado vazio explicado, sem enum nem valor inventado", () => {
    const { container } = render(<EmptyState state="dados_insuficientes" />);
    expect(screen.getByText("Dados insuficientes")).toBeInTheDocument();
    expect(screen.getByText("Ainda não há dados suficientes para este indicador.")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(TECNICOS);
    expect(container.textContent).not.toMatch(/N\/A|undefined|null|\[\]/);
  });

  it("explica o estado vazio padrão em linguagem humana", () => {
    render(<EmptyState />);
    expect(screen.getByText("Sem registros")).toBeInTheDocument();
    expect(screen.getByText("Nenhum registro encontrado para o período.")).toBeInTheDocument();
  });

  it("mantém o estado técnico como gancho de estilo e humaniza o texto do card", () => {
    const { container } = render(<MetricCard label="OEE" value={humanizeSystemState("sem_registros")} availability="sem_registros" />);
    const card = container.querySelector(".metric-card");
    expect(card?.getAttribute("data-availability")).toBe("sem_registros");
    expect(card?.getAttribute("title")).toBe("Nenhum registro encontrado para o período.");
    expect(card?.textContent).toContain("Sem registros");
    expect(card?.textContent).not.toMatch(TECNICOS);
  });

  it("traduz o selo de situação sem expor o identificador", () => {
    render(<StatusBadge value="sem_registros" />);
    expect(screen.getByText("Sem registros")).toBeInTheDocument();
  });
});

describe("apresentação da IA", () => {
  it("substitui estado técnico citado na resposta", () => {
    expect(humanizeAssistantText("KPI = sem_registros")).toBe("KPI: Sem registros");
    expect(humanizeAssistantText("O OEE está com availability = partial_data."))
      .toBe("O OEE está com Parcial.");
    expect(humanizeAssistantText("Indicador em dados_insuficientes no período."))
      .toBe("Indicador em Dados insuficientes no período.");
  });

  it("remove a anotação interna de origem e o nome de tabela", () => {
    expect(humanizeAssistantText("Parada mais longa: 2 h (source = management_insights)"))
      .toBe("Parada mais longa: 2 h");
    expect(humanizeAssistantText("Produção lida de fonte: eventos_quantidade_producao."))
      .toBe("Produção lida de.");
    expect(humanizeAssistantText("Fonte: apontamento do operador."))
      .toBe("Fonte: apontamento do operador.");
  });

  it("não expõe SQL nem rastro de exceção", () => {
    const resposta = [
      "Resumo do turno pronto.",
      "",
      "```sql",
      "SELECT setor FROM apontamentos_operacionais;",
      "```",
    ].join("\n");
    const humanizado = humanizeAssistantText(resposta);
    expect(humanizado).toContain("Resumo do turno pronto.");
    expect(humanizado).not.toMatch(TECNICOS);

    const falha = "Traceback (most recent call last):\n  File \"x.py\", line 3\nValueError: falhou";
    expect(humanizeAssistantText(falha)).toBe("Detalhe interno não exibido.");
  });

  it("preserva o conteúdo analítico e o Markdown da resposta", () => {
    const { container } = render(<AssistantMarkdown content={"**Produção boa: 120 peças.**\n\n- Corte: 80\n- Dobra: 40\n\nUse `OEE` como referência."} />);
    expect(screen.getByText("Produção boa: 120 peças.").tagName).toBe("STRONG");
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByText("OEE").tagName).toBe("CODE");
    expect(container.textContent).not.toMatch(TECNICOS);
  });

  it("humaniza a resposta quando o indicador não tem dado", () => {
    const { container } = render(<AssistantMarkdown content={"Situação: KPI = sem_registros (source = management_insights)."} />);
    expect(container.textContent).toContain("KPI: Sem registros");
    expect(container.textContent).not.toMatch(TECNICOS);
  });

  it("mostra a situação e o tipo do relatório em linguagem de gestão", () => {
    expect(artifactStatusLabel("pronto")).toBe("Relatório pronto");
    expect(artifactStatusLabel("gerando")).toBe("Relatório em preparação");
    expect(artifactStatusLabel("estado_novo_do_backend")).toBe("Situação do relatório em atualização");
    expect(reportTypeLabel("dados_analiticos")).toBe("Dados analíticos");
    expect(reportTypeLabel("gerencial")).toBe("Relatório gerencial");
  });
});
