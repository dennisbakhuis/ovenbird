import type { components } from './api-types.gen';

export type Schemas = components['schemas'];

export const SUPPORTED_API_VERSION = 1;

export type Health = Schemas['Health'];
export type Signal = Schemas['Signal'];
export type Derived = Schemas['Derived'];
export type Snapshot = Schemas['Snapshot'];
export type HistorySeries = Schemas['HistorySeries'];
export type HistoryPoint = HistorySeries['points'][number];
export type History = Schemas['History'];
export type Mode = Schemas['ModeName'];
export type Term = Schemas['Term'];
export type InputRef = Schemas['InputRef'];
export type DecisionRecord = Schemas['DecisionRecord'];
export type ArbiterEntry = Schemas['ArbiterEntry'];
export type CommandEvent = Schemas['CommandEvent'];
export type CommandLogEntry = Schemas['CommandLogEntry'];
export type Decision = Schemas['Decision'];
export type Severity = Schemas['SeverityName'];
export type Alarm = Schemas['Alarm'];
export type Monitor = Schemas['Monitor'];
export type Budget = Schemas['Budget'];
export type AdapterStatus = Schemas['AdapterStatus'];
export type RoomStatus = Schemas['RoomStatus'];
export type StoveRequest = Schemas['StoveRequest'];
export type StoveStatus = Schemas['StoveStatus'];
export type ControlStatus = Schemas['ControlStatus'];
export type DecisionsLatest = Schemas['DecisionsLatest'];
export type DecisionsResponse = Schemas['DecisionsPage'];
export type CommandsResponse = Schemas['CommandsPage'];
export type AlarmEvent = Schemas['AlarmEvent'];
export type AlarmsResponse = Schemas['AlarmsPage'];
export type ServerMessage = Schemas['ServerMessage'];
export type StoveResult = Schemas['StoveResult'];
export type DecisionSeries = Schemas['DecisionSeries'];
export type AuditEvent = Schemas['AuditEvent'];
export type AuditResponse = Schemas['AuditPage'];
export type ModeChange = Schemas['ModeChange'];
export type ReleaseResult = Schemas['ReleaseHoldResult'];

export type CheckState =
  'connected' | 'disconnected' | 'alive' | 'dead' | 'disabled' | 'ok' | 'error';

export type StateValue = number | string | boolean | null;

export type ConfigMode = Schemas['ConfigMode'];
export type ConfigField = Schemas['ConfigField'];
export type ConfigDoc = Schemas['ConfigDoc'];
export type FieldType = Schemas['FieldTypeName'];
export type Tier = Schemas['TierName'];
export type FieldDef = Schemas['FieldDef'];
export type SchemaGroup = Schemas['SchemaGroup'];
export type ConfigSchema = Schemas['ConfigSchema'];
export type ValidationIssue = Schemas['ValidationIssue'];
export type ValidateResult = Schemas['ValidateResult'];
export type PreviewSummary = Schemas['OpenLoopSummary'];
export type OpenLoopRun = Schemas['OpenLoopRun'];
export type PreviewNow = Schemas['PreviewNow'];
export type PreviewResult = Schemas['PreviewResult'];
export type ApplyResult = Schemas['ApplyResult'];
export type VersionChange = Schemas['VersionChange'];
export type ConfigVersion = Schemas['ConfigVersion'];
export type SignalCandidate = Schemas['SignalCandidate'];
export type ConfigSignals = Schemas['ConfigSignals'];
export type ConfigExport = Schemas['ConfigExport'];
export type ResetAckResult = Schemas['ResetAckResult'];
export type HaConnectionResult = Schemas['HaConnectionResult'];
export type HaEntityCheck = Schemas['HaEntityCheck'];
export type HaTestErrorCode = Schemas['HaTestErrorCode'];
export type HaTestResult = Schemas['HaTestResult'];
export type MqttStatus = Schemas['MqttStatus'];
export type MqttApplyState = Schemas['MqttApplyState'];
export type MqttTestErrorCode = Schemas['MqttTestErrorCode'];
export type MqttTestResult = Schemas['MqttTestResult'];
export type MqttConnectionResult = Schemas['MqttConnectionResult'];

export type WeatherPoint = Schemas['WeatherPoint'];
export type ForecastPoint = Schemas['ForecastPoint'];
export type WeatherLocation = Schemas['WeatherLocation'];
export type WeatherOff = Schemas['WeatherOff'];
export type WeatherOn = Schemas['WeatherOn'];
export type WeatherResponse = Schemas['WeatherReport'];

export type PumpWrite = Schemas['PumpWrite'];
export type PumpSetting = Schemas['PumpSetting'];
export type PumpSettingsResponse = Schemas['PumpSettingsPage'];
export type HistorySignals = Schemas['HistorySignals'];
export type StoredSignal = Schemas['StoredSignal'];
export type SignalRange = Schemas['SignalRange'];
export type HistoryStorage = Schemas['HistoryStorage'];
export type StorageResolution = Schemas['StorageResolution'];
export type Compaction = Schemas['Compaction'];
export type CompactResult = Schemas['CompactResult'];
export type RetentionPreset = Schemas['RetentionPreset'];
export type ArchiveStatus = Schemas['ArchiveStatus'];
export type ArchiveMonth = Schemas['ArchiveMonth'];
export type ArchiveGroup = Schemas['ArchiveGroup'];
export type ArchiveRun = Schemas['ArchiveRun'];
export type ArchiveDeleteResult = Schemas['ArchiveDeleteResult'];
export type PumpWriteResult = Schemas['PumpWriteResult'];

export type PumpRefusalCode =
  | 'unknown_setting'
  | 'bad_comment'
  | 'not_an_integer'
  | 'out_of_range'
  | 'expect_required'
  | 'not_publishing'
  | 'hold'
  | 'defrost'
  | 'dhw'
  | 'state_unknown'
  | 'not_fresh'
  | 'value_changed'
  | 'unchanged'
  | 'in_flight'
  | 'rate_limited'
  | 'day_limit'
  | 'write_budget';

/**
 * Body of a structured refusal: `{"detail": {code, message, params}}`.
 */
export interface ErrorDetail<C extends string = string> {
  code: C;
  message: string;
  params: Record<string, unknown>;
}
