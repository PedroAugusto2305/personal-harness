// Ícones de traço, os mesmos do protótipo aprovado.

export const ICON = {
  home: "M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  term: "M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM7 9l3 3-3 3M13 15h4",
  study: "M4 19V5a2 2 0 0 1 2-2h13v14H6a2 2 0 0 0-2 2zm0 0a2 2 0 0 0 2 2h13M8 7h7",
  graph: "M6 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM18 5a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM9 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM8 6h8M10 16l7-7M6.5 8l2 8",
  kanban: "M3 4h5v16H3zM10 4h5v10h-5zM17 4h4v13h-4z",
  canvas: "M4 4h7v7H4zM13 13h7v7h-7zM11 7.5h4.5V13",
  agents: "M9 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM3 20c0-3 3-5 6-5s6 2 6 5M17 7a2.5 2.5 0 1 0 0 5M16 15c3 0 5 1.5 5 4",
  plug: "M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0zM12 16v5",
  gear: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5",
  plus: "M12 5v14M5 12h14",
} as const;

export function Icon({ d, size = 18, strokeWidth = 1.7 }: { d: string; size?: number; strokeWidth?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  );
}
