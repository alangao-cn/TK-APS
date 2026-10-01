import { useMutation, useQuery } from '@tanstack/react-query'
import { Button, Card, Descriptions, Input, Space, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { api, post, put } from '../api/client'

export default function Settings() {
  const { data } = useQuery({ queryKey: ['settings'], queryFn: () => api<any>('/api/settings') })
  const [text, setText] = useState('')

  useEffect(() => { if (data?.config_text) setText(data.config_text) }, [data])

  const save = useMutation({
    mutationFn: () => put('/api/settings', { config_text: text }),
    onSuccess: () => message.success('配置已保存并热加载（新任务立即生效）'),
    onError: (e: any) => message.error(e.message),
  })
  const reload = useMutation({
    mutationFn: () => post('/api/settings/reload'),
    onSuccess: () => message.success('配置已重新加载'),
    onError: (e: any) => message.error(e.message),
  })

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card title="密钥状态（.env）" size="small">
        <Descriptions size="small" column={2}>
          {(data?.env_items ?? []).map(([k, v]: string[]) => (
            <Descriptions.Item key={k} label={<code>{k}</code>}>{v}</Descriptions.Item>
          ))}
        </Descriptions>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          密钥在 .env 文件里改，改完重启服务生效。
        </Typography.Text>
      </Card>

      <Card
        title="config.yaml"
        extra={
          <Space>
            <Button onClick={() => reload.mutate()} loading={reload.isPending}>重新加载</Button>
            <Button type="primary" onClick={() => save.mutate()} loading={save.isPending}>保存配置</Button>
          </Space>
        }
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          模型（llm.model / video.model）、视频规格、筛选条件都在这里。保存时会校验 YAML 并热加载。
          视频模型在当前接口通道不支持时会自动换另一条通道重试。
        </Typography.Paragraph>
        <Input.TextArea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={24}
          spellCheck={false}
          style={{ fontFamily: 'monospace', fontSize: 12.5 }}
        />
      </Card>
    </Space>
  )
}
