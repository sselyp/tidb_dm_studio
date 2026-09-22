import {
  App as AntApp,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { envelopeMessage } from "../api/errorMessages";
import * as api from "../api/endpoints";
import { ApiError } from "../api/http";
import type { ConnectivityResult, DataSource, DataSourceWrite } from "../api/types";

const TYPE_COLORS: Record<string, string> = { mysql: "blue", tidb: "purple" };

export default function DataSourcesPage() {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<DataSourceWrite>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ConnectivityResult | null>(null);

  const listQuery = useQuery({
    queryKey: ["datasources"],
    queryFn: () => api.listDataSources(1, 100),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["datasources"] });

  const saveMutation = useMutation({
    mutationFn: async (values: DataSourceWrite) => {
      if (editingId) {
        const { etag } = await api.getDataSource(editingId);
        return api.updateDataSource(editingId, values, etag ?? "");
      }
      return api.createDataSource(values);
    },
    onSuccess: () => {
      message.success("已保存");
      setModalOpen(false);
      setEditingId(null);
      void invalidate();
    },
    onError: (error) => {
      message.error(
        error instanceof ApiError
          ? envelopeMessage(error.code, error.message)
          : "保存失败",
      );
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteDataSource(id),
    onSuccess: () => {
      message.success("已删除");
      void invalidate();
    },
    onError: (error) => {
      message.error(
        error instanceof ApiError
          ? envelopeMessage(error.code, error.message)
          : "删除失败",
      );
    },
  });

  const openCreate = () => {
    setEditingId(null);
    setTestResult(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: DataSource) => {
    setEditingId(record.id);
    setTestResult(null);
    form.setFieldsValue({
      name: record.name,
      type: record.type,
      host: record.host,
      port: record.port,
      username: record.username,
    });
    setModalOpen(true);
  };

  const runTest = async () => {
    try {
      const values = await form.validateFields();
      const { data } = await api.testDataSource(values);
      setTestResult(data);
    } catch (error) {
      if (error instanceof ApiError) {
        message.error(envelopeMessage(error.code, error.message));
      }
    }
  };

  const columns: ColumnsType<DataSource> = [
    {
      title: "名称 / ID",
      key: "name",
      render: (_, r) => (
        <div>
          <div>{r.name}</div>
          <div style={{ color: "#8f959e", fontSize: 12 }}>{r.id}</div>
        </div>
      ),
    },
    {
      title: "类型",
      dataIndex: "type",
      render: (t: string) => <Tag color={TYPE_COLORS[t]}>{t}</Tag>,
    },
    {
      title: "地址",
      key: "addr",
      render: (_, r) => `${r.host}:${r.port}`,
    },
    { title: "账号", dataIndex: "username" },
    { title: "版本", dataIndex: "version", render: (v?: string) => v ?? "-" },
    {
      title: "操作",
      key: "actions",
      align: "right",
      render: (_, r) => (
        <Space>
          <Button size="small" onClick={() => openEdit(r)}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除该数据源？"
            onConfirm={() => deleteMutation.mutate(r.id)}
          >
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Space
        style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}
      >
        <span style={{ fontSize: 16, fontWeight: 600 }}>数据源管理</span>
        <Button type="primary" onClick={openCreate}>
          + 新建数据源
        </Button>
      </Space>

      <Table<DataSource>
        rowKey="id"
        size="small"
        loading={listQuery.isLoading}
        dataSource={listQuery.data?.data.items ?? []}
        columns={columns}
        pagination={false}
      />

      <Modal
        open={modalOpen}
        title={editingId ? "编辑数据源" : "新建数据源"}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={saveMutation.isPending}
        okText="保存"
        destroyOnClose
      >
        <Form<DataSourceWrite>
          form={form}
          layout="vertical"
          onFinish={(values) => saveMutation.mutate(values)}
        >
          <Form.Item
            label="名称"
            name="name"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item label="类型" name="type" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "mysql", label: "MySQL" },
                { value: "tidb", label: "TiDB" },
              ]}
            />
          </Form.Item>
          <Space>
            <Form.Item
              label="主机"
              name="host"
              rules={[{ required: true, message: "请输入主机" }]}
            >
              <Input style={{ width: 240 }} />
            </Form.Item>
            <Form.Item
              label="端口"
              name="port"
              rules={[{ required: true, message: "请输入端口" }]}
            >
              <InputNumber style={{ width: 120 }} />
            </Form.Item>
          </Space>
          <Form.Item
            label="账号"
            name="username"
            rules={[{ required: true, message: "请输入账号" }]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item label="密码" name="password">
            <Input.Password
              autoComplete="new-password"
              placeholder="留空表示不修改"
            />
          </Form.Item>

          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Button onClick={runTest}>测试连接</Button>
            {testResult && (
              <Tag color={testResult.reachable ? "green" : "red"}>
                {testResult.reachable ? "可达" : "不可达"}
                {testResult.authenticated ? " / 鉴权通过" : ""}
                {typeof testResult.latencyMs === "number"
                  ? ` / ${testResult.latencyMs}ms`
                  : ""}
              </Tag>
            )}
          </Space>
        </Form>
      </Modal>
    </>
  );
}
