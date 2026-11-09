import {
  siAirtable,
  siAnthropic,
  siAsana,
  siAtlassian,
  siBrave,
  siClickup,
  siCloudflare,
  siConfluence,
  siDiscord,
  siDocker,
  siFigma,
  siFirebase,
  siGithub,
  siGitlab,
  siGmail,
  siGoogle,
  siGooglecalendar,
  siGoogledocs,
  siGoogledrive,
  siGooglesheets,
  siHubspot,
  siJira,
  siLinear,
  siMercadopago,
  siModelcontextprotocol,
  siMongodb,
  siN8n,
  siNotion,
  siObsidian,
  siPerplexity,
  siPostgresql,
  siRedis,
  siSentry,
  siShopify,
  siStripe,
  siSupabase,
  siTelegram,
  siTodoist,
  siTrello,
  siVercel,
  siWhatsapp,
  siWordpress,
  siYoutube,
  siZapier,
} from "simple-icons";
import metisIcon from "../../src-tauri/icons/128x128.png";

/**
 * Logo de cada ferramenta nos Conectores (v0.9.9, pedido do Pedro). As marcas vêm do
 * simple-icons (CC0); o Slack saiu do pacote e é desenhado aqui. O conector próprio (MCP por
 * endereço ou comando) é reconhecido pelo nome, pelo servidor e pelo endereço; o que não bate
 * com nenhuma marca fica com o símbolo do MCP. "metis" é o interno (Brain e kanban).
 */

interface Mark {
  title: string;
  hex: string;
  path: string;
}

export type Brand = Mark | "slack" | "metis";

/** Palavra (no nome, servidor, URL ou comando) → marca. A primeira que bater vence. */
const RULES: [RegExp, Brand][] = [
  [/\b(metis|m[êe]tis|brain)\b/, "metis"],
  [/slack/, "slack"],
  [/google ?drive|gdrive|drive\.google/, siGoogledrive],
  [/gmail/, siGmail],
  [/google ?calendar|calendar\.google|gcal/, siGooglecalendar],
  [/google ?sheets|sheets\.google|planilha/, siGooglesheets],
  [/google ?docs|docs\.google/, siGoogledocs],
  [/google|workspace\.google/, siGoogle],
  [/github/, siGithub],
  [/gitlab/, siGitlab],
  [/notion/, siNotion],
  [/clickup/, siClickup],
  [/\bn8n\b/, siN8n],
  [/linear/, siLinear],
  [/figma/, siFigma],
  [/supabase/, siSupabase],
  [/vercel/, siVercel],
  [/stripe/, siStripe],
  [/sentry/, siSentry],
  [/jira/, siJira],
  [/confluence/, siConfluence],
  [/atlassian/, siAtlassian],
  [/asana/, siAsana],
  [/airtable/, siAirtable],
  [/hubspot/, siHubspot],
  [/cloudflare/, siCloudflare],
  [/postgres/, siPostgresql],
  [/obsidian/, siObsidian],
  [/trello/, siTrello],
  [/discord/, siDiscord],
  [/whatsapp/, siWhatsapp],
  [/telegram/, siTelegram],
  [/shopify/, siShopify],
  [/zapier/, siZapier],
  [/todoist/, siTodoist],
  [/docker/, siDocker],
  [/mongo/, siMongodb],
  [/redis/, siRedis],
  [/firebase/, siFirebase],
  [/brave/, siBrave],
  [/perplexity/, siPerplexity],
  [/youtube/, siYoutube],
  [/mercado ?pago/, siMercadopago],
  [/wordpress/, siWordpress],
  [/anthropic|claude/, siAnthropic],
];

const KIND: Record<string, Brand> = {
  slack: "slack",
  clickup: siClickup,
  notion: siNotion,
  github: siGithub,
  google: siGoogle,
  mcp: siModelcontextprotocol,
  brain: "metis",
};

/** A marca de um conector: pelo tipo, e o conector próprio pelo que ele diz de si. */
export function brandFor(kind: string, hints: (string | number | undefined | null)[] = []): Brand {
  if (kind !== "mcp") return KIND[kind] ?? siModelcontextprotocol;
  const text = hints
    .filter((h) => h !== undefined && h !== null && h !== "")
    .join(" ")
    .toLowerCase();
  return RULES.find(([re]) => re.test(text))?.[1] ?? siModelcontextprotocol;
}

/** Marca muito escura (Notion, GitHub, Vercel) some no tema escuro: usa a cor do texto. */
function darkHex(hex: string): boolean {
  const n = parseInt(hex, 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.06;
}

function SlackMark({ size }: { size: number }) {
  // Os quatro traços com o ponto de cada cor, no desenho do símbolo do Slack.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="1.5" y="6.5" width="9" height="4" rx="2" fill="#36C5F0" />
      <rect x="6.5" y="1.5" width="4" height="4" rx="2" fill="#36C5F0" />
      <rect x="13.5" y="1.5" width="4" height="9" rx="2" fill="#2EB67D" />
      <rect x="18.5" y="6.5" width="4" height="4" rx="2" fill="#2EB67D" />
      <rect x="13.5" y="13.5" width="9" height="4" rx="2" fill="#ECB22E" />
      <rect x="13.5" y="18.5" width="4" height="4" rx="2" fill="#ECB22E" />
      <rect x="6.5" y="13.5" width="4" height="9" rx="2" fill="#E01E5A" />
      <rect x="1.5" y="13.5" width="4" height="4" rx="2" fill="#E01E5A" />
    </svg>
  );
}

interface Props {
  brand: Brand;
  /** Lado do quadrado (px); o logo ocupa ~56%. */
  size?: number;
  className?: string;
}

/** O quadradinho com o logo, no lugar da inicial. */
export function BrandIcon({ brand, size = 32, className }: Props) {
  const inner = Math.round(size * 0.56);
  const title = brand === "slack" ? "Slack" : brand === "metis" ? "MÊTIS" : brand.title;
  const tint = typeof brand === "object" && !darkHex(brand.hex) ? `#${brand.hex}` : null;
  return (
    <span
      className={`brand-icon${className ? ` ${className}` : ""}`}
      style={{
        width: size,
        height: size,
        flexBasis: size,
        borderRadius: Math.round(size / 4),
        background: tint ? `color-mix(in srgb, ${tint} 16%, var(--elev))` : undefined,
      }}
      title={title}
      aria-label={title}
      role="img"
    >
      {brand === "slack" ? (
        <SlackMark size={inner} />
      ) : brand === "metis" ? (
        <img src={metisIcon} width={Math.round(size * 0.78)} height={Math.round(size * 0.78)} alt="" />
      ) : (
        <svg width={inner} height={inner} viewBox="0 0 24 24" aria-hidden="true">
          <path d={brand.path} fill={tint ?? "currentColor"} />
        </svg>
      )}
    </span>
  );
}
