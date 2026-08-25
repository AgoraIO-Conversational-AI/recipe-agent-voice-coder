'use client'

import { Check, FolderOpen, Loader2, Settings2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { getLocalSetupAction } from '@/lib/local-setup'
import type { AgentSettingsStatus, LocalRuntimeStatus, WorkspaceStatus } from '@/lib/workspace'
import { workspaceNeedsConfiguration } from '@/lib/workspace'
import { applyBrowseOutcomeWithRuntimeRefresh, selectWorkspaceWithRuntimeRefresh } from '@/lib/workspace-selection'
import {
  browseWorkspace,
  getClaudeAuthStatus,
  getLocalRuntime,
  selectAgentProfile,
  selectWorkspace,
  startClaudeSignIn,
  startLocalRuntime,
} from '@/services/api'

type SelectionOutcome =
  | { state: 'cancelled' }
  | { state: 'ready'; workspace: WorkspaceStatus; runtime: LocalRuntimeStatus }

type BusyMode = 'agent' | 'auth' | 'browse' | 'manual' | 'retry'

type LocalCodingSetupProps = {
  open: boolean
  agentSettings: AgentSettingsStatus | null
  status: WorkspaceStatus | null
  runtimeStatus: LocalRuntimeStatus | null
  initialError: string | null
  onAgentSettingsChange: (settings: AgentSettingsStatus) => void
  onStatusChange: (status: WorkspaceStatus) => void
  onRuntimeStatusChange: (status: LocalRuntimeStatus | null) => void
  onReady: () => void
  onClose: () => void
}

const wait = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds))

export function LocalCodingSetup({
  open,
  agentSettings,
  status,
  runtimeStatus,
  initialError,
  onAgentSettingsChange,
  onStatusChange,
  onRuntimeStatusChange,
  onReady,
  onClose,
}: LocalCodingSetupProps) {
  const [manualPath, setManualPath] = useState('')
  const [busyMode, setBusyMode] = useState<BusyMode | null>(null)
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const selectionInFlightRef = useRef(false)
  const authPollGenerationRef = useRef(0)
  const profileId = agentSettings?.selected_profile.id ?? status?.profile.id ?? 'codex'
  const hasFolder = status ? !workspaceNeedsConfiguration(status) : false
  const setupAction = getLocalSetupAction({
    profileId,
    hasFolder,
    runtimeState: runtimeStatus?.state ?? 'configuration_required',
  })
  const visibleError = error ?? initialError
  const isBusy = busyMode !== null

  useEffect(() => {
    if (!open) {
      setBusyMode(null)
      setError(null)
      setManualPath('')
      selectionInFlightRef.current = false
      authPollGenerationRef.current += 1
    }
  }, [open])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!open || !dialog) return
    const getFocusable = () =>
      Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), summary, a[href], [tabindex]:not([tabindex="-1"]):not([data-focus-guard])',
        ),
      ).filter((element) => element.getClientRects().length > 0 && !element.dataset.focusGuard)
    const retainKeyboardFocus = (event: FocusEvent) => {
      const target = event.target
      if (!(target instanceof HTMLElement)) return
      const focusable = getFocusable()
      if (!dialog.contains(target) || target.dataset.focusGuard === 'end') focusable[0]?.focus()
      else if (target.dataset.focusGuard === 'start') focusable[focusable.length - 1]?.focus()
    }
    document.addEventListener('focusin', retainKeyboardFocus, true)
    if (!dialog.open) dialog.showModal()
    const focusFrame = requestAnimationFrame(() => getFocusable()[0]?.focus())
    return () => {
      cancelAnimationFrame(focusFrame)
      document.removeEventListener('focusin', retainKeyboardFocus, true)
      if (dialog.open) dialog.close()
    }
  }, [open])

  if (!open) return null

  const publishRuntime = (runtime: LocalRuntimeStatus) => {
    onRuntimeStatusChange(runtime)
    onStatusChange(runtime.workspace)
    if (runtime.state === 'ready') onReady()
  }

  const switchProfile = async (nextProfileId: string) => {
    if (isBusy || nextProfileId === profileId) return
    setBusyMode('agent')
    setError(null)
    authPollGenerationRef.current += 1
    try {
      const result = await selectAgentProfile(nextProfileId)
      onAgentSettingsChange(result.settings)
      publishRuntime(result.runtime)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Could not switch the coding Agent')
    } finally {
      setBusyMode(null)
    }
  }

  const runSelection = async (mode: 'browse' | 'manual', select: () => Promise<SelectionOutcome>) => {
    if (selectionInFlightRef.current) return
    selectionInFlightRef.current = true
    const previousError = error
    setBusyMode(mode)
    setError(null)
    try {
      const outcome = await select()
      if (outcome.state === 'cancelled') {
        setError(previousError)
        return
      }
      onStatusChange(outcome.workspace)
      onRuntimeStatusChange(outcome.runtime)
      if (outcome.runtime.state === 'ready') onReady()
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Could not finish local setup')
    } finally {
      selectionInFlightRef.current = false
      setBusyMode(null)
    }
  }

  const runBrowseSelection = () =>
    runSelection('browse', () =>
      applyBrowseOutcomeWithRuntimeRefresh(browseWorkspace, getLocalRuntime, onRuntimeStatusChange),
    )

  const runManualSelection = (path: string) =>
    runSelection('manual', async () => ({
      state: 'ready',
      ...(await selectWorkspaceWithRuntimeRefresh(() => selectWorkspace(path), getLocalRuntime, onRuntimeStatusChange)),
    }))

  const retryRuntime = async () => {
    setBusyMode('retry')
    setError(null)
    try {
      publishRuntime(await startLocalRuntime())
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Could not start the coding Agent')
    } finally {
      setBusyMode(null)
    }
  }

  const signInToClaude = async () => {
    setBusyMode('auth')
    setError(null)
    const generation = authPollGenerationRef.current + 1
    authPollGenerationRef.current = generation
    try {
      const started = await startClaudeSignIn()
      if (started.state === 'failed') throw new Error(started.error ?? 'Could not open Claude Code sign-in')
      for (let attempt = 0; attempt < 120 && authPollGenerationRef.current === generation; attempt += 1) {
        const auth = await getClaudeAuthStatus()
        if (auth.state === 'signed_in') {
          publishRuntime(await startLocalRuntime())
          return
        }
        if (auth.state === 'failed') throw new Error(auth.error ?? 'Could not check Claude Code sign-in')
        await wait(1000)
      }
      if (authPollGenerationRef.current === generation) setError('Sign-in was not completed. Try again when ready.')
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Could not finish Claude Code sign-in')
    } finally {
      if (authPollGenerationRef.current === generation) setBusyMode(null)
    }
  }

  const primaryAction = setupAction.kind === 'ready' ? 'choose-folder' : setupAction.kind
  const primaryLabel = setupAction.kind === 'ready' ? 'Choose Another Folder…' : setupAction.label

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 px-4 py-8 backdrop-blur-sm">
      <dialog
        ref={dialogRef}
        aria-modal="true"
        aria-labelledby="local-coding-setup-title"
        onCancel={(event) => {
          event.preventDefault()
          if (setupAction.canClose) onClose()
        }}
        className="relative m-auto w-full max-w-[32rem] rounded-[24px] border-0 bg-card p-6 text-left text-foreground shadow-[0_24px_80px_rgba(0,0,0,0.48),0_1px_0_rgba(255,255,255,0.06)_inset] md:p-7"
      >
        <button
          type="button"
          data-focus-guard="start"
          aria-label="Return focus to the end of local coding setup"
          className="fixed h-px w-px opacity-0"
        />
        <header className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Settings2 className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <h2 id="local-coding-setup-title" className="text-xl font-semibold tracking-[-0.025em] text-foreground">
                Local Coding Setup
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Choose your coding Agent and where it works.
              </p>
            </div>
          </div>
          {setupAction.canClose ? (
            <button
              type="button"
              onClick={onClose}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-muted-foreground hover:bg-secondary hover:text-foreground"
              aria-label="Close local coding setup"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          ) : null}
        </header>

        <section className="mt-6">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">Coding Agent</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {agentSettings?.profiles.map((profile) => {
              const selected = profile.id === profileId
              return (
                <button
                  key={profile.id}
                  type="button"
                  aria-pressed={selected}
                  disabled={isBusy}
                  onClick={() => void switchProfile(profile.id)}
                  className={`flex h-12 items-center justify-between rounded-xl px-3.5 text-sm font-medium transition-colors ${
                    selected
                      ? 'bg-primary/15 text-primary ring-1 ring-primary/50'
                      : 'bg-secondary/70 text-foreground hover:bg-secondary'
                  }`}
                >
                  {profile.label}
                  {selected ? <Check className="h-4 w-4" aria-hidden="true" /> : null}
                </button>
              )
            })}
          </div>
        </section>

        <section className="mt-5 rounded-2xl bg-secondary/70 p-4">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">Project Folder</p>
              <p className="mt-1 truncate font-mono text-sm text-foreground">
                {status?.workspace?.primary_directory ?? 'No folder selected'}
              </p>
            </div>
            <span
              className={`rounded-full px-2.5 py-1 text-xs font-medium ${runtimeStatus?.state === 'ready' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-300'}`}
            >
              {runtimeStatus?.state === 'ready' ? 'Ready' : 'Needs setup'}
            </span>
          </div>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            This sets session context; it is not a filesystem sandbox.
          </p>
        </section>

        {isBusy ? (
          <div
            className="mt-4 flex items-center gap-3 rounded-xl bg-primary/10 px-3.5 py-3 text-sm text-foreground"
            aria-live="polite"
          >
            <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
            {busyMode === 'auth'
              ? 'Complete sign-in in the Terminal window…'
              : busyMode === 'agent'
                ? `Starting ${agentSettings?.selected_profile.label ?? 'coding Agent'}…`
                : 'Finishing local setup…'}
          </div>
        ) : null}

        {!isBusy && visibleError ? (
          <p className="mt-4 rounded-xl bg-destructive/10 px-3.5 py-3 text-sm text-destructive" aria-live="polite">
            {visibleError}
          </p>
        ) : null}

        <Button
          type="button"
          autoFocus
          disabled={isBusy}
          onClick={() => {
            if (primaryAction === 'sign-in') void signInToClaude()
            else if (primaryAction === 'retry') void retryRuntime()
            else void runBrowseSelection()
          }}
          className="mt-6 h-11 w-full rounded-xl bg-primary font-medium text-primary-foreground hover:bg-primary/90"
        >
          {isBusy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <FolderOpen className="h-4 w-4" aria-hidden="true" />
          )}
          {primaryLabel}
        </Button>

        {setupAction.kind === 'sign-in' ? (
          <button
            type="button"
            disabled={isBusy}
            onClick={() => void switchProfile('codex')}
            className="mt-3 w-full text-center text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            Use Codex instead
          </button>
        ) : null}

        <details className="mt-4 rounded-xl bg-secondary/40 px-4 py-3 text-sm">
          <summary className="cursor-pointer select-none font-medium text-muted-foreground hover:text-foreground">
            Advanced: enter a path
          </summary>
          <form
            className="mt-3 flex flex-col gap-2 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault()
              const path = manualPath.trim()
              if (path) void runManualSelection(path)
            }}
          >
            <label className="sr-only" htmlFor="manual-project-folder">
              Project Folder path
            </label>
            <input
              id="manual-project-folder"
              value={manualPath}
              onChange={(event) => setManualPath(event.target.value)}
              disabled={isBusy}
              placeholder="/Users/name/Projects/my-app"
              className="h-10 min-w-0 flex-1 rounded-lg bg-background px-3 font-mono text-sm text-foreground outline-none ring-1 ring-border focus:ring-2 focus:ring-primary"
            />
            <Button
              type="submit"
              variant="secondary"
              disabled={isBusy || manualPath.trim().length === 0}
              className="h-10 rounded-lg px-4"
            >
              Use Path
            </Button>
          </form>
        </details>
        <button
          type="button"
          data-focus-guard="end"
          aria-label="Return focus to the start of local coding setup"
          className="fixed h-px w-px opacity-0"
        />
      </dialog>
    </div>
  )
}
