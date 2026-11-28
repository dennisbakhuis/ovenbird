<!--
  ByWeatherCard: heat, electricity and COP of the heat pump per band of outside temperature, as
  bars. Bands with few days are drawn paler and say so in their read-out.

  Props: bins (the by_weather rows).
-->
<script lang="ts">
  import Bars from '$components/charts/Bars.svelte';
  import { SERIES } from '$components/charts/palette';
  import { settings, t } from '$lib/core/settings.svelte';
  import { binItems, type WeatherBin } from '$lib/house/basics';
  import Card from '$ui/Card.svelte';

  let { bins }: { bins: WeatherBin[] } = $props();

  const lang = $derived(settings.language);
  const note = (bin: WeatherBin, from: string, to: string) =>
    t(bin.few_days ? 'houseWeatherBinFew' : 'houseWeatherBin', { from, to, days: bin.days });
  const options = (color: string) => ({ color, lang, note });
  const heat = $derived(binItems(bins, (b) => b.heat_w / 1000, options(SERIES.heat)));
  const electric = $derived(
    binItems(
      bins,
      (b) => (b.electric_w === null ? null : b.electric_w / 1000),
      options(SERIES.electric),
    ),
  );
  const cop = $derived(binItems(bins, (b) => b.cop, options(SERIES.outlet)));
</script>

<Card
  title={t('houseWeatherTitle')}
  icon="weather"
  testid="house-by-weather"
  help="house.basics"
  span={12}
>
  {#if bins.length === 0}
    <p class="muted">{t('houseWeatherEmpty')}</p>
  {:else}
    <div class="blocks">
      <section data-testid="house-by-weather-heat">
        <h3>{t('houseWeatherHeat')}</h3>
        <Bars title={t('houseWeatherHeat')} items={heat} unit="kW" digits={1} height={110} />
      </section>
      <section data-testid="house-by-weather-electric">
        <h3>{t('houseWeatherElectric')}</h3>
        <Bars
          title={t('houseWeatherElectric')}
          items={electric}
          unit="kW"
          digits={2}
          height={110}
        />
      </section>
      <section data-testid="house-by-weather-cop">
        <h3>{t('houseWeatherCop')}</h3>
        <Bars title={t('houseWeatherCop')} items={cop} digits={1} height={110} />
      </section>
    </div>
    <p class="note muted caption" data-testid="house-by-weather-note">{t('houseWeatherNote')}</p>
  {/if}
</Card>

<style>
  .blocks {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
    gap: var(--space-3) var(--space-5);
  }
  h3 {
    margin: 0;
    font-size: var(--fs-body);
    color: var(--muted);
    font-weight: var(--fw-semibold);
  }
  .note {
    margin: var(--space-3) 0 0;
  }
</style>
