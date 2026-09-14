import type { PropsWithChildren, ReactNode } from "react";

export function SectionCard({ title, action, children, className = "" }: PropsWithChildren<{
  title: string;
  action?: ReactNode;
  className?: string;
}>) {
  return (
    <section className={`section-card ${className}`}>
      <header className="section-card__header">
        <h2>{title}</h2>
        {action}
      </header>
      <div className="section-card__body">{children}</div>
    </section>
  );
}

