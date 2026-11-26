"""Pure domain logic for the ovenbird heat pump controller."""

from ovenbird_core.catalogue import CATALOGUE, HeishaSignal, TopicSpec, ValueKind
from ovenbird_core.control import (
    ControlInputs,
    Controller,
    DecisionRecord,
    OvenbirdConfig,
    OvenbirdController,
    StepResult,
)
from ovenbird_core.derived import (
    Derived,
    compressor_running,
    defrost_active,
    dhw_active,
    heat_delivered_w,
    heat_power_w,
)
from ovenbird_core.heishamon import (
    DEFAULT_BASE,
    Heartbeat,
    HeishaMonParser,
    LwtNotice,
    MqttMessage,
    ParseResult,
)
from ovenbird_core.inputs import InputRouter, MqttSignal, ha_reading, ha_signal
from ovenbird_core.instant import Instant
from ovenbird_core.pumpsettings import (
    PUMP_SETTINGS,
    PumpSetting,
    PumpSettingSpec,
    pump_setting_spec,
)
from ovenbird_core.readings import (
    Ignored,
    ParseError,
    ParseErrorKind,
    Reading,
    SignalId,
    SourceKind,
    Value,
)
from ovenbird_core.store import (
    HeishaMonStatus,
    SignalView,
    Snapshot,
    StalenessPolicy,
    StateStore,
)

__version__ = "0.4.1"

__all__ = [
    "CATALOGUE",
    "DEFAULT_BASE",
    "PUMP_SETTINGS",
    "ControlInputs",
    "Controller",
    "DecisionRecord",
    "Derived",
    "Heartbeat",
    "HeishaMonParser",
    "HeishaMonStatus",
    "HeishaSignal",
    "Ignored",
    "InputRouter",
    "Instant",
    "LwtNotice",
    "MqttMessage",
    "MqttSignal",
    "OvenbirdConfig",
    "OvenbirdController",
    "ParseError",
    "ParseErrorKind",
    "ParseResult",
    "PumpSetting",
    "PumpSettingSpec",
    "Reading",
    "SignalId",
    "SignalView",
    "Snapshot",
    "SourceKind",
    "StalenessPolicy",
    "StateStore",
    "StepResult",
    "TopicSpec",
    "Value",
    "ValueKind",
    "__version__",
    "compressor_running",
    "defrost_active",
    "dhw_active",
    "ha_reading",
    "ha_signal",
    "heat_delivered_w",
    "heat_power_w",
    "pump_setting_spec",
]
