import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Drawer, FloatButton, List, Tag, Typography, notification } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

type Job = {
  id: number
  type: string
  title: string
  status: 'running' | 'succeeded' | 'failed' | 'interrupted'
  created_at: string
  error: string
  log: string[]
}

const statusTag = (s: Job['status']) =>
  s === 'running' ? <Tag color="processing">进行中</Tag>
    : s === 'succeeded' ? <Tag color="success">完成</Tag>
      : <Tag color="error">{s === 'interrupted' ? '中断' : '失败'}</Tag>

export default function JobMonitor() {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const prevRunning = useRef<number>(0)
  const notified = useRef<Set<number>>(new Set())

  const { data } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api<{ running: number; jobs: Job[] }>('/api/jobs'),
    refetchInterval: (q) => (q.state.data?.running ? 3000 : 15000),
  })

  const running = data?.running ?? 0
  const jobs = data?.jobs ?? []

  useEffect(() => {
    // 有任务从"跑着"变成"跑完"：全局刷新 + 弹通知（新产出立即出现）
    if (prevRunning.current > 0 && running === 0) {
      qc.invalidateQueries()
    }
    prevRunning.current = running
    for (const j of jobs) {
      if (j.status !== 'running' && !notified.current.has(j.id)) {
        notified.current.add(j.id)
        if (j.status === 'succeeded') notification.success({ message: '任务完成', description: j.title })
        else if (j.status === 'failed')
          notification.error({ message: '任务失败', description: j.error || j.title })
      }
    }
  }, [running, jobs, qc])

  return (
    <>
      <FloatButton
        badge={{ count: running, overflowCount: 9 }}
        type={running ? 'primary' : 'default'}
        tooltip="任务进度"
        onClick={() => setOpen(true)}
      />
      <Drawer title="任务进度" open={open} onClose={() => setOpen(false)} width={520}>
        <List
          dataSource={jobs}
          locale={{ emptyText: '还没有任务' }}
          renderItem={(j) => (
            <List.Item>
              <List.Item.Meta
                title={<span>{statusTag(j.status)} {j.title}</span>}
                description={
                  <>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      #{j.id} · {j.created_at}
                    </Typography.Text>
                    {j.error && (
                      <Typography.Paragraph type="danger" style={{ fontSize: 12, marginBottom: 4 }}>
                        {j.error}
                      </Typography.Paragraph>
                    )}
                    {j.log?.length > 0 && (
                      <pre style={{ fontSize: 11, background: '#fafafa', padding: 8, borderRadius: 6, maxHeight: 140, overflow: 'auto' }}>
                        {j.log.join('\n')}
                      </pre>
                    )}
                  </>
                }
              />
            </List.Item>
          )}
        />
      </Drawer>
    </>
  )
}
