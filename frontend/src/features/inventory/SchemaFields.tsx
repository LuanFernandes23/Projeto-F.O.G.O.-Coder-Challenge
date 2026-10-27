// Formulário dinâmico gerado a partir do JSON Schema das características de cada tipo.
// O backend é a fonte da verdade: títulos, limites, opções e rótulos vêm do schema.
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox, Select, Switch } from "@/components/ui/controls";
import { Input, Label } from "@/components/ui/primitives";

export interface JsonSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  $ref?: string;
  items?: JsonSchemaProperty;
  anyOf?: JsonSchemaProperty[];
  "x-enum-labels"?: Record<string, string>;
}

export interface JsonSchema {
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  additionalProperties?: boolean | object;
  $defs?: Record<string, JsonSchemaProperty>;
}

export type FieldKind = "enum" | "multi-enum" | "boolean" | "number" | "integer" | "text";

export interface ResolvedField {
  name: string;
  kind: FieldKind;
  title: string;
  description?: string;
  required: boolean;
  nullable: boolean;
  options: { value: string; label: string }[];
  min?: number;
  max?: number;
  maxLength?: number;
  defaultValue?: unknown;
}

function deref(
  schema: JsonSchema,
  prop: JsonSchemaProperty | undefined,
): JsonSchemaProperty | undefined {
  if (!prop?.$ref) return prop;
  return schema.$defs?.[prop.$ref.split("/").pop() ?? ""];
}

/** Normaliza o schema do Pydantic (``$ref``, ``anyOf`` com null) em campos simples. */
export function resolveFields(schema: JsonSchema): ResolvedField[] {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(([name, raw]) => {
    const nonNull = raw.anyOf?.find((option) => option.type !== "null") ?? raw;
    const nullable = Boolean(raw.anyOf?.some((option) => option.type === "null"));
    const prop = deref(schema, nonNull) ?? nonNull;
    const items = deref(schema, prop.items);
    const enumSource = items?.enum ? items : prop;
    const labels = enumSource["x-enum-labels"] ?? {};
    const options = (enumSource.enum ?? []).map((value) => ({
      value,
      label: labels[value] ?? value,
    }));
    let kind: FieldKind = "text";
    if (prop.type === "array" && items?.enum) kind = "multi-enum";
    else if (prop.enum) kind = "enum";
    else if (prop.type === "boolean") kind = "boolean";
    else if (prop.type === "integer") kind = "integer";
    else if (prop.type === "number") kind = "number";
    return {
      name,
      kind,
      title: raw.title ?? prop.title ?? name,
      description: raw.description ?? prop.description,
      required: required.has(name),
      nullable,
      options,
      min: prop.minimum ?? prop.exclusiveMinimum,
      max: prop.maximum,
      maxLength: prop.maxLength,
      defaultValue: raw.default,
    };
  });
}

export function defaultAttributes(schema: JsonSchema): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  resolveFields(schema).forEach((field) => {
    if (field.defaultValue !== undefined && field.defaultValue !== null)
      values[field.name] = field.defaultValue;
    else if (field.kind === "boolean") values[field.name] = false;
    else if (field.kind === "multi-enum") values[field.name] = [];
  });
  return values;
}

type Values = Record<string, unknown>;

export function SchemaFields({
  schema,
  values,
  onChange,
  errors,
}: {
  schema: JsonSchema;
  values: Values;
  onChange: (values: Values) => void;
  errors: Record<string, string>;
}) {
  const fields = resolveFields(schema);
  const free =
    schema.additionalProperties === true ||
    (fields.length === 0 && schema.additionalProperties !== false);
  const set = (name: string, value: unknown) => onChange({ ...values, [name]: value });

  if (free) return <FreeAttributes values={values} onChange={onChange} />;

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {fields.map((field) => {
        const id = `attr-${field.name}`;
        const error = errors[field.name];
        const label = (
          <Label htmlFor={id}>
            {field.title}
            {field.required && <span className="text-destructive"> *</span>}
          </Label>
        );
        const hint = error ? (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        ) : field.description ? (
          <p className="text-[11px] text-muted-foreground">{field.description}</p>
        ) : null;

        if (field.kind === "boolean") {
          return (
            <div
              key={field.name}
              className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
            >
              <div className="space-y-0.5">
                {label}
                {hint}
              </div>
              <Switch
                id={id}
                checked={Boolean(values[field.name])}
                onCheckedChange={(v) => set(field.name, v)}
              />
            </div>
          );
        }
        if (field.kind === "multi-enum") {
          const selected = (values[field.name] as string[] | undefined) ?? [];
          return (
            <fieldset key={field.name} className="space-y-2 sm:col-span-2">
              <legend className="text-xs font-medium text-muted-foreground">
                {field.title}
                {field.required && <span className="text-destructive"> *</span>}
              </legend>
              <div className="flex flex-wrap gap-x-4 gap-y-2">
                {field.options.map((option) => (
                  <label key={option.value} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={selected.includes(option.value)}
                      onCheckedChange={(checked) =>
                        set(
                          field.name,
                          checked
                            ? [...selected, option.value]
                            : selected.filter((v) => v !== option.value),
                        )
                      }
                    />
                    {option.label}
                  </label>
                ))}
              </div>
              {hint}
            </fieldset>
          );
        }
        if (field.kind === "enum") {
          return (
            <div key={field.name} className="space-y-1.5">
              {label}
              <Select
                id={id}
                value={(values[field.name] as string | undefined) ?? ""}
                onValueChange={(v) => set(field.name, v || undefined)}
                options={field.options}
                allowEmpty={!field.required}
                emptyLabel="Não informado"
                invalid={Boolean(error)}
              />
              {hint}
            </div>
          );
        }
        const numeric = field.kind === "integer" || field.kind === "number";
        return (
          <div key={field.name} className="space-y-1.5">
            {label}
            <Input
              id={id}
              type={numeric ? "number" : "text"}
              inputMode={numeric ? "decimal" : undefined}
              step={field.kind === "integer" ? 1 : "any"}
              min={field.min}
              max={field.max}
              maxLength={field.maxLength}
              aria-invalid={Boolean(error)}
              value={
                values[field.name] === undefined || values[field.name] === null
                  ? ""
                  : String(values[field.name])
              }
              onChange={(e) => {
                const raw = e.target.value;
                if (!numeric) set(field.name, raw || undefined);
                else set(field.name, raw === "" ? undefined : Number(raw));
              }}
            />
            {hint}
          </div>
        );
      })}
    </div>
  );
}

function FreeAttributes({
  values,
  onChange,
}: {
  values: Values;
  onChange: (values: Values) => void;
}) {
  const entries = Object.entries(values);
  const update = (index: number, key: string, value: string) => {
    const next = entries.map(([k, v], i) => (i === index ? [key, value] : [k, v]));
    onChange(Object.fromEntries(next));
  };
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Este tipo aceita características livres (nome e valor), até 30 itens.
      </p>
      {entries.map(([key, value], index) => (
        <div key={index} className="flex gap-2">
          <Input
            aria-label="Nome da característica"
            value={key}
            onChange={(e) => update(index, e.target.value, String(value ?? ""))}
          />
          <Input
            aria-label="Valor"
            value={String(value ?? "")}
            onChange={(e) => update(index, key, e.target.value)}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Remover característica"
            onClick={() => onChange(Object.fromEntries(entries.filter((_, i) => i !== index)))}
          >
            <Trash2 />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={entries.length >= 30}
        onClick={() => onChange({ ...values, [`caracteristica_${entries.length + 1}`]: "" })}
      >
        <Plus /> Adicionar característica
      </Button>
    </div>
  );
}
