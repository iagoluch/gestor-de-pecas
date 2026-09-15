import type { MouseEvent, PropsWithChildren, ReactNode } from "react";

export function SectionCard({ title, action, children, className = "", navigation }: PropsWithChildren<{
  title: string;
  action?: ReactNode;
  className?: string;
  navigation?: { label: string; onNavigate: () => void };
}>) {
  const navigateFromCard = (event: MouseEvent<HTMLElement>) => {
    if (!navigation) return;
    const target = event.target as HTMLElement;
    if (!target.closest("button, a, input, select, textarea, [role='button']")) navigation.onNavigate();
  };

  return (
    <section className={`section-card ${navigation ? "section-card--navigable" : ""} ${className}`} onClick={navigateFromCard}>
      {navigation ? (
        <button type="button" className="section-card__navigation visually-hidden" aria-label={navigation.label} onClick={navigation.onNavigate} />
      ) : null}
      <header className="section-card__header">
        <h2>{title}</h2>
        {action}
      </header>
      <div className="section-card__body">{children}</div>
    </section>
  );
}
