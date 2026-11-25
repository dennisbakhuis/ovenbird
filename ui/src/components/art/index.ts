import type { Component } from 'svelte';
import type { ArtName } from '$lib/help/types';

type Loader = () => Promise<{ default: Component }>;

const LOADERS: Record<ArtName, Loader> = {
  home: () => import('./Home.svelte'),
  setpoint: () => import('./Setpoint.svelte'),
  weather: () => import('./Weather.svelte'),
  pump: () => import('./Pump.svelte'),
  settings: () => import('./Settings.svelte'),
  activity: () => import('./Activity.svelte'),
  system: () => import('./System.svelte'),
  welcome: () => import('./Welcome.svelte'),
  allQuiet: () => import('./AllQuiet.svelte'),
  weatherOff: () => import('./WeatherOff.svelte'),
  shadow: () => import('./Shadow.svelte'),
  noData: () => import('./NoData.svelte'),
};

export const ART_NAMES = Object.keys(LOADERS) as ArtName[];

/**
 * Load a drawing on demand, so no illustration lands in the first-paint bundle.
 */
export async function loadArt(name: ArtName): Promise<Component> {
  const module = await LOADERS[name]();
  return module.default;
}
