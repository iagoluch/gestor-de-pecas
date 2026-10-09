/**
 * Marca própria da IA Industrial: uma porca sextavada (a fábrica) com a
 * faísca de IA no centro. Usa `currentColor`, então herda a cor de quem a usa.
 */
export function AIIcon({ size = 16 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" aria-hidden="true">
      <path
        d="M12 2.4l8.3 4.8v9.6L12 21.6l-8.3-4.8V7.2z"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinejoin="round"
      />
      <path d="M12 6.9l1.3 3.8 3.8 1.3-3.8 1.3L12 17.1l-1.3-3.8L6.9 12l3.8-1.3z" fill="currentColor" />
    </svg>
  );
}
