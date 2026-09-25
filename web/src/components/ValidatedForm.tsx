import { useState, type FormEvent, type PropsWithChildren } from "react";

type Campo = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

const nomeDoCampo = (campo: Campo) => (campo.labels?.[0]?.firstChild?.textContent ?? campo.name).replace("*", "").trim();
const lista = (nomes: string[]) => (nomes.length > 1 ? `${nomes.slice(0, -1).join(", ")} e ${nomes[nomes.length - 1]}` : nomes[0]);

/**
 * Validação em pt-BR no lugar do balão nativo (que segue o idioma do
 * navegador): marca os campos com `aria-invalid`, foca o primeiro e devolve a
 * mensagem, ou "" quando o formulário está válido. Texto só de espaços conta
 * como vazio.
 */
export function validarFormulario(form: HTMLFormElement): string {
  const campos = Array.from(form.elements).filter(
    (el): el is Campo => el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement,
  );
  const vazios: Campo[] = [];
  const invalidos: Campo[] = [];
  for (const campo of campos) {
    if (campo.required && campo.value.trim() === "") vazios.push(campo);
    else if (!campo.checkValidity()) invalidos.push(campo);
    else campo.removeAttribute("aria-invalid");
  }
  const errados = [...vazios, ...invalidos];
  errados.forEach((campo) => campo.setAttribute("aria-invalid", "true"));
  if (!errados.length) return "";
  campos.find((campo) => errados.includes(campo))?.focus();
  return [vazios.length ? `Preencha ${lista(vazios.map(nomeDoCampo))}.` : "", invalidos.length ? `Confira ${lista(invalidos.map(nomeDoCampo))}.` : ""]
    .join(" ")
    .trim();
}

/** Limpa a marcação de erro do campo assim que o usuário o corrige. */
export const limparCampoInvalido = (event: FormEvent<HTMLFormElement>) => (event.target as Element).removeAttribute?.("aria-invalid");

/** Formulário de cadastro com validação inline em pt-BR (GE-04). */
export function ValidatedForm({ className, onValidSubmit, children }: PropsWithChildren<{ className?: string; onValidSubmit: () => void }>) {
  const [erro, setErro] = useState("");
  return (
    <form
      className={className}
      noValidate
      onInput={limparCampoInvalido}
      onSubmit={(event) => {
        event.preventDefault();
        const mensagem = validarFormulario(event.currentTarget);
        setErro(mensagem);
        if (!mensagem) onValidSubmit();
      }}
    >
      {children}
      {erro ? <p className="form-error form-error--inline" role="alert">{erro}</p> : null}
    </form>
  );
}

/** Marca visual de campo obrigatório; o leitor de tela já anuncia `required`. */
export const Obrigatorio = () => <span className="required-mark" aria-hidden="true">*</span>;
