/**
 * The broker connection and extra MQTT sensors (Settings → MQTT), and the chosen outside sensor
 * of the heating curve.
 */
export const integrations = {
  section_mqtt: 'MQTT',
  group_mqtt: 'MQTT broker',
  mqttTitle: 'MQTT broker',
  mqttIntro:
    'ovenbird reads the heat pump through HeishaMon on this MQTT broker. Test new settings first: Save follows a successful test, and ovenbird goes back to the previous broker when the new one brings no HeishaMon data within 60 s.',
  mqttStatusConnected: 'Connected',
  mqttStatusDown: 'Not connected',
  mqttNow: 'Now {broker} · base {base} · {n} HeishaMon messages this session',
  mqttStatusMissing:
    'This service has no MQTT connection that can be changed here. Set the broker in the deployment.',
  mqttLocked: 'Set by the deployment ({env}). Change it there; it cannot be edited here.',
  mqttPasswordStored: 'A password is stored. Leave this empty to keep it.',
  mqttPasswordNone: 'No password is stored.',
  mqttPasswordPlaceholder: 'Optional',
  mqttPasswordDrops:
    'A new broker or port, switching TLS off or another CA file without a password drops the stored password, so it never goes to another broker.',
  mqttCaPlaceholder: "The system's certificates",
  mqttClientPlaceholder: 'Chosen by ovenbird',
  mqttMore: 'Encryption and client',
  mqttProblem_host: "Enter the broker's host name or IP address.",
  mqttProblem_port: 'A port is a whole number from 1 to 65535.',
  mqttProblem_base: 'Leave the wildcards # and + out of the base topic.',
  mqttProblem_spaces: 'Leave out spaces.',
  mqttTest: 'Test connection',
  mqttTesting: 'Testing… (up to 30 s)',
  mqttSave: 'Save connection',
  mqttSaving: 'Saving…',
  mqttSaveBlock_commands:
    'Commands to the pump are on, so the broker cannot be changed here: change it in the deployment and restart.',
  mqttSaveBlock_applying: 'The last change is still being checked.',
  mqttSaveBlock_locked: 'The deployment sets the broker; it cannot be changed here.',
  mqttSaveBlock_unchanged: 'Change a setting first. Testing what runs now is always possible.',
  mqttSaveBlock_untested: 'Test these settings first; you can save them after a successful test.',
  mqttSaveBlock_failed: 'The test of these settings failed. Fix them and test again.',
  mqttSaveBlock_changed: 'The settings changed since the test. Test again to save them.',
  mqttVerdict_ok: 'The broker works and HeishaMon data arrives',
  mqttVerdict_no_heishamon: 'Connected, but no HeishaMon data under this base',
  mqttVerdict_failed: 'No working connection',
  mqttTest_invalid: 'These settings are not valid.',
  mqttTest_unreachable: 'The broker cannot be reached at this address and port.',
  mqttTest_tls: 'The encrypted connection failed. Check TLS, the port and the CA certificate.',
  mqttTest_auth_failed: 'The broker rejected the user name or password.',
  mqttTest_refused: 'The broker refused the connection.',
  mqttTest_timeout: 'The broker did not answer in time.',
  mqttTest_no_heishamon:
    "No HeishaMon value arrived under this base topic. Compare it with the base in HeishaMon's MQTT settings.",
  mqttResultBroker: 'Broker',
  mqttResultConnected: 'Connected',
  mqttResultHeishamon: 'HeishaMon data',
  mqttResultTopic: 'First value on',
  mqttRefused_test_required:
    'Test exactly these settings successfully first. A test counts for 10 minutes.',
  mqttRefused_commands_enabled:
    'Commands to the pump are on, so the broker cannot be changed here: change it in the deployment and restart.',
  mqttRefused_apply_pending: 'The last broker change is still being checked. Wait for its outcome.',
  mqttApplying:
    'Switching to the new broker… ovenbird waits up to 60 s for HeishaMon data and otherwise goes back to the previous broker.',
  mqttApplied: 'Applied at {time}: connected, and HeishaMon data arrives.',
  mqttReverted:
    'Reverted at {time}: the new broker brought no HeishaMon data in time, so ovenbird is back on the previous broker.',
  mqttRevertFailed:
    'At {time} the new broker brought no HeishaMon data and going back to the previous broker failed. Set a working broker here or in the deployment.',
  mqttCommandsNotice:
    'Commands to the pump are on. The command link keeps the broker it started with, so the broker cannot be changed here. Testing still works.',
  overviewMqttInputs: 'Extra MQTT sensors: {n}',
  mqttInputsTitle: 'Extra MQTT sensors',
  mqttInputsIntro:
    'Topics ovenbird reads as sensors. After you apply them they appear in the sensor lists, for example as the outside sensor of the heating curve.',
  mqttInputTopic: 'Topic',
  mqttInputSignal: 'Signal name',
  mqttInputUnit: 'Unit',
  mqttInputMin: 'Minimum',
  mqttInputMax: 'Maximum',
  mqttInputAdd: 'Add MQTT sensor',
  mqttInputRemove: 'Remove {topic}',
  mqttInputNone: 'No extra MQTT sensors yet.',
  mqttInputSignalHint: 'Appears as {signal}',
  mqttInputRow: 'MQTT sensor {n}',
  mqttInputRangeHint: 'Values outside minimum and maximum are ignored.',
  check_mqtt_topic_missing: 'Every MQTT sensor needs a topic.',
  check_mqtt_topic_wildcard: 'A topic cannot contain the wildcards # or +.',
  check_mqtt_topic_duplicate: 'Each topic can be listed once.',
  check_mqtt_range: 'The minimum must not be above the maximum.',
  check_mqtt_topic_too_long: 'A topic can be at most 256 characters long.',
  check_mqtt_topic_reserved:
    'This topic belongs to the HeishaMon board itself (main, commands, stats, LWT); it cannot be an extra sensor.',
  check_mqtt_signal_too_long: 'A signal name can be at most 256 characters long.',
  check_mqtt_signal_reserved:
    'This signal name is reserved for the heat pump, Home Assistant or ovenbird itself (main/, ha/, commands/, derived/, stats, LWT).',
  check_mqtt_signal_duplicate: 'Each signal name can be used once.',
  check_mqtt_inputs_invalid: 'Fix the marked MQTT sensors first.',
  check_not_mqtt_inputs: 'MQTT sensors must be a list of topics.',
  check_ca_file_missing: 'The CA certificate file does not exist on the ovenbird server.',
  curveOutsideTitle: 'Outside temperature',
  curveOutsideOnly:
    "Only the heating curve uses this sensor. The safety envelope and the safety monitors keep the pump's own sensor.",
  curveOutsidePump: "No sensor chosen: the curve uses the pump's own outside sensor.",
  curveOutsideFallback:
    "The chosen sensor has no fresh, plausible value, so the curve uses the pump's sensor now.",
  curveOutsideUsing: 'The curve uses {name} now.',
  fact_outside_source: 'The curve uses the outside temperature of {name} ({raw} °C).',
  fact_outside_fallback:
    "The outside sensor {name} {why}, so the curve uses the pump's sensor ({raw} °C).",
  outsideWhy_stale: 'is {min} min old',
  outsideWhy_missing: 'has no value',
  outsideWhy_implausible: 'reads an implausible value',
  outsideWhy_deviates: "is too far from the pump's own sensor",
  outsideWhy_unknown: 'is not fresh',
  stateOutsideFrom: 'from {name}',
  stateOutsideFallback: "pump's sensor (fallback)",
};
