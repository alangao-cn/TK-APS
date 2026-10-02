import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Button, Card, Col, Descriptions, Form, Image, Input, Modal, Popconfirm, Row,
  Select, Space, Spin, Tag, Timeline, Tooltip, Typography, message,
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
  duration: number
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
  duration: number
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
  const [newerVersion, setNewerVersion] = useState<number | null>(null)
  const [videoModal, setVideoModal] = useState<{ open: boolean; scriptId: number | null }>({
    open: false, scriptId: null,
  })
  const [videoForm] = Form.useForm()

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
    setNewerVersion(null)
  }, [id])

  useEffect(() => {
    // 编辑版本跟随脚本数据：
    // - 没在编辑 → 默认最新成功版本
    // - 出现了更新的版本且当前没有未保存修改（如刚重新生成完）→ 自动切到最新
    // - 有未保存修改 → 保留当前编辑，提示有新版本可切换
    if (!p?.scripts?.length) { setNewerVersion(null); return }
    const latest = p.scripts.filter((s) => s.status === 'ok')
      .sort((a, b) => b.version - a.version)[0]
    if (!latest) { setNewerVersion(null); return }
    if (!editingScript) {
      setEditingScript(latest)
      setPrompt(latest.video_prompt)
      setNewerVersion(null)
      return
    }
    const isDirty = prompt !== editingScript.video_prompt
    if (editingScript.version < latest.version && isDirty) {
      setNewerVersion(latest.version)
      return
    }
    if (editingScript.version !== latest.version) {
      setEditingScript(latest)
      setPrompt(latest.video_prompt)
      setNewerVersion(null)
      return
    }
    setNewerVersion(null)
    if (editingScript !== latest) setEditingScript(latest)  // 同版本刷新元信息
  }, [p])

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
    mutationFn: (v: { scriptId: number; model?: string; resolution?: string }) =>
      post(`/api/scripts/${v.scriptId}/gen-video`, { model: v.model, resolution: v.resolution }),
    onSuccess: () => {
      message.success('视频生成已启动（按条收费，出片约 1–5 分钟）')
      setVideoModal({ open: false, scriptId: null })
      setTimeout(() => qc.invalidateQueries({ queryKey: ['jobs'] }), 500)
    },
    onError: (e: any) => message.error(e.message),
  })

  // 生成视频弹窗选项（模型目录 + 默认值），来自 config.yaml
  const { data: videoOptions } = useQuery({
    queryKey: ['video-options'],
    queryFn: () => api<any>('/api/video/options'),
    staleTime: 60_000,
  })
  const modelWatch = Form.useWatch('model', videoForm)
  const currentSpec = (videoOptions?.models ?? []).find((m: any) => m.name === modelWatch)

  // 选项加载后填默认模型/分辨率；切换模型时若分辨率不被支持则重置回默认
  useEffect(() => {
    if (!videoOptions) return
    if (!videoForm.getFieldValue('model')) {
      videoForm.setFieldsValue({ model: videoOptions.default_model })
    }
    const spec = (videoOptions.models ?? []).find((m: any) => m.name === modelWatch)
    const res = videoForm.getFieldValue('resolution')
    if (!res || (spec && !spec.resolutions?.includes(res))) {
      videoForm.setFieldsValue({ resolution: videoOptions.default_resolution })
    }
  }, [videoOptions, modelWatch])

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
            <Link to={`/batch/${(p as any).batch_id}`}><Button size="small">← 返回</Button></Link>
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
        title={
          <Space wrap>
            脚本
            {editingScript && (
              <Tag color={editingScript.edited ? 'gold' : 'default'}>
                编辑器载入 v{editingScript.version}{editingScript.edited ? '（已人工修改）' : ''}
              </Tag>
            )}
            {editingScript?.duration ? <Tag color="cyan">{editingScript.duration}s</Tag> : null}
            {newerVersion !== null && (
              <Tag color="blue" style={{ cursor: 'pointer' }}
                onClick={() => {
                  const v = p.scripts.find((s) => s.version === newerVersion)
                  if (v) { setEditingScript(v); setPrompt(v.video_prompt); setNewerVersion(null) }
                }}>
                有新版本 v{newerVersion}，点击切换（当前编辑未保存）
              </Tag>
            )}
          </Space>
        }
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
              onClick={() => editingScript && setVideoModal({ open: true, scriptId: editingScript.id })}
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
                模型 {editingScript.model} · 时长 {editingScript.duration ? `${editingScript.duration}s` : '未定'}
                · tokens 入 {editingScript.tokens_in} / 出 {editingScript.tokens_out}
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
                        {s.version === Math.max(...okScripts.map((x) => x.version))
                          && <Tag color="green" style={{ marginLeft: 8 }}>最新</Tag>}
                        {s.edited && <Tag color="gold" style={{ marginLeft: 8 }}>人工修改</Tag>}
                        {s.id === editingScript.id && <Tag color="blue" style={{ marginLeft: 8 }}>编辑器载入</Tag>}
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
                    {v.duration > 0 && <Tag color="cyan">{v.duration}s</Tag>}
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
                      (() => {
                        const s = p.scripts.find((x) => x.version === v.script_version && x.status === 'ok')
                        return s ? (
                          <Button size="small" disabled={videoJobRunning}
                            onClick={() => setVideoModal({ open: true, scriptId: s.id })}>重试</Button>
                        ) : null
                      })()
                    )}
                  </div>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      {/* ---------- 生成视频弹窗：选模型 / 分辨率（脚本时长只读展示） ---------- */}
      <Modal
        title="生成视频"
        open={videoModal.open}
        onCancel={() => setVideoModal({ open: false, scriptId: null })}
        onOk={() => videoForm.validateFields().then((v) =>
          genVideo.mutate({ scriptId: videoModal.scriptId!, model: v.model, resolution: v.resolution }))}
        okText="开始生成（按条收费）"
        cancelText="取消"
        confirmLoading={genVideo.isPending}
      >
        {(() => {
          const s = p.scripts.find((x) => x.id === videoModal.scriptId)
          const scriptDur = s?.duration || 0
          const shown = scriptDur || videoOptions?.default_duration || 0
          const lo = currentSpec?.duration?.[0], hi = currentSpec?.duration?.[1]
          const eff = lo && hi ? Math.max(lo, Math.min(hi, shown)) : shown
          return (
            <Descriptions size="small" column={1} style={{ marginBottom: 12 }} bordered>
              <Descriptions.Item label="脚本">
                v{s?.version}（{s?.model || '—'}）
              </Descriptions.Item>
              <Descriptions.Item label="脚本时长">
                <Tag color={scriptDur ? 'cyan' : 'default'}>
                  {scriptDur ? `${scriptDur}s` : `未定，按默认 ${shown}s`}
                </Tag>
                {scriptDur && eff !== shown && (
                  <Typography.Text type="warning" style={{ fontSize: 12 }}>
                    超出所选模型 {lo}–{hi}s 范围，将按 {eff}s 提交
                  </Typography.Text>
                )}
              </Descriptions.Item>
            </Descriptions>
          )
        })()}
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          时长按脚本里 AI 定的秒数自动提交，超出所选模型允许范围时按边界值提交。
        </Typography.Paragraph>
        <Form form={videoForm} layout="vertical">
          <Form.Item name="model" label="模型" rules={[{ required: true, message: '选择模型' }]}>
            <Select
              options={(videoOptions?.models ?? []).map((m: any) => ({
                value: m.name,
                label: `${m.name}（${m.duration?.[0]}–${m.duration?.[1]}s）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="resolution" label="分辨率" rules={[{ required: true, message: '选择分辨率' }]}>
            <Select
              options={(currentSpec?.resolutions ?? ['480p', '720p', '1080p']).map(
                (r: string) => ({ value: r, label: r }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
