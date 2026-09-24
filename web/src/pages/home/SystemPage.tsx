import { useState } from "react";
import { api, ApiError } from "../../api/client";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { Notice } from "../../components/Notice";

interface RebuildResult {
  ok: boolean;
  output: string;
  duration_seconds: number;
}

/**
 * Reconstrói o bundle do frontend (``npm run build``) para publicar
 * alterações de tela sem precisar de terminal. Só o build: o backend serve
 * ``web/dist`` direto a cada request, então ninguém é desconectado — decisão
 * do usuário, 16/09/2026.
 */
export function ManagementSystemPage() {
  const [status, setStatus] = useState<"idle" | "building" | "done" | "error">("idle");
  const [output, setOutput] = useState("");
  const [duration, setDuration] = useState<number | null>(null);

  async function reiniciarBuild() {
    setStatus("building");
    setOutput("");
    setDuration(null);
    try {
      const result = await api.post<RebuildResult>("/api/v1/system/rebuild-frontend");
      setStatus("done");
      setOutput(result.output);
      setDuration(result.duration_seconds);
    } catch (reason) {
      setStatus("error");
      const details = reason instanceof ApiError ? reason.details as { output?: string } | undefined : undefined;
      setOutput(details?.output ?? (reason instanceof ApiError ? reason.message : "Não foi possível reconstruir o frontend."));
    }
  }

  return (
    <PageFrame
      sectionId="dev"
      title="IagoDev — Sistema"
      subtitle="Ações operacionais do servidor."
      filters={false}
    >
      <SectionCard title="Build do frontend">
        <p className="operator-help">
          Reconstrói a pasta <code>web/dist</code> a partir do código-fonte atual (<code>npm run build</code>).
          O servidor já serve esses arquivos direto, sem reiniciar — quem estiver com o app aberto não é
          desconectado. Depois de terminar, basta atualizar a página (F5) para ver as alterações.
        </p>
        <div className="pause-form__actions">
          <button
            type="button"
            className="button button--primary"
            disabled={status === "building"}
            onClick={() => void reiniciarBuild()}
          >
            {status === "building" ? "Reconstruindo…" : "Reiniciar build"}
          </button>
        </div>
        {status === "done" ? (
          <Notice>
            Build concluído em {duration}s. Atualize a página para ver as alterações.
          </Notice>
        ) : null}
        {status === "error" ? (
          <Notice tone="error">
            O build falhou. Veja o log abaixo.
          </Notice>
        ) : null}
        {output ? <pre className="system-build-log">{output}</pre> : null}
      </SectionCard>
    </PageFrame>
  );
}
