import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Drawer, Empty, FloatButton, List, Tabs, Tag, Typography, notification } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

type Job = {
  id: number
  type: string
  title: string
  key: string | null
  status: 'running' | 'succeeded' | 'failed' | 'interrupted'
  created_at: string
  error: string
  log: string[]
}

const statusTag = (s: Job['status']) =>
  s === 'running' ? <Tag color="processing">进行中</Tag>
    : s === 'succeeded' ? <Tag color="success">完成</Tag>
      : <Tag color="error">{s === 'interrupted' ? '中断' : '失败'}</Tag>

function JobList({ jobs, empty }: { jobs: Job[]; empty: string }) {
  if (!jobs.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={empty} />
  return (
    <List
      dataSource={jobs}
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
  )
}

export default function JobMonitor() {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const prevRunning = useRef<number>(0)
  const notified = useRef<Set<number>>(new Set())
  const seeded = useRef(false)

  const { data } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api<{ running: number; jobs: Job[] }>('/api/jobs'),
    // 有任务在跑每 3 秒轮询；空闲时完全停止（各操作按钮触发任务后会主动刷新这里），
    // 回到浏览器窗口时拉一次，兜住别的标签页/设备触发的任务
    refetchInterval: (q) => (q.state.data?.running ? 3000 : false),
    refetchOnWindowFocus: true,
  })

  const running = data?.running ?? 0
  const jobs = data?.jobs ?? []
  const runningJobs = jobs.filter((j) => j.status === 'running')
  const doneJobs = jobs.filter((j) => j.status !== 'running')

  useEffect(() => {
    // 首次加载：把已完成任务标记为"已见过"，刷新页面时不重放历史通知
    if (!seeded.current && jobs.length) {
      seeded.current = true
      for (const j of jobs) if (j.status !== 'running') notified.current.add(j.id)
      prevRunning.current = running
      return
    }
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
        <Tabs
          defaultActiveKey={running > 0 ? 'running' : 'done'}
          items={[
            {
              key: 'running',
              label: <Badge count={runningJobs.length} size="small" offset={[8, 0]}>进行中</Badge>,
              children: <JobList jobs={runningJobs} empty="没有正在进行的任务" />,
            },
            {
              key: 'done',
              label: <Badge count={doneJobs.length} size="small" color="#999" offset={[8, 0]}>已完成</Badge>,
              children: <JobList jobs={doneJobs} empty="还没有完成的任务" />,
            },
          ]}
        />
      </Drawer>
    </>
  )
}
