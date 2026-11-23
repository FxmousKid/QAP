import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { groupSvg, isThePerson } from './register'

const GROUP = 'v3/night-2/reanalysis'
const FIRST = `You are the session of group ${GROUP} (QAP). Read /content/${GROUP}/brief.md.`

const VIEW = {
  name: 'reanalysis', path: GROUP, title: 'Re-analysis: what is current', order: 1,
  goal: "Every viewer sees the newest analysis's state.", owns: ['MeetingListViewModel.kt'], waits: [],
  blocked_by: [], phase: 'planning', note: '', pr: '', lane: 'needs_you', round: 1,
  page: `/c/${GROUP}/QA-PASS-1.html`,
  session: { state: 'waiting', since: '2026-11-03T11:31:00+01:00', question: 'One question: B1 or B2?', app_id: 'local_abc12345' },
  events: [{ at: '2026-11-03T11:31:00+01:00', kind: 'waiting' }], inbox: [], rules: [],
}
const BOARD = {
  batch: 'v3/night-2', title: 'Night 2', groups: [VIEW], start_next: [], fast: [], ledger: 1,
  triage: { path: 'v3/night-2/triage', page: '/c/v3/night-2/triage/QA-PASS-1.html' },
}

const TREE = { tree: { kind: 'folder', path: '', title: 'QA passes',
  projects: [{ id: 'work', path: '@work', title: 'Work', icon: 'briefcase' }], children: [
  { kind: 'folder', path: 'payments', title: 'Payments', project: 'work', children: [
    { kind: 'subject', path: 'payments/retries', title: 'Payment retries', icon: '💳', updated: '2026-11-03T10:00:00+01:00',
      count: 2, latest: '2', passes: [{ file: 'QA-PASS-1.html' }, { file: 'QA-PASS-2.html' }] },
    { kind: 'subject', path: 'payments/refunds', title: 'Refunds', icon: '', updated: '2026-11-04T10:00:00+01:00' },
  ] },
] } }

// What the person types at the prompt.
const typed = (text: string) => ({ text, wait: false, origin: { kind: 'composer' } } as const)

const PANE = (requestId: string) => ({
  plugin: 'qap', component: 'Pane', requestId,
  props: { title: 'QA board', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} },
} as const)

// qap serve, as the mod reads it: every GET and POST answered from memory, every POST recorded.
function serve(on: On): { posts: Record<string, unknown>[]; tools: Record<string, unknown>[]; filled: string[]; contexts: string[][] } {
  const posts: Record<string, unknown>[] = []
  const tools: Record<string, unknown>[] = []
  const filled: string[] = []
  const contexts: string[][] = []
  let box = ''
  mock.clock(on, { now: Date.parse('2026-11-03T11:45:00+01:00') })
  mock.store(on)
  mock.session(on)
  on('session.id', () => ({ value: 'cc-session-1' }))
  on('command.register', () => ({ value: { command: 'qap-board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('prompt.read', () => ({ value: { text: box, cursor: box.length } }))
  on('prompt.fill', (_, e) => {
    box = e.text
    filled.push(e.text)

    return { isFilled: true, text: box, cursor: box.length }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('prompt.submit', (_, e) => {
    contexts.push([...(e.context ?? [])])
    box = ''

    return { text: e.text }
  })
  on('turn.complete', () => ({ text: '' }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('tool.list', () => ({ value: [{ name: 'mcp__ccd_window__open_session_in', description: '', mcp: true }] }))
  on('tool.call', (_, e) => {
    tools.push(e as unknown as Record<string, unknown>)

    return { result: {}, text: '' }
  })
  on('http.fetch', (_, e) => {
    const path = e.url.replace(/^http:\/\/127\.0\.0\.1:\d+/, '')
    if (e.init?.method === 'POST') {
      posts.push({ path, ...JSON.parse(e.init.body ?? '{}') })
    }
    const body = path.startsWith('/api/batches') ? { batches: [] }
      : path.startsWith('/api/tree') ? TREE
      : path.startsWith('/api/board') ? BOARD
        : path.startsWith('/api/group') ? VIEW : {}

    return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify({ ok: true, ...body }) } }
  })

  return { posts, tools, filled, contexts }
}

test('a group session names its group in its first prompt, and its hooks report to qap serve', async ($, on) => {
  const { posts } = serve(on)
  await $.session.start({ cwd: '/code/wt-reanalysis', surface: 'desktop', isInteractive: true })
  await $.prompt.submit(typed(FIRST))
  expect(posts.at(-1)).toMatchObject({ path: '/api/events', group: GROUP, kind: 'started', session_id: 'cc-session-1' })

  await $.turn.complete({ answer: 'Round 1 is written.\n\nOne question: B1 or B2?', durationMs: 1, isAborted: false,
    turnId: 't1', reason: 'answer' })
  expect(posts.at(-1)).toMatchObject({ kind: 'waiting', text: 'Round 1 is written.\n\nOne question: B1 or B2?' })

  await $.prompt.submit(typed('B1, as on the apps.'))
  expect(posts.at(-1)).toMatchObject({ kind: 'answered' })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE('qap-group'), surface })
    expect((await ui.find({ type: 'Text', text: /Waits for you/ }))?.text).toBe('Waits for you · 14 min')
    expect((await ui.find({ type: 'Button', key: 'round' }))?.text).toBe('Open round 1')
    await ui.unmount()
  }
})

test('a session that runs qap split shows the board, and Jump opens a group in split view', async ($, on) => {
  const { tools } = serve(on)
  await $.session.start({ cwd: '/content', surface: 'desktop', isInteractive: true })
  await $.tool.call({ tool: 'Bash', command: 'bin/qap split night-2 --json' })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE('qap'), surface })
    expect((await ui.find({ type: 'Text', text: /NEEDS YOU/ }))?.text).toBe('NEEDS YOU')
    expect(await ui.find({ type: 'Text', text: /B1 or B2/ })).toBeUndefined()
    expect((await ui.find({ type: 'Button', key: 'jump-reanalysis' }))?.text).toBe('Reanalysis')
    await ui.press({ key: 'jump-reanalysis' })
    expect(tools.at(-1)).toMatchObject({ tool: 'mcp__ccd_window__open_session_in', session_id: 'local_abc12345', target: 'split' })
    await ui.unmount()
  }
})

test('a new chat in the desktop app opens home: a tap on a source writes in the prompt box, sends nothing', async ($, on) => {
  const { posts, filled } = serve(on)
  await $.session.start({ cwd: '/elsewhere', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE('qap'), surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /working on today/ }))?.text).toBe('What are we working on today?')
  await ui.press({ key: 'src-idea' })
  expect(filled.at(-1)).toBe('I have an idea: ')
  await ui.press({ key: 'src-linear' })
  expect(filled.at(-1)).toBe('I have an idea:\nAnd the Linear project ')
  expect(posts).toEqual([])
  await ui.unmount()
})

test('a prompt a source tile started carries its directive, unseen; one typed by hand carries none', async ($, on) => {
  const { contexts } = serve(on)
  await $.session.start({ cwd: '/elsewhere', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE('qap'), surface: 'desktop' })
  await ui.press({ key: 'src-bug' })
  await $.prompt.submit(typed("There's a bug: the export is empty"))
  expect(contexts.at(-1)?.join('\n')).toMatch(/incident-discovery skill/)
  await $.prompt.submit(typed('thanks'))
  expect(contexts.at(-1)).toEqual([])
  await ui.press({ key: 'src-bug' })
  await $.prompt.submit(typed('something else entirely'))
  expect(contexts.at(-1)).toEqual([])
  await ui.unmount()
})

test('home browses the dashboard: projects, then families, then a subject to open or continue', async ($, on) => {
  const { filled } = serve(on)
  await $.session.start({ cwd: '/elsewhere', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE('qap'), surface: 'desktop' })
  expect((await ui.find({ type: 'Button', key: 'nav-@work' }))?.text).toBe('Work')
  await ui.press({ key: 'nav-@work' })
  expect((await ui.find({ type: 'Text', text: 'FAMILIES' }))?.text).toBe('FAMILIES')
  await ui.press({ key: 'nav-payments' })
  expect((await ui.find({ type: 'Button', key: 'nav-payments/refunds' }))?.text).toBe('Refunds')
  await ui.press({ key: 'nav-payments/retries' })
  expect((await ui.find({ type: 'Button', key: 'open' }))?.text).toBe('Open pass 2')
  await ui.press({ key: 'continue' })
  expect(filled.at(-1)).toBe('Let\'s pick up “Payment retries”: ')
  await ui.press({ key: 'crumb-root' })
  expect((await ui.find({ type: 'Button', key: 'nav-@work' }))?.text).toBe('Work')
  await ui.unmount()
})

test('a group tile shows its decisions as a badge', () => {
  expect(groupSvg({ ...VIEW, decisions: 3 } as never, null)).toContain('>3</text>')
  expect(groupSvg({ ...VIEW, session: { state: 'permission' } } as never, null)).toContain('>!</text>')
  expect(groupSvg({ ...VIEW, lane: 'done' } as never, null)).toContain('>✓</text>')
  expect(groupSvg({ ...VIEW, lane: 'working', session: { state: 'working' } } as never, null)).toContain('stroke-dasharray')
})

test('a background task finishing is not the person answering', async ($, on) => {
  const { posts } = serve(on)
  await $.session.start({ cwd: '/code/wt-reanalysis', surface: 'desktop', isInteractive: true })
  await $.prompt.submit(typed(FIRST))
  await $.turn.complete({ answer: 'B1 or B2?', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  await $.prompt.submit({ text: '<task-notification>qap serve exited</task-notification>', wait: false,
    origin: { kind: 'task-notification' } })
  expect(posts.at(-1)).toMatchObject({ kind: 'waiting' })
  await $.turn.complete({ answer: 'The server stopped.', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer' })
  expect(posts.at(-1)).toMatchObject({ kind: 'waiting', text: '' })
})

test('a message from another session is not the person answering, even with no origin', () => {
  const peer = '<system-reminder>Linked sessions now</system-reminder>\n\n<cross-session-message from="local_1">Did the note reach you?</cross-session-message>'
  expect(isThePerson('sdk', peer)).toBe(false)
  expect(isThePerson('sdk', '<task-notification>qap serve exited</task-notification>')).toBe(false)
  expect(isThePerson('sdk', 'B1, as on the apps.')).toBe(true)
  expect(isThePerson('composer', '<system-reminder>x</system-reminder> B1')).toBe(true)
})

test('a session that only quotes a first prompt is not that group', async ($, on) => {
  const { posts } = serve(on)
  await $.session.start({ cwd: '/elsewhere', surface: 'desktop', isInteractive: true })
  await $.prompt.submit(typed(`Review this split output:\n${FIRST}`))
  await $.turn.complete({ answer: 'Looks fine.', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  expect(posts).toEqual([])
})

test('a session that never names a group reports nothing', async ($, on) => {
  const { posts } = serve(on)
  await $.session.start({ cwd: '/elsewhere', surface: 'desktop', isInteractive: true })
  await $.prompt.submit(typed('Clean the worktrees, thanks'))
  await $.turn.complete({ answer: 'Done.', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  expect(posts).toEqual([])
})
