import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Button, Card, Checkbox, Image, Input, Segmented, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, post } from '../api/client'

dayjs.extend(relativeTime)

export type ProductRow = {
  id: number
  product_id: string
  title: string
  category: string
  price_min: number
  price_max: number
  currency: string
  commission_rate: string
  creators: number
  sales_week: number
  stock: number
  rating: number
  profit_cny: number
  image_files: string[]
  fastmoss_url: string
  tiktok_url: string
  confirmed: boolean
  has_script: boolean
  script_version: number | null
  script_count: number
  video_count: number
  video_latest_status: string | null
  updated_at: string
}

export function FreshTag({ updated_at }: { updated_at: string }) {
  const mins = dayjs().diff(dayjs(updated_at), 'minute')
  if (mins < 30) return <Tag color="blue">{mins < 1 ? '刚刚' : `${mins} 分钟前`}</Tag>
  return null
}

export default function BatchDetail() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const qc = useQueryClient()
  const confirmedFilter = params.get('confirmed') ?? 'all'
  const scriptFilter = params.get('has_script') ?? 'all'
  const q = params.get('q') ?? ''

  const { data, isLoading } = useQuery({
    queryKey: ['batch', id, confirmedFilter, scriptFilter, q],
    queryFn: () =>
      api<any>(`/api/batches/${id}?confirmed=${confirmedFilter !== 'all' ? confirmedFilter : ''}&has_script=${scriptFilter !== 'all' ? scriptFilter : ''}&q=${encodeURIComponent(q)}`),
  })

  const saveConfirm = useMutation({
    mutationFn: (ids: number[]) => post(`/api/batches/${id}/confirm`, { product_ids: ids }),
    onSuccess: (r: any) => {
      message.success(`已保存：确认 ${r.confirmed} 件（脚本生成只处理确认的商品）`)
      qc.invalidateQueries({ queryKey: ['batch', id] })
      qc.invalidateQueries({ queryKey: ['batches'] })
    },
    onError: (e: any) => message.error(e.message),
  })

  const genScripts = useMutation({
    mutationFn: () => post(`/api/batches/${id}/gen-scripts`),
    onSuccess: (r: any) => {
      message.success(`批量生成已启动（${r.confirmed} 件已确认商品），进度看右下角浮标`)
      setTimeout(() => qc.invalidateQueries({ queryKey: ['jobs'] }), 500)
    },
    onError: (e: any) => message.error(e.message),
  })

  const products: ProductRow[] = data?.products ?? []
  const confirmedIds = products.filter((p) => p.confirmed).map((p) => p.id)

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value === 'all') next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const columns: any[] = [
    {
      title: '确认',
      dataIndex: 'confirmed',
      width: 60,
      render: (v: boolean, r: ProductRow) => (
        <Checkbox
          checked={v}
          onChange={(e) => saveConfirm.mutate(
            e.target.checked ? [...confirmedIds, r.id] : confirmedIds.filter((x) => x !== r.id),
          )}
        />
      ),
    },
    {
      title: '商品',
      dataIndex: 'title',
      render: (v: string, r: ProductRow) => (
        <Space>
          {r.image_files?.[0] && (
            <Image src={`/api/media/images/${r.image_files[0]}`} width={52} height={52}
              style={{ objectFit: 'cover', borderRadius: 6 }} preview={false} />
          )}
          <div style={{ maxWidth: 380 }}>
            <div>
              <Link to={`/product/${r.id}`}><b>{v}</b></Link>{' '}
              <FreshTag updated_at={r.updated_at} />
            </div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {r.category} ·{' '}
              <a href={r.fastmoss_url} target="_blank" rel="noreferrer">FastMoss</a> ·{' '}
              <a href={r.tiktok_url} target="_blank" rel="noreferrer">TikTok</a>
            </Typography.Text>
          </div>
        </Space>
      ),
    },
    { title: '价格', width: 110, render: (_: any, r: ProductRow) => `R$ ${r.price_min}${r.price_max !== r.price_min ? `–${r.price_max}` : ''}` },
    { title: '佣金', dataIndex: 'commission_rate', width: 70 },
    { title: '利润', dataIndex: 'profit_cny', width: 80, render: (v: number) => <Tag color="orange">¥{v}</Tag> },
    { title: '达人', dataIndex: 'creators', width: 70 },
    { title: '库存', dataIndex: 'stock', width: 80, render: (v: number) => v?.toLocaleString?.() ?? v },
    {
      title: '进度', width: 170,
      render: (_: any, r: ProductRow) => (
        <Space size={4} wrap>
          {r.has_script
            ? <Tag color="green">脚本 v{r.script_version}{r.script_count > 1 ? ` ×${r.script_count}` : ''}</Tag>
            : <Tag>无脚本</Tag>}
          {r.video_count > 0 && <Tag color="green">视频 ×{r.video_count}</Tag>}
          {r.video_latest_status && r.video_latest_status !== 'succeeded' && r.video_count === 0 && (
            <Tooltip title="最近一次生成失败"><Tag color="red">{r.video_latest_status}</Tag></Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '操作', width: 100,
      render: (_: any, r: ProductRow) => <Link to={`/product/${r.id}`}><Button size="small">详情</Button></Link>,
    },
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <Space direction="vertical" size={2}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            批次 {data?.ts}
          </Typography.Title>
          <Typography.Text type="secondary">
            采集于 {data?.created_at} · 共 {products.length} 件，已确认 {confirmedIds.length} 件
            （默认按更新时间排序，最近动过的在最上面）
          </Typography.Text>
        </Space>
        <Space>
          <Button onClick={() => genScripts.mutate()} loading={genScripts.isPending}>
            批量生成脚本（已确认 {confirmedIds.length} 件）
          </Button>
          <Link to="/"><Button>← 返回批次</Button></Link>
        </Space>
      </div>

      <Card size="small">
        <Space wrap>
          <Segmented
            value={confirmedFilter}
            onChange={(v) => setParam('confirmed', v as string)}
            options={[
              { value: 'all', label: '全部' },
              { value: '1', label: '已确认' },
              { value: '0', label: '未确认' },
            ]}
          />
          <Segmented
            value={scriptFilter}
            onChange={(v) => setParam('has_script', v as string)}
            options={[
              { value: 'all', label: '不限脚本' },
              { value: '0', label: '待生成' },
              { value: '1', label: '已有脚本' },
            ]}
          />
          <Input.Search
            placeholder="搜标题 / 商品ID"
            defaultValue={q}
            allowClear
            style={{ width: 220 }}
            onSearch={(v) => setParam('q', v)}
          />
        </Space>
      </Card>

      <Table
        rowKey="id"
        loading={isLoading}
        dataSource={products}
        columns={columns}
        pagination={products.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
        size="middle"
      />
    </Space>
  )
}
