<script lang="ts">
  import Card from '$ui/Card.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import Button from '$ui/Button.svelte';
  import Field from '$components/settings/Field.svelte';
  import Icon from '$ui/Icon.svelte';
  import Why from '$ui/Why.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { formatInputNumber, parseInputNumber } from '$lib/core/fieldFormat';
  import { formatNumber } from '$lib/core/format';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import { canUseGeolocation, roundCoordinate } from '$lib/weather/weather';

  interface Props {
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { schema, config }: Props = $props();

  const lat = $derived(draft.value('weather_latitude', config) as number | null | undefined);
  const lon = $derived(draft.value('weather_longitude', config) as number | null | undefined);
  const source = $derived(String(draft.value('weather_location_source', config) ?? 'ha_zone_home'));
  const locationOptions = $derived([
    { value: 'ha', label: t('weatherFromHa'), testid: 'loc-ha' },
    { value: 'manual', label: t('weatherManual'), testid: 'loc-manual' },
  ]);
  const manual = $derived(lat !== null && lat !== undefined && lon !== null && lon !== undefined);
  const geolocation = canUseGeolocation({
    isSecureContext: window.isSecureContext,
    location: window.location,
    navigator,
  });
  let geoError = $state<string | null>(null);
  let locating = $state(false);

  function setLocation(latitude: number, longitude: number, origin: 'manual' | 'browser'): void {
    draft.set('weather_latitude', roundCoordinate(latitude), config);
    draft.set('weather_longitude', roundCoordinate(longitude), config);
    draft.set('weather_location_source', origin, config);
  }

  function useHomeAssistant(): void {
    draft.reset('weather_latitude', config);
    draft.reset('weather_longitude', config);
    draft.reset('weather_location_source', config);
  }

  function locate(): void {
    geoError = null;
    locating = true;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        locating = false;
        setLocation(position.coords.latitude, position.coords.longitude, 'browser');
      },
      (error) => {
        locating = false;
        geoError = error.code === 1 ? t('geoDenied') : t('geoFailed');
      },
      { timeout: 10_000, maximumAge: 600_000 },
    );
  }

  const issues = (id: string) => ({
    errors: cfg.validation?.errors.filter((e) => e.field === id) ?? [],
    warnings: cfg.validation?.warnings.filter((e) => e.field === id) ?? [],
  });
</script>

<p class="privacy" data-testid="weather-privacy" data-help="settings/weather.privacy">
  <Icon name="globe" size={18} />
  <span>{t('weatherPrivacyShort')}</span>
  <Why title={t('weatherPrivacyTitle')} testid="weather-privacy-why">
    <p>{t('weatherPrivacy')}</p>
  </Why>
</p>

<Card bare as="div">
  <Field
    id="weather_enabled"
    {schema}
    {config}
    {draft}
    helpTarget="settings/weather.enable"
    {...issues('weather_enabled')}
  />

  <div class="location" data-testid="weather-location" data-help="settings/weather.location">
    <h3>{t('weatherLocation')}</h3>
    <Segmented
      options={locationOptions}
      value={manual ? 'manual' : 'ha'}
      onchange={(option) =>
        option === 'ha' ? useHomeAssistant() : setLocation(lat ?? 52.09, lon ?? 5.12, 'manual')}
      semantics="radio"
      appearance="radios"
      name="loc"
      label={t('weatherLocation')}
    />

    {#if manual}
      {#each ['weather_latitude', 'weather_longitude'] as id (id)}
        <Field {id} {schema} {config} {draft} {...issues(id)}>
          {#snippet editor(api)}
            <span class="coord">
              <TextInput
                width="8rem"
                align="end"
                id="field-{id}"
                type="text"
                inputmode="decimal"
                autocomplete="off"
                value={formatInputNumber(api.value as number | null, settings.language)}
                disabled={api.disabled}
                onchange={(e) => {
                  const parsed = parseInputNumber(e.currentTarget.value);
                  if (parsed === null) return;
                  const other = id === 'weather_latitude' ? lon : lat;
                  if (other === null || other === undefined) api.set(roundCoordinate(parsed));
                  else if (id === 'weather_latitude') setLocation(parsed, other, 'manual');
                  else setLocation(other, parsed, 'manual');
                }}
              />
              <span class="unit">°</span>
            </span>
          {/snippet}
        </Field>
      {/each}
    {/if}

    {#if geolocation}
      <Button
        class="weather-locate"
        onclick={locate}
        disabled={locating}
        data-testid="use-location"
      >
        <Icon name="target" size={18} />{t('weatherUseLocation')}
      </Button>
    {/if}
    {#if geoError}<p class="error" role="alert">{geoError}</p>{/if}
    <p class="muted" data-testid="weather-source">
      {t('weatherSourceLabel', { source: tOpt(`weatherSource_${source}`) ?? source })}
      {#if manual}· {formatNumber(lat ?? 0, 2, settings.language)}, {formatNumber(
          lon ?? 0,
          2,
          settings.language,
        )}{/if}
    </p>
  </div>
</Card>

<style>
  .privacy {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
    padding: var(--space-1) var(--space-1) var(--space-1) var(--space-3);
    border-radius: var(--radius);
    background: var(--status-manual-bg);
    color: var(--status-manual);
    font-size: var(--fs-body);
  }
  .privacy span {
    flex: 1;
  }
  .location h3 {
    margin: var(--space-4) 0 var(--space-1);
    font-size: var(--fs-emph);
  }
  .coord {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
  }
  :global(.weather-locate) {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    margin-top: var(--space-2);
  }
  .error {
    color: var(--err-text);
  }
</style>
