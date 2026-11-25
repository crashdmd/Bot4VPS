<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue';
import type { Bridge } from '../main';
import GatewayDialog from '../GatewayDialog.vue';
interface Archive {id:string;filename:string;source_name:string;model?:string;version?:string;size:number;created_at:number;origin:string;}
interface BackupPlan {plan_token:string;node_id:string;action:'restore'|'reboot';filename?:string;files?:number;warnings:string[];}
const props = defineProps<{node:{id:string;luci_url:string};bridge:Bridge}>();
const copies = ref<Archive[]>([]), selected = ref(''), busy = ref(false), available = ref(false), error = ref('');
const taskId = ref<string|null>(null), plan = ref<BackupPlan|null>(null), restored = ref(false);
const uploadInput = ref<HTMLInputElement|null>(null);
let alive=true, timer:ReturnType<typeof setTimeout>|undefined;
const base = '/api/gateways/' + encodeURIComponent(props.node.id) + '/backups';
const post = (url:string, body:unknown) => props.bridge.request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const size = (bytes:number) => bytes<1024*1024 ? Math.round(bytes/1024)+' КБ' : (bytes/1024/1024).toFixed(1)+' МБ';
function chooseUpload(){uploadInput.value?.click();}
async function load() {
  try {
    const response = await props.bridge.request(base);
    if(!alive)return;
    copies.value=response.items;available.value=response.available;taskId.value=response.task?.id||null;restored.value=response.reboot_required===true;
    if(!copies.value.some(row=>row.id===selected.value))selected.value=copies.value[0]?.id||'';
    if(taskId.value)timer=setTimeout(load,2000);
  } catch(e:unknown){if(alive)error.value=e instanceof Error?e.message:String(e);}
}
function track(id:string, title:string, action:'create'|'restore'|'reboot') {
  taskId.value=id;
  props.bridge.task({taskId:id,title,cancellable:false,onDone:async()=>{
    if(!alive)return;
    try{const task=await props.bridge.request('/api/tasks/'+encodeURIComponent(id));if(task.result?.success===false)error.value=task.result.error||'Операция завершилась с ошибкой';}catch(e:unknown){error.value=e instanceof Error?e.message:String(e);}
    clearTimeout(timer);await load();
  }});
  clearTimeout(timer);timer=setTimeout(load,2000);
}
async function create() {
  busy.value=true;error.value='';
  try{const result=await post(base+'/create',{});if(alive)track(result.task_id,'Резервная копия настроек OpenWrt','create');}
  catch(e:unknown){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}
}
async function upload(event:Event) {
  const input=event.target as HTMLInputElement,file=input.files?.[0];if(!file)return;
  busy.value=true;error.value='';
  try{
    const body=new FormData();body.append('file',file);
    const result=await props.bridge.request(base+'/upload',{method:'POST',body});
    if(!alive)return;await load();selected.value=result.archive.id;
  }catch(e:unknown){error.value=e instanceof Error?e.message:String(e);}finally{input.value='';busy.value=false;}
}
async function review(action:'restore'|'reboot') {
  busy.value=true;error.value='';
  try{const result=await post(base+'/plan',{action,archive_id:action==='restore'?selected.value:null});if(alive)plan.value=result;else props.bridge.request(base+'/plans/'+encodeURIComponent(result.plan_token),{method:'DELETE'}).catch(()=>{});}
  catch(e:unknown){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}
}
async function discard() {
  if(!plan.value)return;busy.value=true;
  try{await props.bridge.request(base+'/plans/'+encodeURIComponent(plan.value.plan_token),{method:'DELETE'});plan.value=null;}
  catch(e:unknown){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}
}
async function apply() {
  if(!plan.value)return;busy.value=true;error.value='';const reviewed=plan.value;
  try{const result=await post(base+'/apply',{plan_token:reviewed.plan_token,confirmed:true});if(alive){plan.value=null;track(result.task_id,reviewed.action==='restore'?'Восстановление настроек OpenWrt':'Перезагрузка шлюза',reviewed.action);}}
  catch(e:unknown){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}
}
onMounted(load);
onBeforeUnmount(()=>{alive=false;clearTimeout(timer);if(plan.value)props.bridge.request(base+'/plans/'+encodeURIComponent(plan.value.plan_token),{method:'DELETE'}).catch(()=>{});});
</script>
<template>
  <section class="gw-backups">
    <header class="gw-section-header"><div><h3>Резервные копии</h3><p class="gw-hint">Штатный архив настроек OpenWrt. Прошивка и пакеты в копию не входят.</p></div><button class="gw-primary" :disabled="busy||!!taskId||!available" @click="create">Создать копию на панели</button></header>
    <p v-if="!available" class="gw-notice">Для создания и восстановления нужен управляемый API Bot4VPS. Настройте его во вкладке «Доступ».</p>
    <p v-if="error&&!plan" class="gw-error" role="alert">{{error}}</p>
    <p v-if="taskId" class="gw-notice">Выполняется операция шлюза. <button @click="track(taskId,'Операция резервного копирования','create')">Показать задачу</button></p>
    <div class="gw-backup-restore">
      <header class="gw-section-header"><div><h3>Восстановление</h3><p class="gw-hint">Выберите любую копию на панели или загрузите свой архив из LuCI.</p></div><div class="gw-backup-upload"><button :disabled="busy||!!taskId" @click="chooseUpload">Загрузить свой архив</button><input ref="uploadInput" type="file" accept=".tar.gz,.tgz" hidden :disabled="busy||!!taskId" @change="upload" /></div></header>
      <div class="gw-backup-picker"><label>Архив на панели<select v-model="selected" :disabled="busy||!!taskId"><option v-if="!copies.length" value="">Сохранённых копий пока нет</option><option v-for="row in copies" :key="row.id" :value="row.id">{{row.filename}} · {{size(row.size)}}</option></select></label><button :disabled="busy||!!taskId||!selected||!available" @click="review('restore')">Восстановить</button></div>
      <p class="gw-hint">Копии общие для всех шлюзов. Архив содержит настройки и может содержать пароли и ключи. Скачать или удалить копии можно в «Файлы → Копии шлюзов».</p>
    </div>
    <div v-if="restored" class="gw-notice gw-backup-reboot"><p>Файлы настроек восстановлены. Для применения требуется перезагрузка.</p><div class="gw-actions"><button :disabled="busy||!!taskId" @click="review('reboot')">Перезагрузить и применить</button><a :href="node.luci_url" target="_blank" rel="noopener noreferrer">Открыть LuCI ↗</a></div></div>
    <a v-else class="gw-hint" :href="node.luci_url" target="_blank" rel="noopener noreferrer">Открыть LuCI ↗</a>
  </section>
  <GatewayDialog v-if="plan" :title="plan.action==='restore'?'План восстановления':'Подтверждение перезагрузки'" :busy="busy" @close="discard">
    <p v-if="error" class="gw-error" role="alert">{{error}}</p>
    <p v-if="plan.action==='restore'"><strong>{{plan.filename}}</strong> · {{plan.files}} файлов</p>
    <ul class="gw-change-list"><li v-for="warning in plan.warnings" :key="warning">{{warning}}</li></ul>
    <div class="gw-actions"><button class="gw-primary" :disabled="busy" @click="apply">{{plan.action==='restore'?'Да, восстановить настройки':'Да, перезагрузить шлюз'}}</button><button :disabled="busy" @click="discard">Отмена</button></div>
  </GatewayDialog>
</template>
<style>
.gw-backups{display:grid;gap:15px}.gw-backups h3{font-size:14px;margin:0 0 5px}.gw-backups .gw-hint{font-size:12px;margin:4px 0}.gw-backups .gw-section-header{align-items:center;gap:14px;flex-wrap:wrap}.gw-backup-restore{border-top:1px solid var(--border,#29374b);padding-top:15px;display:grid;gap:10px}.gw-backup-picker{display:flex;align-items:flex-end;gap:10px}.gw-backup-picker label{display:grid;gap:6px;min-width:0;flex:1;font-size:12px}.gw-backup-picker select{width:100%;min-width:0;padding:8px;background:var(--field,#101927);border:1px solid var(--border,#29374b);border-radius:8px;color:inherit}.gw-backup-upload{display:grid;gap:5px;font-size:12px}.gw-backup-upload input{max-width:260px;font-size:12px}.gw-backup-reboot p{margin:0 0 8px}@media(max-width:600px){.gw-backup-picker{align-items:stretch;flex-direction:column}.gw-backup-upload input{max-width:100%}.gw-backups>.gw-section-header>.gw-primary{width:100%}}
</style>
