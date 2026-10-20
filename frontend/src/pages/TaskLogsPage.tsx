import { Button, Card, Space, Table, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import * as api from "../api/endpoints";

const LIMIT = 200;

export default function TaskLogsPage() {
  const { name = "" } = useParams();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);

  const logsQuery = useQuery({
    queryKey: ["task-logs", name, offset],
    queryFn: () => api.getTaskLogs(name, offset, LIMIT),
    enabled: name.length > 0,
  });

  const data = logsQuery.data?.data;
  const items = (data?.items ?? []).map((line, i) => ({
    key: offset + i,
    line,
  }));

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {name} · 日志
        </Typography.Title>
        <Space>
          <Button onClick={() => navigate(`/tasks/${name}`)}>返回详情</Button>
          <Button onClick={() => logsQuery.refetch()} loading={logsQuery.isFetching}>
            刷新
          </Button>
        </Space>
      </Space>

      <Card>
        <Table
          size="small"
          rowKey="key"
          loading={logsQuery.isLoading}
          dataSource={items}
          pagination={false}
          columns={[
            {
              title: "日志",
              dataIndex: "line",
              render: (line: string) => (
                <span style={{ fontFamily: "monospace", whiteSpace: "pre-wrap" }}>
                  {line}
                </span>
              ),
            },
          ]}
        />
        <Space style={{ marginTop: 12 }}>
          <Button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - LIMIT))}
          >
            上一页
          </Button>
          <span style={{ color: "#8f959e" }}>
            offset {offset} · total {data?.total ?? "-"}
          </span>
          <Button
            disabled={data?.total != null && offset + LIMIT >= data.total}
            onClick={() => setOffset(offset + LIMIT)}
          >
            下一页
          </Button>
        </Space>
      </Card>
    </Space>
  );
}
