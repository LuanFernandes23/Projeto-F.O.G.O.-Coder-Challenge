import { describe, expect, it } from "vitest";

import { defaultAttributes, resolveFields, type JsonSchema } from "./SchemaFields";
import { fieldErrors } from "./form-errors";
import { ApiError } from "@/lib/api/client";

// Recorte real do schema gerado pelo Pydantic para o tipo "radar".
const radar: JsonSchema = {
  $defs: {
    RadarSubtype: {
      enum: ["velocidade", "avanco_semaforo"],
      type: "string",
      "x-enum-labels": { velocidade: "Velocidade", avanco_semaforo: "Avanço de semáforo" },
    },
  },
  properties: {
    enforcement_types: {
      items: { $ref: "#/$defs/RadarSubtype" },
      minItems: 1,
      title: "O que fiscaliza",
      type: "array",
    },
    max_speed_kmh: {
      anyOf: [{ maximum: 140, minimum: 10, type: "integer" }, { type: "null" }],
      default: null,
      title: "Velocidade máxima (km/h)",
    },
    monitored_lanes: {
      default: 1,
      maximum: 8,
      minimum: 1,
      title: "Faixas monitoradas",
      type: "integer",
    },
    plate_recognition: {
      default: false,
      title: "Leitura automática de placas (OCR)",
      type: "boolean",
    },
  },
  required: ["enforcement_types"],
};

describe("resolveFields", () => {
  it("normaliza $ref, anyOf com null, limites e rótulos dos enums", () => {
    const fields = Object.fromEntries(resolveFields(radar).map((f) => [f.name, f]));
    expect(fields.enforcement_types).toMatchObject({ kind: "multi-enum", required: true });
    expect(fields.enforcement_types?.options[1]).toEqual({
      value: "avanco_semaforo",
      label: "Avanço de semáforo",
    });
    expect(fields.max_speed_kmh).toMatchObject({
      kind: "integer",
      nullable: true,
      min: 10,
      max: 140,
      required: false,
    });
    expect(fields.plate_recognition?.kind).toBe("boolean");
  });

  it("gera valores iniciais a partir dos defaults", () => {
    expect(defaultAttributes(radar)).toEqual({
      enforcement_types: [],
      monitored_lanes: 1,
      plate_recognition: false,
    });
  });
});

describe("fieldErrors", () => {
  it("mapeia erros da API (problem+json) para o nome do campo", () => {
    const error = new ApiError(422, {
      detail: "Dados inválidos",
      errors: [
        { field: "address.cep", message: "Value error, CEP deve conter 8 dígitos." },
        { field: "max_speed_kmh", message: "Input should be greater than or equal to 10" },
      ],
    });
    expect(fieldErrors(error)).toEqual({
      cep: "CEP deve conter 8 dígitos.",
      max_speed_kmh: "Input should be greater than or equal to 10",
    });
  });
});
