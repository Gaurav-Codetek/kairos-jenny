// The starter guide (an 8-step tour of the sidebar, shown on a first visit) and each screen's own guide (its panels and
// buttons, shown the first time that screen opens). A step points at an element marked data-guide="<target>"; a step
// with no target, or whose element isn't on the screen right now, is shown in the middle instead.
//
// What each screen is for is said in the product's own words, for someone who has never seen Kairos.

export type GuideStep = {
  /** data-guide value of the element to spotlight; none: a centred card */
  target?: string;
  title: string;
  body: string;
};

export type Guide = { id: string; title: string; steps: GuideStep[] };

const nav = (href: string) => `nav:${href}`;

export const WELCOME: Guide = {
  id: "welcome",
  title: "Starter guide",
  steps: [
    {
      target: nav("/"),
      title: "Welcome to Kairos · Overview",
      body:
        "Kairos understands your data; Jenny understands your business. These eight steps walk you through the " +
        "sidebar. Overview is the whole picture on one screen: the warehouse connected, what Kairos has mapped and " +
        "verified, and which AI agents are using it. Every number links to the screen behind it.",
    },
    {
      target: nav("/connections"),
      title: "Connections",
      body:
        "Where data comes in. Connect a Snowflake or Databricks warehouse, run a sync, and see what was mirrored: " +
        "tables, pipelines, runs and lineage. The demo is connected to a food-delivery warehouse in Snowflake.",
    },
    {
      target: nav("/agents"),
      title: "Agents",
      body:
        "Where agents come in. Any AI agent (Claude, Cursor, your own) connects once over MCP and understands this " +
        "data platform. See what they see, how ready the data is for them, their keys and every call they made.",
    },
    {
      target: nav("/graph"),
      title: "Map",
      body:
        "Every table, pipeline and column, and how data flows between them: raw tables, through staging and marts, into " +
        "data products. Click anything to see where it comes from and what depends on it.",
    },
    {
      target: nav("/enrichment"),
      title: "Enrichment",
      body:
        "Agents read your pipelines and profile each table: what it means, how its columns relate, whether its numbers " +
        "check out. This is where a raw table becomes something an agent can trust.",
    },
    {
      target: nav("/products"),
      title: "Data Products",
      body:
        "Business concepts served as one unit: Sales, Delivery Performance, Customer Retention. Each metric is defined " +
        "once, with its SQL, and checked with code: where it came from, whether it's fresh, that it was computed exactly " +
        "as defined.",
    },
    {
      target: nav("/living"),
      title: "Jenny",
      body:
        "Your business companion, running on NVIDIA Nemotron via Nebius. She watches the live numbers against a normal " +
        "day, tells you what matters, answers questions in chat or on a call, and can join your Google Meet. Try asking " +
        "her “How are we doing today?”",
    },
    {
      target: "guide:help",
      title: "Every screen has its own guide",
      body:
        "Each screen walks you through its panels and buttons the first time you open it. Replay it any time with the " +
        "? button in the screen's header, and this starter guide from “Starter guide” at the bottom of the sidebar.",
    },
  ],
};

export const SCREENS: Record<string, Guide> = {
  "/": {
    id: "overview",
    title: "Overview",
    steps: [
      {
        target: "ov:layer",
        title: "The context layer",
        body:
          "Platforms in on the left, agents out on the right, Kairos in the middle: how many tables it has mapped, " +
          "profiled and verified. Everything an agent asks goes through here, read-only, and every call is audited.",
      },
      {
        target: "ov:stats",
        title: "The four numbers that matter",
        body:
          "Entities mapped (tables, columns, pipelines, runs), semantic profiles built, calls agents made this week, and " +
          "pipeline runs that failed. Click any of them to open the screen behind it.",
      },
      {
        target: "ov:trust",
        title: "Trust coverage",
        body:
          "How much of the warehouse an agent can rely on: verified (profiled and checked), profiled, or only synced. " +
          "“Enrich” starts the work that moves tables to verified.",
      },
      {
        target: "ov:composition",
        title: "Warehouse composition",
        body: "What Kairos mirrored: the structure (catalogs, schemas, tables, columns) and the operations (jobs, tasks, runs).",
      },
    ],
  },
  "/connections": {
    id: "connections",
    title: "Connections",
    steps: [
      {
        target: "page:actions",
        title: "Add connection",
        body: "Connect a Snowflake or Databricks warehouse. Credentials stay on the server; Kairos only ever reads.",
      },
      {
        target: "conn:list",
        title: "Your connections",
        body: "Every platform connected, and when it last synced. Pick one to see its details on the right.",
      },
      {
        target: "conn:summary",
        title: "Connection summary",
        body: "Its status, what was synced, and whether each part of the last sync succeeded.",
      },
      {
        target: "conn:mcp",
        title: "Its address for agents",
        body: "The MCP endpoint an AI agent uses to work with this connection. Copy it into any MCP client.",
      },
      {
        target: "conn:domains",
        title: "Sync domains",
        body:
          "A sync runs as a chain: structure, then pipelines, then runs, then lineage. A failure in one doesn't stop " +
          "the others; each shows its own result.",
      },
      {
        target: "conn:sync",
        title: "Run a sync",
        body: "Mirror the platform again. Safe to re-run: unchanged things are updated in place, never duplicated.",
      },
    ],
  },
  "/agents": {
    id: "agents",
    title: "Agents",
    steps: [
      {
        target: "agents:tabs",
        title: "Six views of the agent side",
        body:
          "Connect: the one address and config any agent needs. What agents see: search the map as an agent would. " +
          "Readiness: could a brand-new agent use this platform? Agents & keys: who may connect. Activity: every " +
          "call, its cost and errors. Reports: what agents said was wrong or missing.",
      },
      {
        target: "agents:body",
        title: "Connect once",
        body:
          "One endpoint for every agent: copy the ready-made setup for Claude Code, Claude Desktop, Cursor, Python or " +
          "plain REST. From then on the agent understands this platform with no per-agent setup.",
      },
    ],
  },
  "/graph": {
    id: "map",
    title: "Map",
    steps: [
      {
        target: "map:tree",
        title: "Everything Kairos mapped",
        body:
          "Data sources, data products and pipelines, grouped. Search for any table, or click one to place it on the " +
          "canvas.",
      },
      {
        target: "map:canvas",
        title: "How data flows",
        body:
          "Raw tables on the left, through staging and marts, into data products on the right. Click a bundle to focus " +
          "it: everything upstream and downstream lights up. Drag to pan, scroll to zoom.",
      },
      {
        target: "map:zoom",
        title: "Zoom and fit",
        body: "Zoom in and out, or fit the whole map to the screen.",
      },
      {
        target: "map:legend",
        title: "Reading the lines",
        body: "Solid lines are data flowing from one table to the next; dashed lines are the order tasks run in.",
      },
      {
        target: "page:actions",
        title: "Mesh or Explorer",
        body:
          "Mesh shows the whole warehouse as bundles. Explorer starts from one entity and follows its lineage hop by " +
          "hop, with columns and runs if you want them. “Collapse all” closes every bundle.",
      },
    ],
  },
  "/enrichment": {
    id: "enrichment",
    title: "Enrichment",
    steps: [
      {
        target: "enr:scope",
        title: "Pick what to enrich",
        body:
          "Choose a seed (a table or pipeline); the agent follows its relationships outward. The entity cap keeps a run " +
          "to a size you choose.",
      },
      {
        target: "page:actions",
        title: "Start a run",
        body:
          "Starts the agents on your selection. You can stop a run at any time; it finishes the entity it's on, then " +
          "stops.",
      },
      {
        target: "enr:live",
        title: "Watch it work",
        body:
          "Live: each entity as an agent reads it, what it concluded, and what it checked against the data. Nothing " +
          "here changes the warehouse.",
      },
      {
        target: "enr:side",
        title: "What it learned",
        body:
          "The relationship vocabulary it discovered across tables, and every semantic profile it built. These feed the " +
          "data products and everything an agent sees.",
      },
    ],
  },
  "/products": {
    id: "products",
    title: "Data Products",
    steps: [
      {
        target: "prod:graph",
        title: "Your data products",
        body:
          "Each card is a business concept (Sales, Delivery Performance…) with its metrics, dimensions and inputs. " +
          "Click one to open it: its semantic model (every metric with its SQL), ports, contracts (the checks), supply " +
          "chain, and an Ask tab to query it in plain English.",
      },
      {
        target: "prod:mode",
        title: "Lineage or Semantic",
        body:
          "Lineage shows which tables feed each product. Semantic shows the vocabulary they share: dimensions like City " +
          "or Restaurant used by several products, so their numbers line up.",
      },
      {
        target: "prod:engine",
        title: "Run the engine",
        body:
          "Reads how data flows through the warehouse and builds every product it supports, with contracts checked " +
          "against the live data.",
      },
      {
        target: "prod:new",
        title: "New data product",
        body: "Name one business concept, like Sales, and build it yourself; Kairos finds the tables and defines the metrics.",
      },
    ],
  },
  "/living": {
    id: "jenny",
    title: "Jenny",
    steps: [
      {
        target: "jenny:headline",
        title: "Her live pulse",
        body:
          "Every few minutes Jenny reads the business's vitals against the same hour on recent same weekdays, and says " +
          "what matters in one line. “Look now” makes her look straight away; the switch pauses her.",
      },
      {
        target: "jenny:vitals",
        title: "The vitals",
        body:
          "Each card is one number she watches: today so far, what's normal by now (and its range), and where the day " +
          "is heading. The dotted line is a normal day; the solid line is today.",
      },
      {
        target: "jenny:views",
        title: "Live pulse or her stage",
        body:
          "Jenny's stage holds the charts she showed while talking, on a call or in a meeting, with what she named lit " +
          "up. They're the same charts that appear on her video tile in Google Meet.",
      },
      {
        target: "jenny:desk",
        title: "Her desk",
        body:
          "What you've asked her to keep an eye on, like “tell me if cancellations go above seven percent”, and what " +
          "she's found.",
      },
      {
        target: "jenny:chat",
        title: "Ask Jenny",
        body:
          "Ask anything about the business: “How are we doing today?”, “Which cities are carrying GMV?”. She looks it " +
          "up in the live data through Kairos and answers in plain numbers, putting a chart on her stage when it helps. " +
          "Ask about the weather (“Is rain hitting deliveries in Delhi?”) and she checks weather news for that city. " +
          "Her thinking runs on NVIDIA Nemotron 3.5 Super, served by Nebius Token Factory.",
      },
      {
        target: "jenny:call",
        title: "Call her",
        body: "Talk instead of type: press Call, allow the microphone, and just ask. She answers out loud.",
      },
      {
        target: "jenny:meet",
        title: "Send her to a Google Meet",
        body:
          "Paste a Meet link and she joins as a participant: say “Hey Jenny” and ask. She answers out loud and shows the " +
          "chart on her own video tile. (Joining calls needs her meeting host running beside Kairos; on the hosted demo, " +
          "watch it in the demo video.)",
      },
      {
        target: "jenny:tabs",
        title: "Notebook and replay",
        body:
          "The Notebook is her monthly reading of every metric: what has really changed, and what she's still waiting " +
          "on. Replay history shows how her past looks unfolded.",
      },
    ],
  },
};

/** The screen guide for a route: its own, or its parent screen's (a detail page keeps its screen's guide). */
export function screenGuide(pathname: string): Guide | null {
  if (SCREENS[pathname]) return SCREENS[pathname];
  const parent = Object.keys(SCREENS)
    .filter((k) => k !== "/" && pathname.startsWith(`${k}/`))
    .sort((a, b) => b.length - a.length)[0];
  return parent ? SCREENS[parent] : null;
}

/** Remembered per browser: a guide seen once isn't shown again on its own. Bump to show everyone the new copy. */
export const GUIDE_VERSION = 1;
export const seenKey = (id: string) => `kairos.guide.${id}.v${GUIDE_VERSION}`;
