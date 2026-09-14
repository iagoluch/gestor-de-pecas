import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { humanizeAssistantText } from "../utils/assistantText";

interface AssistantMarkdownProps {
  content: string;
}

/**
 * Renderização da resposta da IA. O mecanismo permanece intacto; aqui a
 * resposta passa pela camada de apresentação para falar como sistema de gestão
 * industrial, sem estado técnico, chave interna, SQL ou rastro de exceção.
 */
export function AssistantMarkdown({ content }: AssistantMarkdownProps) {
  return (
    <div className="ai-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          table({ node, ...props }) {
            void node;
            return <div className="ai-markdown__table"><table {...props} /></div>;
          },
        }}
      >
        {humanizeAssistantText(content)}
      </ReactMarkdown>
    </div>
  );
}
