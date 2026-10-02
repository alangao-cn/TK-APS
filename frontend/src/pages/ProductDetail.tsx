import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Button, Card, Col, Descriptions, Image, Input, Popconfirm, Row, Space, Spin,
  Tag, Timeline, Tooltip, Typography, message,
} from 'antd'
import { LoadingOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Link, useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api, patch, post, put } from '../api/client'
import { FreshTag } from './BatchDetail'

type ScriptRow = {
  id: number
  version: number
  status: string
  model: string
  video_prompt: string
  hook: string
  edited: boolean
  tokens_in: number
  tokens_out: number
  created_at: string
}
type VideoRow = {
  id: number
  version: number
  script_version: number
  status: string
  model: string
  api: string
  error: string
  size_mb: number
  has_file: boolean
  created_at: string
}
type Product = {
  id: number
  product_id: string
  title: string
  category: string
  price_min: number
  price_max: number
  commission_rate: string
  creators: number
  stock: number
  rating: number
  profit_cny: number
  image_files: string[]
  fastmoss_url: string
  tiktok_url: string
  confirmed: boolean
  updated_at: string
  scripts: ScriptRow[]
  videos: VideoRow[]
}

export default function ProductDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const [editingScript, setEditingScript] = useState<ScriptRow | null>(null)
  const [prompt, setPrompt] = useState('')

  const { data: p, isLoading } = useQuery({
    queryKey: ['product', id],
    queryFn: () => api<Product>(`/api/products/${id}`),
  })

  // 该商品正在跑的任务（['jobs'] 与任务浮窗共用轮询缓存，任务清零时浮窗会触发全局刷新）
  const { data: jobsData } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api<{ running: number; jobs: any[] }>('/api/jobs'),
  })
  const pid = p?.product_id ?? ''
  const runningJobs = (jobsData?.jobs ?? []).filter((j) => j.status === 'running')
  const scriptJobRunning = runningJobs.some((j) =>
    j.type === 'gen-scripts' && (j.key === `gen-scripts:${pid}` || j.title.includes(pid)))
  const videoJobRunning = runningJobs.some((j) =>
    j.type === 'gen-videos' && j.key === `gen-videos:${pid}`)

  // 切换到另一个商品时清掉编辑状态（路由复用同一组件实例，state 会残留）
  useEffect(() => {
    setEditingScript(null)
    setPrompt('')
  }, [id])

  useEffect(() => {
    // 默认编辑最新成功脚本；页面数据刷新时保持当前编辑版本
    if (!editingScript && p?.scripts?.length) {
      const latest = p.scripts.find((s) => s.status === 'ok')
      if (latest) {
        setEditingScript(latest)
        setPrompt(latest.video_prompt)
      }
    }
  }, [p, editingScript])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['product', id] })
    qc.invalidateQueries({ queryKey: ['batches'] })
    qc.invalidateQueries({ queryKey: ['batch'] })
    qc.invalidateQueries({ queryKey: ['videos'] })
  }

  const genScript = useMutation({
    mutationFn: () => post(`/api/products/${id}/gen-script`),
    onSuccess: () => {
      message.success('脚本生成已启动，完成后自动显示（看右下角任务浮标）')
      setTimeout(() => qc.invalidateQueries({ queryKey: ['jobs'] }), 500)
    },
    onError: (e: any) => message.error(e.message),
  })

  const saveScript = useMutation({
    mutationFn: () => put(`/api/scripts/${editingScript!.id}`, { video_prompt: prompt }),
    onSuccess: () => {
      message.success(`已保存 v${editingScript!.version} 的修改（生成视频用修改后内容）`)
      invalidate()
    },
    onError: (e: any) => message.error(e.message),
  })

  const genVideo = useMutation({
    mutationFn: (scriptId: number) => post(`/api/scripts/${scriptId}/gen-video`),
    onSuccess: () => {
      message.success('视频生成已启动（按条收费，约 3–5 分钟出片）')
      setTimeout(() => qc.invalidateQueries({ queryKey: ['jobs'] }), 500)
    },
    onError: (e: any) => message.error(e.message),
  })

  const toggleConfirm = useMutation({
    mutationFn: (confirmed: boolean) => patch(`/api/products/${id}/confirmed`, { confirmed }),
    onSuccess: () => invalidate(),
  })

  if (isLoading) return <Spin style={{ display: 'block', margin: '80px auto' }} />
  if (!p) return <Alert type="error" message="商品不存在" />

  const okScripts = p.scripts.filter((s) => s.status === 'ok')
  const dirty = editingScript ? prompt !== editingScript.video_prompt : false

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {/* ---------- 商品信息 ---------- */}
      <Card
        title={
          <Space wrap>
            <span>{p.title}</span>
            <FreshTag updated_at={p.updated_at} />
            {p.confirmed ? <Tag color="green">已确认</Tag> : <Tag>未确认</Tag>}
          </Space>
        }
        extra={
          <Space>
            <Tooltip title="确认 = 标记这个商品要做视频；批次页的「批量生成脚本」只处理已确认的商品（防止误耗 token 的人工门槛），不影响你在这里单独生成">
              <Button size="small" type={p.confirmed ? 'default' : 'primary'}
                onClick={() => toggleConfirm.mutate(!p.confirmed)}>
                {p.confirmed ? '取消确认' : '确认选品'}
              </Button>
            </Tooltip>
            <Link to={`/batch/${(p as any).batch_id}`}><Button size="small">← 返回批次</Button></Link>
          </Space>
        }
      >
        <Row gutter={16}>
          <Col flex="320px">
            <Image.PreviewGroup>
              <Space wrap size={8}>
                {p.image_files.map((f) => (
                  <Image key={f} src={`/api/media/images/${f}`} width={96} height={96}
                    style={{ objectFit: 'cover', borderRadius: 8 }} />
                ))}
              </Space>
            </Image.PreviewGroup>
          </Col>
          <Col flex="auto">
            <Descriptions size="small" column={2}>
              <Descriptions.Item label="商品ID">
                <Typography.Text copyable code>{p.product_id}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="类目">{p.category}</Descriptions.Item>
              <Descriptions.Item label="价格">R$ {p.price_min}{p.price_max !== p.price_min ? `–${p.price_max}` : ''}</Descriptions.Item>
              <Descriptions.Item label="佣金">{p.commission_rate}</Descriptions.Item>
              <Descriptions.Item label="单件利润"><Tag color="orange">¥{p.profit_cny}</Tag></Descriptions.Item>
              <Descriptions.Item label="达人">{p.creators}</Descriptions.Item>
              <Descriptions.Item label="库存">{p.stock?.toLocaleString?.()}</Descriptions.Item>
              <Descriptions.Item label="评分">{p.rating}</Descriptions.Item>
              <Descriptions.Item label="链接">
                <a href={p.fastmoss_url} target="_blank" rel="noreferrer">FastMoss</a> ·{' '}
                <a href={p.tiktok_url} target="_blank" rel="noreferrer">TikTok</a>
              </Descriptions.Item>
            </Descriptions>
          </Col>
        </Row>
      </Card>

      {/* ---------- 脚本 ---------- */}
      <Card
        title={<Space>脚本{editingScript && <Tag color={editingScript.edited ? 'gold' : 'default'}>正在编辑 v{editingScript.version}{editingScript.edited ? '（已人工修改）' : ''}</Tag>}</Space>}
        extra={
          <Space>
            <Popconfirm
              title={okScripts.length ? '重新生成脚本？会写新版本并消耗 token' : '生成脚本？将调用 LLM，消耗 token'}
              onConfirm={() => genScript.mutate()}
              disabled={scriptJobRunning}
            >
              <Button loading={scriptJobRunning} disabled={scriptJobRunning}>
                {okScripts.length ? '重新生成脚本' : '生成脚本'}
              </Button>
            </Popconfirm>
            <Button
              type="primary"
              disabled={!editingScript || dirty || videoJobRunning}
              title={dirty ? '先保存修改再生成视频' : ''}
              onClick={() => editingScript && genVideo.mutate(editingScript.id)}
              loading={genVideo.isPending}
            >
              用此脚本生成视频
            </Button>
          </Space>
        }
      >
        {scriptJobRunning && (
          <Alert style={{ marginBottom: 12 }} showIcon icon={<LoadingOutlined spin />}
            message="脚本生成中…" description="任务完成后这里会自动刷新出新版本（进度也可看右下角任务浮标）" />
        )}
        {!okScripts.length && !p.scripts.length && !scriptJobRunning && (
          <Alert type="info" showIcon message="还没有脚本" description={
            <Space direction="vertical">
              <span>点右上角「生成脚本」为这个商品生成视频脚本（调 LLM，注意 token 消耗）。</span>
              {!p.confirmed && <span style={{ color: '#faad14' }}>提示：该商品还没确认选品（不影响单独生成）。</span>}
            </Space>
          } />
        )}
        {p.scripts.some((s) => s.status !== 'ok') && (
          <Alert type="warning" showIcon style={{ marginBottom: 12 }}
            message={`有 ${p.scripts.filter((s) => s.status !== 'ok').length} 个版本解析失败（parse_failed），不影响其他版本`} />
        )}
        {editingScript ? (
          <>
            <Input.TextArea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={12}
              style={{ fontFamily: 'monospace', fontSize: 12.5 }}
              spellCheck={false}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, flexWrap: 'wrap', gap: 8 }}>
              <Space>
                <Button type="primary" disabled={!dirty} loading={saveScript.isPending}
                  onClick={() => saveScript.mutate()}>
                  保存修改
                </Button>
                {dirty && <Typography.Text type="warning">有未保存的修改</Typography.Text>}
              </Space>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                模型 {editingScript.model} · tokens 入 {editingScript.tokens_in} / 出 {editingScript.tokens_out}
                {editingScript.hook && <> · Hook: {editingScript.hook.slice(0, 60)}</>}
              </Typography.Text>
            </div>
            {okScripts.length > 1 && (
              <div style={{ marginTop: 16 }}>
                <Typography.Title level={5} style={{ marginTop: 0 }}>版本历史（点击切换编辑）</Typography.Title>
                <Timeline
                  items={okScripts.map((s) => ({
                    color: s.id === editingScript.id ? 'blue' : 'gray',
                    children: (
                      <a onClick={() => { setEditingScript(s); setPrompt(s.video_prompt) }}>
                        v{s.version} · {dayjs(s.created_at).format('MM-DD HH:mm')}
                        {s.edited && <Tag color="gold" style={{ marginLeft: 8 }}>人工修改</Tag>}
                        {s.id === editingScript.id && <Tag color="blue" style={{ marginLeft: 8 }}>编辑中</Tag>}
                      </a>
                    ),
                  }))}
                />
              </div>
            )}
          </>
        ) : p.scripts.length ? (
          <Alert type="warning" showIcon message="所有版本都解析失败，点「重新生成」再试" />
        ) : null}
      </Card>

      {/* ---------- 视频 ---------- */}
      <Card title={`视频（${p.videos.length}）`}>
        {videoJobRunning && (
          <Alert style={{ marginBottom: 12 }} showIcon icon={<LoadingOutlined spin />}
            message="视频生成中…（约 3–5 分钟）"
            description="按条收费；完成后这里自动刷新出视频卡片（进度也可看右下角任务浮标）" />
        )}
        {!p.videos.length && !videoJobRunning && (
          <Typography.Text type="secondary">
            还没有视频。编辑好脚本后点上方「用此脚本生成视频」。
          </Typography.Text>
        )}
        <Row gutter={[16, 16]}>
          {p.videos.map((v) => (
            <Col key={v.id} xs={24} sm={12} md={8} lg={6}>
              <Card size="small" style={v.status !== 'succeeded' ? { borderColor: '#ffccc7' } : undefined}>
                {v.has_file ? (
                  <video controls preload="metadata" src={`/api/videos/${v.id}/file`}
                    style={{ width: '100%', aspectRatio: '9/16', maxHeight: 380, background: '#000', borderRadius: 6 }} />
                ) : (
                  <div style={{ aspectRatio: '9/16', maxHeight: 380, borderRadius: 6, background: '#fff2f0',
                    border: '1px dashed #ffccc7', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    padding: 12, textAlign: 'center', fontSize: 12, color: '#cf1322', overflow: 'auto' }}>
                    {v.error || `${v.status}：未生成视频文件`}
                  </div>
                )}
                <div style={{ marginTop: 8 }}>
                  <Space size={4} wrap>
                    <Tag color={v.status === 'succeeded' ? 'green' : 'red'}>v{v.version} · {v.status}</Tag>
                    {v.size_mb > 0 && <Tag>{v.size_mb} MB</Tag>}
                    <Tag>{v.model?.split('/')?.pop()}</Tag>
                  </Space>
                  <div style={{ marginTop: 6, fontSize: 12, color: '#999' }}>
                    脚本 v{v.script_version} · {dayjs(v.created_at).format('MM-DD HH:mm')}
                  </div>
                  <div style={{ marginTop: 6 }}>
                    {v.has_file ? (
                      <Button size="small" href={`/api/videos/${v.id}/download`}>下载</Button>
                    ) : (
                      editingScript && (
                        <Popconfirm title="重试生成视频？按条收费" disabled={videoJobRunning}
                          onConfirm={() => genVideo.mutate(editingScript.id)}>
                          <Button size="small" disabled={videoJobRunning}>重试</Button>
                        </Popconfirm>
                      )
                    )}
                  </div>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>
    </Space>
  )
}
