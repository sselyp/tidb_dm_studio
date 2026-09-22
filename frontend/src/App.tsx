import { Layout, Typography } from "antd";

export default function App() {
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Content style={{ padding: 24 }}>
        <Typography.Title level={3}>TiDB DM Studio</Typography.Title>
        <Typography.Paragraph type="secondary">
          MySQL → TiDB 的 DM 迁移可视化配置平台。骨架初始化中，功能按里程碑 P1/P2 推进。
        </Typography.Paragraph>
      </Layout.Content>
    </Layout>
  );
}
