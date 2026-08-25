import { expect, test } from 'bun:test'

import { getLocalSetupAction } from './local-setup'

test('missing folder has one clear next action', () => {
  expect(
    getLocalSetupAction({
      profileId: 'codex',
      hasFolder: false,
      runtimeState: 'configuration_required',
    }),
  ).toEqual({ kind: 'choose-folder', label: 'Choose Project Folder…', canClose: false })
})

test('Claude authentication points only to sign in', () => {
  expect(
    getLocalSetupAction({
      profileId: 'claude-code',
      hasFolder: true,
      runtimeState: 'authentication_required',
    }),
  ).toEqual({ kind: 'sign-in', label: 'Sign in to Claude', canClose: false })
})

test('ready setup can close without a save step', () => {
  expect(getLocalSetupAction({ profileId: 'codex', hasFolder: true, runtimeState: 'ready' })).toEqual({
    kind: 'ready',
    label: null,
    canClose: true,
  })
})

test('other startup failures offer one retry', () => {
  expect(getLocalSetupAction({ profileId: 'codex', hasFolder: true, runtimeState: 'failed' })).toEqual({
    kind: 'retry-runtime',
    label: 'Try Again',
    canClose: false,
  })
})

test('folder activation failure retries with a fresh folder selection', () => {
  expect(
    getLocalSetupAction({
      profileId: 'codex',
      hasFolder: false,
      runtimeState: 'configuration_required',
      recovery: 'folder',
    }),
  ).toEqual({ kind: 'retry-folder', label: 'Try Again', canClose: false })
})

test('Claude sign-in timeout becomes an explicit retry', () => {
  expect(
    getLocalSetupAction({
      profileId: 'claude-code',
      hasFolder: true,
      runtimeState: 'authentication_required',
      recovery: 'auth-timeout',
    }),
  ).toEqual({ kind: 'retry-auth', label: 'Try Again', canClose: false })
})
