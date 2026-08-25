import type { LocalRuntimeState } from './workspace'

export type LocalSetupAction =
  | { kind: 'choose-folder'; label: 'Choose Project Folder…'; canClose: false }
  | { kind: 'sign-in'; label: 'Sign in to Claude'; canClose: false }
  | { kind: 'retry'; label: 'Try Again'; canClose: false }
  | { kind: 'ready'; label: null; canClose: true }

export function getLocalSetupAction(input: {
  profileId: string
  hasFolder: boolean
  runtimeState: LocalRuntimeState
}): LocalSetupAction {
  if (!input.hasFolder) {
    return { kind: 'choose-folder', label: 'Choose Project Folder…', canClose: false }
  }
  if (input.runtimeState === 'ready') {
    return { kind: 'ready', label: null, canClose: true }
  }
  if (input.profileId === 'claude-code' && input.runtimeState === 'authentication_required') {
    return { kind: 'sign-in', label: 'Sign in to Claude', canClose: false }
  }
  return { kind: 'retry', label: 'Try Again', canClose: false }
}
