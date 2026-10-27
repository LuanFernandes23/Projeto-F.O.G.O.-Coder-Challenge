// Atalhos para os contratos gerados do OpenAPI (fonte única de verdade: a API).
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Overview = Schemas["OverviewOutput"];
export type MapFeatures = Schemas["MapFeaturesOutput"];
export type MapEquipment = Schemas["MapEquipmentOutput"];
export type MapAgent = Schemas["MapAgentOutput"];
export type RegionHealth = Schemas["RegionHealthOutput"];
export type Region = Schemas["RegionOutput"];
export type HeatPoint = Schemas["HeatPointOutput"];
export type TrendPoint = Schemas["TrendPointOutput"];
export type Alert = Schemas["AlertOutput"];
export type Dispatch = Schemas["DispatchOutput"];
export type DispatchSuggestion = Schemas["DispatchSuggestionOutput"];
export type Equipment = Schemas["EquipmentOutput"];
export type EquipmentCreate = Schemas["EquipmentCreate"];
export type EquipmentUpdate = Schemas["EquipmentUpdate"];
export type EquipmentType = Schemas["EquipmentTypeOutput"];
export type StatusChange = Schemas["StatusChangeOutput"];
export type StatusOption = Schemas["StatusOption"];
export type MaintenanceOrder = Schemas["MaintenanceOrderOutput"];
export type Organization = Schemas["OrganizationOutput"];
export type OrganizationListItem = Schemas["OrganizationListItemOutput"];
export type OrganizationCreate = Schemas["OrganizationCreate"];
export type OrganizationUpdate = Schemas["OrganizationUpdate"];
export type OrganizationKind = Schemas["OrganizationKind"];
export type Agent = Schemas["AgentOutput"];
export type AgentCreate = Schemas["AgentCreate"];
export type AgentUpdate = Schemas["AgentUpdate"];
export type CurrentUser = Schemas["CurrentUserOutput"];
export type User = Schemas["UserOutput"];
export type UserCreate = Schemas["UserCreate"];
export type UserUpdate = Schemas["UserUpdate"];
export type UserRole = Schemas["Role"];

// Parte 3 — PROMETHEUS, base de conhecimento e IA do usuário
export type Decision = Schemas["DecisionOutput"];
export type DecisionStatus = Schemas["DecisionStatus"];
export type PrometheusStats = Schemas["PrometheusStatsOutput"];
export type PrometheusSettings = Schemas["PrometheusSettingsOutput"];
export type PrometheusSettingsInput = Schemas["PrometheusSettingsInput"];
export type PrometheusMode = Schemas["PrometheusMode"];
export type Policy = Schemas["PolicyOutput"];
export type ActionType = Schemas["ActionType"];
export type RiskClass = Schemas["RiskClass"];
export type SituationKind = Schemas["SituationKind"];
export type KnowledgeDocument = Schemas["KnowledgeDocumentOutput"];
export type KnowledgeDocumentDetail = Schemas["KnowledgeDocumentDetail"];
export type KnowledgeDocumentInput = Schemas["KnowledgeDocumentInput"];
export type KnowledgeHit = Schemas["KnowledgeHitOutput"];
export type AiSettings = Schemas["AiSettingsOutput"];
export type AiSettingsInput = Schemas["AiSettingsInput"];
export type AiCandidateInput = Schemas["AiCandidateInput"];
export type AiTest = Schemas["AiTestOutput"];
export type AiUsage = Schemas["AiUsageOutput"];
export type AiSave = Schemas["AiSaveOutput"];
export type AiProvider = Schemas["AiProvider"];
export type CepLookup = Schemas["CepLookupOutput"];
export type Address = Schemas["AddressSchema"];

export type EquipmentStatus = Schemas["EquipmentStatus"];
export type DutyStatus = Schemas["DutyStatus"];
export type AlertSeverity = Schemas["AlertSeverity"];
export type AlertStatus = Schemas["AlertStatus"];
export type MaintenanceNeed = Schemas["MaintenanceNeed"];
export type Connectivity = Schemas["Connectivity"];
export type HealthLevel = Schemas["HealthLevel"];
export type DispatchStatus = Schemas["DispatchStatus"];
export type AgentRole = Schemas["AgentRole"];
export type Permission = Schemas["Permission"];

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
