import { App as AntApp, Alert, Button, Space, Steps, Typography } from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { stringify as toYaml } from "yaml";
import * as api from "../api/endpoints";
import { envelopeMessage } from "../api/errorMessages";
import { ApiError } from "../api/http";
import type {
  FormStep,
  TaskConfig,
  TaskMode,
  TaskWrite,
  ValidationData,
} from "../api/types";
import SchemaForm from "../components/SchemaForm";
import {
  lintTopLevelCoverage,
  setByPointer,
  type JsonSchemaNode,
} from "../components/schemaUtils";
import ValidationReport from "../components/ValidationReport";
import YamlEditor from "../components/YamlEditor";
import {
  buildTaskWrite,
  rawYamlForMode,
  type YamlMode,
} from "../components/yamlMode";

const YAML_STEP_KEY = "__yaml__";

const FALLBACK_STEP: FormStep = {
  key: "basic",
  title: "基础",
  groups: [
    { key: "meta", title: "任务元信息", fields: ["/name"] },
  ],
};

export default function TaskWizardPage() {
  const { message } = AntApp.useApp();
  const navigate = useNavigate();

  const [form, setForm] = useState<Record<string, unknown>>({
    name: "",
    taskMode: "all",
  });
  const [step, setStep] = useState(0);
  const [rawYaml, setRawYaml] = useState<string | undefined>(undefined);
  const [yamlMode, setYamlMode] = useState<YamlMode>("form");
  const [validation, setValidation] = useState<ValidationData | null>(null);

  const mode = (form.taskMode as TaskMode) ?? "all";

  const schemaQuery = useQuery({
    queryKey: ["task-schema", mode],
    queryFn: () => api.getTaskSchema(mode),
  });

  const datasourcesQuery = useQuery({
    queryKey: ["datasources"],
    queryFn: () => api.listDataSources(1, 100),
  });

  const schemaSteps = schemaQuery.data?.data.formLayout?.steps;
  const formLayout = schemaQuery.data?.data.formLayout;

  // Surface, at dev time, any jsonSchema property the layout never references:
  // it would otherwise be silently invisible in the wizard (see incident: a new
  // param missing from formLayout.steps).
  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }
    const data = schemaQuery.data?.data;
    if (!data) {
      return;
    }
    const gaps = lintTopLevelCoverage(
      data.jsonSchema as JsonSchemaNode | undefined,
      data.formLayout,
    );
    if (gaps.length > 0) {
      console.warn(
        "[dm-web] jsonSchema properties not rendered (absent from formLayout.steps/ui):",
        gaps,
      );
    }
  }, [schemaQuery.data]);

  const steps: FormStep[] = useMemo(() => {
    const base = schemaSteps && schemaSteps.length > 0 ? schemaSteps : [FALLBACK_STEP];
    return [...base, { key: YAML_STEP_KEY, title: "YAML 与校验", groups: [] }];
  }, [schemaSteps]);

  const config = useMemo<TaskConfig>(() => {
    const { name: _name, ...rest } = form;
    void _name;
    return rest as TaskConfig;
  }, [form]);

  const generatedYaml = useMemo(() => {
    try {
      return toYaml(config, { lineWidth: 0 });
    } catch {
      return "";
    }
  }, [config]);

  // The submitted body follows the view the user is looking at, so `mode` is
  // owned here rather than inside YamlEditor.
  const buildBody = (): TaskWrite =>
    buildTaskWrite(String(form.name ?? ""), yamlMode, rawYaml, config);

  // Editing a form field returns to form mode (rawYaml discarded) per ruling:
  // the submitted body follows the current mode. Any change invalidates the
  // previous validation result.
  const handleFormChange = (pointer: string, value: unknown) => {
    setForm((prev) => setByPointer(prev, pointer, value));
    if (rawYaml !== undefined) {
      setRawYaml(undefined);
    }
    setYamlMode("form");
    setValidation(null);
  };

  const handleYamlModeChange = (next: YamlMode) => {
    setRawYaml(rawYamlForMode(next, rawYaml, generatedYaml));
    setYamlMode(next);
    setValidation(null);
  };

  const handleRawYamlChange = (value: string) => {
    setRawYaml(value);
    setYamlMode("yaml");
    setValidation(null);
  };

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

  const dynamicOptions = useMemo(() => {
    const names = (arr: unknown) =>
      Array.isArray(arr)
        ? arr
            .map((row) => (row as { name?: unknown })?.name)
            .filter((n): n is string => typeof n === "string" && n.length > 0)
            .map((n) => ({ value: n, label: n }))
        : [];
    return {
      // §4.3: backend injects sourceRef candidates into ui.options; this is the
      // fallback until the schema generator emits them.
      sourceRef:
        datasourcesQuery.data?.data.items.map((d) => ({
          value: d.id,
          label: `${d.name}（${d.id}）`,
        })) ?? [],
      routeRules: names(form.routes),
      filters: names(form.filters),
    };
  }, [form.routes, form.filters, datasourcesQuery.data]);

  const current = steps[step] ?? steps[0];
  const isYamlStep = current.key === YAML_STEP_KEY;

  const renderStep = (stepDef: FormStep) => (
    <>
      {stepDef.groups.map((group) => (
        <SchemaForm
          key={group.key}
          jsonSchema={schemaQuery.data?.data.jsonSchema}
          layout={formLayout}
          group={group}
          value={form}
          dynamicOptions={dynamicOptions}
          onChange={(pointer, value) => handleFormChange(pointer, value)}
        />
      ))}
    </>
  );

  return (
    <>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        新建迁移任务
      </Typography.Title>
      <Steps
        current={step}
        size="small"
        items={steps.map((s) => ({ title: s.title }))}
        style={{ marginBottom: 24 }}
      />

      {schemaQuery.isError && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="schema 获取失败：表单仅可编辑任务名（其余字段无 schema 无法渲染）；请在「YAML 与校验」步骤编辑完整配置。"
        />
      )}

      {isYamlStep ? (
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <YamlEditor
            mode={yamlMode}
            generated={generatedYaml}
            rawYaml={rawYaml}
            onModeChange={handleYamlModeChange}
            onRawYamlChange={handleRawYamlChange}
          />
          <Button
            onClick={() => validateMutation.mutate()}
            loading={validateMutation.isPending}
          >
            校验
          </Button>
          {validation && <ValidationReport result={validation} />}
        </Space>
      ) : (
        renderStep(current)
      )}

      <Space style={{ marginTop: 24 }}>
        <Button disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
          上一步
        </Button>
        {step < steps.length - 1 ? (
          <Button type="primary" onClick={() => setStep((s) => s + 1)}>
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
