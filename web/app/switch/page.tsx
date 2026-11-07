'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { pushToast } from '@/components/Toast'

interface SwitchStatus {
  mode: string
  switch_server_url: string
  connected_to_switch: boolean
  poster_agent_id: string
  is_configured: boolean
  last_activity_at: string
  last_active_agent: string
  agents: {
    scout: { role: string; capabilities: string[]; status: string }
    analyst: { role: string; capabilities: string[]; status: string }
    editor: { role: string; capabilities: string[]; status: string; approval_gate: string }
  }
}

interface PipelineResult {
  room_key: string
  scout_candidates: number
  analyst_verified: number
  digest_id?: string
  approval_status: string
  publish_result?: any
  status: string
}

export default function SwitchAgentsPage() {
  const queryClient = useQueryClient()
  const [selectedRoom, setSelectedRoom] = useState('aiml')
  const [autoApprove, setAutoApprove] = useState(false)
  const [lastResult, setLastResult] = useState<PipelineResult | null>(null)

  const { data: status, isLoading } = useQuery<SwitchStatus>({
    queryKey: ['switchStatus'],
    queryFn: () => api.get<SwitchStatus>('/switch/status'),
    refetchInterval: 6000,
  })

  const cycleMutation = useMutation({
    mutationFn: async () => {
      return api.post<PipelineResult>('/switch/cycle', {
        room_key: selectedRoom,
        auto_approve: autoApprove,
        reviewer: '@gnaneshwar',
      })
    },
    onSuccess: (data) => {
      setLastResult(data)
      queryClient.invalidateQueries({ queryKey: ['switchStatus'] })
      queryClient.invalidateQueries({ queryKey: ['agentActivity'] })
      pushToast({
        kind: 'success',
        message: `Autonomous cycle for #${data.room_key} complete: ${data.analyst_verified} stories verified!`,
      })
    },
    onError: (err: any) => {
      pushToast({ kind: 'error', message: err?.message || 'Pipeline execution failed' })
    },
  })

  return (
    <main style={{ padding: '24px 20px', maxWidth: 1040, margin: '0 auto', width: '100%' }}>
      {/* Page Title & Status Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: 'var(--ink)' }}>
            Switch Agent Protocol & Autonomous Coordination
          </h1>
          <p style={{ fontSize: 13, color: 'var(--mute)', marginTop: 4 }}>
            Direct runtime integration between NewsOps backend and Switch rooms via Scout, Analyst, and Editor.
          </p>
        </div>

        {/* Server Connection Chip */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px', borderRadius: 8,
          background: status?.connected_to_switch ? 'rgba(34, 197, 94, 0.12)' : 'rgba(234, 179, 8, 0.12)',
          border: `1px solid ${status?.connected_to_switch ? 'rgba(34, 197, 94, 0.3)' : 'rgba(234, 179, 8, 0.3)'}`,
        }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: status?.connected_to_switch ? '#22c55e' : '#eab308',
          }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: status?.connected_to_switch ? '#15803d' : '#854d0e' }}>
            Switch Server: {status?.connected_to_switch ? 'LIVE (Connected)' : 'STANDBY (Local / Ready)'}
          </span>
          <span style={{ fontSize: 11, color: 'var(--mute)', marginLeft: 4 }}>
            ({status?.switch_server_url || 'http://127.0.0.1:55316'})
          </span>
        </div>
      </div>

      {/* Agents Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16, marginBottom: 24 }}>
        {/* Scout Agent */}
        <div style={{
          padding: 18, borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--line)',
          boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--ink)' }}>📡 Scout Agent</span>
            <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 9999, background: '#e0e7ff', color: '#3730a3', fontWeight: 600 }}>
              Discovery
            </span>
          </div>
          <p style={{ fontSize: 12, color: 'var(--mute)', marginBottom: 12 }}>
            Monitors GitHub, Hacker News, Reddit, and RSS feeds. Normalizes releases and extracts CLI installation commands.
          </p>
          <div style={{ fontSize: 11, color: 'var(--mute)' }}>
            <strong>Capabilities:</strong> news_discovery, command_extraction, deduplication
          </div>
        </div>

        {/* Analyst Agent */}
        <div style={{
          padding: 18, borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--line)',
          boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--ink)' }}>🔍 Analyst Agent</span>
            <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 9999, background: '#ecfdf5', color: '#065f46', fontWeight: 600 }}>
              AI Fact-Check
            </span>
          </div>
          <p style={{ fontSize: 12, color: 'var(--mute)', marginBottom: 12 }}>
            Extracts individual claims, checks primary sources (PyPI, npm, GitHub tags), detects contradictions, and scores confidence.
          </p>
          <div style={{ fontSize: 11, color: 'var(--mute)' }}>
            <strong>Capabilities:</strong> claim_verification, evidence_evaluation, contradiction_detection
          </div>
        </div>

        {/* Editor Agent */}
        <div style={{
          padding: 18, borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--line)',
          boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--ink)' }}>📰 Editor Agent</span>
            <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 9999, background: '#fef3c7', color: '#92400e', fontWeight: 600 }}>
              403 Gate
            </span>
          </div>
          <p style={{ fontSize: 12, color: 'var(--mute)', marginBottom: 12 }}>
            Curates verified digests and strictly enforces human editorial approval before publishing to configured Switch rooms.
          </p>
          <div style={{ fontSize: 11, color: 'var(--mute)' }}>
            <strong>Capabilities:</strong> digest_creation, publication, approval_workflow
          </div>
        </div>
      </div>

      {/* Autonomous Trigger Control Panel */}
      <div style={{
        padding: 20, borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--line)',
        marginBottom: 24,
      }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12, color: 'var(--ink)' }}>
          ⚡ Trigger Autonomous Intelligence Pipeline (Scout → Analyst → Editor)
        </h2>

        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginBottom: 16 }}>
          {/* Room Selection */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>Target Room:</label>
            <select
              value={selectedRoom}
              onChange={(e) => setSelectedRoom(e.target.value)}
              style={{
                padding: '6px 12px', borderRadius: 6, border: '1px solid var(--line)',
                background: 'var(--bg)', color: 'var(--ink)', fontSize: 13,
              }}
            >
              <option value="aiml">#aiml (AI & Machine Learning)</option>
              <option value="cloud">#cloud (Cloud & Infrastructure)</option>
              <option value="security">#security (Security Advisories)</option>
            </select>
          </div>

          {/* Auto-Approve Checkbox */}
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={autoApprove}
              onChange={(e) => setAutoApprove(e.target.checked)}
            />
            <span>Auto-Approve Digest (demonstrates full publication gate flow)</span>
          </label>

          {/* Trigger Button */}
          <button
            onClick={() => cycleMutation.mutate()}
            disabled={cycleMutation.isPending}
            style={{
              padding: '8px 18px', borderRadius: 6, fontWeight: 600, fontSize: 13,
              background: 'var(--ink)', color: 'var(--bg)', cursor: 'pointer', border: 'none',
              opacity: cycleMutation.isPending ? 0.6 : 1,
            }}
          >
            {cycleMutation.isPending ? 'Executing Pipeline...' : 'Run Autonomous Pipeline'}
          </button>
        </div>

        {/* Live Execution Output Banner */}
        {lastResult && (
          <div style={{
            padding: 16, borderRadius: 8, background: 'var(--bg)', border: '1px solid var(--line)',
            marginTop: 14,
          }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#15803d', marginBottom: 8 }}>
              ✅ Pipeline Executed Successfully for #{lastResult.room_key}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10, fontSize: 12 }}>
              <div><strong>Scout Discovered:</strong> {lastResult.scout_candidates} candidate stories</div>
              <div><strong>Analyst Verified:</strong> {lastResult.analyst_verified} stories analyzed</div>
              <div><strong>Digest ID:</strong> <code>{lastResult.digest_id || 'N/A'}</code></div>
              <div><strong>Approval Status:</strong> <code>{lastResult.approval_status}</code></div>
            </div>
          </div>
        )}
      </div>

      {/* Switch Protocol Commands Cheatsheet */}
      <div style={{ padding: 20, borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--line)' }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 8, color: 'var(--ink)' }}>
          💻 Switch Console Room Chat Commands
        </h2>
        <p style={{ fontSize: 12, color: 'var(--mute)', marginBottom: 12 }}>
          When participating in Switch Console rooms, you or other agents can address the NewsOps agents directly:
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10, fontSize: 12, fontFamily: 'monospace' }}>
          <div style={{ padding: 10, background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--line)' }}>
            <strong>@scout discover aiml</strong>
            <p style={{ fontSize: 11, color: 'var(--mute)', marginTop: 4 }}>Scout scans releases and hands off to Analyst.</p>
          </div>
          <div style={{ padding: 10, background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--line)' }}>
            <strong>@analyst verify &lt;story_id&gt;</strong>
            <p style={{ fontSize: 11, color: 'var(--mute)', marginTop: 4 }}>Analyst extracts claims, checks primary sources, and scores confidence.</p>
          </div>
          <div style={{ padding: 10, background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--line)' }}>
            <strong>@editor approve &lt;digest_id&gt;</strong>
            <p style={{ fontSize: 11, color: 'var(--mute)', marginTop: 4 }}>Editor records review, passes 403 gate, and broadcasts published digest.</p>
          </div>
        </div>
      </div>
    </main>
  )
}
