import type { components } from './schema'

type S = components['schemas']

export type AgentConfig = S['AgentConfig']
export type AgentOut = S['AgentOut']
export type VersionOut = S['VersionOut']
export type VersionSummary = S['VersionSummary']
export type MeOut = S['MeOut']
export type CatalogOut = S['CatalogOut']
export type ModelOut = S['ModelOut']
export type TestSessionOut = S['TestSessionOut']
export type HttpTool = S['HttpTool']
