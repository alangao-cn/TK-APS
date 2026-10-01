import { Button, Card, Form, Input, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { login } from '../api/client'

export default function Login() {
  const nav = useNavigate()
  const [form] = Form.useForm()

  return (
    <div style={{ minHeight: '80vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Card style={{ width: 360 }}>
        <Typography.Title level={3} style={{ textAlign: 'center' }}>TK·APS</Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center' }}>
          自动化选品 + AI 视频素材
        </Typography.Paragraph>
        <Form
          form={form}
          onFinish={async (v) => {
            try {
              await login(v.username, v.password)
              nav('/')
            } catch (e: any) {
              form.setFields([{ name: 'password', errors: [e.message] }])
            }
          }}
        >
          <Form.Item name="username" rules={[{ required: true, message: '请输入账号' }]}>
            <Input placeholder="账号" autoFocus autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>登录</Button>
        </Form>
      </Card>
    </div>
  )
}
