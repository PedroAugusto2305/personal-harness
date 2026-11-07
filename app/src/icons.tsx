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
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  clip: "M20 11.5l-8.2 8.2a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8",
  send: "M5 12h13M13 6l6 6-6 6",
  split: "M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM12 4v16",
  close: "M6 6l12 12M18 6L6 18",
  refresh: "M20 11a8 8 0 0 0-14.6-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.6 4.5L20 16M20 20v-4h-4",
  float: "M4 5h16v10H4zM8 19h8M7 9l2 1.5L7 12",
  user: "M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 21c0-4 4-6 8-6s8 2 8 6",
  palette: "M12 3a9 9 0 1 0 0 18c1 0 1.6-.8 1.6-1.6 0-.5-.2-.8-.5-1.2-.3-.3-.5-.7-.5-1.2 0-.9.7-1.6 1.6-1.6H16a5 5 0 0 0 5-5c0-4-4-7.4-9-7.4zM7.5 12a1 1 0 1 0 0-.1M10 8a1 1 0 1 0 0-.1M15 8a1 1 0 1 0 0-.1",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v6M12 7.5v.1",
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
