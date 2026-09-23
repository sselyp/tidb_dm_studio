import {
  App as AntApp,
  Button,
  Popconfirm,
  Space,
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { devContractAssert } from "../api/contractAssert";
import * as api from "../api/endpoints";
import { envelopeMessage } from "../api/errorMessages";
import { ApiError } from "../api/http";
import type { DesiredState, TaskSummary } from "../api/types";
import StateTag from "../components/StateTag";
import { ACTION_META, resolveAllowedActions } from "../components/taskActions";

export default function TasksPage() {
  const { message } = AntApp.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api.listTasks(1, 100),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["tasks"] });

  const stateMutation = useMutation({
    mutationFn: ({
      name,
      desiredState,
    }: {
      name: string;
      desiredState: DesiredState;
    }) => api.putTaskState(name, desiredState),
    onSuccess: (res) => {
      message.success(
        res.data.applied === false ? "目标状态已满足" : "已提交状态变更",
      );
      void invalidate();
    },
    onError: (error) =>
      message.error(
        error instanceof ApiError
          ? envelopeMessage(error.code, error.message)
          : "操作失败",
      ),
  });

  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.deleteTask(name),
    onSuccess: () => {
      message.success("已删除");
      void invalidate();
    },
    onError: (error) =>
      message.error(
        error instanceof ApiError
          ? envelopeMessage(error.code, error.message)
          : "删除失败",
      ),
  });

  const columns: ColumnsType<TaskSummary> = [
    {
      title: "任务名",
      dataIndex: "name",
      render: (name: string) => <Link to={`/tasks/${name}`}>{name}</Link>,
    },
    {
      title: "状态",
      dataIndex: "state",
      render: (state: TaskSummary["state"]) => <StateTag state={state} />,
    },
    { title: "阶段", dataIndex: "stage", render: (v?: string) => v ?? "-" },
    {
      title: "延迟",
      dataIndex: "lag",
      render: (v?: number) => (typeof v === "number" ? `${v}s` : "-"),
    },
    { title: "源数", dataIndex: "sourceCount", render: (v?: number) => v ?? "-" },
    {
      title: "操作",
      key: "actions",
      align: "right",
      render: (_, r) => {
        // D15: the server owns the action set; the state mapping is a dev-only
        // compatibility fallback for list responses that omit `allowedActions`.
        const { actions } = resolveAllowedActions(r.allowedActions, r.state);
        devContractAssert(
          r.allowedActions !== undefined,
          "task list item is missing allowedActions; using frontend state→action fallback",
        );
        const stateActions = actions.filter(
          (action) => ACTION_META[action].desiredState !== undefined,
        );
        return (
          <Space>
            <Button size="small" onClick={() => navigate(`/tasks/${r.name}`)}>
              详情
            </Button>
            {stateActions.map((action) => {
              const meta = ACTION_META[action];
              const desiredState = meta.desiredState as DesiredState;
              return (
                <Button
                  key={action}
                  size="small"
                  type={meta.primary ? "primary" : "default"}
                  loading={
                    stateMutation.isPending &&
                    stateMutation.variables?.name === r.name &&
                    stateMutation.variables.desiredState === desiredState
                  }
                  onClick={() => stateMutation.mutate({ name: r.name, desiredState })}
                >
                  {meta.label}
                </Button>
              );
            })}
            {actions.includes("delete") && (
              <Popconfirm
                title="确认删除该任务？"
                onConfirm={() => deleteMutation.mutate(r.name)}
              >
                <Button size="small" danger>
                  删除
                </Button>
              </Popconfirm>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <Space
        style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}
      >
        <span style={{ fontSize: 16, fontWeight: 600 }}>任务管理</span>
        <Button type="primary" onClick={() => navigate("/tasks/new")}>
          + 新建任务
        </Button>
      </Space>

      <Table<TaskSummary>
        rowKey="name"
        size="small"
        loading={listQuery.isLoading}
        dataSource={listQuery.data?.data.items ?? []}
        columns={columns}
        pagination={false}
      />
    </>
  );
}
