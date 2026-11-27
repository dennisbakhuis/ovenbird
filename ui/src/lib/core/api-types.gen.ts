// Generated from docs/openapi.json by `npm run api-types`; do not edit.
// The Python response models are the source: run `make api-schema` first.

export interface paths {
  '/api/v1/alarms': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Alarms */
    get: operations['alarms_api_v1_alarms_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/archive': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Archive Status
     * @description ``GET archive``: whether the archive runs, the stored months, years and seasons.
     */
    get: operations['archive_status_api_v1_archive_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/archive/delete': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Delete Archive
     * @description ``POST archive/delete``: delete a frozen month or every frozen month of a year.
     */
    post: operations['delete_archive_api_v1_archive_delete_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/archive/months/{month}': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Download Month
     * @description ``GET archive/months/{month}``: one month's zip (the open month as it stands).
     */
    get: operations['download_month_api_v1_archive_months__month__get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/archive/seasons/{season}': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Download Season
     * @description ``GET archive/seasons/{season}``: the frozen months of a heating season (Aug-Jul).
     */
    get: operations['download_season_api_v1_archive_seasons__season__get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/archive/years/{year}': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Download Year
     * @description ``GET archive/years/{year}``: the frozen months of a calendar year and a manifest.
     */
    get: operations['download_year_api_v1_archive_years__year__get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/audit': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Audit Events
     * @description ``GET audit``: audit events (JSON or CSV).
     */
    get: operations['audit_events_api_v1_audit_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/commands': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Commands */
    get: operations['commands_api_v1_commands_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Current */
    get: operations['current_api_v1_config_get'];
    /** Apply */
    put: operations['apply_api_v1_config_put'];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/export': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Export */
    get: operations['export_api_v1_config_export_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/ha': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    /** Ha Connection */
    put: operations['ha_connection_api_v1_config_ha_put'];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/ha/test': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Ha Test */
    post: operations['ha_test_api_v1_config_ha_test_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/mqtt': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Mqtt Status */
    get: operations['mqtt_status_api_v1_config_mqtt_get'];
    /** Mqtt Connection */
    put: operations['mqtt_connection_api_v1_config_mqtt_put'];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/mqtt/test': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Mqtt Test */
    post: operations['mqtt_test_api_v1_config_mqtt_test_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/preview': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Preview */
    post: operations['preview_api_v1_config_preview_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/reset-ack': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Reset Ack */
    post: operations['reset_ack_api_v1_config_reset_ack_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/rollback': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Rollback */
    post: operations['rollback_api_v1_config_rollback_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/schema': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Schema */
    get: operations['schema_api_v1_config_schema_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/signals': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Signal Candidates */
    get: operations['signal_candidates_api_v1_config_signals_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/validate': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Validate */
    post: operations['validate_api_v1_config_validate_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/versions': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Versions */
    get: operations['versions_api_v1_config_versions_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/config/versions/{number}': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Version */
    get: operations['version_api_v1_config_versions__number__get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/control/pause': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Pause
     * @description ``POST control/pause``: pause control (nothing is sent until resumed).
     */
    post: operations['pause_api_v1_control_pause_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/control/release': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Release Status
     * @description ``GET control/release``: the last release and rehearsals.
     */
    get: operations['release_status_api_v1_control_release_get'];
    put?: never;
    /**
     * Release
     * @description ``POST control/release``: hand control back to the pump (or rehearse it).
     */
    post: operations['release_api_v1_control_release_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/control/release-hold': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Release Hold
     * @description ``POST control/release-hold``: release a foreign-writer or verification hold.
     */
    post: operations['release_hold_api_v1_control_release_hold_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/control/resume': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Resume
     * @description ``POST control/resume``: resume control.
     */
    post: operations['resume_api_v1_control_resume_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/control/snapshot': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Snapshot
     * @description ``GET control/snapshot``: the go-live snapshot and whether one can be captured.
     */
    get: operations['snapshot_api_v1_control_snapshot_get'];
    put?: never;
    /**
     * Capture
     * @description ``POST control/snapshot``: capture the pump's settings by hand.
     */
    post: operations['capture_api_v1_control_snapshot_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/control/stove': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Stove
     * @description ``POST control/stove``: switch wood-stove mode on or off.
     */
    post: operations['stove_api_v1_control_stove_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/decisions': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Decisions */
    get: operations['decisions_api_v1_decisions_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/decisions/latest': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Decisions Latest */
    get: operations['decisions_latest_api_v1_decisions_latest_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/decisions/series': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Decision Series
     * @description ``GET decisions/series``: the controller's decisions over time.
     */
    get: operations['decision_series_api_v1_decisions_series_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/diagnostics': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Diagnostics
     * @description ``GET diagnostics``: the redacted diagnostics bundle as a download.
     */
    get: operations['diagnostics_api_v1_diagnostics_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/export/archive': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Export Archive
     * @description ``GET export/archive``: a fresh copy of ``history.db``, the configuration and a manifest.
     */
    get: operations['export_archive_api_v1_export_archive_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/export/journal/{kind}': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Export Journal
     * @description ``GET export/journal/{kind}``: decisions, commands, alarms or forecasts, streamed.
     */
    get: operations['export_journal_api_v1_export_journal__kind__get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/export/series': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Export Series
     * @description ``GET export/series``: signal history as a streamed CSV or NDJSON download.
     */
    get: operations['export_series_api_v1_export_series_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/health': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Health */
    get: operations['health_api_v1_health_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/history': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** History */
    get: operations['history_api_v1_history_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/history/compact': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * History Compact
     * @description ``POST history/compact``: compact ``history.db`` now (the writer pauses meanwhile).
     */
    post: operations['history_compact_api_v1_history_compact_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/history/signals': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * History Signals
     * @description ``GET history/signals``: every signal with stored history and its range per resolution.
     */
    get: operations['history_signals_api_v1_history_signals_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/history/storage': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * History Storage
     * @description ``GET history/storage``: database size per table and resolution, and the projection.
     */
    get: operations['history_storage_api_v1_history_storage_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/insight/daily': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Daily */
    get: operations['daily_api_v1_insight_daily_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/insight/house': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** House Model */
    get: operations['house_model_api_v1_insight_house_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/insight/house/history': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** House History */
    get: operations['house_history_api_v1_insight_house_history_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/insight/house/proposal/draft': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Proposal Draft */
    post: operations['proposal_draft_api_v1_insight_house_proposal_draft_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/insight/house/run': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** House Run */
    get: operations['house_run_api_v1_insight_house_run_get'];
    put?: never;
    /** Start House Run */
    post: operations['start_house_run_api_v1_insight_house_run_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/insight/runs': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Runs
     * @description ``GET insight/runs``: compressor runs per local day.
     */
    get: operations['runs_api_v1_insight_runs_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/live/ticket': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Live Ticket */
    post: operations['live_ticket_api_v1_live_ticket_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/notifications/status': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Notifications
     * @description ``GET notifications/status``: what is configured, sent and failing (no secrets).
     */
    get: operations['notifications_api_v1_notifications_status_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/notifications/test': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Notifications Test
     * @description ``POST notifications/test``: send a test notification at once.
     */
    post: operations['notifications_test_api_v1_notifications_test_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/pump/settings': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Read */
    get: operations['read_api_v1_pump_settings_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/pump/settings/{setting_id}': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Write */
    post: operations['write_api_v1_pump_settings__setting_id__post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/replay': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Start Replay
     * @description ``POST replay``: start a replay of a period with the chosen configuration.
     */
    post: operations['start_replay_api_v1_replay_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/replay/{job_id}': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Replay Job
     * @description ``GET replay/{id}``: a replay's phase and progress, and its result when done.
     */
    get: operations['replay_job_api_v1_replay__job_id__get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/replay/{job_id}/cancel': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Cancel Replay
     * @description ``POST replay/{id}/cancel``: stop a running replay.
     */
    post: operations['cancel_replay_api_v1_replay__job_id__cancel_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/replay/coverage': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Coverage
     * @description ``GET replay/coverage``: where stored decisions exist, per day and version.
     *
     *     The history database is read in a worker thread, never on the event loop.
     */
    get: operations['coverage_api_v1_replay_coverage_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/shadow/divergence': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Divergence
     * @description ``GET shadow/divergence``: ovenbird against the pump's setpoint, with episodes.
     */
    get: operations['divergence_api_v1_shadow_divergence_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/shadow/episodes/explain': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Explain
     * @description ``POST shadow/episodes/explain``: mark (or unmark) an episode as explained.
     */
    post: operations['explain_api_v1_shadow_episodes_explain_post'];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/snapshot': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Snapshot */
    get: operations['snapshot_api_v1_snapshot_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/system/about': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * About
     * @description ``GET system/about``: version, uptime, connections and the control state.
     */
    get: operations['about_api_v1_system_about_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/trial/status': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Trial Status
     * @description ``GET trial/status``: the go-live checklist and the trial summary.
     */
    get: operations['trial_status_api_v1_trial_status_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  '/api/v1/weather': {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Read */
    get: operations['read_api_v1_weather_get'];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    /** @description The control loop's mode, ticks and state. */
    AboutControl: {
      configured_mode: components['schemas']['ModeName'];
      interval_s: number;
      last_tick_at: string | null;
      mode: components['schemas']['ModeName'];
      paused: boolean;
      publishing: boolean;
      releasing: boolean;
      restored_state: boolean;
      ticks: number;
    };
    /** @description The command adapter: holds, queue, verification, budget and counters. */
    AdapterStatus: {
      budget: components['schemas']['Budget'];
      corrections: components['schemas']['Corrections'];
      counters: {
        [key: string]: number;
      };
      hold: string | null;
      hold_incidents: number;
      hold_latched: boolean;
      hold_until: string | null;
      in_flight: components['schemas']['InFlight'] | null;
      queued: {
        [key: string]: number;
      };
      safety_hold: string[];
      setpoint_register: string;
      verified: {
        [key: string]: number | null;
      };
    };
    /** @description An active alarm. */
    Alarm: {
      code: string;
      detail: {
        [key: string]: unknown;
      };
      message: string;
      severity: components['schemas']['SeverityName'];
      since: string;
    };
    /** @description A journalled alarm or hold transition. */
    AlarmEvent: {
      at: string;
      code: string;
      detail: {
        [key: string]: unknown;
      };
      event: components['schemas']['AlarmEventName'];
      message: string;
      severity: components['schemas']['SeverityName'];
    };
    /** @enum {string} */
    AlarmEventName: 'raised' | 'cleared' | 'started' | 'expired' | 'released' | 'recognised';
    /** @description ``GET alarms``: the active alarms and the events in a window. */
    AlarmsPage: {
      active: components['schemas']['Alarm'][];
      events: components['schemas']['AlarmEvent'][];
      from: string;
      limit: number;
      to: string;
    };
    /** @description ``PUT config`` and ``POST config/rollback``: the new version and configuration. */
    ApplyResult: {
      /** @constant */
      applies: 'next_tick';
      config: components['schemas']['ConfigDoc'];
      version: number;
    };
    /** @description What the arbiter decided for one intent. */
    ArbiterEntry: {
      action: string;
      actual: number | null;
      intent: number | null;
      kind: string;
      reason: string;
    };
    /** @description ``POST archive/delete``: the months removed and the archive afterwards. */
    ArchiveDeleteResult: {
      archive: components['schemas']['ArchiveStatus'];
      deleted: string[];
    };
    /** @description A calendar year or heating season with stored months. */
    ArchiveGroup: {
      bytes: number;
      complete: boolean;
      first: string | null;
      id: string;
      kind: components['schemas']['ArchiveGroupKind'];
      last: string | null;
      months: string[];
      of: number;
      open_months: string[];
      period: string;
    };
    /** @enum {string} */
    ArchiveGroupKind: 'year' | 'season';
    /** @description One stored month: frozen (final) or open (being built). */
    ArchiveMonth: {
      archived_to: string | null;
      bytes: number;
      complete: boolean | null;
      created_at: string | null;
      days: number | null;
      days_total: number;
      decision_days: number | null;
      from: string | null;
      missing_days: number | null;
      period: string;
      state: components['schemas']['ArchiveMonthState'];
      to: string | null;
    };
    /** @enum {string} */
    ArchiveMonthState: 'frozen' | 'open';
    /** @description What the archive's last step did (``null`` without a history writer). */
    ArchiveRun: {
      archived_to: string | null;
      behind: boolean;
      error: string | null;
      last_run_at: string | null;
    };
    /** @description ``GET archive``: whether the archive runs, what it holds and what it costs. */
    ArchiveStatus: {
      bytes_per_year: number | null;
      enabled: boolean;
      months: components['schemas']['ArchiveMonth'][];
      notice: string;
      seasons: components['schemas']['ArchiveGroup'][];
      state: components['schemas']['ArchiveRun'] | null;
      timezone: string;
      total_bytes: number;
      years: components['schemas']['ArchiveGroup'][];
    };
    /** @description One audit row. */
    AuditEvent: {
      action: string;
      actor: string;
      at: string;
      detail: {
        [key: string]: unknown;
      };
      source_ip: string | null;
    };
    /** @description ``GET audit``: audit events in a window. */
    AuditPage: {
      events: components['schemas']['AuditEvent'][];
      from: string;
      limit: number;
      to: string;
    };
    /** @enum {string} */
    AutoVacuumName: 'none' | 'full' | 'incremental';
    /** @description Today's write budget. */
    Budget: {
      day: string | null;
      limit: number;
      safety_reserve: number;
      used: number;
    };
    /** @enum {string} */
    CaptureRefusalName: 'controlling' | 'in_use' | 'in_progress';
    /** @description The promoted model named by the learner's ``current.json``. */
    Champion: {
      model: string | null;
      promoted_at: string | null;
    };
    /** @description Checklist items per status. */
    CheckCounts: {
      fail: number;
      ok: number;
      warn: number;
    };
    /** @description One phase of the checklist: readiness, counts and item ids. */
    CheckGroup: {
      counts: components['schemas']['CheckCounts'];
      ids: string[];
      ready: boolean;
    };
    /** @description The checklist per phase. */
    CheckGroups: {
      go_live: components['schemas']['CheckGroup'];
      trial: components['schemas']['CheckGroup'];
    };
    /** @enum {string} */
    CheckPhaseName: 'go_live' | 'trial';
    /** @enum {string} */
    CheckStatusName: 'ok' | 'warn' | 'fail';
    /** @description A command life-cycle event as the adapter reports it (with a decision, a write). */
    CommandEvent: {
      at: string;
      attempt: number;
      detail: string;
      kind: string;
      payload: string | null;
      status: string;
      topic: string | null;
      value: number;
    };
    /** @description One journalled command event (journal column order: ``detail`` last). */
    CommandLogEntry: {
      at: string;
      attempt: number;
      detail: string;
      kind: string;
      payload: string | null;
      status: string;
      topic: string | null;
      value: number;
    };
    /** @description ``GET commands``: command events in a window. */
    CommandsPage: {
      commands: components['schemas']['CommandLogEntry'][];
      from: string;
      limit: number;
      to: string;
    };
    /** @description The last compaction of ``history.db`` (``POST history/compact``). */
    Compaction: {
      error: string | null;
      freed_bytes: number | null;
      last_at: string | null;
      pending: boolean;
      running: boolean;
    };
    /** @description ``POST history/compact``: whether the request was queued, and the state. */
    CompactResult: {
      accepted: boolean;
      compaction: components['schemas']['Compaction'];
    };
    /** @description ``GET config``: the effective configuration. */
    ConfigDoc: {
      applied_version: number;
      fields: {
        [key: string]: components['schemas']['ConfigField'];
      };
      hot_water: components['schemas']['HotWaterState'];
      mode: components['schemas']['ConfigMode'];
      reset_pending: boolean;
      updated_at: string | null;
      updated_by: string | null;
      version: number;
    };
    /** @description ``GET config/export``: the stored values and every non-secret effective value. */
    ConfigExport: {
      app_version: string;
      effective: {
        [key: string]: unknown;
      };
      exported_at: string;
      ovenbird_config: number;
      values: {
        [key: string]: unknown;
      };
      version: number;
    };
    /** @description One field of the configuration: effective value, source, lock, stored value, default. */
    ConfigField: {
      default: unknown;
      locked: boolean;
      source: components['schemas']['ValueSourceName'];
      stored: unknown;
      value: unknown;
    };
    /** @description A configuration version took effect. */
    ConfigMessage: {
      data: components['schemas']['ConfigNotice'];
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'config';
    };
    /** @description The configured and effective mode, pause and pending reset. */
    ConfigMode: {
      configured: components['schemas']['ModeName'];
      effective: components['schemas']['ModeName'];
      paused: boolean;
      reset_pending: boolean;
    };
    /** @description A configuration version took effect. */
    ConfigNotice: {
      applied_at: string;
      version: number | null;
    };
    /** @description ``GET config/schema``: field definitions, groups, presets per emitter, envelope. */
    ConfigSchema: {
      envelope: components['schemas']['Envelope'];
      fields: {
        [key: string]: components['schemas']['FieldDef'];
      };
      groups: components['schemas']['SchemaGroup'][];
      presets: {
        [key: string]: {
          [key: string]: unknown;
        };
      };
      schema: number;
    };
    /** @description ``GET config/signals``: the signal picker's candidates. */
    ConfigSignals: {
      crosscheck: components['schemas']['SignalCandidate'][];
      ha: components['schemas']['HaLinkState'];
      liveness: components['schemas']['SignalCandidate'][];
      room: components['schemas']['SignalCandidate'][];
    };
    /** @description A stored configuration version; ``values`` only from ``config/versions/{number}``. */
    ConfigVersion: {
      actor: string;
      applied_at: string | null;
      changed: components['schemas']['VersionChange'][];
      comment: string | null;
      created_at: string;
      origin: components['schemas']['OriginName'];
      values?: {
        [key: string]: unknown;
      };
      version: number;
    };
    /** @description ``GET config/versions``: the newest versions first. */
    ConfigVersions: {
      versions: components['schemas']['ConfigVersion'][];
    };
    /** @description The service's connections. */
    Connections: {
      ha: components['schemas']['HaConnection'];
      integration_token: boolean;
      mqtt: components['schemas']['MqttConnection'];
    };
    /** @description The control loop's state. */
    ControlStatus: {
      adapter: components['schemas']['AdapterStatus'] | null;
      alarms: components['schemas']['Alarm'][];
      config_version: number | null;
      configured_mode: components['schemas']['ModeName'];
      controller: string;
      interval_s: number;
      mode: components['schemas']['ModeName'];
      paused: boolean;
      publishing: boolean;
      refusals: string[];
      releasing: boolean;
      reset_pending: boolean;
      restored_state: boolean;
      room: components['schemas']['RoomStatus'] | null;
      safety: components['schemas']['Safety'] | null;
      stove: components['schemas']['StoveStatus'];
      ticks: number;
    };
    /** @description Recent corrective writes against their limit. */
    Corrections: {
      limit: number;
      recent: number;
      window_s: number;
    };
    /** @description Stored decisions of one local day of the window. */
    CoverageDay: {
      date: string;
      decisions: number;
      expected: number;
      first: string | null;
      from: string;
      last: string | null;
      to: string;
    };
    /** @description Stored decisions of one configuration version in the window. */
    CoverageVersion: {
      decisions: number;
      from: string;
      to: string;
      version: number | null;
    };
    /** @enum {string} */
    CriterionStatusName: 'ok' | 'fail' | 'info' | 'unknown';
    /** @description A heating curve as a configuration change (``null`` when there is none). */
    CurveChange: {
      control_curve: [number, number][] | null;
    };
    /** @description The curve's water temperature on the forecast. */
    CurveOutlook: {
      points: components['schemas']['WeatherPoint'][];
    };
    /** @description The dead-man ping; only ``configured`` without a notifier. */
    DeadmanStatus: {
      configured: boolean;
      healthy?: boolean;
      interval_s?: number;
      last_error?: components['schemas']['DeliveryError'] | null;
      last_ok?: string | null;
      last_skip?: string | null;
      pings?: number;
      server?: string | null;
      unhealthy_reason?: string | null;
    };
    /** @description One journalled decision: the summary columns, the arbiter, commands and the record. */
    Decision: {
      arbiter: components['schemas']['ArbiterEntry'][];
      at: string;
      commands: components['schemas']['CommandEvent'][];
      config_version: number | null;
      controller: string;
      ladder: string;
      mode: components['schemas']['ModeName'];
      note: string;
      reason: string;
      record: components['schemas']['DecisionRecord'];
      setpoint: number | null;
    };
    /** @description A new controller decision. */
    DecisionMessage: {
      data: components['schemas']['Decision'];
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'decision';
    };
    /** @description The core's complete explanation of one controller tick (schema 1). */
    DecisionRecord: {
      actor: string | null;
      at: components['schemas']['RecordInstant'];
      binding: string | null;
      controller: string;
      controller_state: {
        [key: string]: number | string | boolean | null;
      };
      flip_distance: number | null;
      flip_input: string | null;
      inputs_used: components['schemas']['InputRef'][];
      intents: components['schemas']['Intent'][];
      ladder: string;
      mode: components['schemas']['ModeName'];
      note: string;
      pre_round: number | null;
      reason: string;
      schema: number;
      setpoint: number | null;
      terms: components['schemas']['Term'][];
    };
    /** @description ``GET decisions/series``: the controller's decisions as columns over time. */
    DecisionSeries: {
      at: string[];
      binding: (string | null)[];
      config_version: (number | null)[];
      curve: (number | null)[];
      cycling_floor: (number | null)[];
      from: string;
      ladder: (string | null)[];
      other: (number | null)[];
      plan: (number | null)[];
      pre_round: (number | null)[];
      reason: (string | null)[];
      room_feedback: (number | null)[];
      safety_delta: (number | null)[];
      safety_high: (number | null)[];
      safety_low: (number | null)[];
      setpoint: (number | null)[];
      start_ramp: (number | null)[];
      step: number;
      stove: (number | null)[];
      to: string;
    };
    /** @description ``GET decisions/latest``: the newest decision and the control state. */
    DecisionsLatest: {
      control: components['schemas']['ControlStatus'] | null;
      decision: components['schemas']['Decision'] | null;
    };
    /** @description ``GET decisions``: decisions in a window. */
    DecisionsPage: {
      decisions: components['schemas']['Decision'][];
      from: string;
      limit: number;
      to: string;
    };
    /**
     * @description The live defrost as the safety monitor latched it at its start.
     *
     *     ``mode`` is the deice mode the unit picks (1: reverse cycle, water pump running;
     *     2: hot gas, water pump off by design); ``None`` for an unknown model. Everything
     *     but ``active`` is ``None`` outside a defrost; ``max_s`` is the ``defrost_stuck``
     *     limit in effect.
     */
    DefrostState: {
      active: boolean;
      inlet_at_start_c: number | null;
      max_s: number | null;
      mode: (1 | 2) | null;
      outside_at_start_c: number | null;
      since: string | null;
    };
    /** @description The last notification ntfy accepted. */
    Delivery: {
      at: string;
      title: string;
    };
    /** @description The last failed send or ping. */
    DeliveryError: {
      at: string;
      error: string;
    };
    /** @description A derived signal with the reason it has no value. */
    Derived: {
      reason: string | null;
      value: number | string | boolean | null;
    };
    /** @enum {string} */
    DirectionName: 'above' | 'below';
    /** @description ``GET shadow/divergence``: ovenbird against the pump's setpoint, with episodes. */
    Divergence: {
      days: components['schemas']['DivergenceDay'][];
      episodes: components['schemas']['Episode'][];
      episodes_total: number;
      from: string;
      series: components['schemas']['DivergenceSeries'];
      signal: string;
      step: number;
      summary: components['schemas']['DivergenceSummary'];
      threshold_k: number;
      timezone: string;
      to: string;
    };
    /** @description The divergence of one local day. */
    DivergenceDay: {
      bias_k: number | null;
      compared_minutes: number;
      coverage: number;
      date: string;
      episodes: number;
      from: string;
      gap_minutes: number;
      hours_over: number;
      longest_episode_min: number;
      max_abs_k: number | null;
      mean_abs_k: number | null;
      minutes: number;
      to: string;
    };
    /** @description Ovenbird's and the pump's setpoints as columns over time. */
    DivergenceSeries: {
      at: string[];
      diff: (number | null)[];
      max_abs: (number | null)[];
      mode: (string | null)[];
      ovenbird: (number | null)[];
      pump: (number | null)[];
      writer: (string | null)[];
    };
    /** @description Ovenbird against the pump's setpoint over the window. */
    DivergenceSummary: {
      bias_k: number | null;
      compared_minutes: number;
      coverage: number;
      episodes: number;
      gap_minutes: number;
      hours_over: number;
      longest_episode_min: number;
      max_abs_k: number | null;
      mean_abs_k: number | null;
      minutes: number;
    };
    /** @description The safety envelope around the heating curve. */
    Envelope: {
      above_k: number;
      below_k: number;
      curve: [number, number][];
    };
    /** @description The envelope band at the current outside temperature. */
    EnvelopeBand: {
      high_c: number;
      low_c: number;
      outside_c: number;
    };
    /** @description Ovenbird's corrective writes against their limit, and in total. */
    EnvelopeCorrections: {
      limit: number;
      recent: number;
      total: number;
      window_s: number;
    };
    /** @description The last correction of the pump's envelope rule ovenbird recognised. */
    EnvelopeEvidence: {
      at: string | null;
      from_c: number;
      high_c: number;
      low_c: number;
      outside_c: number | null;
      to_c: number;
    };
    /** @description Whether the pump's own envelope rule is declared and seen acting. */
    EnvelopeRule: {
      adopted: number | null;
      count: number;
      first_at: string | null;
      installed: boolean;
      last: components['schemas']['EnvelopeEvidence'] | null;
      state: components['schemas']['EnvelopeStateName'];
    };
    /** @enum {string} */
    EnvelopeStateName: 'not_declared' | 'declared' | 'proven';
    /** @description A run of minutes with a divergence above the threshold. */
    Episode: {
      end: string;
      /** @enum {string} */
      ended_by: 'open' | 'gap' | 'converged';
      explained: components['schemas']['EpisodeNote'] | null;
      max_abs_k: number;
      max_diff_k: number;
      minutes: number;
      mode: string | null;
      ovenbird_c: number | null;
      pump_c: number | null;
      reason: string | null;
      reason_at_max: string | null;
      start: string;
      writer: string | null;
    };
    /** @enum {string} */
    EpisodeEndName: 'open' | 'gap' | 'converged';
    /** @description A stored explanation of an episode. */
    EpisodeMark: {
      at: string;
      by: string | null;
      note: string;
      start: string;
      start_ts: number;
    };
    /** @description Why an episode is explained, by whom and when. */
    EpisodeNote: {
      at: string | null;
      by: string | null;
      note: string | null;
      start: string | null;
    };
    /** @description ``POST shadow/episodes/explain``: the mark, ``null`` after a removal. */
    ExplainResult: {
      explained: components['schemas']['EpisodeMark'] | null;
    };
    /** @description The schema of one configuration field. */
    FieldDef: {
      display: string | null;
      editable: boolean;
      env: string;
      exclusive_max: boolean;
      exclusive_min: boolean;
      group: string;
      level_max?: number;
      level_min?: number;
      max: number | null;
      max_items?: number;
      max_points?: number;
      min: number | null;
      min_points?: number;
      nullable: boolean;
      options?: string[];
      outside_max?: number;
      outside_min?: number;
      preset_default: boolean;
      soft_max: number | null;
      soft_min: number | null;
      step: number | null;
      tier: components['schemas']['TierName'];
      type: components['schemas']['FieldTypeName'];
      unit: string | null;
    };
    /** @enum {string} */
    FieldTypeName:
      | 'number'
      | 'integer'
      | 'boolean'
      | 'string'
      | 'enum'
      | 'curve'
      | 'windows'
      | 'list'
      | 'secret'
      | 'signal'
      | 'signal_list'
      | 'mqtt_inputs'
      | 'retention';
    /** @description Bias and mean absolute error of the stored forecasts per lead. */
    ForecastError: {
      bias_k: (number | null)[];
      lead_h: number[];
      mae_k: (number | null)[];
      n: number[];
    };
    ForecastPoint: [string, number | null, number | null, number | null, number | null];
    /** @description The forecast hours: time, temperature, radiation, cloud cover, wind. */
    ForecastSeries: {
      points: components['schemas']['ForecastPoint'][];
      step: number;
    };
    /** @enum {string} */
    Format: 'json' | 'csv';
    /** @description The Home Assistant link (``connected`` ``null`` when not configured). */
    HaConnection: {
      configured: boolean;
      connected: boolean | null;
    };
    /** @description ``PUT config/ha``: the configuration after the connection change. */
    HaConnectionResult: {
      config: components['schemas']['ConfigDoc'];
    };
    /** @description What a connection test found for one ``ha/`` signal. */
    HaEntityCheck: {
      entity_id: string;
      found: boolean;
      problem: string | null;
      signal: string;
      state: string | null;
      unit: string | null;
      value: number | null;
    };
    /** @description Whether Home Assistant is configured and connected, and its temperature unit. */
    HaLinkState: {
      enabled: boolean;
      link_up: boolean;
      temperature_unit?: string | null;
    };
    /** @enum {string} */
    HaTestErrorCode:
      | 'invalid_url'
      | 'not_configured'
      | 'token_required'
      | 'unreachable'
      | 'auth_failed'
      | 'http_error'
      | 'protocol'
      | 'timeout'
      | 'websocket';
    /** @description ``POST config/ha/test``: the outcome of a read-only connection test. */
    HaTestResult: {
      auth_ok: boolean | null;
      entities: components['schemas']['HaEntityCheck'][];
      error: string | null;
      error_code: components['schemas']['HaTestErrorCode'] | null;
      ha_version: string | null;
      latency_ms: number | null;
      metric: boolean | null;
      ok: boolean;
      reachable: boolean;
      temperature_unit: string | null;
      url: string | null;
    };
    /** @description ``GET health``: liveness, readiness, version and the component checks. */
    Health: {
      api_version: number;
      checks: components['schemas']['HealthChecks'];
      live: boolean;
      ready: boolean;
      version: string;
    };
    /** @description The component checks of ``health``. */
    HealthChecks: {
      alarms: string;
      /** @enum {string} */
      ha: 'connected' | 'disconnected' | 'disabled';
      /** @enum {string} */
      heishamon: 'alive' | 'dead';
      /** @enum {string} */
      history: 'ok' | 'starting' | 'error';
      /** @enum {string} */
      mqtt: 'connected' | 'disconnected';
      weather: string;
    };
    /** @description The health body, whenever it changed. */
    HealthMessage: {
      data: components['schemas']['Health'];
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'health';
    };
    /** @description HeishaMon's heartbeat and last will. */
    HeishamonLink: {
      alive: boolean;
      last_heartbeat_age: number | null;
      lwt: ('Online' | 'Offline') | null;
    };
    /** @description ``GET history``: the requested signals over a window. */
    History: {
      from: string;
      series: {
        [key: string]: components['schemas']['HistorySeries'];
      };
      step: number;
      to: string;
    };
    /** @description One signal's points (``[time, value]``). */
    HistorySeries: {
      points: [string, number | string | boolean | null][];
      unit: string | null;
    };
    /** @description ``GET history/signals``: every signal with stored history. */
    HistorySignals: {
      signals: components['schemas']['StoredSignal'][];
    };
    /** @description ``GET history/storage``: sizes, ranges, the projection and the compaction state. */
    HistoryStorage: {
      auto_vacuum: components['schemas']['AutoVacuumName'];
      compaction: components['schemas']['Compaction'] | null;
      files: components['schemas']['StorageFiles'];
      growth_bytes_per_year: number | null;
      preset: components['schemas']['PresetName'] | null;
      presets: components['schemas']['RetentionPreset'][];
      projected_bytes: number | null;
      reclaimable_bytes: number;
      resolutions: components['schemas']['StorageResolution'][];
      tables: components['schemas']['StorageTable'][];
    };
    /** @description Whether the UI shows hot water: the setting, the pump's report and the outcome. */
    HotWaterState: {
      installed: boolean | null;
      /** @enum {string} */
      setting: 'auto' | 'on' | 'off';
      shown: boolean;
    };
    /** @description ``GET insight/house/history``: every promoted model. */
    HouseHistory: {
      floor_area_m2: number | null;
      models: components['schemas']['HouseHistoryModel'][];
    };
    /** @description A promoted model of the learner's index and its score at the current floor area. */
    HouseHistoryModel: {
      champion: boolean;
      credible: boolean | null;
      data_to: string | null;
      generated: string | null;
      model: string | null;
      room_rmse_24h_k: number | null;
      score: components['schemas']['HouseScore'];
      time_constant_h: number | null;
      ua_interval_90: [number, number] | null;
      ua_w_per_k: number | null;
    };
    /**
     * @description ``GET insight/house`` with a promoted model: the learner's insight and the score.
     *
     *     The learner's keys are passed through; ``proposal`` gains ``current_curve`` and
     *     ``stale`` (whether the curve changed since the run).
     */
    HouseReady: {
      balance_temperature_c?: unknown;
      champion: components['schemas']['Champion'];
      credibility?: {
        [key: string]: unknown;
      };
      daily_error?: unknown;
      data?: unknown;
      error_trend?: unknown;
      events?: unknown;
      internal_gains_w?: unknown;
      last_run: components['schemas']['LastRun'] | null;
      learner: components['schemas']['LearnerHealth'];
      limits?: unknown;
      model?: unknown;
      proposal?: {
        [key: string]: unknown;
      };
      provenance?: unknown;
      schema?: unknown;
      score: components['schemas']['HouseScore'];
      signature?: unknown;
      solar_aperture_m2?: unknown;
      /** @constant */
      state: 'ready';
      time_constant_h?: unknown;
      ua?: {
        [key: string]: unknown;
      };
      validation?: unknown;
    };
    HouseReport: components['schemas']['HouseWaiting'] | components['schemas']['HouseReady'];
    /** @description ``GET`` and ``POST insight/house/run``: the embedded learner's state and schedule. */
    HouseRun: {
      enabled: boolean;
      failure: components['schemas']['HouseRunFailure'] | null;
      interval_h: number;
      last: components['schemas']['HouseRunLast'] | null;
      next_due_at: string | null;
      started_at: string | null;
      state: components['schemas']['RunState'];
    };
    /** @description The service's last failed attempt to run the learner. */
    HouseRunFailure: {
      at: string;
      detail: string;
      reason: components['schemas']['RunFailureReason'];
    };
    /** @description The learner's last run as ``status.json`` reports it. */
    HouseRunLast: {
      at: string;
      message: string | null;
      model: string | null;
      outcome: string;
      runtime_s: number | null;
    };
    /** @description The indicative insulation score, recomputed for the current floor area. */
    HouseScore: {
      band?: string;
      band_interval?: [string, string];
      bands: components['schemas']['ScoreBand'][];
      design_indoor_c: number;
      design_outside_c: number;
      floor_area_m2: number | null;
      heat_loss_w?: number;
      indicative: boolean;
      interval_90?: [number, number];
      message?: string;
      note: string;
      state: components['schemas']['ScoreState'];
      w_per_m2?: number;
    };
    /** @description ``GET insight/house`` before a model is promoted: what is missing. */
    HouseWaiting: {
      last_run: components['schemas']['LastRun'] | null;
      learner: components['schemas']['LearnerHealth'];
      missing: string[];
      /** @enum {string} */
      state: 'learning' | 'not_run';
    };
    HTTPValidationError: {
      detail?: components['schemas']['ValidationError'][];
    };
    /** @description The command published and not yet verified. */
    InFlight: {
      attempt: number;
      corrective: boolean;
      kind: string;
      sent_at: string;
      value: number;
    };
    /** @description An input a decision used, with its provenance. */
    InputRef: {
      age: number | null;
      fresh: boolean;
      issued: string | null;
      signal: string;
      source: string | null;
      value: number | string | boolean | null;
    };
    /** @description ``GET insight/daily``: the last days, oldest first. */
    InsightDaily: {
      band_below_k: number;
      days: components['schemas']['InsightDay'][];
      room_signal: string | null;
      timezone: string;
    };
    /** @description One local day of energy, runs, temperatures and comfort. */
    InsightDay: {
      below_comfort_kh: number | null;
      comfort_c: number;
      compressor_starts: number | null;
      cop: number | null;
      coverage: number;
      date: string;
      defrost_s: number | null;
      defrosts: number | null;
      dhw_electric_kwh: number | null;
      dhw_heat_kwh: number | null;
      dhw_runs: number | null;
      dhw_s: number | null;
      electric_kwh: number | null;
      from: string;
      heat_kwh: number | null;
      hours: number;
      outside_mean_c: number | null;
      outside_min_c: number | null;
      partial: boolean;
      room_mean_c: number | null;
      room_min_c: number | null;
      run_s: number | null;
      setpoint_changes: number | null;
      setpoint_mean_c: number | null;
      to: string;
      writes: number;
    };
    /** @description ``GET insight/runs``: compressor runs per local day and in total. */
    InsightRuns: {
      days: components['schemas']['RunDay'][];
      short_run_min: number;
      signal: string;
      timezone: string;
      total: components['schemas']['RunStats'];
    };
    /** @description A command intent returned with a decision record. */
    Intent: {
      kind: string;
      reason: string;
      value: number;
    };
    /** @description The allow-listed essentials of the learner's last run (``status.json``). */
    LastRun: {
      at?: string | null;
      champion?: string | null;
      error?: string | null;
      interval_h?: number | null;
      message?: string | null;
      missing?: string[] | null;
      model?: string | null;
      outcome?: string | null;
      runtime_s?: number | null;
    };
    /** @enum {string} */
    LayoutName: 'long' | 'wide';
    /** @description When the learner last ran and whether that is too long ago. */
    LearnerHealth: {
      age_h: number | null;
      interval_h: number;
      last_run_at: string | null;
      stale: boolean;
      stale_after_h: number;
    };
    /** @description ``POST live/ticket``: a single-use pass for the WebSocket. */
    LiveTicket: {
      expires_in: number;
      ticket: string;
    };
    /** @description ``POST control/pause`` and ``control/resume``: the new mode and the control state. */
    ModeChange: {
      control: components['schemas']['ControlStatus'] | null;
      mode: components['schemas']['ConfigMode'];
    };
    /** @enum {string} */
    ModeName: 'off' | 'shadow' | 'auto' | 'manual';
    /** @description The result of one safety monitor. */
    Monitor: {
      code: string;
      direction: components['schemas']['DirectionName'] | null;
      limit: number | null;
      message: string;
      severity: components['schemas']['SeverityName'];
      since: string | null;
      status: components['schemas']['MonitorState'];
      unit: string | null;
      value: number | string | null;
    };
    /** @enum {string} */
    MonitorState: 'ok' | 'pending' | 'active' | 'unknown';
    /**
     * @description The last broker change: ``idle``, ``applying``, ``applied``, ``reverted`` or ``failed``.
     *
     *     ``failed``: the change gave no live HeishaMon data and putting the previous broker
     *     back failed (alarm ``mqtt_revert_failed``).
     */
    MqttApplyState: {
      at: string | null;
      message: string | null;
      /** @enum {string} */
      state: 'idle' | 'applying' | 'applied' | 'reverted' | 'failed';
    };
    /** @description The MQTT link and HeishaMon. */
    MqttConnection: {
      connected: boolean;
      heishamon_alive: boolean;
      heishamon_base: string;
      tls: boolean;
    };
    /** @description ``PUT config/mqtt``: the configuration and the link after the change. */
    MqttConnectionResult: {
      config: components['schemas']['ConfigDoc'];
      mqtt: components['schemas']['MqttStatus'];
    };
    /** @description ``GET config/mqtt``: the broker link and the last change made in the app. */
    MqttStatus: {
      apply: components['schemas']['MqttApplyState'];
      base: string;
      commands_enabled: boolean;
      connected: boolean;
      heishamon_messages: number;
      host: string;
      port: number;
    };
    /** @enum {string} */
    MqttTestErrorCode:
      'invalid' | 'unreachable' | 'tls' | 'auth_failed' | 'refused' | 'timeout' | 'no_heishamon';
    /** @description ``POST config/mqtt/test``: the outcome of a subscribe-only broker test. */
    MqttTestResult: {
      base: string;
      connected: boolean;
      error: string | null;
      error_code: components['schemas']['MqttTestErrorCode'] | null;
      heishamon: boolean;
      host: string;
      latency_ms: number | null;
      ok: boolean;
      port: number;
      topic: string | null;
    };
    /** @description ``GET notifications/status``: what is configured, sent and failing (no secrets). */
    NotificationStatus: {
      deadman: components['schemas']['DeadmanStatus'];
      health?: components['schemas']['NotifyHealth'];
      ntfy: components['schemas']['NtfyStatus'];
    };
    /** @description Whether alarms reach the phone. */
    NotifyHealth: {
      deadman_state: string;
      failing_since: string | null;
      failures_in_row: number;
      pending: string[];
      reason: string | null;
      state: components['schemas']['NotifyStateName'];
    };
    /** @enum {string} */
    NotifyStateName: 'not_configured' | 'untested' | 'ok' | 'failing';
    /** @description The outcome of a test notification. */
    NotifyTest: {
      at: string;
      by: string | null;
      error: string | null;
      ok: boolean;
    };
    /** @description ``POST notifications/test``: the test's outcome and the status after it. */
    NotifyTestResult: {
      status: components['schemas']['NotificationStatus'];
      test: components['schemas']['NotifyTest'];
    };
    /** @description A go-live item that is not ok. */
    NotReady: {
      id: string;
      message: string;
    };
    /** @description The ntfy channel; only ``configured`` without a notifier. */
    NtfyStatus: {
      clear_hold_s?: number;
      configured: boolean;
      deferred?: number;
      dropped?: number;
      events?: boolean;
      language?: string;
      last_error?: components['schemas']['DeliveryError'] | null;
      last_sent?: components['schemas']['Delivery'] | null;
      last_test?: components['schemas']['NotifyTest'] | null;
      min_severity?: string;
      queued?: number;
      rate_limit_per_hour?: number;
      rate_limits?: {
        [key: string]: number;
      };
      retries?: number;
      sent?: number;
      server?: string | null;
      suppressed?: number;
      test_spacing_s?: number;
      token?: boolean;
    };
    /** @description The candidate replayed over the recorded decisions (open loop). */
    OpenLoopRun: {
      from: string;
      identity_first_mismatch: string | null;
      identity_mismatches: number;
      identity_ok: boolean;
      identity_ticks: number;
      limitations: string[];
      open_loop: boolean;
      series: components['schemas']['OpenLoopSeries'];
      skipped: number;
      summary: components['schemas']['OpenLoopSummary'];
      ticks: number;
      to: string;
    };
    /** @description The recorded and replayed setpoints of the window. */
    OpenLoopSeries: {
      at: string[];
      candidate: (number | null)[];
      candidate_pre_round: (number | null)[];
      recorded: (number | null)[];
    };
    /** @description How the candidate differs from what was recorded. */
    OpenLoopSummary: {
      binding: {
        [key: string]: number;
      };
      budget: number;
      changes_candidate: number;
      changes_recorded: number;
      ladder: {
        [key: string]: number;
      };
      max_diff_k: number;
      mean_diff_k: number;
      min_diff_k: number;
      share_feedback_limited: number;
      share_safety_clamped: number;
      writes_per_day: number;
    };
    /** @enum {string} */
    OriginName: 'ui' | 'rollback' | 'seed' | 'reset';
    /** @enum {string} */
    OwnerName: 'operator' | 'controller' | 'pump';
    /** @description What the forecast said at a fixed lead for the hours that passed. */
    PastForecast: {
      lead_h: number;
      points: components['schemas']['WeatherPoint'][];
    };
    /** @enum {string} */
    PresetName: 'short' | 'standard' | 'long' | 'unlimited';
    /** @description The current tick decided with the active and the candidate configuration. */
    PreviewNow: {
      candidate: components['schemas']['DecisionRecord'];
      current: components['schemas']['DecisionRecord'];
      delta_setpoint: number | null;
    };
    /**
     * @description ``POST config/preview``: the validation, and for a valid candidate *now* and the open loop.
     *
     *     ``now`` is ``null`` without a control loop.
     */
    PreviewResult: {
      effective: {
        [key: string]: unknown;
      };
      errors: components['schemas']['ValidationIssue'][];
      now?: components['schemas']['PreviewNow'] | null;
      open_loop_run?: components['schemas']['OpenLoopRun'];
      valid: boolean;
      warnings: components['schemas']['ValidationIssue'][];
    };
    /**
     * @description ``POST insight/house/proposal/draft``: the proposal as a configuration draft.
     *
     *     ``points`` is the learner's; ``validation`` is ``null`` without a configuration store.
     */
    ProposalDraft: {
      changes: components['schemas']['CurveChange'];
      comment: string;
      credible: boolean;
      current: components['schemas']['CurveChange'];
      label: string;
      model: string;
      points: unknown;
      stale: boolean;
      validation: components['schemas']['ValidateResult'] | null;
    };
    /** @description The model profile matched by ``Heat_Pump_Model``. */
    PumpProfileInfo: {
      name: string;
      source: string;
    };
    /** @description One row of the pump settings; only the writable rows carry the write keys. */
    PumpSetting: {
      /** @enum {string} */
      access: 'read' | 'write';
      age: number | null;
      command?: string;
      fresh: boolean;
      id: string;
      label: string | null;
      last_write?: components['schemas']['PumpWrite'] | null;
      max?: number;
      min?: number;
      owner: components['schemas']['OwnerName'];
      signal: string;
      supported: boolean;
      unit: string | null;
      value: number | string | boolean | null;
    };
    /** @description ``GET pump/settings``: whether writes are possible, the model and its profile, every row. */
    PumpSettingsPage: {
      model: number | string | boolean | null;
      profile: components['schemas']['PumpProfileInfo'] | null;
      refusals: string[];
      settings: components['schemas']['PumpSetting'][];
      writable: boolean;
    };
    /** @description The pump's own settings, captured at go-live or by hand. */
    PumpSnapshot: {
      age_s: number | null;
      by: string | null;
      complete: boolean;
      facts: {
        [key: string]: number | string | boolean | null;
      };
      items: components['schemas']['SnapshotItem'][];
      origin: string;
      outside_c: number | null;
      own_values_possible: boolean;
      previous_mode: string | null;
      register: string | null;
      released_at: string | null;
      stale: boolean | null;
      stale_after_s: number | null;
      taken_at: string;
    };
    /** @description The last operator write of a setting and how it ended. */
    PumpWrite: {
      at: string;
      by: string;
      from: number | null;
      status: string | null;
      to: number | null;
    };
    /** @description ``202`` of ``POST pump/settings/{id}``: the queued command event. */
    PumpWriteResult: {
      command: components['schemas']['CommandEvent'];
    };
    /** @description The tick's instant on both clock axes. */
    RecordInstant: {
      monotonic: number;
      wall: string;
    };
    /** @description The hold an operator released. */
    ReleasedHold: {
      incident: number;
      latched: boolean;
      reason: string;
      until: string | null;
    };
    /** @description ``POST control/release-hold``: the released hold and what still holds. */
    ReleaseHoldResult: {
      by: string;
      control: components['schemas']['ControlStatus'];
      hold: string | null;
      released: components['schemas']['ReleasedHold'];
      safety_hold: string[];
    };
    /** @description One pump value a release restores. */
    ReleaseItem: {
      at: string | null;
      before: number | string | boolean | null;
      clamped: string | null;
      detail: string | null;
      kind: string;
      ok: boolean;
      signal: string;
      snapshot: number | string | boolean | null;
      status: components['schemas']['ReleaseItemStatusName'];
      target: number | string | boolean | null;
      waited_for: string | null;
    };
    /** @enum {string} */
    ReleaseItemStatusName:
      | 'pending'
      | 'queued'
      | 'sent'
      | 'retry'
      | 'verified'
      | 'unchanged'
      | 'not_managed'
      | 'planned'
      | 'missing'
      | 'refused'
      | 'failed'
      | 'dropped'
      | 'timeout'
      | 'changed';
    /** @enum {string} */
    ReleaseOutcomeName: 'running' | 'ok' | 'incomplete' | 'interrupted';
    /** @description A release of control to the pump, or a rehearsal of it. */
    ReleaseRun: {
      by: string | null;
      done: boolean;
      dry: boolean;
      duration_s: number | null;
      finished_at: string | null;
      interrupted: boolean;
      items: components['schemas']['ReleaseItem'][];
      outcome: components['schemas']['ReleaseOutcomeName'];
      outside_c: number | null;
      paused_before: boolean;
      reason: string | null;
      rehearsal: boolean;
      snapshot_age_s: number | null;
      snapshot_origin: string | null;
      snapshot_taken_at: string | null;
      started_at: string;
      within_limit: boolean | null;
    };
    /** @description ``POST control/release``: the started release (``202`` while it runs). */
    ReleaseStarted: {
      control: components['schemas']['ControlStatus'];
      release: components['schemas']['ReleaseRun'];
    };
    /** @description ``GET control/release``: the running or last release and the last rehearsals. */
    ReleaseState: {
      last_dry_rehearsal: components['schemas']['ReleaseRun'] | null;
      last_rehearsal: components['schemas']['ReleaseRun'] | null;
      release: components['schemas']['ReleaseRun'] | null;
      timeout_s: number | null;
    };
    /** @description The configuration a replay ran with: the active one, a stored version or a draft. */
    ReplayConfig: {
      changes?: {
        [key: string]: unknown;
      };
      kind: components['schemas']['ReplayKindName'];
      version: number | null;
    };
    /** @description ``GET replay/coverage``: where stored decisions exist, per day and version. */
    ReplayCoverage: {
      days: components['schemas']['CoverageDay'][];
      from: string;
      interval_s: number;
      max_days: number;
      newest: string | null;
      oldest: string | null;
      retention_days: number;
      timezone: string;
      to: string;
      versions: components['schemas']['CoverageVersion'][];
    };
    /** @description Writes of one local day: replayed, recorded setpoint changes and commands sent. */
    ReplayDay: {
      changes_recorded: number;
      date: string;
      from: string;
      sent_recorded: number;
      to: string;
      writes: number;
    };
    /** @description A run of minutes with the replayed setpoint away from the pump's target. */
    ReplayEpisode: {
      end: string;
      ended_by: components['schemas']['EpisodeEndName'];
      max_abs_k: number;
      max_diff_k: number;
      minutes: number;
      mode: string | null;
      ovenbird_c: number | null;
      pump_c: number | null;
      reason: string | null;
      reason_at_max: string | null;
      recorded_c: number | null;
      start: string;
      writer: string | null;
    };
    /**
     * @description Whether replaying each tick with its own version reproduced every recorded setpoint.
     *
     *     ``ok`` is ``null`` when no tick could be compared.
     */
    ReplayIdentity: {
      first_mismatch: string | null;
      mismatches: number;
      ok: boolean | null;
      ticks: number;
      unknown: number;
      versions: components['schemas']['VersionIdentityModel'][];
    };
    /** @description ``POST replay`` and ``GET replay/{id}``: a replay job and, when done, its result. */
    ReplayJob: {
      config: components['schemas']['ReplayConfig'];
      error: string | null;
      finished_at: string | null;
      from: string;
      id: string;
      phase: string;
      progress: number;
      result: components['schemas']['ReplayResult'] | null;
      started_at: string;
      state: components['schemas']['ReplayStateName'];
      to: string;
    };
    /** @enum {string} */
    ReplayKindName: 'active' | 'version' | 'draft';
    /** @description A finished replay (open loop: no comfort or energy claim follows from it). */
    ReplayResult: {
      config: components['schemas']['ReplayConfig'];
      days: components['schemas']['ReplayDay'][];
      episodes: components['schemas']['ReplayEpisode'][];
      episodes_total: number;
      from: string;
      identity: components['schemas']['ReplayIdentity'];
      limitations: string[];
      open_loop: boolean;
      run_s: number;
      series: components['schemas']['ReplaySeries'];
      signal: string;
      skipped: number;
      step: number;
      summary: components['schemas']['ReplaySummary'];
      threshold_k: number;
      ticks: number;
      timezone: string;
      to: string;
    };
    /** @description The recorded, replayed and pump setpoints per step (the last value of each step). */
    ReplaySeries: {
      at: string[];
      pump: (number | null)[];
      recorded: (number | null)[];
      replayed: (number | null)[];
    };
    /** @enum {string} */
    ReplayStateName: 'running' | 'done' | 'failed' | 'cancelled';
    /** @description What the chosen configuration would have done, against the pump and the recording. */
    ReplaySummary: {
      above_pump_min: number;
      above_recorded_min: number;
      below_pump_min: number;
      below_recorded_min: number;
      bias_k: number | null;
      binding: {
        [key: string]: number;
      };
      budget: number;
      budget_use: number | null;
      changes_pump: number;
      changes_recorded: number;
      changes_replayed: number;
      compared_minutes: number;
      coverage: number;
      days_over_budget: number;
      differs_recorded_min: number;
      episodes: number;
      gap_minutes: number;
      hours_over: number;
      ladder: {
        [key: string]: number;
      };
      longest_episode_min: number;
      max_abs_k: number | null;
      max_writes_day: number;
      mean_abs_k: number | null;
      mean_diff_recorded_k: number;
      minutes: number;
      reason: {
        [key: string]: number;
      };
      sent_recorded: number;
      share_feedback_limited: number;
      share_safety_clamped: number;
      writes: number;
      writes_per_day: number;
    };
    /** @description ``POST config/reset-ack``: the mode and the configuration after the acknowledgement. */
    ResetAckResult: {
      config: components['schemas']['ConfigDoc'];
      mode: components['schemas']['ConfigMode'];
    };
    /** @enum {string} */
    ResolutionId: 'raw' | '60' | '900' | '3600' | 'journal' | 'forecast';
    /** @description One simple retention choice: its settings and the size it would come to. */
    RetentionPreset: {
      growth_bytes_per_year: number | null;
      id: components['schemas']['PresetName'];
      projected_bytes: number | null;
      values: {
        [key: string]: number;
      };
    };
    /** @description The room input: profile, held and alive ages, link. */
    RoomStatus: {
      alive_by: string | null;
      alive_s: number | null;
      authority: number | null;
      crosscheck: string | null;
      fresh: boolean;
      held_s: number | null;
      link_up: boolean | null;
      liveness: string[];
      max_age_s: number | null;
      plausible: boolean | null;
      profile: string;
      report_interval_s: number | null;
      signal: string;
      silence_limit_s: number | null;
      step_k: number | null;
      value: number | null;
    };
    /** @description A histogram bin of run lengths (``to_min`` ``null`` for the last, open bin). */
    RunBin: {
      from_min: number;
      runs: number;
      to_min: number | null;
    };
    /** @description The run statistics of one local day. */
    RunDay: {
      censored: number;
      date: string;
      from: string;
      histogram: components['schemas']['RunBin'][];
      longest_min: number | null;
      mean_min: number | null;
      median_min: number | null;
      min_off_min: number | null;
      partial: boolean;
      runs: number;
      short_runs: number;
      short_share: number | null;
      to: string;
    };
    /** @enum {string} */
    RunFailureReason: 'timeout' | 'memory' | 'exit' | 'spawn';
    /** @enum {string} */
    RunState: 'idle' | 'running' | 'unavailable';
    /** @description Compressor run statistics of a span. */
    RunStats: {
      censored: number;
      histogram: components['schemas']['RunBin'][];
      longest_min: number | null;
      mean_min: number | null;
      median_min: number | null;
      min_off_min: number | null;
      runs: number;
      short_runs: number;
      short_share: number | null;
    };
    /** @description The safety monitor: overall level and every monitor. */
    Safety: {
      interval_s: number;
      level: string;
      monitors: components['schemas']['Monitor'][];
    };
    /** @description The safety net: the envelope rule, the band now and the hard limits. */
    SafetyNet: {
      envelope_above_k: number;
      envelope_below_k: number;
      envelope_now: components['schemas']['EnvelopeBand'] | null;
      envelope_rule: components['schemas']['EnvelopeRule'];
      max_supply_c: number;
      min_setpoint_c: number;
      ovenbird_corrections: components['schemas']['EnvelopeCorrections'] | null;
    };
    /** @description A settings group and its fields, in display order. */
    SchemaGroup: {
      fields: string[];
      id: string;
    };
    /** @description An indicative band and the heat loss per m2 it lies below. */
    ScoreBand: {
      band: string;
      below_w_per_m2: number | null;
    };
    /** @enum {string} */
    ScoreState: 'learning' | 'no_floor_area' | 'ready';
    ServerMessage:
      | components['schemas']['SnapshotMessage']
      | components['schemas']['HealthMessage']
      | components['schemas']['DecisionMessage']
      | components['schemas']['ConfigMessage'];
    /** @enum {string} */
    SeverityName: 'info' | 'warning' | 'critical';
    /** @description One signal of the snapshot: value, provenance and freshness. */
    Signal: {
      age: number | null;
      alive_by: string | null;
      fresh: boolean;
      held: number | null;
      label: string | null;
      max_age: number;
      reason: string | null;
      retained: boolean;
      source: components['schemas']['SourceName'];
      source_unit?: string | null;
      unit: string | null;
      value: number | string | boolean | null;
    };
    /**
     * @description A signal the room, liveness or cross-check picker offers.
     *
     *     Home Assistant candidates also carry their entity id and, when Home Assistant's
     *     registry could be read, the area name and the device id (the liveness picker
     *     lists the room sensor's own device first). ``pump_mirror`` is true for a Home
     *     Assistant entity on a device whose entities copy the heat pump's HeishaMon values;
     *     the pickers list those apart.
     */
    SignalCandidate: {
      area?: string | null;
      device_id?: string | null;
      entity_id?: string | null;
      held_s: number | null;
      name: string | null;
      pump_mirror: boolean;
      signal: string;
      source: components['schemas']['SourceName'];
      unit: string | null;
      value: number | null;
    };
    /** @enum {string} */
    SignalKindName: 'number' | 'enum' | 'bool';
    /** @description The stored range of one signal at one resolution (``step`` 0 is raw). */
    SignalRange: {
      first: string;
      last: string;
      points: number;
      step: number;
    };
    /** @description ``GET snapshot``: every signal, the derived values and the defrost at one instant. */
    Snapshot: {
      at: string;
      defrost: components['schemas']['DefrostState'];
      derived: {
        [key: string]: components['schemas']['Derived'];
      };
      heishamon: components['schemas']['HeishamonLink'];
      links: {
        [key: string]: boolean;
      };
      signals: {
        [key: string]: components['schemas']['Signal'];
      };
    };
    /** @description A pump value the snapshot holds. */
    SnapshotItem: {
      kind: string;
      signal: string;
      value: number | string | boolean | null;
    };
    /** @description The latest snapshot (at most once per snapshot interval). */
    SnapshotMessage: {
      data: components['schemas']['Snapshot'];
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'snapshot';
    };
    /** @description ``GET`` and ``POST control/snapshot``: the snapshot and whether one can be captured. */
    SnapshotState: {
      armed: boolean;
      can_capture: boolean;
      capture_refusal: components['schemas']['CaptureRefusalName'] | null;
      publishing: boolean;
      snapshot: components['schemas']['PumpSnapshot'] | null;
    };
    /** @enum {string} */
    SourceName: 'heishamon' | 'ha' | 'mqtt' | 'provider';
    /** @enum {string} */
    StepName: 'raw' | '60' | '900' | '3600';
    /** @description A series at a fixed step (seconds). */
    SteppedSeries: {
      points: components['schemas']['WeatherPoint'][];
      step: number;
    };
    /** @description Sizes in bytes of the files in the data directory and its free space. */
    StorageFiles: {
      database: number;
      free: number | null;
      snapshot: number | null;
      wal: number;
    };
    /** @description What one resolution holds and what it costs per day. */
    StorageResolution: {
      bytes: number | null;
      bytes_per_day: number | null;
      id: components['schemas']['ResolutionId'];
      newest: string | null;
      oldest: string | null;
      retention_days: number | null;
      rows: number;
    };
    /** @description One table or index of ``history.db``. */
    StorageTable: {
      bytes: number;
      name: string;
      rows: number | null;
    };
    /** @description One signal with history: id, unit, kind and its range per resolution. */
    StoredSignal: {
      id: string;
      kind: components['schemas']['SignalKindName'];
      resolutions: components['schemas']['SignalRange'][];
      unit: string | null;
    };
    /** @description A manual wood-stove request. */
    StoveRequest: {
      actor: string;
      at: string;
      on: boolean;
      until: string | null;
    };
    /** @description ``POST control/stove``: the accepted request and wood-stove mode. */
    StoveResult: {
      request: components['schemas']['StoveRequest'];
      stove: components['schemas']['StoveStatus'];
    };
    /** @enum {string} */
    StoveSourceName: 'auto' | 'manual';
    /** @description Wood-stove mode: configuration, state and the request. */
    StoveStatus: {
      active: boolean;
      auto: boolean;
      backoff_k: number | null;
      blocked: boolean;
      enabled: boolean;
      enter_c: number | null;
      entry_c: number | null;
      exit_c: number | null;
      integral_k: number | null;
      level_blocked: boolean;
      reentry_wait: boolean;
      reference_c: number | null;
      request: components['schemas']['StoveRequest'] | null;
      since: string | null;
      source: components['schemas']['StoveSourceName'] | null;
      trigger: components['schemas']['StoveTriggerName'] | null;
    };
    /** @enum {string} */
    StoveTriggerName: 'level' | 'rise' | 'manual' | 'handover';
    /** @enum {string} */
    StreamFormat: 'csv' | 'ndjson';
    /** @description ``GET system/about``: version, uptime, connections and the control state. */
    SystemAbout: {
      api_version: number;
      clock_speed: number;
      connections: components['schemas']['Connections'];
      control: components['schemas']['AboutControl'] | null;
      control_interval_s: number;
      failing_components: {
        [key: string]: unknown;
      };
      previous_start: string | null;
      restored_state: boolean | null;
      safety_net: components['schemas']['SafetyNet'] | null;
      service_starts: number | null;
      service_time: string;
      setpoint_register: string;
      simulation: boolean;
      started_at: string;
      timezone: string;
      uptime_s: number;
      version: string;
    };
    /** @description One named contribution to the water setpoint. */
    Term: {
      name: string;
      note: string;
      raw: number;
      unit: string;
      value: number;
    };
    /** @enum {string} */
    TierName: 'basic' | 'advanced' | 'expert';
    /** @description One item of the go-live checklist; ``evidence`` differs per item. */
    TrialCheck: {
      evidence: {
        [key: string]: unknown;
      };
      id: string;
      message: string;
      phase: components['schemas']['CheckPhaseName'];
      status: components['schemas']['CheckStatusName'];
    };
    /** @description A cut-over criterion: the trial against the baseline. */
    TrialCriterion: {
      baseline: number | null;
      delta: number | null;
      id: string;
      limit: number | null;
      status: components['schemas']['CriterionStatusName'];
      trial: number | null;
    };
    /** @description One period's figures: room, outside, runs and writes. */
    TrialPeriod: {
      days: number;
      from: string;
      outside_mean_c: number | null;
      pump_errors: number | null;
      room_hours: number | null;
      room_mean_c: number | null;
      room_min_c: number | null;
      runs: components['schemas']['RunStats'] | null;
      setpoint_changes_per_day: number | null;
      to: string;
      writes: number | null;
      writes_per_day: number | null;
    };
    /** @enum {string} */
    TrialStateName: 'no_trial' | 'running' | 'ended_early' | 'complete' | 'not_a_trial';
    /** @description ``GET trial/status``: the go-live checklist and the trial summary. */
    TrialStatus: {
      at: string;
      checklist: components['schemas']['TrialCheck'][];
      configured_mode: components['schemas']['ModeName'] | null;
      counts: components['schemas']['CheckCounts'];
      groups: components['schemas']['CheckGroups'];
      mode: components['schemas']['ModeName'] | null;
      not_ready: components['schemas']['NotReady'][];
      ready: boolean;
      ready_for_cutover: boolean;
      summary: components['schemas']['TrialSummary'] | null;
    };
    /** @description The trial against the baseline, the trial's state and length. */
    TrialSummary: {
      baseline: components['schemas']['TrialPeriod'];
      criteria: components['schemas']['TrialCriterion'][];
      criteria_met: boolean;
      days: number;
      met: boolean;
      min_days: number;
      /** @enum {string} */
      source: 'go_live' | 'default' | 'query';
      state: components['schemas']['TrialStateName'];
      trial: components['schemas']['TrialPeriod'];
    };
    /** @description ``POST config/validate``: errors, warnings and the changed fields' effective values. */
    ValidateResult: {
      effective: {
        [key: string]: unknown;
      };
      errors: components['schemas']['ValidationIssue'][];
      valid: boolean;
      warnings: components['schemas']['ValidationIssue'][];
    };
    ValidationError: {
      ctx?: Record<string, never>;
      input?: unknown;
      loc: (string | number)[];
      msg: string;
      type: string;
    };
    /** @description An error or warning of a configuration change. */
    ValidationIssue: {
      code: string;
      field: string | null;
      message: string;
      params: {
        [key: string]: unknown;
      };
    };
    /** @enum {string} */
    ValueSourceName: 'env' | 'file' | 'store' | 'preset' | 'default';
    /** @description A field's stored value before and after a version (absent is ``null``). */
    VersionChange: {
      field: string;
      from: unknown;
      to: unknown;
    };
    /** @description The identity check of one configuration version. */
    VersionIdentityModel: {
      first_mismatch: string | null;
      mismatches: number;
      ticks: number;
      version: number | null;
    };
    /** @description The forecast location (rounded to 0.01°) and where it came from. */
    WeatherLocation: {
      latitude: number;
      longitude: number;
      source: string;
    };
    /** @description The outside temperature now: measured, filtered, forecast, and the curve's water. */
    WeatherNow: {
      curve_c: number | null;
      filtered_c: number | null;
      forecast_c: number | null;
      measured_c: number | null;
    };
    /** @description ``GET weather`` while no forecast is fetched. */
    WeatherOff: {
      /** @constant */
      enabled: false;
      location: components['schemas']['WeatherLocation'] | null;
      provider: string;
      reason: string | null;
    };
    /** @description ``GET weather`` while forecasts are fetched. */
    WeatherOn: {
      age: number | null;
      curve_outlook: components['schemas']['CurveOutlook'];
      /** @constant */
      enabled: true;
      error: components['schemas']['ForecastError'];
      filtered: components['schemas']['SteppedSeries'];
      forecast: components['schemas']['ForecastSeries'];
      forecast_past: components['schemas']['PastForecast'];
      issued: string | null;
      location: components['schemas']['WeatherLocation'] | null;
      measured: components['schemas']['SteppedSeries'];
      now: components['schemas']['WeatherNow'];
      provider: string;
      stale: boolean;
    };
    WeatherPoint: [string, number | null];
    WeatherReport: components['schemas']['WeatherOff'] | components['schemas']['WeatherOn'];
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
  alarms_api_v1_alarms_get: {
    parameters: {
      query?: {
        format?: components['schemas']['Format'];
        from?: string | null;
        limit?: number;
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['AlarmsPage'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  archive_status_api_v1_archive_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ArchiveStatus'];
        };
      };
    };
  };
  delete_archive_api_v1_archive_delete_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ArchiveDeleteResult'];
        };
      };
    };
  };
  download_month_api_v1_archive_months__month__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        month: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': unknown;
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  download_season_api_v1_archive_seasons__season__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        season: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': unknown;
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  download_year_api_v1_archive_years__year__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        year: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': unknown;
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  audit_events_api_v1_audit_get: {
    parameters: {
      query?: {
        format?: components['schemas']['Format'];
        from?: string | null;
        limit?: number;
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['AuditPage'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  commands_api_v1_commands_get: {
    parameters: {
      query?: {
        format?: components['schemas']['Format'];
        from?: string | null;
        limit?: number;
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['CommandsPage'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  current_api_v1_config_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ConfigDoc'];
        };
      };
    };
  };
  apply_api_v1_config_put: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ApplyResult'];
        };
      };
    };
  };
  export_api_v1_config_export_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ConfigExport'];
        };
      };
    };
  };
  ha_connection_api_v1_config_ha_put: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HaConnectionResult'];
        };
      };
    };
  };
  ha_test_api_v1_config_ha_test_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HaTestResult'];
        };
      };
    };
  };
  mqtt_status_api_v1_config_mqtt_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['MqttStatus'];
        };
      };
    };
  };
  mqtt_connection_api_v1_config_mqtt_put: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['MqttConnectionResult'];
        };
      };
    };
  };
  mqtt_test_api_v1_config_mqtt_test_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['MqttTestResult'];
        };
      };
    };
  };
  preview_api_v1_config_preview_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['PreviewResult'];
        };
      };
    };
  };
  reset_ack_api_v1_config_reset_ack_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ResetAckResult'];
        };
      };
    };
  };
  rollback_api_v1_config_rollback_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ApplyResult'];
        };
      };
    };
  };
  schema_api_v1_config_schema_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ConfigSchema'];
        };
      };
    };
  };
  signal_candidates_api_v1_config_signals_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ConfigSignals'];
        };
      };
    };
  };
  validate_api_v1_config_validate_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ValidateResult'];
        };
      };
    };
  };
  versions_api_v1_config_versions_get: {
    parameters: {
      query?: {
        limit?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ConfigVersions'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  version_api_v1_config_versions__number__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        number: number;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ConfigVersion'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  pause_api_v1_control_pause_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ModeChange'];
        };
      };
    };
  };
  release_status_api_v1_control_release_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ReleaseState'];
        };
      };
    };
  };
  release_api_v1_control_release_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ReleaseStarted'];
        };
      };
      /** @description The release runs. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ReleaseStarted'];
        };
      };
    };
  };
  release_hold_api_v1_control_release_hold_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ReleaseHoldResult'];
        };
      };
    };
  };
  resume_api_v1_control_resume_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ModeChange'];
        };
      };
    };
  };
  snapshot_api_v1_control_snapshot_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['SnapshotState'];
        };
      };
    };
  };
  capture_api_v1_control_snapshot_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['SnapshotState'];
        };
      };
    };
  };
  stove_api_v1_control_stove_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['StoveResult'];
        };
      };
    };
  };
  decisions_api_v1_decisions_get: {
    parameters: {
      query?: {
        format?: components['schemas']['Format'];
        from?: string | null;
        limit?: number;
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['DecisionsPage'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  decisions_latest_api_v1_decisions_latest_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['DecisionsLatest'];
        };
      };
    };
  };
  decision_series_api_v1_decisions_series_get: {
    parameters: {
      query?: {
        from?: string | null;
        step?: number | null;
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['DecisionSeries'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  diagnostics_api_v1_diagnostics_get: {
    parameters: {
      query?: {
        format?: 'json' | 'zip';
        items?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': unknown;
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  export_archive_api_v1_export_archive_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': unknown;
        };
      };
    };
  };
  export_journal_api_v1_export_journal__kind__get: {
    parameters: {
      query?: {
        format?: components['schemas']['StreamFormat'];
        from?: string | null;
        to?: string | null;
      };
      header?: never;
      path: {
        kind: 'decisions' | 'commands' | 'alarms' | 'forecast';
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': unknown;
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  export_series_api_v1_export_series_get: {
    parameters: {
      query?: {
        format?: components['schemas']['StreamFormat'];
        from?: string | null;
        layout?: components['schemas']['LayoutName'];
        signals?: string;
        step?: components['schemas']['StepName'];
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': unknown;
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  health_api_v1_health_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['Health'];
        };
      };
    };
  };
  history_api_v1_history_get: {
    parameters: {
      query: {
        format?: components['schemas']['Format'];
        from?: string | null;
        signals: string;
        step?: number | null;
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['History'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  history_compact_api_v1_history_compact_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['CompactResult'];
        };
      };
    };
  };
  history_signals_api_v1_history_signals_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HistorySignals'];
        };
      };
    };
  };
  history_storage_api_v1_history_storage_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HistoryStorage'];
        };
      };
    };
  };
  daily_api_v1_insight_daily_get: {
    parameters: {
      query?: {
        days?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['InsightDaily'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  house_model_api_v1_insight_house_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HouseReport'];
        };
      };
    };
  };
  house_history_api_v1_insight_house_history_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HouseHistory'];
        };
      };
    };
  };
  proposal_draft_api_v1_insight_house_proposal_draft_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ProposalDraft'];
        };
      };
    };
  };
  house_run_api_v1_insight_house_run_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HouseRun'];
        };
      };
    };
  };
  start_house_run_api_v1_insight_house_run_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HouseRun'];
        };
      };
    };
  };
  runs_api_v1_insight_runs_get: {
    parameters: {
      query?: {
        days?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['InsightRuns'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  live_ticket_api_v1_live_ticket_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['LiveTicket'];
        };
      };
    };
  };
  notifications_api_v1_notifications_status_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['NotificationStatus'];
        };
      };
    };
  };
  notifications_test_api_v1_notifications_test_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['NotifyTestResult'];
        };
      };
    };
  };
  read_api_v1_pump_settings_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['PumpSettingsPage'];
        };
      };
    };
  };
  write_api_v1_pump_settings__setting_id__post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        setting_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['PumpWriteResult'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  start_replay_api_v1_replay_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ReplayJob'];
        };
      };
    };
  };
  replay_job_api_v1_replay__job_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        job_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ReplayJob'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  cancel_replay_api_v1_replay__job_id__cancel_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        job_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ReplayJob'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  coverage_api_v1_replay_coverage_get: {
    parameters: {
      query?: {
        from?: string | null;
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ReplayCoverage'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  divergence_api_v1_shadow_divergence_get: {
    parameters: {
      query?: {
        from?: string | null;
        step?: number | null;
        threshold_k?: number;
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['Divergence'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  explain_api_v1_shadow_episodes_explain_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['ExplainResult'];
        };
      };
    };
  };
  snapshot_api_v1_snapshot_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['Snapshot'];
        };
      };
    };
  };
  about_api_v1_system_about_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['SystemAbout'];
        };
      };
    };
  };
  trial_status_api_v1_trial_status_get: {
    parameters: {
      query?: {
        baseline_from?: string | null;
        baseline_to?: string | null;
        from?: string | null;
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['TrialStatus'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
  read_api_v1_weather_get: {
    parameters: {
      query?: {
        ahead_h?: number;
        back_h?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['WeatherReport'];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          'application/json': components['schemas']['HTTPValidationError'];
        };
      };
    };
  };
}
