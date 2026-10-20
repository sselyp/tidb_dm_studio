import { App as AntApp, Button, Card, Form, Input, Typography } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { envelopeMessage } from "../api/errorMessages";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";

interface LoginForm {
  username: string;
  password: string;
}

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: LoginForm) => {
    setLoading(true);
    try {
      const me = await login(values.username, values.password);
      navigate(me.mustChangePassword ? "/account" : "/", { replace: true });
    } catch (error) {
      const text =
        error instanceof ApiError
          ? envelopeMessage(error.code, error.message)
          : "登录失败，请稍后重试";
      message.error(text);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#f5f6f8",
      }}
    >
      <Card style={{ width: 380 }} styles={{ body: { padding: 32 } }}>
        <Typography.Title level={4} style={{ textAlign: "center", marginBottom: 4 }}>
          TiDB DM Studio
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: "center" }}>
          MySQL → TiDB 迁移可视化配置平台
        </Typography.Paragraph>
        <Form<LoginForm>
          layout="vertical"
          initialValues={{ username: "", password: "" }}
          onFinish={onFinish}
        >
          <Form.Item
            label="用户名"
            name="username"
            rules={[{ required: true, message: "请输入用户名" }]}
          >
            <Input autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item
            label="密码"
            name="password"
            rules={[{ required: true, message: "请输入密码" }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  );
}
