<!--
  ProposalCard: the curve the house model suggests. Current curve against the suggestion, the
  change per point (with what limited it and whether the point lies beyond the measured data),
  the mean and largest change, and "Open as draft": the suggestion goes into the settings draft
  and the usual review and apply flow on the curve page. Nothing is applied from here. While the
  model is not credible the button is disabled with the reason.

  Props: house (HouseInsight), ctl (ControlStore).
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Button from '$ui/Button.svelte';
  import { actionKey, classifyError, type ControlStore } from '$lib/core/control.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { formatNumber } from '$lib/core/format';
  import { curveDiffers, draftProposal, type HouseInsight } from '$lib/house/house';
  import { router } from '$lib/core/router.svelte';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import MiniCurve from '$components/settings/MiniCurve.svelte';
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';

  let { house, ctl }: { house: HouseInsight; ctl: ControlStore } = $props();

  const lang = $derived(settings.language);
  const num = (value: number, digits = 1) => formatNumber(value, digits, lang).replace('-', '−');
  const signed = (value: number) =>
    value > 0.04 ? `+${num(value)}` : value < -0.04 ? `−${num(Math.abs(value))}` : num(0);
  const proposal = $derived(house.proposal);
  const credible = $derived(Boolean(proposal?.credible));
  const same = $derived(
    proposal
      ? !curveDiffers(proposal.curve, proposal.current_curve ?? proposal.based_on_curve)
      : false,
  );
  const xs = $derived(proposal ? proposal.curve.map((p) => p[0]) : []);
  const xRange = $derived<[number, number]>([Math.min(-15, ...xs) - 1, Math.max(20, ...xs) + 1]);

  let busy = $state(false);
  let error = $state<string | null>(null);
  let notice = $state<string | null>(null);

  async function open(): Promise<void> {
    busy = true;
    error = null;
    notice = null;
    try {
      const result = await draftProposal();
      const kept = draft.loadChanges(
        result.changes,
        {
          label: result.label,
          comment: t('houseDraftComment', { model: result.model }),
          kind: 'house',
        },
        ctl.config,
      );
      if (kept === 0) notice = t('houseProposalSame');
      else router.navigate('settings', ['curve']);
    } catch (failure) {
      error = t(actionKey(classifyError(failure)));
    }
    busy = false;
  }
</script>

<Card
  title={t('houseProposalTitle')}
  icon="chart"
  testid="house-proposal"
  help="house.proposal"
  span={5}
>
  {#if !proposal}
    <p class="muted" data-testid="house-proposal-none">{t('houseProposalNone')}</p>
  {:else}
    <p class="lead">
      <Pill tone="info" icon="home">{t('houseSuggestedLabel')}</Pill>
      <span>{t('houseProposalLead', { comfort: num(proposal.comfort_c) })}</span>
    </p>
    <MiniCurve
      curve={proposal.curve}
      before={proposal.current_curve ?? proposal.based_on_curve}
      height={120}
      labels
      axis
      {xRange}
      testid="house-proposal-curve"
    />
    <p class="caption legend">
      <span class="key now"></span>{t('houseCurveNow')}
      <span class="key new"></span>{t('houseCurveSuggested')}
    </p>
    <div class="table-wrap">
      <table data-testid="house-proposal-table">
        <thead>
          <tr>
            <th scope="col">{t('houseColOutside')}</th>
            <th scope="col">{t('houseColNow')}</th>
            <th scope="col">{t('houseColSuggested')}</th>
            <th scope="col">{t('houseColChange')}</th>
          </tr>
        </thead>
        <tbody>
          {#each proposal.points as point (point.outside_c)}
            <tr>
              <td class="num">{num(point.outside_c, 0)}&#8239;°C</td>
              <td class="num">{num(point.current_c)}&#8239;°C</td>
              <td class="num"
                >{num(point.water_c)}&#8239;°C
                {#if point.limited_by || point.extrapolated}
                  <span class="note"
                    >{[
                      point.limited_by
                        ? (tOpt(`houseLimited_${point.limited_by}`) ?? point.limited_by)
                        : null,
                      point.extrapolated ? t('houseExtrapolated') : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}</span
                  >
                {/if}</td
              >
              <td class="num">{signed(point.change_k)}&#8239;K</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="caption change">
      {t('houseProposalChange', {
        mean: num(proposal.mean_change_k),
        max: num(proposal.max_change_k),
      })}
    </p>
    {#if proposal.stale}
      <p class="warn" data-testid="house-proposal-stale">
        <Icon name="warning" size={16} />{t('houseProposalStale')}
      </p>
    {/if}
    {#if !credible}
      <p class="warn" data-testid="house-proposal-uncredible">
        <Icon name="clock" size={16} />{t('houseProposalNotCredible')}
      </p>
    {/if}
    <ActionRow center loose>
      <Button
        type="button"
        variant="primary"
        disabled={!credible || same || busy}
        onclick={open}
        data-testid="house-open-draft"
      >
        {t('houseProposalOpen')}
      </Button>
      <span class="caption">{same ? t('houseProposalSame') : t('houseProposalOpenHint')}</span>
    </ActionRow>
    {#if notice}<p class="caption" role="status">{notice}</p>{/if}
    {#if error}<InlineMessage tone="error" size="md">{error}</InlineMessage>{/if}
  {/if}
</Card>

<style>
  .lead {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    margin: 0;
  }
  .key {
    display: inline-block;
    width: 1.2rem;
    margin-left: var(--space-2);
  }
  .key:first-child {
    margin-left: 0;
  }
  .key.now {
    border-top: 2px dashed var(--muted);
  }
  .key.new {
    border-top: 2px solid var(--accent);
  }
  .table-wrap {
    overflow-x: auto;
  }
  td {
    white-space: nowrap;
  }
  .note {
    display: block;
    color: var(--muted);
    font-size: var(--fs-caption);
    white-space: normal;
  }
  .change {
    margin: 0;
  }
  .warn {
    display: flex;
    gap: var(--space-2);
    align-items: flex-start;
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-control);
    background: var(--status-limited-bg);
    color: var(--status-limited);
  }
  .warn :global(.icon) {
    flex: none;
    margin-top: 0.15rem;
  }
</style>
