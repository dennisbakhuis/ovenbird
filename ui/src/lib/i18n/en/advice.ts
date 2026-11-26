export const advice = {
  alarmNow_mode_mismatch:
    'Sends nothing until the pump is back in Direct mode and heating; the pump keeps its current setpoint.',
  alarmYou_mode_mismatch:
    'Check on the Panasonic remote that the pump heats and its water temperature is set to Direct, not to the curve.',
  alarmNow_verification_failed:
    'Holds its commands for a while; the pump keeps the value it reports. A pump setting of yours that failed does not stop control.',
  alarmYou_verification_failed:
    'Check that HeishaMon is online and the pump is on. If it was a setting you changed, your pump model may not support it.',
  alarmNow_write_budget:
    'Sends nothing more today except safety corrections; the pump keeps its last values. The budget starts again at midnight UTC.',
  alarmYou_write_budget:
    'Nothing urgent. If it happens often, look in Activity → Commands for a value that keeps changing.',
  alarmNow_foreign_writer:
    'Holds its writes for the hold time, 1 hour at first; the pump keeps the value the other writer set.',
  alarmYou_foreign_writer:
    'Find out who changed the pump (remote, Node-RED, an app) and stop it. Then wait, or release the hold in Activity → Holds.',
  alarmNow_hold_latched:
    'Sends nothing until an administrator releases the hold; the pump keeps its current values.',
  alarmYou_hold_latched:
    'Find out what keeps changing the pump and stop it, then release the hold in Activity → Holds.',
  alarmNow_heishamon_restarted:
    'Sends its own values again; values changed by the restart do not count as someone else writing.',
  alarmYou_heishamon_restarted:
    'Nothing to do. If HeishaMon restarts often, check its power supply and WiFi.',
  alarmNow_correction_failed:
    'Could not bring the setpoint back under the maximum; it tries again later and meanwhile releases only lower values.',
  alarmYou_correction_failed:
    'Set a lower water temperature on the remote, find out what keeps raising it and stop it. Call your installer if unsure.',
  alarmNow_setpoint_above_max:
    'Sends its own safe setpoint right away to bring the pump back under the maximum, at most 3 times an hour.',
  alarmYou_setpoint_above_max:
    'Find out who set the high value (remote, Node-RED, an app) and stop it.',
  alarmNow_outlet_overshoot:
    'Releases only lower water temperatures until the water leaving the pump has cooled down.',
  alarmYou_outlet_overshoot:
    'Check the remote for an error code and that floor and radiator valves are open. If it stays, call your installer.',
  alarmNow_low_flow:
    'Releases only lower water temperatures until the flow is back above the minimum.',
  alarmYou_low_flow:
    'Open closed radiator or floor valves, check the water pressure and the filter. If it stays, call your installer.',
  alarmNow_low_flow_defrost:
    'Nothing to correct: the pump runs its own defrost and ovenbird never writes during a defrost. The normal low-flow protection resumes when the defrost ends.',
  alarmYou_low_flow_defrost:
    'If the message names deice mode 2, the pump stops its water pump by design (return water below 27 °C) and the defrost lasts longer than a normal one; if that happens often, a slightly higher minimum water temperature in frosty weather avoids it. Otherwise the pump should keep running: have the water pump, flow sensor and filter checked. Settings → Comfort temperature → Monitors → “No flow during defrost” decides whether this is an alarm or only logged.',
  alarmNow_pump_error: 'Releases only lower water temperatures while the pump reports an error.',
  alarmYou_pump_error:
    'Read the error code on the Panasonic remote and look it up in the manual, or call your installer.',
  alarmNow_backup_heater:
    'Nothing changes: it keeps controlling as usual. The electric backup heater uses a lot of electricity.',
  alarmYou_backup_heater:
    'Check why it runs: very cold weather, a defrost problem or its setting on the remote. Ask your installer if unsure.',
  alarmNow_backup_heater_allowed:
    'Nothing changes; it only tells you the pump may switch on its electric backup heater.',
  alarmYou_backup_heater_allowed:
    'Nothing to do. If you never want the backup heater, ask your installer whether it can be blocked.',
  alarmNow_heating_off_outdoor:
    'Keeps deciding and sending, but the pump itself does not heat above this outdoor temperature.',
  alarmYou_heating_off_outdoor:
    'Nothing to do in mild weather. If the house gets cold, raise Heating off above outdoor temperature on the Pump page.',
  alarmNow_defrost_stuck:
    'As in every defrost: room correction is frozen and the setpoint is not lowered until the defrost ends.',
  alarmYou_defrost_stuck:
    'Look at the outdoor unit for ice, snow or a blocked fan. If it keeps happening, call your installer.',
  alarmNow_room_below_floor:
    'Room correction, if on, keeps raising the water temperature within its limit; the alarm itself changes nothing.',
  alarmYou_room_below_floor:
    'Check for open windows or closed valves. If the house is cold in all weather, raise the heating curve.',
  alarmNow_room_sensor_silent:
    'Room correction is paused: it runs on the heating curve, and a warming correction fades out over 24 hours.',
  alarmYou_room_sensor_silent:
    'Check the room sensor’s battery and its connection in Home Assistant.',
  alarmNow_room_sensor_quiet:
    'No longer lets the room lower the water temperature; cooling learned since the sensor went quiet is undone.',
  alarmYou_room_sensor_quiet:
    'Check the sensor’s battery and connection. The alarm clears on its next report.',
  alarmNow_room_report_overdue:
    'Room correction pauses once the value is too old: it runs on the heating curve until the sensor reports again.',
  alarmYou_room_report_overdue:
    'Check the sensor’s battery and connection. If it only reports on change, set Sensor type to On change.',
  alarmNow_room_implausible:
    'Room correction is paused: it runs on the heating curve until the room sensor and the cross-check sensor agree again.',
  alarmYou_room_implausible:
    'Compare both sensors and move or replace the wrong one, or remove the Cross-check sensor in Settings.',
  alarmNow_ha_link_down:
    'Keeps controlling; room values from Home Assistant are trusted for a shorter time, then it runs on the heating curve.',
  alarmYou_ha_link_down:
    'Check that Home Assistant is running and that the address and token ovenbird uses still work.',
  alarmNow_config_reset:
    'Runs in Shadow on the installation defaults: it decides every minute but sends nothing.',
  alarmYou_config_reset:
    'Check the settings, use Import from file… in Versions and backup if you have an export, then click Acknowledge.',
  alarmNow_pump_setting_changed:
    'Nothing changes; it notes that a pump setting changed without ovenbird. The alarm clears after 24 hours.',
  alarmYou_pump_setting_changed:
    'Nothing to do if you changed it on the remote. If not, find out who did.',
  alarmNow_envelope_mismatch:
    "Keeps the value the safety rule wrote instead of treating it as someone else's change, and keeps its next values inside the rule's band. The alarm clears when its own value is inside the band again.",
  alarmYou_envelope_mismatch:
    'Usually nothing. If it comes back, check that the envelope settings in ovenbird match the rule on the HeishaMon.',
  alarmNow_notify_failing:
    'Keeps every alarm on screen and tries to send the waiting messages again; this alarm itself is not sent.',
  alarmYou_notify_failing:
    'Check the ntfy server, the topic and the internet connection, then use Send test on System.',
  alarmNow_release_interrupted:
    'Stays paused and sends nothing; the pump keeps the values it has now.',
  alarmYou_release_interrupted:
    'Open Trial, check which values are back, and use Release control now again, or set the rest by hand.',
  alarmNow_stove_reference_missing:
    'Keeps only part of the back-off until the reference room reports again, so the rest of the house cools less.',
  alarmYou_stove_reference_missing:
    'Check the reference room sensor (battery, Home Assistant), or pick another one under Wood stove.',
  alarmNow_archive_failing:
    'Keeps controlling and recording. Retention waits up to 3 days for the archive, then removes old history even if it is not archived.',
  alarmYou_archive_failing:
    'Check the free space of the data directory and the archive error under System → Data. The alarm clears at the next successful copy.',
  alarmNow_archive_rebuilt:
    'Moved the damaged working copy aside (.corrupt file in the archive folder) and rebuilt the month from the history it still keeps. The alarm clears after 24 hours.',
  alarmYou_archive_rebuilt:
    'Nothing to do. Days the history no longer held are missing from that month; keep the .corrupt file if you want to try to recover them.',
  alarmNow_room_unit_refused:
    'Room correction is off: without a unit the value cannot be read safely, so it runs on the heating curve.',
  alarmYou_room_unit_refused:
    'Give the sensor a temperature unit in Home Assistant (°C or °F), or set Home Assistant to the metric unit system.',
  alarmNow_outside_sensor_stale:
    "Keeps controlling; the heating curve uses the pump's own outside sensor until the chosen sensor reports again.",
  alarmYou_outside_sensor_stale:
    'Check the outside sensor (battery, Home Assistant or MQTT), or choose another one under Heating curve.',
  alarmNow_mqtt_revert_failed:
    'Stays on the new broker, which delivers no pump data: control falls back as with any lost pump data.',
  alarmYou_mqtt_revert_failed:
    'Set a working broker under MQTT (test, then save) or in the deployment and restart.',
  alarmNow_outside_sensor_implausible:
    "Keeps controlling; the heating curve uses the pump's own outside sensor until the chosen sensor reads a plausible value again.",
  alarmYou_outside_sensor_implausible:
    'Check where the outside sensor hangs (direct sun, a warm wall) and what it reports, or adjust its limits under Heating curve.',
  alarmNow_mqtt_connection_reverted: 'Keeps running on the previous broker, as before the change.',
  alarmYou_mqtt_connection_reverted:
    "Check the new broker's address, port, user name and HeishaMon base, test it again under MQTT and save it once the test finds HeishaMon data.",
};
