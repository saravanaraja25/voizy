/**
 * Opt-in: runs the real API client against a running Voizy API.
 *   VOIZY_E2E_API=http://127.0.0.1:8010 VOIZY_E2E_KEY=vz_... pnpm test integration
 * Proves the configs this dashboard generates are accepted by the server's own validation.
 */
import { describe, expect, it } from 'vitest'
import { ApiError, createClient, fieldErrors } from '@/api/client'
import { newAgentConfig, newHttpTool } from '@/lib/config'

const API = process.env.VOIZY_E2E_API
const KEY = process.env.VOIZY_E2E_KEY

describe.skipIf(!API || !KEY)('against a live API', () => {
  const api = createClient(API ?? '', KEY ?? '')

  it('creates, edits, validates, publishes and starts a test session', async () => {
    const who = await api.me()
    expect(who.permissions).toContain('agents:create')

    const catalog = await api.catalog()
    expect(catalog.llm.length).toBeGreaterThan(0)

    const name = `e2e ${Date.now()}`
    const created = await api.createAgent(name, newAgentConfig(name, catalog))
    expect(created.published_version).toBeNull()

    const v1 = await api.getVersion(created.id, 1)
    expect(v1.config.system_prompt).toContain('{{company}}')

    // An edited config with an http tool is accepted as a new version.
    const edited = structuredClone(v1.config)
    edited.system_prompt += '\nBe concise.'
    edited.tools = [{ ...newHttpTool([]), name: 'lookup', description: 'Look something up', url: 'https://example.com/lookup' }]
    const v2 = await api.createVersion(created.id, edited)
    expect(v2.version).toBe(2)
    expect((await api.listVersions(created.id)).map((v) => v.version)).toEqual([2, 1])

    // The server's validation errors map onto form fields.
    const bad = structuredClone(edited)
    bad.turn!.vad_min_silence_ms = 5
    const err = await api.createVersion(created.id, bad).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(fieldErrors(err)['turn.vad_min_silence_ms']).toBeTruthy()

    const badTool = structuredClone(edited)
    badTool.tools = [{ ...newHttpTool([]), name: 'lookup', description: 'x', url: 'http://not-allowed.example/x' }]
    const toolErr = await api.createVersion(created.id, badTool).catch((e: unknown) => e)
    // Tool-level rules are reported on the tool itself, which the tool card displays.
    expect(fieldErrors(toolErr)['tools.0']).toMatch(/https/)

    const live = await api.publish(created.id, 2)
    expect(live.published_version).toBe(2)

    const session = await api.testSession(created.id, 2)
    expect(session.token.split('.')).toHaveLength(3)
    expect(session.expires_in_s).toBe(600)
  })
})
