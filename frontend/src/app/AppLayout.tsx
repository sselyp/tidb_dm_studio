import { Button, Layout, Menu, Space, Typography } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const { Sider, Header, Content } = Layout;

const MENU_ITEMS = [
  { key: "/tasks", label: "任务" },
  { key: "/datasources", label: "数据源" },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { me, logout } = useAuth();

  const selected = location.pathname.startsWith("/datasources")
    ? "/datasources"
    : "/tasks";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider theme="dark" breakpoint="lg" collapsedWidth={0}>
        <div
          style={{
            color: "#fff",
            padding: 16,
            fontWeight: 600,
            fontSize: 16,
          }}
        >
          DM Studio
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          items={MENU_ITEMS}
          onClick={(e) => navigate(e.key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: "#fff",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            paddingInline: 20,
          }}
        >
          <Typography.Text strong>TiDB DM Studio</Typography.Text>
          <Space>
            <span>{me?.username}</span>
            <Button size="small" onClick={() => navigate("/account")}>
              修改密码
            </Button>
            <Button size="small" onClick={() => void logout()}>
              退出
            </Button>
          </Space>
        </Header>
        <Content style={{ padding: 20 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
