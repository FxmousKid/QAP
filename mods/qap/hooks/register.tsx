// The qap mod: QAP in the Claude app, drawn as tiles (the dashboard's, which follow the dotfiles map).
//
// One QAP pane, beside every chat in the desktop app:
//   - home: "What are we working on today?". A tile per place work comes from: a tap writes a starting sentence in
//     the prompt box and sends nothing; on Enter, the prompt carries that source's directive (which skill, which
//     connector), unseen. Under it, the dashboard's home: the projects, their families and subjects, to browse.
//   - board: a batch's groups as tiles, one row per state, a badge for who needs you. A tap opens the group's chat
//     in split view (the app's own tool), or its page when this session did not start it.
// A session is also one of three things to QAP:
//   - a group session: its first prompt is the one qap split writes ("You are the session of group <batch>/<group>
//     (QAP). Read …/brief.md."). Its hooks tell qap serve when it starts, when its turn ends (it waits for you),
//     when it asks for a permission, when you answer, and when it ends. Its pane shows its own tile, and notes from
//     other groups (qap tell) are added to its conversation.
//   - the triage session: it ran qap split (or new-batch, board) or started a group session. Its pane shows the board.
//   - anything else: the pane shows home, and the mod reports nothing.
// The state lives in qap serve (GET /api/board, /api/tree, POST /api/events); the mod only reports and draws.
import { atom, read, update } from 'claude-code'
import type { ElementTable, EngineInterface, Register, RenderChildren } from 'claude-code'

import type { QapBoard, QapGroup, QapNode, QapRole, QapView } from '../types'

const PANE = 'qap'
const GROUP_PANE = 'qap-group'
const EVERY_MS = 5_000
const TREE_EVERY = 6 // ticks: the tree changes slowly
const PORTS = [8750, 8751, 8752, 8753, 8754]
// The whole first prompt qap split writes. Anchored: a session that only quotes it (a pasted split output, a review
// of this code) is not that group.
const FIRST_PROMPT = /^You are the session of group (.+?) \(QAP\)\. Read /
// `qap split <batch>`, `bin/qap board night-2 --json`, …: the batch a triage session works on.
const QAP_BATCH = /\bqap\b[^\n;&|]*?\s(?:split|new-batch|board)\s+["']?([A-Za-z0-9][^\s"';&|]*)/
const APP_SESSION = /\blocal_[A-Za-z0-9-]{8,}/
const NONE: QapRole = { kind: 'none' }
// A background task's notification, a message from another session, a trigger or a plugin also submit a prompt;
// none of them is the person answering. Every other origin is (the terminal, the desktop app, Remote Control).
const NOT_THE_PERSON = new Set(['task-notification', 'scheduled-trigger', 'peer', 'peer-send-message', 'projects-relay',
  'coordinator', 'observer', 'observer-activity', 'auto-continuation', 'slack-ping', 'plugin'])

// What every start ends in: the QA pass before any code.
const QA_PASS = 'Then write a QA pass with the qa-pass skill: what you found, and the decisions it needs, each with a '
  + 'default. No code, no write anywhere, until the person answers.'
// The places work comes from. A tap writes `text` in the prompt box (a second tap adds `also` on a new line); on
// Enter the prompt carries `directive`, which the person does not see.
const SOURCES = [
  { key: 'linear', icon: 'layers', colour: '#5E6AD2', name: 'Linear project', text: "Let's work on the Linear project ", also: 'the Linear project ',
    directive: 'Read the Linear project they name, its issues and their comments, through the Linear MCP connector '
      + 'only. If Linear is not connected or not authorized, say so, ask them to run /mcp, and stop. When the project '
      + `holds more than about six decisions, make it a batch: a triage pass, then one session per group. ${QA_PASS}` },
  { key: 'tickets', icon: 'flag', colour: '#5E6AD2', name: 'Linear tickets', text: "Let's work on these Linear tickets: ", also: 'these Linear tickets: ',
    directive: 'Read each ticket they name, with its comments and links, through the Linear MCP connector only. If '
      + 'Linear is not connected or not authorized, say so, ask them to run /mcp, and stop. For tickets of the Coach '
      + `product, the coach-idea-resolver skill drives the work, and its plan and open questions go in the QA pass. ${QA_PASS}` },
  { key: 'idea', icon: 'bulb', colour: '#B07D00', name: 'An idea', text: 'I have an idea: ', also: 'my idea: ',
    directive: 'Restate the idea in one line, then study what it touches (the code, the data, the screens). For an '
      + `idea about the Coach product, the coach-idea-resolver skill drives the work. ${QA_PASS}` },
  { key: 'bug', icon: 'bug', colour: '#D6304F', name: 'A bug', text: "There's a bug: ", also: 'a bug: ',
    directive: 'Run the incident-discovery skill on it first: read-only, the root cause before any fix. Put the '
      + `evidence, the cause and the fix options (each says whether it fixes the cause or hides the symptom) in the QA pass. ${QA_PASS}` },
  { key: 'meeting', icon: 'mic', colour: '#1E9E3A', name: 'A meeting', text: "Let's work from my meeting ", also: 'my meeting ',
    directive: 'Find the meeting they name and read it through the Granola MCP connector only: its notes, then its '
      + 'transcript where a detail is missing. If Granola is not reachable, say so. The QA pass says what was decided, '
      + `what is still open, and who said what (quoted). ${QA_PASS}` },
  { key: 'slack', icon: 'chat', colour: '#611f69', name: 'Slack thread', text: "Let's work from this Slack thread: ", also: 'this Slack thread: ',
    directive: 'Read the whole thread they name, replies included, through the Slack MCP connector only. Send nothing '
      + `on Slack. The QA pass quotes the messages it answers. ${QA_PASS}` },
  { key: 'pr', icon: 'code', colour: '#57606a', name: 'A pull request', text: "Let's review the pull request ", also: 'the pull request ',
    directive: 'Review the pull request they name (read it with gh): the pr-review skill in the Coach repo, the '
      + 'code-review skill elsewhere. The QA pass lists the findings, the most severe first. Post nothing on the PR '
      + `without their yes. ${QA_PASS}` },
] as const

// The dashboard's colours (src/qap/web/icons.js PALETTE, the dotfiles map's), and its icon set (icons.json).
const PALETTE = ['#5E60CE', '#0F8B8D', '#F46D01', '#2F6FDB', '#8338EC', '#1E9E3A', '#D6304F', '#0B66C3', '#A8650C',
  '#7B2CBF', '#138FA3', '#C15F3C']
// For a group with no icon of its own: one picked from its name, so it keeps it.
const GROUP_ICONS = ['bell', 'shield', 'layers', 'plug', 'spark', 'key', 'database', 'chart', 'flask', 'gear', 'link', 'globe']
const RED = '#e5484d'
const ORANGE = '#f08c00'
const GREEN = '#30a46c'
const BLUE = '#3b82f6'
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const ICONS: Record<string, string> = {
  folder: "<path d=\"M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z\"/>",
  doc: "<path d=\"M7 3h7l4 4v14H7z\"/><path d=\"M14 3v4h4M10 12h5M10 16h5\"/>",
  chat: "<path d=\"M4 5h16v11H9l-5 4z\"/><path d=\"M8 9.5h8M8 12.5h5\"/>",
  shield: "<path d=\"M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z\"/><path d=\"M8.5 12l2.5 2.5 4.5-5\"/>",
  key: "<circle cx=\"8\" cy=\"15\" r=\"4\"/><path d=\"M11 12l8-8M16 7l3 3M14 9l2 2\"/>",
  lock: "<rect x=\"5\" y=\"11\" width=\"14\" height=\"10\" rx=\"2\"/><path d=\"M8 11V7a4 4 0 0 1 8 0v4\"/>",
  database: "<ellipse cx=\"12\" cy=\"5\" rx=\"8\" ry=\"3\"/><path d=\"M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5\"/><path d=\"M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3\"/>",
  users: "<circle cx=\"9\" cy=\"8\" r=\"3.5\"/><path d=\"M2.5 20c.5-3.5 3.2-6 6.5-6s6 2.5 6.5 6\"/><circle cx=\"17\" cy=\"9\" r=\"2.5\"/><path d=\"M17 14c2.5 0 4.2 1.8 4.5 4.5\"/>",
  bulb: "<path d=\"M9 18h6M10 21h4\"/><path d=\"M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z\"/>",
  spark: "<path d=\"M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z\"/><path d=\"M19 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z\"/>",
  plug: "<path d=\"M9 2v6M15 2v6\"/><path d=\"M6 8h12v4a6 6 0 0 1-12 0z\"/><path d=\"M12 18v4\"/>",
  mic: "<rect x=\"9\" y=\"3\" width=\"6\" height=\"11\" rx=\"3\"/><path d=\"M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6\"/>",
  calendar: "<rect x=\"3\" y=\"5\" width=\"18\" height=\"16\" rx=\"2\"/><path d=\"M3 10h18M8 3v4M16 3v4\"/>",
  chart: "<path d=\"M4 20V4M4 20h16\"/><path d=\"M8 16v-5M12 16V8M16 16v-3M20 16V6\"/>",
  bell: "<path d=\"M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z\"/><path d=\"M10 21h4\"/>",
  rocket: "<path d=\"M12 3c3 2 5 5.5 5 9.5L15 17H9l-2-4.5C7 8.5 9 5 12 3z\"/><circle cx=\"12\" cy=\"10\" r=\"1.8\"/><path d=\"M9 17l-2 4M15 17l2 4\"/>",
  bug: "<rect x=\"7\" y=\"7\" width=\"10\" height=\"13\" rx=\"5\"/><path d=\"M12 7V4M9 4l1.5 2M15 4l-1.5 2M3 12h4M17 12h4M4 18l3-2M20 18l-3-2M4 7l3 2M20 7l-3 2\"/>",
  flask: "<path d=\"M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3\"/><path d=\"M7 15h10\"/>",
  book: "<path d=\"M4 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4z\"/><path d=\"M20 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6z\"/>",
  gear: "<circle cx=\"12\" cy=\"12\" r=\"3\"/><circle cx=\"12\" cy=\"12\" r=\"7\"/><path d=\"M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1\"/>",
  layers: "<path d=\"M12 3l9 5-9 5-9-5z\"/><path d=\"M3 13l9 5 9-5\"/>",
  link: "<path d=\"M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1\"/><path d=\"M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1\"/>",
  globe: "<circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z\"/>",
  phone: "<rect x=\"7\" y=\"2\" width=\"10\" height=\"20\" rx=\"2.5\"/><path d=\"M11 18h2\"/>",
  code: "<path d=\"M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16\"/>",
  terminal: "<rect x=\"3\" y=\"4\" width=\"18\" height=\"16\" rx=\"2\"/><path d=\"M7 9l3 3-3 3M12 15h5\"/>",
  star: "<path d=\"M12 2.8l2.75 5.57 6.15.9-4.45 4.33 1.05 6.12L12 16.84l-5.5 2.89 1.05-6.12L3.1 9.27l6.15-.9z\"/>",
  flag: "<path d=\"M5 21V4M5 4h11l-2 4 2 4H5\"/>",
  box: "<path d=\"M3 7l9-4 9 4v10l-9 4-9-4z\"/><path d=\"M3 7l9 4 9-4M12 11v10\"/>",
  compass: "<circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"M15.5 8.5l-2 5-5 2 2-5z\"/>",
  money: "<rect x=\"2\" y=\"6\" width=\"20\" height=\"12\" rx=\"2\"/><circle cx=\"12\" cy=\"12\" r=\"2.5\"/><path d=\"M6 9v.01M18 15v.01\"/>",
  mail: "<rect x=\"3\" y=\"5\" width=\"18\" height=\"14\" rx=\"2\"/><path d=\"M3 7l9 6 9-6\"/>",
  briefcase: "<rect x=\"3\" y=\"7\" width=\"18\" height=\"13\" rx=\"2\"/><path d=\"M8.5 7V5.5A1.5 1.5 0 0 1 10 4h4a1.5 1.5 0 0 1 1.5 1.5V7M3 13h18M10.5 13v2h3v-2\"/>",
  home: "<path d=\"M3.5 11.5L12 4.5l8.5 7\"/><path d=\"M5.5 10v9.5h13V10\"/><path d=\"M10 19.5v-5.5h4v5.5\"/>",
}
const ICON_COLOURS: Record<string, string> = {
  folder: "#4A86CF", doc: "#6A4C93", chat: "#0F8B8D", shield: "#2F6FDB", key: "#B07D00", lock: "#8338EC", database: "#0B66C3", users: "#F05133", bulb: "#C98A00", spark: "#C15F3C", plug: "#9D4EDD", mic: "#D6304F", calendar: "#1E9E3A", chart: "#138FA3", bell: "#E5620F", rocket: "#F46D01", bug: "#AF1B3F", flask: "#3F8F1F", book: "#7B2CBF", gear: "#4D4D4D", layers: "#5E60CE", link: "#0E7C7B", globe: "#1F8FE5", phone: "#3E8E41", code: "#8A5CF5", terminal: "#33312C", star: "#D99A00", flag: "#C8283F", box: "#A8650C", compass: "#2563B8", money: "#4A7C2F", mail: "#3478F6", briefcase: "#3D5A80", home: "#2E8B57",
}

// Change a tag when the shape of its value changes: a value an earlier version stored is then read as the default.
const role = atom({ plugin: 'qap', key: 'role' } as const, NONE, { shape: 'role-1' })
const board = atom({ plugin: 'qap', key: 'board' } as const, null, { shape: 'board-2' })
const groupView = atom({ plugin: 'qap', key: 'group' } as const, null, { shape: 'group-2' })
const problem = atom({ plugin: 'qap', key: 'problem' } as const, null)
const server = atom({ plugin: 'qap', key: 'server' } as const, null)
const delivered = atom({ plugin: 'qap', key: 'delivered' } as const, 0)
const view = atom({ plugin: 'qap', key: 'view' } as const, 'home' as QapView, { shape: 'view-1' })
const tree = atom({ plugin: 'qap', key: 'tree' } as const, null as QapNode | null, { shape: 'tree-1' })
// Where home is browsing: '' (the projects), a project ('@work'), a folder or a subject path.
const place = atom({ plugin: 'qap', key: 'place' } as const, '', { shape: 'place-1' })

type McpName = `mcp__${string}__${string}`
type Json = Record<string, unknown>
type TreeJson = { path: string; name?: string; kind: string; title: string; icon?: string; color?: string; count?: number;
  latest?: string; updated?: string; project?: string; passes?: { file: string }[]; children?: TreeJson[];
  projects?: { id: string; path: string; title: string; icon?: string; color?: string; updated?: string }[] }

// Module variables start over on a reload; session.start runs again then.
let lastKind = ''
// Whether the person (or the first prompt) started the running turn: only then are its last words a question.
let byPerson = false
let isRefreshing = false
let ticks = 0
let openTool: McpName | undefined
// What the tiles tapped since the last prompt wrote in the box, and the directive each one adds once it is sent.
let pending: { phrase: string; directive: string }[] = []

// ---------------------------------------------------------------- qap serve

async function findServer($: EngineInterface): Promise<string | null> {
  const known = await read($, server)
  if (known !== null) {
    return known
  }
  for (const port of PORTS) {
    const base = `http://127.0.0.1:${port}`
    try {
      const res = await $.http.fetch(`${base}/api/batches`)
      if (res.ok && res.text.includes('"batches"')) {
        await update($, server, () => base)

        return base
      }
    } catch {
      // nothing on this port
    }
  }

  return null
}

async function api($: EngineInterface, path: string, body?: Json): Promise<Json | null> {
  const base = await findServer($)
  if (base === null) {
    await update($, problem, () => 'QAP is not running.')

    return null
  }
  try {
    const init = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined
    const res = await $.http.fetch(`${base}${path}`, init)
    const data = JSON.parse(res.text) as Json
    if (data.ok !== true) {
      await update($, problem, () => `qap serve: ${String(data.error ?? res.status)}`)

      return null
    }
    await update($, problem, () => null)

    return data
  } catch (error) {
    await update($, server, () => null)
    await update($, problem, () => `qap serve did not answer: ${String(error)}`)

    return null
  }
}

// ---------------------------------------------------------------- roles

async function bindGroup($: EngineInterface, group: string): Promise<void> {
  const batch = group.split('/').slice(0, -1).join('/')
  const bound: QapRole = { kind: 'group', group, batch }
  await update($, role, () => bound)
  await $.store.set(`role:${await $.session.id()}`, bound)
  void $.ui.open({ id: GROUP_PANE, title: 'This group' })
}

async function bindTriage($: EngineInterface, ref: string): Promise<void> {
  const current = await read($, role)
  if (current.kind === 'group') {
    return
  }
  if (!(await showBoard($, ref))) {
    return
  }
  const b = await read($, board)
  const bound: QapRole = { kind: 'triage', batch: b?.batch ?? ref }
  await update($, role, () => bound)
  await $.store.set(`role:${await $.session.id()}`, bound)
}

// The batch's board in the pane, from the triage session or a tap on a batch's folder at home.
async function showBoard($: EngineInterface, ref: string): Promise<boolean> {
  const data = await api($, `/api/board?path=${encodeURIComponent(ref)}`)
  if (data === null) {
    return false
  }
  await update($, board, () => data as unknown as QapBoard)
  await update($, view, () => 'board' as QapView)
  void $.ui.open({ id: PANE, title: 'QAP' })

  return true
}

// The board could not be read. When qap serve answered, the batch is gone (deleted, moved): this session is no
// batch's triage any more, and the pane goes home. When qap serve is down, nothing changes: the next tick retries.
async function leaveBatch($: EngineInterface): Promise<void> {
  if (!(await read($, problem))?.startsWith('qap serve: ')) {
    return
  }
  await update($, problem, () => null)
  await update($, board, () => null)
  if ((await read($, role)).kind === 'triage') {
    await update($, role, () => NONE)
    await $.store.set(`role:${await $.session.id()}`, NONE)
  }
  void $.ui.open({ id: PANE, title: 'QAP' })
  await goHome($)
}

async function goHome($: EngineInterface): Promise<void> {
  await update($, view, () => 'home' as QapView)
  await refreshTree($)
}

async function report($: EngineInterface, kind: string, text = '', origin = ''): Promise<void> {
  const current = await read($, role)
  if (current.kind !== 'group') {
    return
  }
  lastKind = kind
  await api($, '/api/events', { group: current.group, kind, text: text.slice(-1500), origin,
    session_id: await $.session.id() })
  await refresh($)
}

// ---------------------------------------------------------------- refreshing what the panes draw

async function refresh($: EngineInterface): Promise<void> {
  if (isRefreshing) {
    return
  }
  isRefreshing = true
  try {
    const current = await read($, role)
    const shown = await read($, view)
    const b = await read($, board)
    if (current.kind === 'group') {
      const data = await api($, `/api/group?path=${encodeURIComponent(current.group)}`)
      if (data !== null) {
        const g = data as unknown as QapGroup
        await update($, groupView, () => g)
        await deliver($, g)
      }
    } else if (shown === 'board' && b !== null) {
      const data = await api($, `/api/board?path=${encodeURIComponent(b.batch)}`)
      if (data !== null) {
        await update($, board, () => data as unknown as QapBoard)
      } else {
        await leaveBatch($)
      }
    } else if (ticks % TREE_EVERY === 0) {
      await refreshTree($)
    }
  } finally {
    isRefreshing = false
  }
}

// The dashboard's tree, as its home shows it: the projects, each holding its families; what belongs to no project
// next to them. Only the fields a tile draws are kept.
async function refreshTree($: EngineInterface): Promise<void> {
  const data = await api($, '/api/tree')
  if (data === null) {
    return
  }
  const raw = data.tree as TreeJson
  const node = (n: TreeJson): QapNode => ({
    kind: n.kind === 'subject' ? 'subject' : 'folder', path: n.path, name: n.name ?? n.path.split('/').pop() ?? '',
    title: n.title, icon: n.icon ?? '', color: n.color ?? '', count: n.count, latest: n.latest, updated: n.updated,
    file: n.passes?.at(-1)?.file, children: (n.children ?? []).map(node),
  })
  const top = raw.children ?? []
  const projects = (raw.projects ?? []).map(p => ({
    kind: 'project' as const, path: p.path, name: p.id, title: p.title, icon: p.icon ?? '', color: p.color ?? '',
    updated: p.updated, children: top.filter(c => c.project === p.id).map(node),
  }))
  const loose = top.filter(c => !projects.some(p => p.name === c.project)).map(node)
  const root: QapNode = { kind: 'root', path: '', name: '', title: 'QA passes', icon: '', color: '', children: [...projects, ...loose] }
  await update($, tree, () => root)
}

// A note another group sent (qap tell) is added to this conversation once, where the model reads it next turn.
async function deliver($: EngineInterface, g: QapGroup): Promise<void> {
  const seen = await read($, delivered)
  const notes = (g.inbox ?? []).filter(note => note.id > seen)
  for (const note of notes) {
    const text = `Note from group ${note.from} (qap tell, ${note.at}):\n\n${note.text}`
    await $.session.append({ message: { type: 'user', content: [{ type: 'text', text }] } })
    $.ui.toast(`A note from ${note.from.split('/').pop() ?? note.from}`)
    await update($, delivered, () => note.id)
    await $.store.set(`delivered:${await $.session.id()}`, note.id)
  }
}

// ---------------------------------------------------------------- actions from the panes

// A source tile: its sentence in the prompt box, nothing sent. A second tap keeps what is there and adds a line.
async function startFrom($: EngineInterface, key: string): Promise<void> {
  const s = SOURCES.find(x => x.key === key)
  if (!s) {
    return
  }
  const typed = (await $.prompt.read()).text.trimEnd()
  if (!typed) {
    pending = []
  }
  const phrase = typed ? `And ${s.also}` : s.text
  const filled = await $.prompt.fill({ text: typed ? `${typed}\n${phrase}` : phrase })
  if (filled.isFilled) {
    pending.push({ phrase: phrase.trim(), directive: `Started from “${s.name}” in the QAP pane. ${s.directive}` })
  } else {
    $.ui.toast('The prompt box is busy: close the dialog first.')
  }
}

// A subject reached by browsing: carry on with it here.
async function continueSubject($: EngineInterface, n: QapNode): Promise<void> {
  const phrase = `Let's pick up “${n.title}”`
  const filled = await $.prompt.fill({ text: `${phrase}: ` })
  if (filled.isFilled) {
    pending = [{ phrase, directive: `Started from the QA subject ${n.path} in the QAP pane. Run \`qap where ${n.path} --json\`, `
      + 'read its latest pass, and say in a few lines where the thread stands and what waits for the person. The next '
      + 'round follows the qa-pass skill (qap carry, then the answers, then qap build --check).' }]
  }
}

// Opening a folder that is a batch shows its board; anything else is browsed.
async function go($: EngineInterface, path: string): Promise<void> {
  const root = await read($, tree)
  const n = root ? find(root, path) : undefined
  if (n?.kind === 'folder') {
    const listed = await api($, '/api/batches')
    const batches = (listed?.batches ?? []) as { path: string }[]
    if (batches.some(x => x.path === path) && (await showBoard($, path))) {
      return
    }
  }
  await update($, place, () => path)
}

// A group tile: its chat beside this one when this session started it, else its page.
async function openGroup($: EngineInterface, g: QapGroup): Promise<void> {
  const id = g.session.app_id
  if (id && openTool) {
    const ran = await $.tool.call({ tool: openTool, session_id: id, target: 'split' } as never)
    const said = ran.deny ?? (ran.isError ? ran.text : '')
    if (!said) {
      return
    }
  }
  if (g.page) {
    await openPage($, g.page)
  } else {
    $.ui.toast(`${pretty(g.name)} has no page yet.`)
  }
}

async function openPage($: EngineInterface, path: string): Promise<void> {
  const base = await findServer($)
  if (base === null || !path) {
    return
  }
  const url = path.startsWith('http') ? path : `${base}${path}`
  const ran = await $.process.run(['open', url])
  if (ran.exitCode !== 0) {
    $.ui.toast(`Could not open ${url}`)
  }
}

async function findOpenTool($: EngineInterface): Promise<void> {
  const all = await $.tool.list()
  const name = all.find(t => t.name.includes('ccd_window') && t.name.endsWith('__open_session_in'))?.name
  openTool = name as McpName | undefined
}

// ---------------------------------------------------------------- the hooks

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'qap', description: 'Open the QAP pane: what are we working on today?' })
    await $.command.register({ name: 'qap-board', description: 'Show the board of a batch: qap-board <batch>' })
    await findOpenTool($)
    const saved = (await $.store.get(`role:${await $.session.id()}`)) as QapRole | undefined
    const current = await read($, role)
    if (current.kind === 'none' && saved && saved.kind !== 'none') {
      await update($, role, () => saved)
      // A resumed session has had these notes already.
      const seen = Number((await $.store.get(`delivered:${await $.session.id()}`)) ?? 0)
      await update($, delivered, n => Math.max(n ?? 0, seen))
    }
    const now = await read($, role)
    if (now.kind === 'group') {
      void $.ui.open({ id: GROUP_PANE, title: 'This group' })
      void refresh($).catch(quiet)
    } else if (now.kind === 'triage') {
      void showBoard($, now.batch).then(isShown => isShown ? undefined : leaveBatch($)).catch(quiet)
    } else if (e.surface === 'desktop') {
      void $.ui.open({ id: PANE, title: 'QAP' })
      void goHome($).catch(quiet)
    }
    $.clock.every(EVERY_MS, () => {
      ticks += 1
      void refresh($).catch(quiet)
    })

    return next(e)
  })

  on('command.run', { command: 'qap' }, async $ => {
    await $.ui.open({ id: PANE, title: 'QAP' })
    await goHome($)

    return { text: 'QAP opened.' }
  })

  on('command.run', { command: 'qap-board' }, async ($, e) => {
    const ref = (e.args ?? '').trim()
    const current = await read($, role)
    if (ref) {
      await bindTriage($, ref)
    } else if (current.kind === 'group') {
      await $.ui.open({ id: GROUP_PANE, title: 'This group' })
    } else if (current.kind === 'triage') {
      await showBoard($, current.batch)
    } else {
      return { text: 'Give the batch: /qap-board <batch>.' }
    }

    return { text: 'Board opened.' }
  })

  // A prompt the tiles started carries their directives, unseen. The first prompt of a group names the group; every
  // later prompt of the person is an answer.
  on('prompt.submit', async ($, e, next) => {
    if (e.isMeta || e.command) {
      return next(e)
    }
    const directives = pending.filter(p => e.text.includes(p.phrase)).map(p => `<qap-start>\n${p.directive}\n</qap-start>`)
    pending = []
    const current = await read($, role)
    const named = FIRST_PROMPT.exec(e.text.replace(REMINDERS, '').trim())
    if (current.kind === 'none' && named?.[1]) {
      await bindGroup($, named[1])
      byPerson = true
      await report($, 'started')
    } else if (current.kind === 'group' && isThePerson(e.origin.kind, e.text)) {
      byPerson = true
      await report($, 'answered', e.text.replace(REMINDERS, '').trim().slice(0, 300), e.origin.kind)
    }

    return next(directives.length ? { ...e, context: [...(e.context ?? []), ...directives] } : e)
  }).catch(($, e, next) => next(e))

  // Any turn of the main loop is work, whoever started it: a task's notification, a queued prompt, a note.
  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined && (lastKind === '' || lastKind === 'waiting' || lastKind === 'permission')) {
      await report($, 'working')
    }

    return next(e)
  })

  // The main loop's turn ended: the session waits for the person. Its last words are the question.
  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) {
      await report($, 'waiting', byPerson ? e.answer : '')
      byPerson = false
    }

    return next(e)
  })

  on('classic.PermissionRequest', async ($, e, next) => {
    await report($, 'permission', `Asks to run ${e.tool_name}`)

    return next(e)
  }).catch(($, e, next) => next(e))

  on('classic.Notification', async ($, e, next) => {
    if (e.notification_type.includes('permission')) {
      await report($, 'permission', e.message)
    }

    return next(e)
  }).catch(($, e, next) => next(e))

  on('tool.call', async ($, e, next) => {
    const args = e as unknown as Json
    const startsGroup = e.tool.endsWith('__start_session') ? FIRST_PROMPT.exec(String(args.prompt ?? '').trim()) : null
    const ran = await next(e)
    // The permission dialog runs inside next(e): once the tool returns, the person has answered it.
    if (lastKind === 'permission') {
      await report($, 'working')
    }
    if (startsGroup?.[1] && ran.deny === undefined) {
      const id = APP_SESSION.exec(ran.text ?? '')?.[0]
      const group = startsGroup[1]
      await bindTriage($, group.split('/').slice(0, -1).join('/'))
      if (id) {
        await api($, '/api/events', { group, kind: 'spawned', app_id: id })
        await refresh($)
      }
    }
    if (e.tool === 'Bash' && ran.deny === undefined && !ran.isError) {
      const batch = QAP_BATCH.exec(String(args.command ?? ''))?.[1]
      if (batch) {
        await bindTriage($, batch)
      }
    }

    return ran
  }).catch(($, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    await report($, 'ended')

    return next(e)
  })

  // ---------------------------------------------------------------- the QAP pane: home, or a batch's board

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const table = $.ui.resolve(e)
    const { Box, Text, Button } = table
    const Svg = 'Svg' in table ? (table as ElementTable<'desktop'>).Svg : undefined
    const shown = await read($, view)
    const b = await read($, board)
    const trouble = await read($, problem)

    // One tile: the picture (when the surface draws SVG), and its name, which is the button.
    const tile = (key: string, name: string, svg: string, onPress: () => void, size = 72) => (
      <Box key={`tile-${key}`} flexDirection="column" alignItems="center">
        {Svg ? <Svg source={svg} alt={name} width={size} height={Math.round(size * svgRatio(svg))} /> : null}
        <Button key={key} plain label={name} onPress={onPress} />
      </Box>
    )
    const row = (key: string, tiles: RenderChildren[]) => (
      <Box key={`row-${key}`} flexDirection="row" flexWrap="wrap" justifyContent="center" gap={1}>{tiles}</Box>
    )
    const heading = (text: string, isRed = false) => (
      <Text key={`h-${text}`} size="caption" weight="semibold" dimColor={!isRed} color={isRed ? 'error' : undefined}>
        {text.toUpperCase()}
      </Text>
    )

    if (shown === 'board' && b !== null) {
      const lane = (name: QapGroup['lane']) => b.groups.filter(g => g.lane === name)
      const groupTile = (g: QapGroup) => tile(`jump-${g.name}`, pretty(g.name), groupSvg(g, b), () => void openGroup($, g))
      const rows: [string, QapGroup[], boolean][] = [
        ['Needs you', lane('needs_you'), true], ['Working', lane('working'), false],
        ['Waits for another group', lane('waits'), false], ['Not started', [...lane('ready'), ...lane('stopped')], false],
        ['Done', lane('done'), false],
      ]
      const fixes = b.fast.flatMap(f => f.topics)
      const needs = lane('needs_you').length

      return (
        <Box flexDirection="column" alignItems="center" gap={1}>
          <Box flexDirection="row" justifyContent="space-between" alignItems="center" gap={1}>
            <Button key="home" plain dimColor label="‹ Home" onPress={() => void goHome($)} />
            <Text weight="semibold">{b.title}</Text>
          </Box>
          <Text dimColor size="footnote">
            {needs ? `${needs} need${needs === 1 ? 's' : ''} you` : 'nobody waits for you'} · {b.groups.length} groups
          </Text>
          {rows.filter(([, gs]) => gs.length > 0).flatMap(([title, gs, isRed]) => [heading(title, isRed), row(title, gs.map(groupTile))])}
          {fixes.length > 0 && heading('Quick fixes')}
          {fixes.length > 0 && row('fixes', fixes.map(t => tile(`fix-${t.num}`, clip(t.title, 22), tileSvg('doc', '#0F8B8D'),
            () => void openPage($, b.triage.page))))}
          {b.start_next.length > 0 && (
            <Button key="start" variant="primary" label={`Start ${b.start_next.length} chat${b.start_next.length === 1 ? '' : 's'}`}
              onPress={() => void $.prompt.fill({ text: `Start the next groups of ${b.title}: ${b.start_next.map(g => pretty(g.name)).join(', ')}.` })} />
          )}
          {trouble !== null && <Text dimColor size="footnote">{trouble}</Text>}
        </Box>
      )
    }

    // Home: where work comes from, then the dashboard's home to browse.
    const root = await read($, tree)
    const at = await read($, place)
    const here = root ? find(root, at) ?? root : null
    const chain = root && here ? trail(root, here.path) : []
    const nodeTile = (n: QapNode) => tile(`nav-${n.path}`, clip(n.title, 24), nodeSvg(n), () => void go($, n.path),
      n.kind === 'project' ? 92 : 72)
    let browse: RenderChildren = null
    if (here?.kind === 'subject') {
      browse = (
        <Box key="subject" flexDirection="column" alignItems="center" gap={1}>
          {Svg ? <Svg source={nodeSvg(here)} alt={here.title} width={88} height={88} /> : null}
          <Text weight="semibold">{here.title}</Text>
          <Text dimColor size="footnote">
            {here.count ?? 0} pass{here.count === 1 ? '' : 'es'}{here.updated ? ` · ${shortDate(here.updated)}` : ''}
          </Text>
          <Box flexDirection="row" gap={1}>
            {here.file ? <Button key="open" variant="primary" label={`Open pass ${here.latest ?? ''}`}
              onPress={() => void openPage($, `/c/${here.path}/${here.file ?? ''}`)} /> : null}
            <Button key="continue" label="Continue here" onPress={() => void continueSubject($, here)} />
          </Box>
        </Box>
      )
    } else if (here) {
      const kids = here.children
      const groups: [string, QapNode[]][] = here.kind === 'root'
        ? [['Projects', kids.filter(n => n.kind === 'project')], ['Folders', kids.filter(n => n.kind === 'folder')],
            ['Subjects', kids.filter(n => n.kind === 'subject')]]
        : [[here.kind === 'project' ? 'Families' : 'Folders', kids.filter(n => n.kind === 'folder')],
            ['Subjects', kids.filter(n => n.kind === 'subject')]]
      browse = groups.filter(([, ns]) => ns.length > 0).flatMap(([title, ns]) => [heading(title), row(title, ns.map(nodeTile))])
    }

    return (
      <Box flexDirection="column" alignItems="center" gap={1}>
        <Text size="heading" weight="semibold">What are we working on today?</Text>
        <Text dimColor size="footnote">Tap one, or several. Nothing is sent before you press Enter.</Text>
        {heading('Start from')}
        {row('sources', SOURCES.map(s => tile(`src-${s.key}`, s.name, tileSvg(s.icon, s.colour), () => void startFrom($, s.key))))}
        <Box key="crumbs" flexDirection="row" flexWrap="wrap" justifyContent="center" alignItems="center" marginTop={1}>
          {chain.map((n, i) => (
            <Button key={`crumb-${n.path || 'root'}`} plain dimColor={i < chain.length - 1}
              label={`${i ? '› ' : ''}${n.title}`} onPress={() => void go($, n.path)} />
          ))}
        </Box>
        {browse}
        {trouble !== null && <Text dimColor size="footnote">{trouble}</Text>}
      </Box>
    )
  })

  // ---------------------------------------------------------------- the group pane (a group session)

  on('ui.render', { component: 'Pane', requestId: GROUP_PANE }, async ($, e) => {
    const table = $.ui.resolve(e)
    const { Box, Text, Button } = table
    const Svg = 'Svg' in table ? (table as ElementTable<'desktop'>).Svg : undefined
    const g = await read($, groupView)
    const trouble = await read($, problem)
    const now = await $.clock.now()
    if (g === null) {
      return <Text dimColor>{trouble ?? 'Reading the group…'}</Text>
    }
    const state = g.session.state === 'waiting' ? `Waits for you · ${ago(now, g.session.since)}`
      : g.session.state === 'permission' ? `Asks for a permission · ${ago(now, g.session.since)}`
        : g.session.state === 'working' ? 'Working' : g.session.state === 'ended' ? 'Chat ended' : 'Not started'
    const rules = (g.rules ?? []).length
    const notes = (g.inbox ?? []).length

    return (
      <Box flexDirection="column" alignItems="center" gap={1}>
        {Svg ? <Svg source={groupSvg(g, null)} alt={pretty(g.name)} width={96} height={96} /> : null}
        <Text size="heading" weight="semibold">{pretty(g.name)}</Text>
        <Text color={g.session.state === 'waiting' ? 'error' : g.session.state === 'permission' ? 'warning' : undefined}>{state}</Text>
        {g.page ? <Button key="round" variant="primary" label={`Open round ${g.round}`} onPress={() => void openPage($, g.page)} /> : null}
        <Text dimColor size="footnote">
          {rules} rule{rules === 1 ? '' : 's'} · {notes} note{notes === 1 ? '' : 's'} from other groups
        </Text>
        {trouble !== null && <Text dimColor size="footnote">{trouble}</Text>}
      </Box>
    )
  })
}

// ---------------------------------------------------------------- the tree

export function find(root: QapNode, path: string): QapNode | undefined {
  if (root.path === path) {
    return root
  }
  for (const c of root.children) {
    const found = find(c, path)
    if (found) {
      return found
    }
  }

  return undefined
}

// The nodes from the top down to `path`, both ends included: the breadcrumb.
export function trail(root: QapNode, path: string): QapNode[] {
  if (root.path === path) {
    return [root]
  }
  for (const c of root.children) {
    const below = trail(c, path)
    if (below.length) {
      return [root, ...below]
    }
  }

  return []
}

function shortDate(iso: string): string {
  const d = new Date(iso)

  return Number.isNaN(d.getTime()) ? '' : `${d.getDate()} ${MONTHS[d.getMonth()] ?? ''}`
}

// ---------------------------------------------------------------- tiles

type Badge = { text: string; colour: string; ink?: string }
type Look = 'plain' | 'ring' | 'dim'
type Shape = 'tile' | 'folder' | 'project'

const FONT = 'font-family="-apple-system,Helvetica,Arial,sans-serif"'

// A tile as the dashboard draws it: a rounded square in its colour with a white icon (or an emoji), a badge at its
// top right; a blue ring while it works; faded while it waits, with the group it waits for at its bottom right.
// A folder has a tab and a second sheet behind it; a project, bigger, two sheets under it and its families' colours.
export function tileSvg(icon: string, colour: string, badge?: Badge, look: Look = 'plain',
  waits?: { icon: string; colour: string }, shape: Shape = 'tile', minis: string[] = []): string {
  const big = shape === 'project'
  const s = big ? 1.2 : 1
  const side = 64 * s
  const x = 8
  const glyph = ICONS[icon]
    ? `<g transform="translate(${x + side / 2 - 18 * s} ${8 + side / 2 - 18 * s}) scale(${1.5 * s})" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${ICONS[icon]}</g>`
    : `<text x="${x + side / 2}" y="${8 + side / 2 + 11 * s}" font-size="${30 * s}" text-anchor="middle">${esc(icon || '📄')}</text>`
  const ring = look === 'ring'
    ? `<rect x="2.5" y="2.5" width="75" height="75" rx="20" fill="none" stroke="${BLUE}" stroke-width="3" stroke-linecap="round" stroke-dasharray="190 106"/>`
    : ''
  const shade = (rx: number, ry: number, w: number, h: number, r: number, dark: number, alpha = 1) =>
    `<g opacity="${alpha}"><rect x="${rx}" y="${ry}" width="${w}" height="${h}" rx="${r}" fill="${colour}"/>`
    + `<rect x="${rx}" y="${ry}" width="${w}" height="${h}" rx="${r}" fill="#000" opacity="${dark}"/></g>`
  const behind = shape === 'folder'
    ? shade(13, 13, 64, 62, 15, 0.3, 0.55) + shade(15, 3, 24, 12, 4, 0.12)
    : big ? shade(28, 32, side - 40, side, 16, 0.38, 0.45) + shade(20, 22, side - 24, side, 18, 0.2, 0.7) : ''
  const edge = big
    ? `<rect x="${x + 1.5}" y="9.5" width="${side - 3}" height="${side - 3}" rx="${17 * s}" fill="none" stroke="#fff" stroke-opacity=".26" stroke-width="3"/>`
    : ''
  const body = `<g opacity="${look === 'dim' ? 0.4 : 1}">${behind}<rect x="${x}" y="8" width="${side}" height="${side}" rx="${15 * s}" fill="${colour}"/>${edge}${glyph}</g>`
  const bx = x + side - 5
  const mark = badge
    ? `<circle cx="${bx}" cy="13" r="11" fill="${badge.colour}"${badge.ink ? ' stroke="#d3cec2" stroke-width="1"' : ''}/>`
      + `<text x="${bx}" y="17.5" font-size="12.5" font-weight="700" fill="${badge.ink ?? '#fff'}" text-anchor="middle">${esc(badge.text)}</text>`
    : ''
  const after = waits
    ? `<rect x="48" y="54" width="26" height="22" rx="6" fill="${waits.colour}" stroke="#fff" stroke-width="2"/>`
      + (ICONS[waits.icon] ? `<g transform="translate(53 57) scale(0.68)" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${ICONS[waits.icon]}</g>` : '')
    : ''
  const width = big ? 96 : 80
  const height = big ? (minis.length ? 124 : 108) : 80
  const start = width / 2 - (Math.min(minis.length, 7) * 14 - 4) / 2
  const row = minis.slice(0, 7).map((c, i) => `<rect x="${start + i * 14}" y="112" width="10" height="10" rx="3" fill="${c}"/>`).join('')

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" ${FONT}>${ring}${body}${mark}${after}${row}</svg>`
}

// How tall a tile's picture is for its width (a project's carries its sheets and its families' colours).
function svgRatio(svg: string): number {
  const m = /viewBox="0 0 (\d+) (\d+)"/.exec(svg)

  return m ? Number(m[2]) / Number(m[1]) : 1
}

// A project, folder or subject of the tree, as the dashboard draws it; a subject's badge is its pass count.
export function nodeSvg(n: QapNode): string {
  const colour = nodeColour(n)
  const icon = n.icon || (n.kind === 'project' ? 'layers' : n.kind === 'folder' ? 'folder' : 'doc')
  if (n.kind === 'project') {
    return tileSvg(icon, colour, undefined, 'plain', undefined, 'project', n.children.map(nodeColour))
  }
  if (n.kind === 'folder') {
    return tileSvg(icon, colour, undefined, 'plain', undefined, 'folder')
  }

  return tileSvg(icon, colour, n.count ? { text: String(n.count), colour: '#ffffff', ink: '#14130f' } : undefined)
}

// The dashboard's colour for an item (src/qap/web/icons.js colorOf): its own, its icon's, or one from its name.
function nodeColour(n: QapNode): string {
  return n.color || ICON_COLOURS[n.icon] || colourOf(n.name || n.path)
}

// A group's tile, its badge from its state: the number of decisions waiting for you, ! for a permission, ✓ merged.
export function groupSvg(g: QapGroup, b: QapBoard | null): string {
  const icon = groupIcon(g)
  const colour = colourOf(g.name)
  const state = g.session.state
  if (g.lane === 'done') {
    return tileSvg(icon, colour, { text: '✓', colour: GREEN })
  }
  if (state === 'permission') {
    return tileSvg(icon, colour, { text: '!', colour: ORANGE })
  }
  if (state === 'waiting') {
    return tileSvg(icon, colour, { text: g.decisions ? String(g.decisions) : '?', colour: RED })
  }
  if (state === 'working') {
    return tileSvg(icon, colour, undefined, 'ring')
  }
  if (g.lane === 'waits') {
    const first = b?.groups.find(x => x.name === g.blocked_by[0])

    return tileSvg(icon, colour, undefined, 'dim', first ? { icon: groupIcon(first), colour: colourOf(first.name) } : undefined)
  }

  return tileSvg(icon, colour, undefined, g.lane === 'stopped' ? 'dim' : 'plain')
}

function groupIcon(g: QapGroup): string {
  return g.icon || (GROUP_ICONS[hash(g.name) % GROUP_ICONS.length] ?? 'layers')
}

// The dashboard's colour for a name (src/qap/web/icons.js): it keeps its colour wherever it is drawn.
export function colourOf(path: string): string {
  return PALETTE[hash(path.split('/').pop() ?? path) % PALETTE.length] ?? '#5E60CE'
}

function hash(text: string): number {
  let h = 2166136261
  for (const c of text) {
    h = Math.imul(h ^ (c.codePointAt(0) ?? 0), 16777619)
  }

  return h >>> 0
}

// board-transport → Board transport
export function pretty(name: string): string {
  const words = name.replace(/[-_]+/g, ' ').trim()

  return words.charAt(0).toUpperCase() + words.slice(1)
}

function esc(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function ago(now: number, since: string | undefined): string {
  const ms = now - Date.parse(since ?? '')
  if (!(ms >= 0)) {
    return 'just now'
  }
  const minutes = Math.round(ms / 60_000)
  if (minutes < 1) {
    return 'just now'
  }

  return minutes < 60 ? `${minutes} min` : `${Math.round(minutes / 60)} h`
}

// The desktop app hands a message from another session, or a background task's notification, to the session as an
// ordinary prompt with no origin: what tells it apart is its frame, once the system reminders are taken out.
const FRAMED = /^<(cross-session-message|task-notification)\b/
const REMINDERS = /<system-reminder>[\s\S]*?<\/system-reminder>/g

export function isThePerson(origin: string, text: string): boolean {
  const said = text.replace(REMINDERS, '').trim()

  return !NOT_THE_PERSON.has(origin) && said !== '' && !FRAMED.test(said)
}

// A refresh started in the background that failed: the next tick tries again.
function quiet(): void {}

function clip(text: string, max: number): string {
  const flat = text.replace(/\s+/g, ' ').trim()

  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}
