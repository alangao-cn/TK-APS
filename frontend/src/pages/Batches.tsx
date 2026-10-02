import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Button, Card, Checkbox, Col, Collapse, Form, Input, InputNumber, Modal, Row,
  Select, Space, Spin, Statistic, Tag, Typography, message,
} from 'antd'
import dayjs from 'dayjs'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { api, post } from '../api/client'

type Batch = {
  id: number
  ts: string
  created_at: string
  note: string
  counts: { products: number; confirmed: number; scripts: number; videos: number }
}

const PERIODS = [
  { value: 'weekly', label: '周榜' },
  { value: 'daily', label: '日榜' },
  { value: 'monthly', label: '月榜' },
]
const FALLBACK_CATEGORIES = ['运动与户外', '居家日用', '五金工具']

function dayGroup(created_at: string): string {
  const d = dayjs(created_at)
  if (d.isSame(dayjs(), 'day')) return '今天'
  if (d.isSame(dayjs().subtract(1, 'day'), 'day')) return '昨天'
  return d.format('M月D日 ddd')
}

function ScrapeButton() {
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const qc = useQueryClient()

  // 预填值从后端配置读（config.yaml 改了表单跟着变），拿到后才允许打开弹窗
  const { data: defaults } = useQuery({
    queryKey: ['scrape-defaults'],
    queryFn: () => api<any>('/api/scrape/defaults'),
    staleTime: 60_000,
  })

  const start = useMutation({
    mutationFn: (v: any) => post('/api/scrape', v),
    onSuccess: (r: any) => {
      if (r.ok) {
        message.success('采集任务已启动（浏览器窗口会弹出，任务进度看右下角浮标）')
        setOpen(false)
        setTimeout(() => qc.invalidateQueries({ queryKey: ['jobs'] }), 500)
      } else message.error(r.error)
    },
    onError: (e: any) => message.error(e.message),
  })

  return (
    <>
      <Button type="primary" disabled={!defaults} onClick={() => setOpen(true)}>发起选品采集</Button>
      <Modal
        title="采集参数"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.validateFields().then((v) => start.mutate(v))}
        okText="开始采集"
        cancelText="取消"
        confirmLoading={start.isPending}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          参数只影响本次采集（预填 config.yaml 默认值），不写回配置文件。完成后自动出现在批次列表。
        </Typography.Paragraph>
        <Form
          form={form}
          layout="vertical"
          initialValues={defaults}
        >
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="period" label="榜单周期" rules={[{ required: true }]}>
                <Select options={PERIODS} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="region" label="地区" rules={[{ required: true }]}>
                <Input maxLength={4} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="max_pages" label="每类目翻页" rules={[{ required: true }]}>
                <InputNumber min={1} max={50} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="categories" label="类目" rules={[{ required: true, message: '至少选一个类目' }]}>
            <Checkbox.Group options={defaults?.categories?.length ? defaults.categories : FALLBACK_CATEGORIES} />
          </Form.Item>
          <Collapse
            size="small"
            items={[{
              key: 'filters',
              label: '筛选参数（采集后的导出阶段生效）',
              children: (
                <Row gutter={12}>
                  <Col span={12}>
                    <Form.Item name="min_profit_cny" label="单件利润下限（元）">
                      <InputNumber min={0} step={0.5} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="min_stock" label="库存下限">
                      <InputNumber min={0} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="creators_min" label="带货达人下限">
                      <InputNumber min={0} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="creators_max" label="带货达人上限">
                      <InputNumber min={0} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                </Row>
              ),
            }]}
          />
        </Form>
      </Modal>
    </>
  )
}

export default function Batches() {
  const { data, isLoading } = useQuery({
    queryKey: ['batches'],
    queryFn: () => api<{ batches: Batch[] }>('/api/batches'),
  })

  if (isLoading) return <Spin style={{ display: 'block', margin: '80px auto' }} />

  const batches = data?.batches ?? []
  const groups: { name: string; items: Batch[] }[] = []
  for (const b of batches) {
    const name = dayGroup(b.created_at || b.ts)
    const g = groups.find((x) => x.name === name)
    if (g) g.items.push(b)
    else groups.push({ name, items: [b] })
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>批次工作台</Typography.Title>
        <ScrapeButton />
      </div>

      {groups.map((g) => (
        <div key={g.name}>
          <Typography.Title level={5} type="secondary" style={{ margin: '0 0 8px' }}>{g.name}</Typography.Title>
          <Row gutter={[16, 16]}>
            {g.items.map((b) => (
              <Col key={b.id} xs={24} sm={12} lg={8}>
                <Card
                  hoverable
                  title={
                    <span>
                      {dayjs(b.created_at || b.ts).format('MM-DD HH:mm')}
                      {b.note && <Tag style={{ marginLeft: 8 }}>{b.note}</Tag>}
                    </span>
                  }
                  extra={<Link to={`/batch/${b.id}`}>进入 →</Link>}
                >
                  <Row gutter={8}>
                    <Col span={6}><Statistic title="入选" value={b.counts.products} /></Col>
                    <Col span={6}><Statistic title="确认" value={b.counts.confirmed} /></Col>
                    <Col span={6}><Statistic title="脚本" value={b.counts.scripts} /></Col>
                    <Col span={6}><Statistic title="视频" value={b.counts.videos} /></Col>
                  </Row>
                </Card>
              </Col>
            ))}
          </Row>
        </div>
      ))}

      {!batches.length && (
        <Card>
          <Typography.Text type="secondary">
            还没有采集批次，点右上角「发起选品采集」开始第一次选品。
          </Typography.Text>
        </Card>
      )}
    </Space>
  )
}
