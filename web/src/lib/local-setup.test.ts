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
    kind: 'retry',
    label: 'Try Again',
    canClose: false,
  })
})
