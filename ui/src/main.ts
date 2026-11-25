import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';
import { ControlStore } from '$lib/core/control.svelte';
import { setClock } from '$lib/core/format';
import { hotWater } from '$lib/core/hotWater.svelte';
import { browserDeps, LiveStore } from '$lib/core/live.svelte';

const live = new LiveStore(await browserDeps());
const ctl = new ControlStore();
setClock(() => live.serviceNow());
hotWater.connect(() => ({ snapshot: live.snapshot, config: ctl.config }));
live.start();
ctl.start();

mount(App, { target: document.getElementById('app')!, props: { live, ctl } });
