import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout, Menu, Typography } from 'antd'
import dayjs from 'dayjs'
import { HashRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import JobMonitor from './components/JobMonitor'
import Batches from './pages/Batches'
import BatchDetail from './pages/BatchDetail'
import Login from './pages/Login'
import ProductDetail from './pages/ProductDetail'
import Settings from './pages/Settings'
import Videos from './pages/Videos'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

function TopMenu() {
  const loc = useLocation()
  // HashRouter 下路由信息在 pathname 里；商品/批次详情页归属"批次"菜单
  const key = loc.pathname.split('?')[0]
  const selected = key.startsWith('/batch') || key.startsWith('/product') ? '/' : key || '/'
  return (
    <Layout.Header style={{ display: 'flex', alignItems: 'center', padding: '0 24px' }}>
      <Typography.Title level={4} style={{ color: '#fff', margin: '0 24px 0 0' }}>
        TK·APS
      </Typography.Title>
      <Menu
        theme="dark"
        mode="horizontal"
        selectedKeys={[selected]}
        style={{ flex: 1, minWidth: 0 }}
        items={[
          { key: '/', label: <Link to="/">批次</Link> },
          { key: '/videos', label: <Link to="/videos">视频库</Link> },
          { key: '/settings', label: <Link to="/settings">设置</Link> },
        ]}
      />
      <Typography.Text style={{ color: 'rgba(255,255,255,0.65)', fontSize: 12 }}>
        {dayjs().format('YYYY-MM-DD ddd')}
      </Typography.Text>
    </Layout.Header>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <Layout style={{ minHeight: '100vh' }}>
          <TopMenu />
          <Layout.Content style={{ padding: '20px 24px', maxWidth: 1280, width: '100%', margin: '0 auto' }}>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/" element={<Batches />} />
              <Route path="/batch/:id" element={<BatchDetail />} />
              <Route path="/product/:id" element={<ProductDetail />} />
              <Route path="/videos" element={<Videos />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Layout.Content>
          <JobMonitor />
        </Layout>
      </HashRouter>
    </QueryClientProvider>
  )
}
