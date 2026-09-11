// No browser/network: validate the published script and price precision.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(require('node:path').join(__dirname, '../dashboard.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
new vm.Script(script);
const line = script.split('\n').find(line => line.startsWith('const price='));
const price = vm.runInNewContext(line + '; price');
assert.equal(price(1000000), '1000000');
assert.equal(price(100), '100');
assert.equal(Number(price(0.00000000001)), 0.00000000001);
assert.equal(price(null), '—');
assert.equal(price(Infinity), '—');
assert.equal(price(NaN), '—');
assert.ok(html.includes('Kalite Kontrol CSV'));
assert.ok(html.includes('Kısmi teslim'));
assert.ok(html.includes('measurementNote'), 'dashboard must render measurement note');
assert.ok(html.includes('fMarket'), 'dashboard must expose market filter');
assert.ok(html.includes('fUniverse'), 'dashboard must expose universe filter');
assert.ok(html.includes('TP dokunması'), 'dashboard must explain target touch measurement');

// Execute the actual handlers against a small DOM contract without network.
// Browser rendering is checked separately; these tests guard data selection,
// refresh, escaping, empty/error states and async file replacement in CI.
const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], {
  value: '', innerHTML: '', textContent: '', hidden: false, listeners: {},
  addEventListener(type, fn) { this.listeners[type] = fn; },
  scrollIntoView() {}
}]));
const get = id => { assert.ok(elements.has(id), `missing DOM element ${id}`); return elements.get(id); };
get('fSort').value = 'new'; get('fNot').value = '50';
const context = vm.createContext({document: {getElementById: get}, console,
  fetch: () => { throw Error('test_network_forbidden'); }, setInterval: () => {},
});
vm.runInContext(script.replace('load();setInterval(load,60000);', ''), context);
const run = code => vm.runInContext(code, context);
const base = {t:'2025-01-01T00:00:00Z', symbol:'BTCUSDT', strategy:'S3', status:'OLGUN',
  direction:'LONG', confidence:'ORTA', notification_status:'GONDERILDI', note:'sample',
  pnl_pct:1.88, entry:100, horizon_h:4, performance_market:'spot', universe:'core30',
  engine_version:'live-compatible-v1', engine_config_hash:'hash', config_version:'v1',
  measurement_version:'signal-reference-touch-v1'};
context.fixture = {strategies:[], signals:[base, {...base, symbol:'ETHUSDT', universe:'observe',
  performance_market:'um_perp', measurement_version:'legacy_unknown'},
  {...base, symbol:'SOLUSDT', universe:null, performance_market:null, measurement_version:null}]};
run('D=fixture;fillOptions();drawRows()');
get('fMarket').value='um_perp';
assert.equal(run('filters().length'), 1);
get('fMarket').value='';get('fUniverse').value='UNKNOWN';
assert.equal(run('filters()[0].symbol'), 'SOLUSDT');
get('fUniverse').value='';get('fMeasurement').value='legacy_unknown';
assert.equal(run('filters().length'), 2);
get('fMeasurement').value='signal-reference-touch-v1';
run('fillOptions()');
assert.equal(get('fMeasurement').value,'signal-reference-touch-v1');
run('D.signals.push({...D.signals[0],universe:"new_universe"});fillOptions()');
assert.ok(get('fUniverse').innerHTML.includes('new_universe'));
get('reset').listeners.click();
assert.equal(get('fMeasurement').value,'');
assert.ok(get('rows').innerHTML.includes('funding hariç'));
assert.ok(run('drawer(D.signals[0])').includes('Motor hash'));

const cohort = {strategy:'S3',direction:'LONG',performance_market:'spot',universe:'core30',
  config_version:'v1',engine_version:'v1',engine_config_hash:'h1',evidence_source:'forward_confirmed_delivery',
  measurement_version:'paper-barriers-v1',execution_spec_hash:'spec',n_total:3,n_measured:1,
  n_pending:1,n_unavailable:1,n_full_net:1,event_days:1,tp_before_sl_lower_pct:0,tp_before_sl_upper_pct:100,
  mean_net_pct:-1.62,median_net_pct:-1.62,q10_net_pct:-1.62,q90_net_pct:-1.62,
  mean_net_ex_funding_pct:-1.62,median_net_ex_funding_pct:-1.62,q10_net_ex_funding_pct:-1.62,q90_net_ex_funding_pct:-1.62,
  execution_spec:{target_pct:2,stop_pct:1.5,horizon_hours:4,latency_ms:0,round_trip_cost_bps:12},
  warnings:['small_sample','pending_or_missing_outcomes_not_losses_or_wins']};
context.report = {schema_version:'paper-signals-report-v1',as_of_ms:1735689600000,
  summary:{schema_version:'cohort-evidence-v1',cohorts:[cohort]},rejected_counts:{bad:1}};
run('renderPaperReport(report)');
assert.ok(get('paperCohorts').innerHTML.includes('küçük N'));
assert.ok(get('paperStatus').textContent.includes('manifesti doğrulanmadı'));
assert.equal(context.fixture.signals.length,4,'paper must not mutate legacy data');
context.report.summary.cohorts=[{...cohort, performance_market:'um_perp', n_full_net:0,
  mean_net_pct:null,median_net_pct:null,q10_net_pct:null,q90_net_pct:null,config_version:'<img src=x onerror=alert(1)>'}];
run('renderPaperReport(report)');
assert.ok(get('paperCohorts').innerHTML.includes('Funding hariç'));
assert.ok(!get('paperCohorts').innerHTML.includes('<img'));
assert.ok(get('paperCohorts').innerHTML.includes('&lt;img'));
context.report.summary.cohorts[0].mean_net_pct=1.88;
assert.throws(()=>run('renderPaperReport(report)'), /invalid_paper_report/);
run('clearPaperReport()');
assert.equal(get('paperCohorts').innerHTML,'');
assert.ok(get('paperStatus').textContent.includes('Yeni yöntemle değerlendirilmedi'));

(async()=>{
  const change=get('paperFile').listeners.change;
  await change({target:{files:[{size:10,text:async()=>'{invalid'}]}});
  assert.ok(get('paperStatus').textContent.includes('rapor okunamadı'));
  let resolve;
  const pending=change({target:{files:[{size:10,text:()=>new Promise(r=>{resolve=r})}]}});
  get('paperClear').listeners.click();
  resolve('{}'); await pending;
  assert.ok(get('paperStatus').textContent.includes('raporu seçilmedi'));
  console.log('PASS dashboard syntax, filters/refresh/reset, paper cohorts/funding/escaping, async file errors');
})().catch(error=>{console.error(error);process.exitCode=1});
