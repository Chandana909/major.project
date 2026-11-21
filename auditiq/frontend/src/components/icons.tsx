// Line icons for the navigation, drawn on a 24-unit grid with the current text colour.

const PATHS: Record<string, string[]> = {
  overview: ["M3 13h8V3H3z", "M13 21h8V11h-8z", "M3 21h8v-6H3z", "M13 9h8V3h-8z"],
  queue: ["M4 21V4", "M4 4h11l-1.5 4L15 12H4"],
  invoice: ["M6 2h9l5 5v15H6z", "M14 2v6h6", "M9 13h8", "M9 17h6"],
  policy: ["M12 2 4 6v6c0 5 3.4 8.6 8 10 4.6-1.4 8-5 8-10V6z", "m9 12 2 2 4-4"],
  copilot: ["M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z", "M19 17l.8 2.2L22 20l-2.2.8L19 23l-.8-2.2L16 20l2.2-.8z"],
  architecture: ["M12 2.5 3.5 7.2v9.6l8.5 4.7 8.5-4.7V7.2z", "m3.5 7.2 8.5 4.7 8.5-4.7", "M12 11.9v9.6"],
  pipeline: ["M5 6h4v4H5z", "M15 14h4v4h-4z", "M15 4h4v4h-4z", "M9 8h3v8h3", "M12 6h3"],
  results: ["M4 20V10", "M10 20V4", "M16 20v-7", "M22 20H2"],
  analytics: ["M3 3v18h18", "M7 15l4-5 3 3 5-7", "M18 6h1v1"],
  rings: ["M8 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M17 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M9.5 8.5 15.5 15.5", "M7 9v6", "M9 18h5"],
  kafka: ["M4 6h16", "M4 12h16", "M4 18h16", "M8 4v4", "M14 10v4", "M10 16v4"],
  ai: ["M9 3v2", "M15 3v2", "M9 19v2", "M15 19v2", "M3 9h2", "M3 15h2", "M19 9h2", "M19 15h2", "M7 5h10v14H7z", "M10 9h4v6h-4z"],
  knowledge: ["M12 3 3 8l9 5 9-5z", "m3 13 9 5 9-5", "m3 17.5 9 5 9-5"],
  graph: ["M6 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4z", "M18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4z", "M12 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4z", "M7.7 5.8l8.6 1.4", "M7 6.8l4 10.4", "M16.9 8.7 13 17.2"],
  rag: ["M5 3h9l5 5v13H5z", "M14 3v5h5", "M10.5 16a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z", "m12.5 15.5 2 2"],
  search: ["M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14z", "m20 20-4-4"],
  assurance: ["M7 11V7a5 5 0 0 1 10 0v4", "M5 11h14v10H5z", "M12 15v2"],
  agent: ["M12 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6z", "M5 21v-2a7 7 0 0 1 14 0v2", "M17 8h4", "M19 6v4"],
  explain: ["M4 20h16", "M6 16V10", "M10 16V6", "M14 16v-8", "M18 16v-3", "M5 6l4-2 4 3 6-4"],
  investigator: ["M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z", "m21 21-5.6-5.6", "M8 10.5l2 2 3.5-4"],
  mail: ["M3 6h18v12H3z", "m3 7 9 6 9-6", "M16 15l2 2 3-3"],
  process: ["M3 6h5v4H3z", "M16 6h5v4h-5z", "M9.5 15h5v4h-5z", "M8 8h8", "M18.5 10v2.5H12V15", "M5.5 10v2.5H12"],
};

export function Icon({ name, size = 18 }: { name: keyof typeof PATHS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {(PATHS[name] ?? []).map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
