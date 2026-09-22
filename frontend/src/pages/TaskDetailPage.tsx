import {
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Progress,
  Space,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import * as api from "../api/endpoints";
import { envelopeMessage } from "../api/errorMessages";
import { ApiError } from "../api/http";
import type { DesiredState } from "../api/types";
import StateTag from "../components/StateTag";

export default function TaskDetailPage() {
  const { name = "" } = useParams();
  const { message } = AntApp.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [yaml, setYaml] = useState<string | null>(null);

  const statusQuery = useQuery({
    queryKey: ["task-status", name],
    queryFn: () => api.getTaskStatus(name),
    refetchInterval: 5000,
    enabled: name.length > 0,
  });

  const taskQuery = useQuery({
    queryKey: ["task", name],
    queryFn: () => api.getTask(name),
    enabled: name.length > 0,
  });

  const stateMutation = useMutation({
    mutationFn: (desiredState: DesiredState) => api.putTaskState(name, desiredState),
    onSuccess: (res) => {
      message.success(res.data.applied === false ? "目标状态已满足" : "已提交状态变更");
      void queryClient.invalidateQueries({ queryKey: ["task-status", name] });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (error) =>
      message.error(
        error instanceof ApiError
          ? envelopeMessage(error.code, error.message)
          : "操作失败",
      ),
  });

  const status = statusQuery.data?.data;
  const task = taskQuery.data?.data;
  const progressPct = status?.progress != null ? Math.round(status.progress * 100) : 0;

  const exportYaml = async () => {
    try {
      setYaml(await api.exportTaskYaml(name));
    } catch (error) {
      message.error(
        error instanceof ApiError
          ? envelopeMessage(error.code, error.message)
          : "导出失败",
      );
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Space>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {name}
          </Typography.Title>
          <StateTag state={status?.state} />
        </Space>
        <Space>
          {(status?.state === "new" ||
            status?.state === "stopped" ||
            status?.state === "failed") && (
            <Button type="primary" onClick={() => stateMutation.mutate("running")}>
              启动
            </Button>
          )}
          {status?.state === "running" && (
            <Button onClick={() => stateMutation.mutate("paused")}>暂停</Button>
          )}
          {status?.state === "paused" && (
            <Button type="primary" onClick={() => stateMutation.mutate("running")}>
              恢复
            </Button>
          )}
          {(status?.state === "running" || status?.state === "paused") && (
            <Button onClick={() => stateMutation.mutate("stopped")}>停止</Button>
          )}
          <Button onClick={() => navigate(`/tasks/${name}/logs`)}>日志</Button>
          <Button onClick={exportYaml}>导出 YAML</Button>
        </Space>
      </Space>

      <Card>
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <div>
            <div style={{ marginBottom: 6 }}>总进度</div>
            <Progress percent={progressPct} />
          </div>
          <Descriptions size="small" column={3}>
            <Descriptions.Item label="阶段">{status?.stage ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="原生状态">
              {status?.nativeState ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="延迟">
              {status?.lag != null ? `${status.lag}s` : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="上游源数">
              {task?.sources.length ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="更新时间">
              {status?.updatedAt ?? "-"}
            </Descriptions.Item>
          </Descriptions>
          {status?.lastError && (
            <Typography.Text type="danger">最近错误：{status.lastError}</Typography.Text>
          )}
        </Space>
      </Card>

      {yaml && (
        <Card title="task.yaml">
          <Typography.Paragraph>
            <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{yaml}</pre>
          </Typography.Paragraph>
        </Card>
      )}
    </Space>
  );
}
