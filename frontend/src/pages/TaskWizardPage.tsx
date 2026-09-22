import {
  App as AntApp,
  Button,
  Input,
  Select,
  Space,
  Steps,
  Typography,
} from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../api/endpoints";
import { envelopeMessage } from "../api/errorMessages";
import { ApiError } from "../api/http";
import type {
  SourceInstance,
  TaskConfig,
  TaskMode,
  TaskWrite,
  ValidationData,
} from "../api/types";
import SchemaForm from "../components/SchemaForm";
import SourcesEditor from "../components/SourcesEditor";
import ValidationReport from "../components/ValidationReport";
import YamlEditor from "../components/YamlEditor";

const MODES: Array<{ value: TaskMode; label: string }> = [
  { value: "all", label: "all（全量 + 增量）" },
  { value: "full", label: "full（仅全量）" },
  { value: "incremental", label: "incremental（仅增量）" },
];

const STEP_ITEMS = [
  { title: "基础" },
  { title: "上游" },
  { title: "高级参数" },
  { title: "YAML 与校验" },
];

export default function TaskWizardPage() {
  const { message } = AntApp.useApp();
  const navigate = useNavigate();

  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [mode, setMode] = useState<TaskMode>("all");
  const [sources, setSources] = useState<SourceInstance[]>([]);
  const [scalars, setScalars] = useState<Record<string, unknown>>({});
  const [rawYaml, setRawYaml] = useState<string | undefined>(undefined);
  const [validation, setValidation] = useState<ValidationData | null>(null);

  const schemaQuery = useQuery({
    queryKey: ["task-schema", mode],
    queryFn: () => api.getTaskSchema(mode),
  });

  const datasourcesQuery = useQuery({
    queryKey: ["datasources"],
    queryFn: () => api.listDataSources(1, 100),
  });

  const config: TaskConfig = useMemo(
    () => ({ taskMode: mode, ...scalars, sources }),
    [mode, scalars, sources],
  );

  const buildBody = (): TaskWrite =>
    rawYaml !== undefined
      ? { name, rawYaml }
      : { name, config };

  const validateMutation = useMutation({
    mutationFn: () => api.validateTask(buildBody()),
    onSuccess: (res) => setValidation(res.data),
    onError: (error) =>
      message.error(
        error instanceof ApiError
          ? envelopeMessage(error.code, error.message)
          : "校验失败",
      ),
  });

  const createMutation = useMutation({
    mutationFn: () => api.createTask(buildBody()),
    onSuccess: (res) => {
      message.success("任务已创建");
      navigate(`/tasks/${res.data.name}`);
    },
    onError: (error) =>
      message.error(
        error instanceof ApiError
          ? envelopeMessage(error.code, error.message)
          : "创建失败",
      ),
  });

  const datasourceOptions =
    datasourcesQuery.data?.data.items.map((d) => ({
      id: d.id,
      label: `${d.name}（${d.id}）`,
    })) ?? [];

  const canNext = step === 0 ? name.trim().length > 0 : true;

  const renderStep = () => {
    switch (step) {
      case 0:
        return (
          <Space direction="vertical" size={16} style={{ width: "100%", maxWidth: 520 }}>
            <div>
              <div style={{ marginBottom: 6 }}>任务名称</div>
              <Input
                value={name}
                placeholder="task-orders"
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div>
              <div style={{ marginBottom: 6 }}>任务模式</div>
              <Select
                style={{ width: "100%" }}
                value={mode}
                options={MODES}
                onChange={(v) => setMode(v)}
              />
            </div>
          </Space>
        );
      case 1:
        return (
          <SourcesEditor
            value={sources}
            datasourceOptions={datasourceOptions}
            onChange={setSources}
          />
        );
      case 2:
        return (
          <>
            {schemaQuery.isLoading && <Typography.Text>加载 schema…</Typography.Text>}
            {schemaQuery.data && (
              <SchemaForm
                schema={schemaQuery.data.data.jsonSchema}
                layout={schemaQuery.data.data.formLayout}
                value={scalars}
                onChange={(field, value) =>
                  setScalars((prev) => ({ ...prev, [field]: value }))
                }
              />
            )}
            {!schemaQuery.isLoading && !schemaQuery.data && (
              <Typography.Text type="secondary">
                schema 未提供（P0 待定），可切到 YAML 步骤直接编辑。
              </Typography.Text>
            )}
          </>
        );
      default:
        return (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <YamlEditor
              config={config}
              rawYaml={rawYaml}
              onRawYamlChange={setRawYaml}
            />
            <Space>
              <Button
                onClick={() => validateMutation.mutate()}
                loading={validateMutation.isPending}
              >
                校验
              </Button>
            </Space>
            {validation && <ValidationReport result={validation} />}
          </Space>
        );
    }
  };

  return (
    <>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        新建迁移任务
      </Typography.Title>
      <Steps
        current={step}
        size="small"
        items={STEP_ITEMS}
        style={{ marginBottom: 24 }}
      />
      {renderStep()}
      <Space style={{ marginTop: 24 }}>
        <Button disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
          上一步
        </Button>
        {step < STEP_ITEMS.length - 1 ? (
          <Button type="primary" disabled={!canNext} onClick={() => setStep((s) => s + 1)}>
            下一步
          </Button>
        ) : (
          <Button
            type="primary"
            loading={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            创建任务
          </Button>
        )}
        <Button onClick={() => navigate("/tasks")}>取消</Button>
      </Space>
    </>
  );
}
