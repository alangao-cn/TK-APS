import { useQuery } from '@tanstack/react-query'
import {
  Button, Card, Checkbox, Col, Empty, Input, Row, Segmented, Select, Space, Tag, Typography, message,
} from 'antd'
import dayjs from 'dayjs'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { api, downloadBlob } from '../api/client'

type VideoRow = {
  id: number
  product_id: string
  product_title: string
  batch_id: number
  version: number
  status: string
  model: string
  error: string
  size_mb: number
  has_file: boolean
  created_at: string
}

export default function Videos() {
  const [status, setStatus] = useState('succeeded')
  const [q, setQ] = useState('')
  const [batch, setBatch] = useState<number | undefined>()
  const [picked, setPicked] = useState<number[]>([])

  const { data: batchesData } = useQuery({
    queryKey: ['batches'],
    queryFn: () => api<any>('/api/batches'),
  })
  const { data, isLoading } = useQuery({
    queryKey: ['videos', status, q, batch],
    queryFn: () => api<{ videos: VideoRow[] }>(
      `/api/videos?status=${status}&q=${encodeURIComponent(q)}${batch ? `&batch_id=${batch}` : ''}`),
  })

  const videos = (data?.videos ?? []).filter((v) => v.has_file || status !== 'succeeded')
  const pickable = videos.filter((v) => v.has_file).map((v) => v.id)
  const allPicked = picked.length > 0 && picked.length === pickable.length

  const zip = async () => {
    if (!picked.length) return message.warning('先勾选要打包的视频')
    try {
      await downloadBlob('/api/videos/zip', { ids: picked }, `tkaps_videos_${dayjs().format('YYYYMMDD_HHmm')}.zip`)
      message.success(`已打包 ${picked.length} 个视频`)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>视频库</Typography.Title>
        <Space wrap>
          <Segmented
            value={status}
            onChange={(v) => { setStatus(v as string); setPicked([]) }}
            options={[
              { value: 'succeeded', label: '已出片' },
              { value: 'filtered', label: '被拦截' },
              { value: '', label: '全部' },
            ]}
          />
          <Select
            allowClear placeholder="按批次"
            style={{ minWidth: 160 }}
            value={batch}
            onChange={(v) => { setBatch(v); setPicked([]) }}
            options={(batchesData?.batches ?? []).map((b: any) => ({
              value: b.id, label: `${dayjs(b.created_at || b.ts).format('MM-DD')} 批次`,
            }))}
          />
          <Input.Search placeholder="搜标题 / 商品ID" allowClear style={{ width: 200 }} onSearch={setQ} />
          <Button onClick={() => setPicked(allPicked ? [] : pickable)}>
            {allPicked ? '取消全选' : '全选'}
          </Button>
          <Button type="primary" onClick={zip} disabled={!picked.length}>
            打包下载 ZIP（{picked.length}）
          </Button>
        </Space>
      </div>

      {!videos.length && !isLoading && <Empty description="没有匹配的视频" />}

      <Row gutter={[16, 16]}>
        {videos.map((v) => (
          <Col key={v.id} xs={24} sm={12} md={8} lg={6}>
            <Card size="small">
              {v.has_file ? (
                <video controls preload="metadata" src={`/api/videos/${v.id}/file`}
                  style={{ width: '100%', aspectRatio: '9/16', maxHeight: 380, background: '#000', borderRadius: 6 }} />
              ) : (
                <div style={{ aspectRatio: '9/16', maxHeight: 380, borderRadius: 6, background: '#fff2f0',
                  border: '1px dashed #ffccc7', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  padding: 12, textAlign: 'center', fontSize: 12, color: '#cf1322', overflow: 'auto' }}>
                  {v.error || '未生成视频文件'}
                </div>
              )}
              <div style={{ marginTop: 8 }}>
                <Space size={4} wrap>
                  {v.has_file && (
                    <Checkbox
                      checked={picked.includes(v.id)}
                      onChange={(e) => setPicked(e.target.checked ? [...picked, v.id] : picked.filter((x) => x !== v.id))}
                    />
                  )}
                  <Tag color={v.status === 'succeeded' ? 'green' : 'red'}>v{v.version} · {v.status}</Tag>
                  {v.size_mb > 0 && <Tag>{v.size_mb} MB</Tag>}
                </Space>
                <Typography.Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 4, fontSize: 13 }}>
                  <Link to={`/product/${v.product_id}`}>{v.product_title}</Link>
                </Typography.Paragraph>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {dayjs(v.created_at).format('YYYY-MM-DD HH:mm')} · {v.size_mb} MB
                </Typography.Text>
                <div style={{ marginTop: 6 }}>
                  {v.has_file
                    ? <Button size="small" href={`/api/videos/${v.id}/download`}>下载</Button>
                    : <Tag color="red">在商品详情里重试</Tag>}
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </Space>
  )
}
