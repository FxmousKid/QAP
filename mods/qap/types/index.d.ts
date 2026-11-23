// What a session is to QAP: nothing, one group of a batch (its first prompt named it), or the triage session
// that started the groups (it ran qap split, or started a group session).
export type QapRole =
  | { kind: 'none' }
  | { kind: 'group'; group: string; batch: string }
  | { kind: 'triage'; batch: string }

export type QapSession = {
  state?: 'working' | 'waiting' | 'permission' | 'ended'
  since?: string
  question?: string
  id?: string
  app_id?: string
}

export type QapEvent = { at: string; kind: string; text?: string; phase?: string; group?: string }

export type QapRule = { id: string; rule: string; who?: string; where?: string; date?: string }

export type QapNote = { id: number; at: string; from: string; text: string }

// One group as GET /api/board and GET /api/group give it (the fields the panes draw).
export type QapGroup = {
  name: string
  path: string
  title: string
  order: number
  goal: string
  owns: string[]
  waits: string[]
  blocked_by: string[]
  phase: string
  note: string
  pr: string
  lane: 'needs_you' | 'working' | 'waits' | 'stopped' | 'ready' | 'done'
  session: QapSession
  round: number | null
  page: string
  events?: QapEvent[]
  inbox?: QapNote[]
  rules?: QapRule[]
  icon?: string
  // the items of the latest round's "What I need from you": the number on the tile's badge
  decisions?: number
}

export type QapBoard = {
  batch: string
  title: string
  groups: QapGroup[]
  start_next: QapGroup[]
  fast: { title: string; topics: { num: string; title: string }[] }[]
  triage: { path: string; page: string }
  ledger: number
}

// The dashboard's tree, as the pane browses it: the projects at the top, then their families, folders and subjects
// (the fields a tile draws). A subject's file is its latest page.
export type QapNode = {
  kind: 'root' | 'project' | 'folder' | 'subject'
  path: string
  name: string
  title: string
  icon: string
  color: string
  count?: number
  latest?: string
  file?: string
  updated?: string
  children: QapNode[]
}

// What the QAP pane shows: the start ("What are we working on today?") or a batch's board.
export type QapView = 'home' | 'board'

declare module 'claude-code' {
  interface PluginState {
    qap: {
      role: Shaped<QapRole>
      board: Shaped<QapBoard | null>
      group: Shaped<QapGroup | null>
      problem: string | null
      server: string | null
      delivered: number
      view: Shaped<QapView>
      tree: Shaped<QapNode | null>
      place: Shaped<string>
    }
  }
}
