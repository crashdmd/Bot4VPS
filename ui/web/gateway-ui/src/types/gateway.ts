export type ServiceId = 'podkop' | 'ssclash' | 'adguardhome' | 'dnsmasq' | 'firewall';
export interface Service { id: ServiceId; name: string; running: boolean; managed?: boolean; version?: string; web_port?: number; web_https?: boolean; web_scope?: 'lan'|'wan'; }
export type UpdateStage = 'prepare' | 'review' | 'apply';
export interface ServiceUpdateState { stage: UpdateStage; task_id?: string; }
export interface IntegrationUpdatePlan { nodeId:string;name:string;plan_token:string;files:string[];warnings:string[]; }
export interface TlsTrustChange { nodeId:string;previous:string;next:string|null; }
export interface TrafficCounters { rx_bps?: number | null; tx_bps?: number | null; rx_bytes?: number | null; tx_bytes?: number | null; up?: boolean; }
export interface TrafficHistory { at: number; lan: TrafficCounters; wan: TrafficCounters; }
export interface NetworkInterface { name: string; device?: string; up: boolean; addresses?: string[]; }
export interface WirelessRadio { name: string; band?: '2g'|'5g'|'6g'; channel?: string; runtime_channel?: number; frequencies: {channel:number;mhz:number;restricted?:boolean}[]; countries?: {code:string;country:string}[]; txpowers?: {dbm:number;mw:number}[]; }
export interface DhcpLease { hostname?: string; ipaddr: string; macaddr: string; }
export interface DhcpReservation { id: string; name?: string; ip: string; mac: string[]; shared_ipv6?: boolean; }
export interface DhcpReservationForm { configHash: string; mode: 'add' | 'edit' | 'delete'; reservation?: DhcpReservation; lease?: DhcpLease; }
export interface GatewayMonitor { ok?: boolean; stale?: boolean; checked_at?: number; board?: {model?:string;release?:{version?:string;target?:string}}; services?: Service[]; clients?: DhcpLease[]; capabilities?: {controls?:{available?:boolean};clients?:{available?:boolean}}; traffic?: {lan:TrafficCounters;wan:TrafficCounters}; traffic_history?: TrafficHistory[]; }
export interface Gateway { id:string; name:string; host:string; luci_url:string; bootstrap_state?:'ready'|'commit_pending'; monitor: GatewayMonitor; service_update_tasks?: {service:ServiceId;task_id:string;stage:UpdateStage}[]; }
export interface ServiceUpdate { fingerprint?:string|null; installed_version?:string|null; status?:'update'|'current'|'current_cached'|'newer'|'unverified'|'not_installed'|'system'; warning?:string|null; current:string|null; latest:string|null; available:boolean; task_id?:string|null; stage?:UpdateStage|null; plan?:OperationPlan|null; }
export interface OperationPlan { plan_token:string;node_id?:string;preparation_task_id?:string|null;service:ServiceId;action:'install'|'update'|'remove'|'start'|'stop'|'restart'|'web_access';version?:string;network_check?:boolean;web_scope?:'lan'|'wan';warnings?:string[];removed:string[];preserved:string[];keep_backup?:boolean;changes:{package:string;before:string|null;after:string}[]; }
