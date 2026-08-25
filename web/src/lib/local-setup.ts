import type { LocalRuntimeState } from './workspace'

export type LocalSetupAction =
  | { kind: 'choose-folder'; label: 'Choose Project Folder…'; canClose: false }
  | { kind: 'sign-in'; label: 'Sign in to Claude'; canClose: false }
  | { kind: 'retry-auth'; label: 'Try Again'; canClose: false }
  | { kind: 'retry-folder'; label: 'Try Again'; canClose: false }
  | { kind: 'retry-runtime'; label: 'Try Again'; canClose: false }
  | { kind: 'ready'; label: null; canClose: true }

export type LocalSetupRecovery = 'auth-timeout' | 'folder' | null

export function getLocalSetupAction(input: {
  profileId: string
  hasFolder: boolean
  runtimeState: LocalRuntimeState
  recovery?: LocalSetupRecovery
}): LocalSetupAction {
  if (input.recovery === 'auth-timeout') {
    return { kind: 'retry-auth', label: 'Try Again', canClose: false }
  }
  if (input.recovery === 'folder') {
    return { kind: 'retry-folder', label: 'Try Again', canClose: false }
  }
  if (!input.hasFolder) {
    return { kind: 'choose-folder', label: 'Choose Project Folder…', canClose: false }
  }
  if (input.runtimeState === 'ready') {
    return { kind: 'ready', label: null, canClose: true }
  }
  if (input.profileId === 'claude-code' && input.runtimeState === 'authentication_required') {
    return { kind: 'sign-in', label: 'Sign in to Claude', canClose: false }
  }
  return { kind: 'retry-runtime', label: 'Try Again', canClose: false }
}
