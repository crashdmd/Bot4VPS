import { createApp } from 'vue';
import Gateways from './Gateways.vue';
export interface Bridge {
  request: (url: string, options?: RequestInit) => Promise<any>;
  task: (options: any) => void;
  navigate: (page: string) => void;
  changed: () => void;
  console?: (node: any) => Promise<void>;
  close?: () => void;
  add?: () => void;
}
export function mount(root: HTMLElement, bridge: Bridge, wizard = false, plan: any = null) {
  const app = createApp(Gateways, { bridge, wizard, initialPlan: plan });
  app.mount(root);
  return () => app.unmount();
}
