import { App as AntApp, Button, Card, Form, Input, Typography } from "antd";
import { useState } from "react";
import { envelopeMessage } from "../api/errorMessages";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";

interface PasswordForm {
  oldPassword: string;
  newPassword: string;
  confirm: string;
}

export default function AccountPage() {
  const { changePassword, me } = useAuth();
  const { message } = AntApp.useApp();
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: PasswordForm) => {
    setLoading(true);
    try {
      await changePassword(values.oldPassword, values.newPassword);
      message.success("密码已修改，请重新登录");
    } catch (error) {
      const text =
        error instanceof ApiError
          ? envelopeMessage(error.code, error.message)
          : "修改失败，请稍后重试";
      message.error(text);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card style={{ maxWidth: 520 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        修改密码
      </Typography.Title>
      {me?.mustChangePassword && (
        <Typography.Paragraph type="warning">
          当前为初始密码，请修改后再继续使用。
        </Typography.Paragraph>
      )}
      <Form<PasswordForm> layout="vertical" onFinish={onFinish}>
        <Form.Item
          label="当前密码"
          name="oldPassword"
          rules={[{ required: true, message: "请输入当前密码" }]}
        >
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          label="新密码"
          name="newPassword"
          rules={[{ required: true, message: "请输入新密码" }]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          label="确认新密码"
          name="confirm"
          dependencies={["newPassword"]}
          rules={[
            { required: true, message: "请再次输入新密码" },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue("newPassword") === value) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error("两次输入的密码不一致"));
              },
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={loading}>
          提交
        </Button>
      </Form>
    </Card>
  );
}
